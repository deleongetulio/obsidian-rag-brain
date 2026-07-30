"""
enlazar_notas.py — ENLAZA la nota del móvil con el subrayado exacto del Kindle.

Idea: lees en el Kindle, subrayas un pasaje y, al mandarte la nota desde el móvil,
antepones el número de *location* que muestra el Kindle. Este script lee My Clippings.txt,
busca el subrayado más cercano a esa location en ese libro, y REESCRIBE la nota del inbox
para que incluya la CITA VERBATIM bajo tu pensamiento. Así no transcribes la cita: la pesca
el script, y tu idea queda pegada al pasaje exacto (no solo al libro).

Corre ANTES de archivar_inbox.py: enriquece la nota; archivar_inbox la archiva como siempre.
Las notas SIN ancla (o cuya location no cae cerca de ningún subrayado) se dejan intactas
→ archivar_inbox las trata con su lógica normal. Cero regresión.

Refresco de subrayados AUTOMÁTICO: si el Kindle está conectado por USB, copia su
My Clippings.txt a notas/ solo (Win/Linux/macOS); si no, usa el que ya esté ahí. Así el sync
semanal queda al día sin pasos manuales. Desactívalo con --no-usb.

Convención del correo (desde el móvil):
  Asunto:  nota: <Libro>
  Cuerpo:  <location> <tu pensamiento>      p. ej.  "6343 la fe secular apunta a una causa"
  (también valen prefijos: "loc 6343 …", "@6343 …", "[6343] …")

Uso:
  python enlazar_notas.py            # enriquece notas/inbox/ en sitio
  python enlazar_notas.py --dry      # muestra qué haría, sin escribir
  python enlazar_notas.py --tol 150  # tolerancia de cercanía de location (def. 100)
"""
from __future__ import annotations

import argparse
import glob
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from config import NOTAS, KINDLE_DATOS, CLIPPINGS_TXT, utf8
from kindle_clippings import parsear, deduplicar, exportar

utf8()
INBOX = NOTAS / "inbox"
CLIPPINGS_JSON = KINDLE_DATOS / "clippings.json"

# Palabras de bajo valor para emparejar el libro (igual criterio que archivar_inbox).
STOP = {"the", "and", "for", "una", "uno", "los", "las", "del", "con", "por", "very",
        "a", "an", "of", "to", "in", "el", "la", "de", "y", "un"}

# Ancla de location al inicio del cuerpo: dígitos, con prefijo opcional (loc/pos/@/#/[..]).
RE_ANCLA = re.compile(
    r"^\s*(?:loc(?:ation|\.)?|posici[oó]n|pos\.?|ubic\.?|[@#])?\s*\[?\s*"
    r"(\d{2,6})\s*\]?\s*[:\-–—.]?\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _toks(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]+", s) if len(w) > 2 and w not in STOP}


def _frontmatter(doc: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    if doc.startswith("---"):
        for ln in doc.split("---", 2)[1].splitlines():
            if ":" in ln:
                k, _, v = ln.partition(":")
                fm[k.strip()] = v.strip().strip('"')
    return fm


def _cuerpo(doc: str) -> str:
    """El texto de la nota: lo que va tras el frontmatter y el '# Título' inicial."""
    cuerpo = doc.split("---", 2)[2] if doc.startswith("---") else doc
    lineas = cuerpo.splitlines()
    while lineas and (not lineas[0].strip() or lineas[0].lstrip().startswith("#")):
        lineas.pop(0)
    return "\n".join(lineas).strip()


def _rango(ubic: str | None) -> tuple[int, int] | None:
    """'6342-6345' -> (6342, 6345); '6345' -> (6345, 6345); None si no hay número."""
    if not ubic:
        return None
    nums = [int(n) for n in re.findall(r"\d+", ubic)]
    if not nums:
        return None
    return (nums[0], nums[-1])


def _kindles_conectados() -> list[Path]:
    """Rutas a 'documents/My Clippings.txt' de cualquier Kindle montado (Win/Linux/macOS)."""
    cands: list[Path] = []
    if sys.platform.startswith("win"):
        import ctypes
        import string
        k32 = ctypes.windll.kernel32
        prev = k32.SetErrorMode(1)  # SEM_FAILCRITICALERRORS: sin diálogos "inserte disco"
        try:
            for letra in string.ascii_uppercase:
                if letra == "C":
                    continue
                raiz = f"{letra}:\\"
                if k32.GetDriveTypeW(raiz) not in (2, 3):  # 2=extraíble, 3=fijo
                    continue
                p = Path(raiz) / "documents" / "My Clippings.txt"
                try:
                    if p.exists():
                        cands.append(p)
                except OSError:
                    pass
        finally:
            k32.SetErrorMode(prev)
    else:  # Linux / macOS: puntos de montaje habituales
        for pat in ("/media/*/*/documents/My Clippings.txt",
                    "/run/media/*/*/documents/My Clippings.txt",
                    "/media/*/documents/My Clippings.txt",
                    "/Volumes/*/documents/My Clippings.txt"):
            cands += [Path(x) for x in glob.glob(pat)]
    return cands


def refrescar_desde_kindle() -> None:
    """Si hay un Kindle conectado por USB, copia su My Clippings.txt a notas/ (si es más
    nuevo). Silencioso si no hay Kindle: se usa el que ya esté en notas/."""
    cands = _kindles_conectados()
    if not cands:
        return
    fuente = max(cands, key=lambda p: p.stat().st_mtime)
    try:
        d = CLIPPINGS_TXT
        if (not d.exists() or fuente.stat().st_size != d.stat().st_size
                or fuente.stat().st_mtime > d.stat().st_mtime):
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fuente, d)
            print(f"  ⎘ Kindle detectado en {fuente.parents[1]} → copiado a notas/My Clippings.txt")
    except OSError as e:
        print(f"  ⚠ no pude copiar de {fuente}: {e}")


def cargar_subrayados(usb: bool = True) -> list[dict]:
    """Subrayados del Kindle (solo tipo 'subrayado', con location parseable).
    Si `usb`, primero intenta refrescar My Clippings.txt desde un Kindle conectado."""
    if usb:
        refrescar_desde_kindle()
    if not CLIPPINGS_TXT.exists():
        return []
    regs = deduplicar(parsear(CLIPPINGS_TXT))
    # De paso, refresca kindle/clippings.json (lo lee indexar_notas para 'mis-notas').
    try:
        if not CLIPPINGS_JSON.exists() or \
                CLIPPINGS_TXT.stat().st_mtime > CLIPPINGS_JSON.stat().st_mtime:
            exportar(regs)
    except OSError:
        pass
    subs = []
    for r in regs:
        if r["tipo"] != "subrayado" or not (r.get("texto") or "").strip():
            continue
        rg = _rango(r.get("ubicacion"))
        if rg:
            r["_rango"] = rg
            subs.append(r)
    return subs


def libro_de_nota(libro: str, subs: list[dict]) -> str | None:
    """Resuelve a qué libro del Kindle se refiere el asunto de la nota (título o autor)."""
    objetivo = _toks(libro)
    if not objetivo:
        return None
    por_libro: dict[str, set[str]] = {}
    for r in subs:
        toks = _toks(r["libro"]) | _toks(r.get("autor", ""))
        por_libro.setdefault(r["libro"], set()).update(toks)
    puntuados = sorted((len(objetivo & toks), lib) for lib, toks in por_libro.items())
    if not puntuados or puntuados[-1][0] == 0:
        return None
    mejor_n, mejor = puntuados[-1]
    segundo_n = puntuados[-2][0] if len(puntuados) > 1 else -1
    if segundo_n == mejor_n:  # empate entre libros → no adivinar
        return None
    return mejor


def subrayado_cercano(loc: int, libro: str, subs: list[dict], tol: int) -> dict | None:
    """El subrayado de `libro` cuya location está más cerca de `loc` (dentro de `tol`)."""
    mejor, mejor_d = None, tol + 1
    for r in subs:
        if r["libro"] != libro:
            continue
        a, b = r["_rango"]
        d = 0 if a <= loc <= b else min(abs(loc - a), abs(loc - b))
        if d < mejor_d:
            mejor, mejor_d = r, d
    return mejor


def enriquecer(cuerpo: str, sub: dict) -> str:
    """Pone tu pensamiento y, pegada debajo (sin línea en blanco → un solo trozo RAG),
    la cita verbatim con su location."""
    cita = " ".join((sub["texto"] or "").split())
    loc = sub.get("ubicacion") or ""
    return f"{cuerpo}\n> {cita} (loc. {loc})"


def main() -> None:
    ap = argparse.ArgumentParser(description="Enlaza la nota del móvil con el subrayado del Kindle.")
    ap.add_argument("--dry", action="store_true", help="muestra qué haría, sin escribir")
    ap.add_argument("--tol", type=int, default=100, help="cercanía máx. de location (def. 100)")
    ap.add_argument("--no-usb", action="store_true", help="no buscar el Kindle conectado por USB")
    a = ap.parse_args()

    subs = cargar_subrayados(usb=not a.no_usb)
    if not subs:
        print("(sin subrayados: conecta el Kindle y copia 'My Clippings.txt' a notas/)")
        return

    notas = [p for p in sorted(INBOX.rglob("*.md")) if p.name != "README.md"]
    if not notas:
        print("(inbox vacío)")
        return

    n_enl = n_sin = n_lejos = 0
    for p in notas:
        doc = p.read_text(encoding="utf-8")
        fm = _frontmatter(doc)
        libro = fm.get("libro", "") or p.stem
        cuerpo = _cuerpo(doc)

        if re.search(r"(?m)^>\s+.*\(loc\.", cuerpo):  # ya enlazada (idempotente)
            continue
        m = RE_ANCLA.match(cuerpo)
        if not m:
            n_sin += 1
            continue
        loc, pensamiento = int(m.group(1)), m.group(2).strip()

        klibro = libro_de_nota(libro, subs)
        sub = subrayado_cercano(loc, klibro, subs, a.tol) if klibro else None
        if not sub:
            # Hay ancla pero no resuelve: deja la nota intacta (archivar_inbox la maneja).
            n_lejos += 1
            print(f"  ⚠ «{libro[:32]}» loc {loc}: no hallé subrayado cerca "
                  f"({'libro no identificado' if not klibro else 'fuera de tolerancia'}). "
                  f"La dejo sin enlazar.")
            continue

        nuevo_cuerpo = enriquecer(pensamiento, sub)
        cita_prev = " ".join((sub["texto"] or "").split())[:60]
        print(f"  ✓ «{libro[:32]}» loc {loc} → loc. {sub.get('ubicacion')}: “{cita_prev}…”")
        if not a.dry:
            nuevo_doc = doc[: doc.index(cuerpo)] + nuevo_cuerpo + "\n"
            p.write_text(nuevo_doc, encoding="utf-8")
        n_enl += 1

    sufijo = " (dry-run: no se escribió nada)" if a.dry else ""
    print(f"\n{n_enl} nota(s) enlazada(s) a su cita · {n_sin} sin ancla · "
          f"{n_lejos} con ancla sin match.{sufijo}")
    if n_enl and not a.dry:
        print("Ahora corre  python archivar_inbox.py  para archivarlas en libros/.")


if __name__ == "__main__":
    main()
