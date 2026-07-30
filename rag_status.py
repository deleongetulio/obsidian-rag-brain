"""
rag_status.py — lista qué libros/colecciones están indexados en el RAG (citables verbatim).

Solo lee los meta.json (stdlib), así que corre con el Python del sistema, SIN el venv.
El tutor lo usa para saber de qué puede dar cita textual y de qué no.

Uso:  python rag_status.py
"""
import json
import sys
from pathlib import Path

RAG = Path(__file__).with_name("rag_index")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if not RAG.exists():
        print("(no hay índices RAG todavía)")
        return
    filas = []
    for meta in sorted(RAG.glob("*/meta.json")):
        m = json.loads(meta.read_text(encoding="utf-8"))
        filas.append((meta.parent.name, m.get("libro", ""), m.get("n_chunks", 0)))
    print(f"📚 {len(filas)} índices RAG — citables VERBATIM:\n")
    for slug, libro, n in filas:
        etiqueta = libro or slug
        print(f"  • [{slug}]  {etiqueta}  ({n} trozos)")
    print("\nPara cualquier libro que NO esté en esta lista: el tutor solo tiene "
          "conocimiento general (no debe inventar citas textuales).")


if __name__ == "__main__":
    main()
