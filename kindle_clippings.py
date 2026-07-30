"""
kindle_clippings.py — rescata y estructura TODAS las notas/subrayados del Kindle.

El Kindle guarda cada subrayado, nota y marcador en  documents/My Clippings.txt  (texto
plano). Este script lo parsea, agrupa por libro, quita duplicados típicos del Kindle
(selecciones que se solapan) y exporta:
  - notas/kindle/clippings.json   (estructurado, para volcar a Notion / RAG)
  - notas/kindle/<Libro>.md       (uno por libro, legible)

Soporta metadatos en inglés y español (Highlight/Note vs Subrayado/Nota; page/página; etc.).

Uso:
  1. Conecta el Kindle por USB. Busca el archivo (suele estar en E:\\documents\\My Clippings.txt).
  2. python kindle_clippings.py "E:\\documents\\My Clippings.txt"
     (o copia el archivo aquí y pásale la ruta local).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

SALIDA = Path(__file__).with_name("kindle")
SEP = re.compile(r"^=+\s*$", re.MULTILINE)


def _tipo(meta: str) -> str:
    m = meta.lower()
    if "highlight" in m or "subrayad" in m:
        return "subrayado"
    if "note" in m or "nota" in m:
        return "nota"
    if "bookmark" in m or "marcador" in m:
        return "marcador"
    return "otro"


def _num(patron: str, meta: str) -> str | None:
    m = re.search(patron, meta, re.IGNORECASE)
    return m.group(1) if m else None


def _titulo_autor(linea: str) -> tuple[str, str]:
    """'El Capital (Karl Marx)' -> ('El Capital', 'Karl Marx'). Autor = último (...)."""
    linea = linea.lstrip("﻿").strip()
    m = re.search(r"\(([^()]*)\)\s*$", linea)
    if m:
        return linea[:m.start()].strip(), m.group(1).strip()
    return linea, ""


def parsear(path: Path) -> list[dict]:
    texto = path.read_text(encoding="utf-8-sig", errors="replace")
    registros = []
    for bloque in SEP.split(texto):
        lineas = [l for l in bloque.splitlines()]
        # quita líneas vacías al inicio/fin manteniendo el cuerpo
        while lineas and not lineas[0].strip():
            lineas.pop(0)
        while lineas and not lineas[-1].strip():
            lineas.pop()
        if len(lineas) < 2:
            continue
        titulo, autor = _titulo_autor(lineas[0])
        meta = lineas[1]
        cuerpo = "\n".join(lineas[2:]).strip()
        tipo = _tipo(meta)
        if tipo in ("marcador", "otro") and not cuerpo:
            continue
        registros.append({
            "libro": titulo,
            "autor": autor,
            "tipo": tipo,
            "pagina": _num(r"(?:page|p[áa]gina)\s+([0-9ivxlcdmIVXLCDM\-]+)", meta),
            "ubicacion": _num(r"(?:location|posici[óo]n|loc\.?)\s+([0-9\-]+)", meta),
            "fecha": (re.split(r"(?:Added on|A[ñn]adido el)\s+", meta, maxsplit=1) + [""])[-1].strip(),
            "texto": cuerpo,
        })
    return registros


def _loc_ini(r: dict) -> int:
    u = r.get("ubicacion") or ""
    m = re.match(r"(\d+)", u)
    return int(m.group(1)) if m else -1


def deduplicar(regs: list[dict]) -> list[dict]:
    """
    Quita registros redundantes (artefacto del Kindle: cada edición de un subrayado o nota
    se guarda como entrada nueva, progresivamente más larga/corta). Agrupa por
    libro+tipo+ubicación y, dentro de cada grupo, descarta los que son subcadena de otro,
    quedándose con la versión más completa.
    """
    from collections import defaultdict
    for i, r in enumerate(regs):
        r["_i"] = i  # orden cronológico (el archivo está en orden)

    # NOTAS: cada edición se reguarda; quedarse con la ÚLTIMA por (libro, ubicación).
    ultimas: dict[tuple, dict] = {}
    for r in (x for x in regs if x["tipo"] == "nota"):
        k = (r["libro"], r.get("ubicacion"))
        if k not in ultimas or r["_i"] > ultimas[k]["_i"]:
            ultimas[k] = r
    out = list(ultimas.values())

    # SUBRAYADOS/otros: descartar subcadenas dentro de (libro, tipo, ubicación).
    grupos: dict[tuple, list[dict]] = defaultdict(list)
    for r in (x for x in regs if x["tipo"] != "nota"):
        grupos[(r["libro"], r["tipo"], r.get("ubicacion"))].append(r)
    for items in grupos.values():
        items.sort(key=lambda r: -len(r["texto"]))
        mantenidos: list[dict] = []
        for r in items:
            if r["texto"] and any(r["texto"] in m["texto"] for m in mantenidos):
                continue
            mantenidos.append(r)
        out.extend(mantenidos)

    for r in out:
        r.pop("_i", None)
    out.sort(key=lambda r: (r["libro"], _loc_ini(r)))
    return out


def exportar(regs: list[dict]) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "clippings.json").write_text(
        json.dumps(regs, ensure_ascii=False, indent=2), encoding="utf-8")
    por_libro: dict[str, list[dict]] = {}
    for r in regs:
        por_libro.setdefault(r["libro"], []).append(r)
    for libro, items in sorted(por_libro.items()):
        autor = next((i["autor"] for i in items if i["autor"]), "")
        safe = re.sub(r'[<>:"/\\|?*]', "", libro)[:120].strip() or "Sin titulo"
        lineas = [f"# {libro}", f"*{autor}*" if autor else "", ""]
        for r in sorted(items, key=_loc_ini):
            loc = f"loc. {r['ubicacion']}" if r["ubicacion"] else (f"p. {r['pagina']}" if r["pagina"] else "")
            if r["tipo"] == "nota":
                lineas.append(f"> **📝 Nota** ({loc}): {r['texto']}\n")
            else:
                lineas.append(f"- {r['texto']}  \n  <sub>{loc}</sub>\n")
        (SALIDA / f"{safe}.md").write_text("\n".join(lineas), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Parsea My Clippings.txt del Kindle.")
    p.add_argument("archivo", help="ruta a My Clippings.txt")
    a = p.parse_args()
    path = Path(a.archivo)
    if not path.exists():
        sys.exit(f"No existe: {path}")
    regs = deduplicar(parsear(path))
    exportar(regs)

    libros: dict[str, dict] = {}
    for r in regs:
        d = libros.setdefault(r["libro"], {"subrayado": 0, "nota": 0, "autor": r["autor"]})
        d[r["tipo"]] = d.get(r["tipo"], 0) + 1
    print(f"✓ {len(regs)} notas de {len(libros)} libros → {SALIDA}\n")
    for libro, d in sorted(libros.items()):
        print(f"  • {libro[:60]:60}  {d.get('subrayado',0):>3} subr · {d.get('nota',0):>2} notas")


if __name__ == "__main__":
    main()
