"""
vault_tools.py — utilidades compartidas para cerrar el bucle bajar → catalogar → anotar.

- ya_lo_tienes(titulo): avisa si un libro con título parecido ya está en biblioteca/ o en
  Google Drive (evita descargas duplicadas). NO bloquea — solo informa.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

AQUI = Path(__file__).parent
BIBLIOTECA = AQUI / "biblioteca"
DRIVE = Path(r"G:\My Drive\Biblioteca")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|z-?library|\.epub|\.pdf|\.mobi", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def _palabras_clave(titulo: str) -> set[str]:
    stop = {"the", "a", "an", "of", "and", "to", "in", "el", "la", "los", "las", "de",
            "del", "y", "un", "una", "for", "how", "on", "is"}
    return {w for w in _norm(titulo).split() if len(w) > 2 and w not in stop}


def _inventario() -> list[tuple[str, str]]:
    """(nombre_normalizado, ruta_legible) de todo lo que ya hay en biblioteca/ y Drive."""
    inv: list[tuple[str, str]] = []
    for base, etiqueta in ((BIBLIOTECA, "biblioteca"), (DRIVE, "Drive")):
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".epub", ".pdf", ".mobi", ".azw3"):
                inv.append((_norm(p.stem), f"{etiqueta}/{p.parent.name}/{p.name}"))
    return inv


def ya_lo_tienes(titulo: str, umbral: float = 0.6) -> str | None:
    """Devuelve la ruta del archivo existente si hay un solapamiento alto de palabras
    clave con `titulo`; si no, None. Pensado para avisar antes de descargar."""
    claves = _palabras_clave(titulo)
    if not claves:
        return None
    mejor, mejor_score = None, 0.0
    for norm, ruta in _inventario():
        tokens = set(norm.split())
        if not tokens:
            continue
        score = len(claves & tokens) / len(claves)
        if score > mejor_score:
            mejor, mejor_score = ruta, score
    return mejor if mejor_score >= umbral else None


def avisar_si_duplicado(titulo: str) -> bool:
    """Imprime un aviso si el libro ya existe. Devuelve True si se halló duplicado."""
    hit = ya_lo_tienes(titulo)
    if hit:
        print(f"  ⚠️  Posible duplicado: ya tienes algo parecido → «{hit}»")
        print("     (descargo igual porque lo pediste explícito; cancela con Ctrl-C si no querías).")
        return True
    return False


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Capital Marx"
    print(ya_lo_tienes(q) or "(no encontrado en biblioteca/ ni Drive)")
