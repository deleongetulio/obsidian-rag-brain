"""
graphrag.py — GraphRAG ligero (corre en el venv .venv-rag).

En vez de solo trocear y vectorizar, construye un GRAFO DE CONOCIMIENTO sobre tus conceptos:
- Nodos: los conceptos de notas/conceptos/ (tu framework) + los libros del corpus RAG.
- Aristas concepto↔concepto: DESCUBIERTAS por similitud de embeddings (qué conceptos están
  cerca en significado), comparables con las que TÚ declaraste a mano (wikilinks de Obsidian).
- Aristas concepto→libro: GROUNDING — en qué libros del corpus se desarrolla cada concepto
  (vía búsqueda semántica), con la cita textual de respaldo.

No requiere un LLM de extracción: reusa los embeddings locales (e5) y el corpus ya indexado.
Encaja con el proyecto de 4 capas: revela el puente físico→necropolítico grounded en los libros.

Uso (venv):
    .venv-rag/Scripts/python.exe graphrag.py build               # construye el grafo
    .venv-rag/Scripts/python.exe graphrag.py concept "Emergy"    # vecinos + grounding
    .venv-rag/Scripts/python.exe graphrag.py related "deuda termodinámica colonial"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

import rag_embed as R
from config import NOTAS, RAG_DIR, utf8

GRAPH = RAG_DIR / "graph.json"
GVECS = RAG_DIR / "graph_concepts.npy"

# Aristas TIPADAS sin LLM (idea de gbrain): el tipo de relacion sale de como YA escribes.
#  - Dataview inline:     critica:: [[Shaikh]]
#  - Linea etiquetada:    **Fuente:** ... [[Odum]]   /   - Relacionado: [[X]], [[Y]]
_DV = re.compile(r"([A-Za-zÁÉÍÓÚáéíóúÑñ_-]+)::\s*(.+)")
_LBL = re.compile(r"^\s*-?\s*\*{0,2}\s*([A-Za-zÁÉÍÓÚáéíóúÑñ][A-Za-zÁÉÍÓÚáéíóúÑñ ]{1,22}?)\s*\*{0,2}\s*:\s*(.+)$")
_LINK = re.compile(r"\[\[([^\]|#]+)")


def relaciones_tipadas(raw: str) -> list[tuple[str, str]]:
    """[(tipo_relacion, destino)] leyendo campos Dataview `::` y lineas etiquetadas con [[ ]]."""
    out: list[tuple[str, str]] = []
    for ln in raw.splitlines():
        if "[[" not in ln:
            continue
        m = _DV.search(ln) or _LBL.match(ln)
        if not m:
            continue
        rel = re.sub(r"\s+", "-", m.group(1).strip().lower())
        for dst in _LINK.findall(m.group(2)):
            out.append((rel, dst.strip()))
    return out


def cargar_conceptos() -> list[tuple[str, str, list[str], list[tuple[str, str]]]]:
    """[(nombre, texto, wikilinks_declarados, relaciones_tipadas)] desde conceptos/*.md (omite _*.md)."""
    out: list[tuple[str, str, list[str], list[tuple[str, str]]]] = []
    d = NOTAS / "conceptos"
    for p in sorted(d.glob("*.md")):
        if p.name.startswith("_"):
            continue
        raw = p.read_text(encoding="utf-8")
        typed = relaciones_tipadas(raw)
        if raw.startswith("---"):
            partes = raw.split("---", 2)
            if len(partes) == 3:
                raw = partes[2]
        decl = sorted(set(re.findall(r"\[\[([^\]|#]+)", raw)))  # wikilinks declarados
        body = re.sub(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", r"\1", raw)  # deja el nombre como texto
        body = re.sub(r"[#>*`_]", " ", body)
        body = re.sub(r"\s+", " ", body).strip()
        out.append((p.stem, body, decl, typed))
    return out


def build() -> None:
    utf8()
    conc = cargar_conceptos()
    if not conc:
        sys.exit("No hay notas en notas/conceptos/.")
    names = [c[0] for c in conc]
    print(f"→ Embebiendo {len(names)} conceptos…", flush=True)
    cvecs = R._emb([c[1] for c in conc], prefijo="query: ")  # normalizados

    # Aristas concepto↔concepto: top-3 por similitud de embedding (no triviales).
    sims = cvecs @ cvecs.T
    cc, seen = [], set()
    for i in range(len(names)):
        for j in np.argsort(-sims[i]):
            j = int(j)
            if j == i:
                continue
            key = tuple(sorted((i, j)))
            if key in seen:
                continue
            seen.add(key)
            cc.append({"a": names[i], "b": names[j], "w": round(float(sims[i, j]), 3)})
            if sum(1 for e in cc if names[i] in (e["a"], e["b"])) >= 3:
                break

    # Aristas concepto→libro: grounding en el corpus (excluye mis-notas para no auto-citarse).
    print("→ Aterrizando conceptos en los libros (grounding)…", flush=True)
    cb = []
    for name, text, _, _ in conc:
        byslug: dict[str, dict] = {}
        for h in R.search_all(text, k=8):
            s = h["slug"]
            if s == "mis-notas":
                continue
            if s not in byslug or h["score"] > byslug[s]["score"]:
                byslug[s] = {"slug": s, "tema": h.get("tema", "?"),
                             "score": h["score"], "cita": h["texto"][:200]}
        for t in sorted(byslug.values(), key=lambda x: -x["score"])[:4]:
            cb.append({"concepto": name, **t})

    declared = [{"a": n, "links": d} for (n, _, d, _) in conc]
    typed = [{"a": n, "rel": rel, "b": dst} for (n, _, _, ts) in conc for (rel, dst) in ts]
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    np.save(GVECS, cvecs)
    GRAPH.write_text(json.dumps(
        {"names": names, "cc": cc, "cb": cb, "declared": declared, "typed": typed},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Grafo: {len(names)} conceptos · {len(cc)} aristas concepto↔concepto · "
          f"{len(cb)} groundings concepto→libro · {len(typed)} aristas TIPADAS.  → {GRAPH}")


def _g() -> dict:
    if not GRAPH.exists():
        sys.exit("No hay grafo. Constrúyelo: graphrag.py build")
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def show_concept(name: str) -> None:
    utf8()
    g = _g()
    match = (next((n for n in g["names"] if n.lower() == name.lower()), None)
             or next((n for n in g["names"] if name.lower() in n.lower()), None))
    if not match:
        print("No existe. Conceptos:", ", ".join(g["names"]))
        return
    print(f"\n🧩 {match}")
    rel = sorted([e for e in g["cc"] if match in (e["a"], e["b"])], key=lambda x: -x["w"])[:5]
    print("\n  Conceptos cercanos (descubiertos por embedding):")
    for e in rel:
        otro = e["b"] if e["a"] == match else e["a"]
        print(f"    ~ {otro}  ({e['w']})")
    decl = next((d["links"] for d in g["declared"] if d["a"] == match), [])
    if decl:
        print("  Enlaces que declaraste en Obsidian:", ", ".join(decl))
    sal = [(e["rel"], e["b"]) for e in g.get("typed", []) if e["a"] == match]
    ent = [(e["rel"], e["a"]) for e in g.get("typed", []) if e["b"] == match]
    if sal:
        print("\n  Relaciones tipadas (salientes):")
        for rel, b in sal:
            print(f"    -[{rel}]-> {b}")
    if ent:
        print("  Relaciones tipadas (entrantes):")
        for rel, a in ent:
            print(f"    {a} -[{rel}]->")
    print("\n  Dónde lo desarrollan tus libros (grounding en el corpus):")
    for c in [x for x in g["cb"] if x["concepto"] == match]:
        print(f"    📖 [{c['tema']}] {c['slug']}  ({c['score']})")
        print(f"       “{c['cita'][:150]}…”")


def related(text: str) -> None:
    utf8()
    g = _g()
    cvecs = np.load(GVECS)
    q = R._emb([text], prefijo="query: ")[0]
    sims = cvecs @ q
    print("Conceptos de tu framework más cercanos a la consulta:")
    for i in np.argsort(-sims)[:5]:
        print(f"  ~ {g['names'][int(i)]}  ({round(float(sims[int(i)]), 3)})")


def search(query: str, k: int = 6, beta: float = 0.12) -> None:
    """Retrieval con SEÑAL DE GRAFO (opt-in; NO toca search_all del tutor).
    Sube los pasajes cuyos libros aterrizan los conceptos más cercanos a la consulta
    (adjacency boost, idea de gbrain). Marca [+grafo] lo que el grafo empujó."""
    utf8()
    g = _g()
    cvecs = np.load(GVECS)
    q = R._emb([query], prefijo="query: ")[0]
    top = [g["names"][int(i)] for i in np.argsort(-(cvecs @ q))[:3]]
    grounded = {c["slug"] for c in g["cb"] if c["concepto"] in top}
    res = R.search_all(query, k=max(k * 3, 12))
    for r in res:
        if r.get("slug") in grounded:
            r["score"] = round(r["score"] + beta, 3)
            r["grafo"] = True
    res.sort(key=lambda r: r["score"], reverse=True)
    print(f"Conceptos que guían el grafo: {', '.join(top)}")
    for r in res[:k]:
        marca = " [+grafo]" if r.get("grafo") else ""
        print(f"\n[{r['score']:.3f}]{marca} ({r.get('slug','?')} · {r.get('tema','?')})")
        print("  " + r["texto"][:300] + ("…" if len(r["texto"]) > 300 else ""))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="GraphRAG ligero sobre tus conceptos + corpus.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    pc = sub.add_parser("concept"); pc.add_argument("nombre")
    pr = sub.add_parser("related"); pr.add_argument("texto")
    ps = sub.add_parser("search", help="retrieval con señal de grafo (opt-in)")
    ps.add_argument("query"); ps.add_argument("-k", type=int, default=6)
    a = p.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "concept":
        show_concept(a.nombre)
    elif a.cmd == "search":
        search(a.query, a.k)
    else:
        related(a.texto)
