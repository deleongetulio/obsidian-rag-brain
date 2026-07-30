"""
neat_clippings.py — estructura las notas exportadas de Neat Reader (JSON en .txt).

Cada archivo es JSON: {"bookName": ..., "noteList": [{text, note, spineIndex,
startCharIndex, bgColor, showTime, ...}, ...]}.

La posición viene como spineIndex (capítulo en el orden del EPUB) + startCharIndex.
Este script resuelve spineIndex → TÍTULO DE CAPÍTULO cruzando con el EPUB real
(buscado en la carpeta de Neat Reader), y exporta:
  - notas/neatreader/<Libro>.md   (subrayados + notas, con capítulo y fecha)
  - notas/neatreader/notes.json   (todo unificado)

Uso:
  python neat_clippings.py
  python neat_clippings.py --notas "<dir de .txt>" --epubs "<dir con los EPUB>"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

AQUI = Path(__file__).parent
NOTAS_DIR = AQUI.parent / "biblioteca" / "_entrada" / "neat-reader" / "notas"
EPUB_ROOT = AQUI.parent / "biblioteca" / "_entrada" / "neat-reader"
SALIDA = AQUI / "neatreader"

_ATTR = lambda name, tag: (re.search(rf'{name}="([^"]+)"', tag) or [None, None])[1]


def _norm(s: str) -> str:
    s = re.sub(r"\(z-library\)|\.epub$", "", s, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]", "", s.lower())[:40]


def indexar_epubs(root: Path) -> dict[str, Path]:
    idx = {}
    for p in root.rglob("*.epub"):
        idx[_norm(p.stem)] = p
    return idx


def capitulos_del_epub(epub: Path) -> list[str]:
    """Lista de títulos de capítulo en orden de spine (índice = spineIndex)."""
    try:
        z = zipfile.ZipFile(epub)
        cont = z.read("META-INF/container.xml").decode("utf-8", "replace")
        opf_path = _ATTR("full-path", cont)
        opf = z.read(opf_path).decode("utf-8", "replace")
        base = "/".join(opf_path.split("/")[:-1])
        # manifest: id -> href
        manifest = {}
        for tag in re.findall(r"<item\b[^>]*>", opf):
            i, h = _ATTR("id", tag), _ATTR("href", tag)
            if i and h:
                manifest[i] = h
        # spine: orden de idrefs
        spine = re.findall(r'<itemref\b[^>]*idref="([^"]+)"', opf)
        # toc.ncx: href(basename sin ancla) -> título
        titulos = {}
        ncx_id = next((i for i, h in manifest.items() if h.endswith(".ncx")), None)
        if ncx_id:
            ncx = z.read((base + "/" if base else "") + manifest[ncx_id]).decode("utf-8", "replace")
            for np in re.findall(r"<navPoint\b.*?</navPoint>", ncx, re.DOTALL):
                t = re.search(r"<text>(.*?)</text>", np, re.DOTALL)
                src = re.search(r'src="([^"#]+)', np)
                if t and src:
                    titulos[src.group(1).split("/")[-1]] = re.sub(r"\s+", " ", t.group(1)).strip()
        caps = []
        for idref in spine:
            href = manifest.get(idref, "")
            base_href = href.split("/")[-1]
            caps.append(titulos.get(base_href, base_href or idref))
        return caps
    except Exception:
        return []


def parsear_archivo(path: Path, epubs: dict[str, Path]) -> dict | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return None
    nombre = d.get("bookName", path.stem)
    caps = capitulos_del_epub(epubs[_norm(nombre)]) if _norm(nombre) in epubs else []
    notas = []
    for n in d.get("noteList", []):
        si = n.get("spineIndex")
        cap = caps[si] if (caps and isinstance(si, int) and 0 <= si < len(caps)) else (f"sección {si}" if si is not None else "")
        notas.append({
            "libro": nombre,
            "capitulo": cap,
            "spineIndex": si,
            "charInicio": n.get("startCharIndex"),
            "subrayado": (n.get("text") or "").strip(),
            "nota": (n.get("note") or "").strip(),
            "color": n.get("bgColor"),
            "fecha": n.get("showTime", ""),
        })
    notas.sort(key=lambda x: (x["spineIndex"] if isinstance(x["spineIndex"], int) else 0,
                              x["charInicio"] or 0))
    return {"libro": nombre, "resuelto": bool(caps), "notas": notas}


def exportar(libros: list[dict]) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    todo = []
    for b in libros:
        todo.extend(b["notas"])
        safe = re.sub(r'[<>:"/\\|?*]', "", b["libro"])[:120].strip() or "Sin titulo"
        out = [f"# {b['libro']}", ""]
        cap_actual = None
        for n in b["notas"]:
            if n["capitulo"] != cap_actual:
                cap_actual = n["capitulo"]
                out.append(f"\n## {cap_actual}\n")
            if n["nota"]:
                out.append(f"> **📝 Nota:** {n['nota']}")
                if n["subrayado"]:
                    out.append(f"> \n> *sobre:* «{n['subrayado']}»")
                out.append("")
            elif n["subrayado"]:
                out.append(f"- {n['subrayado']}\n")
        (SALIDA / f"{safe}.md").write_text("\n".join(out), encoding="utf-8")
    (SALIDA / "notes.json").write_text(json.dumps(todo, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notas", default=str(NOTAS_DIR))
    ap.add_argument("--epubs", default=str(EPUB_ROOT))
    a = ap.parse_args()
    notas_dir, epub_root = Path(a.notas), Path(a.epubs)
    epubs = indexar_epubs(epub_root)
    archivos = list(notas_dir.glob("*.txt")) + list(notas_dir.glob("*.json"))
    libros = [b for f in archivos if (b := parsear_archivo(f, epubs))]
    exportar(libros)

    tot = sum(len(b["notas"]) for b in libros)
    res = sum(1 for b in libros if b["resuelto"])
    print(f"✓ {tot} notas de {len(libros)} libros → {SALIDA}")
    print(f"  ({res}/{len(libros)} con capítulos resueltos desde el EPUB)\n")
    for b in sorted(libros, key=lambda x: -len(x["notas"])):
        subr = sum(1 for n in b["notas"] if not n["nota"])
        nts = sum(1 for n in b["notas"] if n["nota"])
        flag = "" if b["resuelto"] else "  ⚠ sin EPUB"
        print(f"  • {b['libro'][:55]:55} {subr:>3} subr · {nts:>2} notas{flag}")


if __name__ == "__main__":
    main()
