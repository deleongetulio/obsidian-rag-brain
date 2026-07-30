"""
rag_embed.py — RAG SEMÁNTICO con embeddings locales (corre en el venv .venv-rag / Python 3.12).

Reutiliza la extracción y el troceado de rag_lib.py (para que los trozos coincidan con el
índice BM25) y añade búsqueda por significado con un modelo multilingüe local. Todo offline,
gratis y privado: ni el texto ni las consultas salen de tu máquina.

Modelo: intfloat/multilingual-e5-base (español + inglés). La primera ejecución descarga
el modelo (~1.1 GB) a la caché de HuggingFace; después es instantáneo y sin red.

Uso (SIEMPRE con el python del venv):
    .venv-rag/Scripts/python.exe rag_embed.py ingest "ruta/al/libro.epub" --slug heinrich-capital
    .venv-rag/Scripts/python.exe rag_embed.py search heinrich-capital "qué es el trabajo abstracto" -k 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

import rag_lib  # extracción + troceado (puro Python)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

MODEL_NAME = "intfloat/multilingual-e5-base"
RAG_DIR = Path(__file__).with_name("rag_index")

_model = None


def modelo():
    """Carga perezosa del modelo (la 1ª vez descarga ~1.1 GB)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"→ Cargando modelo {MODEL_NAME} (1ª vez descarga ~1.1 GB)...", flush=True)
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _emb(textos: list[str], prefijo: str) -> np.ndarray:
    """Embeddings normalizados. e5 requiere prefijos 'query:'/'passage:'."""
    m = modelo()
    pares = [f"{prefijo}{t}" for t in textos]
    v = m.encode(pares, normalize_embeddings=True, show_progress_bar=True, batch_size=32)
    return np.asarray(v, dtype=np.float32)


def _h(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()


def emb_passages_cache(textos: list[str], destino: Path) -> np.ndarray:
    """Embeddings de pasajes REUTILIZANDO el índice previo: solo embebe los trozos cuyo
    texto cambió (hash distinto). Convierte un reindexado completo (~10 min) en segundos
    cuando casi nada cambió. Guarda `hashes.json` junto a `vectors.npy`."""
    hp = destino / "hashes.json"
    vp = destino / "vectors.npy"
    prev: dict[str, np.ndarray] = {}
    if hp.exists() and vp.exists():
        try:
            old_hashes = json.loads(hp.read_text(encoding="utf-8"))
            old_vecs = np.load(vp)
            if len(old_hashes) == len(old_vecs):
                prev = {h: old_vecs[i] for i, h in enumerate(old_hashes)}
        except Exception:
            prev = {}
    hashes = [_h(t) for t in textos]
    faltan = [(i, t) for i, (t, h) in enumerate(zip(textos, hashes)) if h not in prev]
    if faltan:
        print(f"→ Embebiendo {len(faltan)} trozos nuevos/cambiados "
              f"(reuso {len(textos) - len(faltan)} de caché)…", flush=True)
        nuevos = _emb([t for _, t in faltan], prefijo="passage: ")
        for (i, _), v in zip(faltan, nuevos):
            prev[hashes[i]] = v
    else:
        print("→ Sin cambios: 100% reusado de caché (no se embebe nada).", flush=True)
    dim = next(iter(prev.values())).shape[0]
    out = np.zeros((len(textos), dim), dtype=np.float32)
    for i, h in enumerate(hashes):
        out[i] = prev[h]
    hp.write_text(json.dumps(hashes), encoding="utf-8")
    return out


def ingest(libro: Path, slug: str) -> None:
    destino = RAG_DIR / slug
    destino.mkdir(parents=True, exist_ok=True)

    # 1) Mismos trozos que el BM25 (con sección + página).
    chunks = rag_lib.chunks_de(libro)
    if not chunks:
        print(f"⚠ {libro.name}: 0 trozos extraíbles (¿EPUB sin texto plano o protegido?). Omitido.")
        return
    (destino / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n",
        encoding="utf-8")
    print(f"→ {len(chunks)} trozos extraídos (sin front/back matter).")

    # 2) Embeddings de los pasajes.
    vecs = _emb([c["texto"] for c in chunks], prefijo="passage: ")
    np.save(destino / "vectors.npy", vecs)
    (destino / "meta.json").write_text(json.dumps(
        {"slug": slug, "libro": libro.name, "n_chunks": len(chunks),
         "model": MODEL_NAME, "dim": int(vecs.shape[1])},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Índice semántico guardado en {destino}  ({vecs.shape}).")


def search(slug: str, query: str, k: int = 5) -> list[dict]:
    destino = RAG_DIR / slug
    vecs = np.load(destino / "vectors.npy")
    chunks = [json.loads(l) for l in (destino / "chunks.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    q = _emb([query], prefijo="query: ")[0]
    sims = vecs @ q  # coseno (todo normalizado)
    idx = np.argsort(-sims)[:k]
    out = []
    for i in idx:
        c = dict(chunks[int(i)])
        c["score"] = round(float(sims[int(i)]), 3)
        out.append(c)
    return out


def _slug_tema() -> dict[str, str]:
    """Mapa slug→tema escaneando biblioteca/<tema>/* (el índice 'mis-notas' → 'notas')."""
    from config import BIBLIOTECA, slug_libro
    m: dict[str, str] = {}
    if BIBLIOTECA.exists():
        for td in BIBLIOTECA.iterdir():
            if td.is_dir() and not td.name.startswith(("_", ".")):
                for f in td.iterdir():
                    if f.is_file() and f.suffix.lower() in (
                            ".epub", ".pdf", ".mobi", ".azw3", ".md", ".txt"):
                        m[slug_libro(f)] = td.name
    return m


def search_all(query: str, k: int = 5, temas: set[str] | None = None,
               slugs: set[str] | None = None) -> list[dict]:
    """Busca en el corpus y fusiona por score (semántico). Cada resultado lleva su 'slug'
    y 'tema' de origen. Si `temas` se da, solo busca en esos géneros. Si `slugs` se da,
    solo busca en esos índices exactos (para agenets de autor). Embebe la consulta UNA vez."""
    q = _emb([query], prefijo="query: ")[0]
    s2t = _slug_tema()  # mapa slug→tema (barato; siempre, para etiquetar el origen)
    pool: list[dict] = []
    for d in sorted(RAG_DIR.glob("*")):
        vp, cp = d / "vectors.npy", d / "chunks.jsonl"
        if not (vp.exists() and cp.exists()):
            continue
        if slugs is not None and d.name not in slugs:
            continue
        tema = s2t.get(d.name, "notas" if d.name == "mis-notas" else "?")
        if temas is not None and tema not in temas:
            continue
        vecs = np.load(vp)
        chunks = [json.loads(l) for l in cp.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(chunks) != len(vecs):
            continue
        sims = vecs @ q
        for i in np.argsort(-sims)[:k]:
            c = dict(chunks[int(i)])
            c["score"] = round(float(sims[int(i)]), 3)
            c["slug"] = d.name
            c["tema"] = tema
            pool.append(c)
    pool.sort(key=lambda c: c["score"], reverse=True)
    return pool[:k]


def search_hybrid(slug: str, query: str, k: int = 5, pool: int = 20) -> list[dict]:
    """Fusiona semántico (cross-lingual) + BM25 (términos exactos/nombres propios) con
    Reciprocal Rank Fusion. Mejor para términos técnicos y nombres que el embedding difumina."""
    sem = search(slug, query, pool)
    try:
        lex = rag_lib.buscar(slug, query, pool)
    except Exception:
        lex = []
    C = 60  # constante RRF estándar
    fus: dict = {}
    for ranking in (sem, lex):
        for rank, r in enumerate(ranking):
            e = fus.setdefault(r["id"], {"r": r, "s": 0.0})
            e["s"] += 1.0 / (C + rank)
    orden = sorted(fus.values(), key=lambda x: x["s"], reverse=True)[:k]
    out = []
    for f in orden:
        c = dict(f["r"]); c["score"] = round(f["s"], 4); out.append(c)
    return out


def _cita(r: dict) -> str:
    sec = (r.get("sec") or "").strip()
    pg = r.get("page")
    partes = [r.get("cap", "?")]
    if sec:
        partes.append(f"§ {sec[:70]}")
    if pg:
        partes.append(f"p. {pg}")
    return " · ".join(partes)


def _print(res: list[dict]) -> None:
    for r in res:
        origen = f"{r['slug']} · " if r.get("slug") else ""
        print(f"\n[{r['score']:.3f}] ({origen}{_cita(r)})")
        print("  " + r["texto"][:600] + ("…" if len(r["texto"]) > 600 else ""))


def _via_server(cmd: str, params: dict) -> list[dict] | None:
    """Intenta el servidor RAG persistente (rag_server.py). None si no está corriendo."""
    import urllib.error
    import urllib.parse
    import urllib.request
    url = f"http://127.0.0.1:8765/{cmd}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read())
        return data if isinstance(data, list) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None  # servidor caído → el llamador cae al modo en-proceso


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="RAG semántico local.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("ingest"); pi.add_argument("libro"); pi.add_argument("--slug", required=True)
    ps = sub.add_parser("search"); ps.add_argument("slug"); ps.add_argument("query"); ps.add_argument("-k", type=int, default=5)
    ph = sub.add_parser("hybrid", help="semántico + BM25 (RRF) en un libro"); ph.add_argument("slug"); ph.add_argument("query"); ph.add_argument("-k", type=int, default=5)
    pa = sub.add_parser("search-all", help="busca en TODO el corpus"); pa.add_argument("query"); pa.add_argument("-k", type=int, default=5)
    pa.add_argument("--tema", default=None, help="filtra por géneros (coma-separados): p.ej. marx,filo,ecol")
    pa.add_argument("--slugs", default=None, help="filtra por slugs exactos (coma-separados): para agentes de autor")
    a = p.parse_args()
    if a.cmd == "ingest":
        ingest(Path(a.libro), a.slug)
    elif a.cmd == "hybrid":
        _print(_via_server("hybrid", {"slug": a.slug, "q": a.query, "k": a.k}) or search_hybrid(a.slug, a.query, a.k))
    elif a.cmd == "search-all":
        temas = {t.strip() for t in a.tema.split(",")} if a.tema else None
        slugs = {s.strip() for s in a.slugs.split(",")} if a.slugs else None
        params: dict = {"q": a.query, "k": a.k}
        if a.tema:
            params["tema"] = a.tema
        if a.slugs:
            params["slugs"] = a.slugs
        _print(_via_server("search-all", params) or search_all(a.query, a.k, temas, slugs))
    else:
        _print(_via_server("search", {"slug": a.slug, "q": a.query, "k": a.k}) or search(a.slug, a.query, a.k))
