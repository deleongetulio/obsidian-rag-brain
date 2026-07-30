"""
repaso.py — repaso espaciado local (la idea buena de Readwise, sin la suscripcion ni la nube).

Saca N subrayados/notas al azar de tu Kindle (My Clippings.txt) y los deja en una nota del
vault (diario/<fecha>-repaso.md) para que reaparezcan pasajes viejos y no se mueran enterrados.
Local, gratis, tuyo: lee el MISMO My Clippings.txt que ya usa el pipeline, no manda nada a ningun
servidor. La nota se sincroniza al movil via Obsidian Sync, asi lo lees donde estes.

- Evita repetir lo que ya salio en los ultimos 7 dias (mira las notas de repaso recientes).
- Si un libro tiene su nota en libros/<slug>.md, enlaza [[slug]] para que saltes a tu nota.

Uso:
  python repaso.py            # 5 pasajes a diario/<hoy>-repaso.md
  python repaso.py --n 8      # 8 pasajes
  python repaso.py --dry      # imprime sin escribir
"""
from __future__ import annotations

import argparse
import random
import re
from datetime import date, timedelta
from pathlib import Path

from config import NOTAS, CLIPPINGS_TXT, slug_libro, utf8
from kindle_clippings import parsear, deduplicar

utf8()
DIARIO = NOTAS / "diario"
LIBROS = NOTAS / "libros"
MIN_LEN = 40  # ignora fragmentos cortos (subrayados de una palabra, etc.)


def _locs_recientes(dias: int = 7) -> set[str]:
    """Ubicaciones que ya aparecieron en notas de repaso de los ultimos `dias` (no repetir)."""
    if not DIARIO.exists():
        return set()
    corte = date.today() - timedelta(days=dias)
    vistas: set[str] = set()
    for p in DIARIO.glob("*-repaso.md"):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", p.name)
        if not m:
            continue
        if date(int(m[1]), int(m[2]), int(m[3])) < corte:
            continue
        for loc in re.findall(r"\(loc\.\s*([0-9\-]+)\)", p.read_text(encoding="utf-8")):
            vistas.add(loc)
    return vistas


def _enlace_libro(titulo: str) -> str:
    """[[slug]] si existe la nota del libro en libros/, si no el titulo a secas."""
    slug = slug_libro(Path(titulo + ".x"))
    if slug and (LIBROS / f"{slug}.md").exists():
        return f"[[{slug}]]"
    return f"*{titulo}*"


def main() -> None:
    ap = argparse.ArgumentParser(description="Repaso espaciado de subrayados del Kindle.")
    ap.add_argument("--n", type=int, default=5, help="cuantos pasajes (def. 5)")
    ap.add_argument("--dry", action="store_true", help="imprime sin escribir la nota")
    a = ap.parse_args()

    if not CLIPPINGS_TXT.exists():
        print(f"(no encuentro {CLIPPINGS_TXT.name}: conecta el Kindle o corre el sync primero)")
        return

    regs = deduplicar(parsear(CLIPPINGS_TXT))
    vistas = _locs_recientes()
    pool = [r for r in regs
            if r["tipo"] in ("subrayado", "nota")
            and len((r.get("texto") or "").strip()) >= MIN_LEN
            and (r.get("ubicacion") or "") not in vistas]

    if not pool:
        print("(sin pasajes nuevos que mostrar: o el Kindle esta vacio o ya repasaste todo esta semana)")
        return

    elegidos = random.sample(pool, min(a.n, len(pool)))

    hoy = date.today().isoformat()
    lineas = [f"# Repaso del {hoy}", "",
              f"{len(elegidos)} pasajes de tu Kindle para reencontrarte con lo que leiste.",
              "Si alguno te detona una idea, captura con QuickAdd o discutelo en /teoria-critica.", ""]
    for r in elegidos:
        cita = " ".join((r["texto"] or "").split())
        loc = r.get("ubicacion") or r.get("pagina") or "?"
        sello = "📝 (tu nota)" if r["tipo"] == "nota" else ""
        lineas.append(f"> {cita}")
        lineas.append(f"> — {_enlace_libro(r['libro'])} (loc. {loc}) {sello}".rstrip())
        lineas.append("")

    nota = "\n".join(lineas)
    if a.dry:
        print(nota)
        return

    DIARIO.mkdir(parents=True, exist_ok=True)
    destino = DIARIO / f"{hoy}-repaso.md"
    destino.write_text(nota, encoding="utf-8")
    print(f"✓ {len(elegidos)} pasaje(s) -> diario/{destino.name}  "
          f"(pool: {len(pool)} disponibles, {len(vistas)} excluidos por recientes)")


if __name__ == "__main__":
    main()
