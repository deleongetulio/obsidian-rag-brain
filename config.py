"""
config.py — constantes y utilidades compartidas del agente.

Centraliza lo que estaba duplicado en varios scripts: rutas, lista de temas, el slug
de índice RAG, y el arreglo de UTF-8 de la consola de Windows. Importa de aquí en vez
de redefinir.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
BIBLIOTECA = AQUI / "biblioteca"
RAG_DIR = AQUI / "rag_index"
NOTAS = Path.home() / "Documents" / "Obsidian" / "Obsidian"  # ajustar a tu propio vault
KINDLE_DATOS = AQUI / "datos-kindle"
CLIPPINGS_TXT = AQUI / "My Clippings.txt"
VENV_PY = AQUI / ".venv-rag" / "Scripts" / "python.exe"

# Espejo de la biblioteca en Google Drive para Escritorio (puede no existir).
DRIVE = Path(r"G:\My Drive\Biblioteca")

# Rocketbook: la app enruta cada pagina (por el simbolo marcado) a una subcarpeta de
# esta ruta de Drive. Los raw escaneados se archivan fuera de todo sync en DATOS_ROCKETBOOK.
ROCKETBOOK = Path(r"G:\My Drive\Rocketbook")
DATOS_ROCKETBOOK = AQUI / "datos-rocketbook"

# Géneros = subcarpetas de biblioteca/ (ver notas/generos_biblioteca.md).
TEMAS = ["econ", "marx", "filo", "crit", "psic", "antr", "hist", "cari",
         "raza", "femi", "anar", "ecol", "geop", "tech", "lite", "cien"]

# Notion "Media List" (data source) — catálogo espejo de la biblioteca.
# Sustituir por el ID de tu propio data source de Notion.
NOTION_DATASOURCE = "your-notion-datasource-id"


def slug_libro(p: Path) -> str:
    """Slug de índice RAG desde el nombre de un libro (quita paréntesis/[..]/z-library)."""
    stem = p.stem if isinstance(p, Path) else str(p)
    s = re.sub(r"\(.*?\)|\[.*?\]|z-library", "", stem, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:45]


def utf8() -> None:
    """Fuerza UTF-8 en stdout/stderr (la consola de Windows usa cp1252 por defecto)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
