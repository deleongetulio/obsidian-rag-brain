"""
indexar_notas.py — indexa TODAS tus notas (Kindle + Neat Reader) en un índice RAG
llamado 'mis-notas', para que el tutor pueda recuperar y dialogar con tu propio pensamiento.

Corre en el venv:
  .venv-rag/Scripts/python.exe indexar_notas.py

Luego el tutor busca tus notas con:
  .venv-rag/Scripts/python.exe rag_embed.py search mis-notas "tu tema"
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

import rag_embed as R

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))
from config import NOTAS, KINDLE_DATOS  # noqa: E402
OUT = AQUI / "rag_index" / "mis-notas"


def _quitar_frontmatter(txt: str) -> str:
    if txt.startswith("---"):
        partes = txt.split("---", 2)
        if len(partes) == 3:
            return partes[2]
    return txt


def _trozos(texto: str, maxlen: int = 700) -> list[str]:
    """Parte un markdown en trozos por párrafo/viñeta, ignorando ruido (callouts vacíos)."""
    out: list[str] = []
    buf = ""
    for linea in texto.splitlines():
        l = linea.strip()
        if not l or l.startswith("#") or l.startswith("> [!") or l.startswith("**Autor") \
                or l.startswith("**Fuente") or set(l) <= {"-", "—", "·"}:
            if buf:
                out.append(buf.strip()); buf = ""
            continue
        l = re.sub(r"^[>*\-\s]+", "", l)  # limpia viñetas/blockquote
        if not l:
            continue
        buf = (buf + " " + l).strip()
        if len(buf) >= maxlen:
            out.append(buf.strip()); buf = ""
    if buf:
        out.append(buf.strip())
    return [t for t in out if len(t) >= 12]


def cargar_curadas() -> list[dict]:
    """Indexa el pensamiento CURADO de Getulio en Obsidian: las notas atómicas de
    `conceptos/` (enteras) y la sección 'Mis notas (digeridas)' de `libros/`
    (los subrayados crudos NO, porque ya entran vía el JSON de Kindle/NeatReader)."""
    chunks: list[dict] = []
    # Conceptos (notas atómicas, enteras)
    for p in sorted((NOTAS / "conceptos").glob("*.md")):
        if p.name.startswith("_"):  # _mapa.md y otras notas Dataview/MOC
            continue
        cuerpo = _quitar_frontmatter(p.read_text(encoding="utf-8"))
        for t in _trozos(cuerpo):
            chunks.append({"libro": f"⟦concepto⟧ {p.stem}", "loc": "", "tipo": "concepto",
                           "fuente": "Obsidian", "texto": t})
    # Libros: solo la sección 'Mis notas (digeridas)'
    for p in sorted((NOTAS / "libros").glob("*.md")):
        if p.name.startswith("_"):  # _indice.md
            continue
        doc = p.read_text(encoding="utf-8")
        m = re.search(r"## Mis notas.*?(?=\n## |\Z)", doc, flags=re.S)
        if not m:
            continue
        titulo = ""
        fm = re.search(r'titulo:\s*"?(.+?)"?\s*$', doc, flags=re.M)
        if fm:
            titulo = fm.group(1).strip()
        for t in _trozos(m.group(0)):
            chunks.append({"libro": titulo or p.stem, "loc": "mis notas", "tipo": "nota propia",
                           "fuente": "Obsidian", "texto": t})
    # Investigacion (notas de investigacion, enteras; se quitan los embeds de imagen)
    inv = NOTAS / "investigacion"
    if inv.exists():
        for p in sorted(inv.rglob("*.md")):
            if p.name.startswith("_"):
                continue
            cuerpo = _quitar_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            cuerpo = re.sub(r"!\[\[[^\]]*\]\]", "", cuerpo)      # embeds ![[img]]
            cuerpo = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", cuerpo)  # embeds ![](url)
            for t in _trozos(cuerpo):
                chunks.append({"libro": f"⟦investigacion⟧ {p.stem}", "loc": "", "tipo": "investigacion",
                               "fuente": "Obsidian", "texto": t})
    return chunks


def cargar() -> list[dict]:
    chunks: list[dict] = []
    # Neat Reader
    p = AQUI / "datos-kindle" / "neatreader" / "notes.json"
    if not p.exists():
        p = AQUI / "neatreader" / "notes.json"  # ruta legacy
    if p.exists():
        for r in json.load(open(p, encoding="utf-8")):
            nota = (r.get("nota") or "").strip()
            sub = (r.get("subrayado") or "").strip()
            texto = nota or sub
            if len(texto) < 3:
                continue
            chunks.append({"libro": r.get("libro", ""), "loc": r.get("capitulo", ""),
                           "tipo": "nota" if nota else "subrayado", "fuente": "Neat Reader",
                           "texto": texto})
    # Kindle
    p = KINDLE_DATOS / "clippings.json"
    if p.exists():
        for r in json.load(open(p, encoding="utf-8")):
            texto = (r.get("texto") or "").strip()
            if len(texto) < 3:
                continue
            loc = (f"loc. {r['ubicacion']}" if r.get("ubicacion")
                   else (f"p. {r['pagina']}" if r.get("pagina") else ""))
            chunks.append({"libro": r.get("libro", ""), "loc": loc,
                           "tipo": r.get("tipo", "subrayado"), "fuente": "Kindle",
                           "texto": texto})
    return chunks


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    crudos = cargar()
    curadas = cargar_curadas()
    print(f"→ Highlights crudos: {len(crudos)} · notas curadas (Obsidian): {len(curadas)}")
    crudos += curadas
    # Formato compatible con rag_embed.search: cap (libro) · sec (tipo+loc) · texto
    chunks = []
    for i, c in enumerate(crudos):
        chunks.append({"id": i, "cap": c["libro"],
                       "sec": f"{c['tipo']} · {c['loc']}".strip(" ·"),
                       "page": None, "texto": c["texto"], "fuente": c["fuente"]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")
    print(f"→ {len(chunks)} notas a indexar (incremental: solo lo nuevo se embebe)…", flush=True)
    vecs = R.emb_passages_cache([c["texto"] for c in chunks], OUT)
    np.save(OUT / "vectors.npy", vecs)
    (OUT / "meta.json").write_text(json.dumps(
        {"slug": "mis-notas", "libro": "⭐ MIS NOTAS (Kindle + Neat Reader)",
         "n_chunks": len(chunks), "model": R.MODEL_NAME, "dim": int(vecs.shape[1])},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Índice 'mis-notas' guardado ({vecs.shape}).")


if __name__ == "__main__":
    main()
