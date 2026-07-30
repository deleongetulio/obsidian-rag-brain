#!/usr/bin/env python3
"""enlazar_archivos.py
Matchea libros/*.md con biblioteca/*.epub|pdf y escribe el campo `archivo:`
en el frontmatter de cada libro, apuntando a la ruta relativa dentro del vault.

Esto permite que PDF++ y Weave EPUB Reader inserten anotaciones directamente
en la nota del libro (libros/X.md ## Subrayados), via proxyMDProperty="archivo".

Matching difuso: normaliza titulo + autor del frontmatter y del nombre del
archivo, y busca el mejor candidato por solapamiento de tokens significativos.

Uso:
  python enlazar_archivos.py            # DRY: muestra propuesta, no escribe
  python enlazar_archivos.py --apply     # escribe en el frontmatter
"""
from __future__ import annotations
import re, sys, unicodedata
from pathlib import Path

def utf8():
    for stream in (sys.stdout, sys.stderr):
        try: stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError): pass

utf8()

VAULT = Path.home() / "Documents" / "Obsidian" / "Obsidian"  # ajustar a tu propio vault
LIBROS = VAULT / "libros"
BIBLIO = VAULT / "biblioteca"
APPLY = "--apply" in sys.argv

STOP = {"the", "and", "for", "una", "uno", "los", "las", "del", "con", "por",
        "very", "a", "an", "of", "to", "in", "el", "la", "de", "y", "un",
        "is", "on", "or", "how", "what", "why", "who", "from", "as", "at",
        "sk", "1lib", "z", "zlibrary", "library"}

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s)

def tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", norm(s)) if len(w) > 2 and w not in STOP}

def fm_field(doc: str, field: str) -> str:
    m = re.search(rf'^{field}:\s*"([^"]*)"', doc, re.M)
    if m: return m.group(1)
    m = re.search(rf'^{field}:\s*(.+)$', doc, re.M)
    return m.group(1).strip() if m else ""

def parse_fm(doc: str) -> dict:
    fm = {}
    if doc.startswith("---"):
        block = doc.split("---", 2)[1]
        for ln in block.splitlines():
            if ":" in ln:
                k, _, v = ln.partition(":")
                fm[k.strip()] = v.strip().strip('"')
    return fm

def find_files(folder: Path) -> list[Path]:
    if not folder.exists(): return []
    return [p for p in folder.rglob("*") if p.suffix.lower() in (".epub", ".pdf")]

def strip_noise(name: str) -> str:
    name = re.sub(r"\(z-library[^)]*\)", "", name, flags=re.I)
    name = re.sub(r"\(z.?library[^)]*\)", "", name, flags=re.I)
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r"\(.*?librería.*?\)", "", name, flags=re.I)
    return name

def main():
    archivos = find_files(BIBLIO)
    if not archivos:
        print("No se encontraron EPUBs/PDFs en biblioteca/")
        return

    # Precomputar tokens de cada archivo
    arch_tokens = []
    for p in archivos:
        rel = p.relative_to(VAULT).as_posix()
        stem = strip_noise(p.stem)
        arch_tokens.append((p, rel, tokens(stem)))

    md_files = sorted(p for p in LIBROS.glob("*.md") if not p.name.startswith("_"))
    n_linked = 0
    n_skip = 0
    n_amb = 0

    for md in md_files:
        doc = md.read_text(encoding="utf-8")
        fm = parse_fm(doc)
        titulo = fm.get("titulo", md.stem)
        autor = fm.get("autor", "")
       # Si ya tengo archivo, skip
        if fm.get("archivo", "").strip():
            n_skip += 1
            continue

        obj_tokens = tokens(titulo) | tokens(autor)
        if not obj_tokens:
            continue

        scored = []
        for p, rel, atoks in arch_tokens:
            overlap = len(obj_tokens & atoks)
            if overlap > 0:
                scored.append((overlap, rel, p))

        if not scored:
            continue

        scored.sort(reverse=True)
        best_n, best_rel, best_p = scored[0]
        segundo_n = scored[1][0] if len(scored) > 1 else 0

        if best_n >= 2 and best_n > segundo_n:
            print(f"  OK  {md.name[:45]:45s} -> {best_rel[:60]}")
            if APPLY:
                if re.search(r'^archivo:\s*"', doc, re.M):
                    doc = re.sub(
                        r'^archivo:\s*"[^"]*"\s*$',
                        f'archivo: "{best_rel}"',
                        doc, count=1, flags=re.M
                    )
                elif re.search(r'^tags:\s*\[libro', doc, re.M):
                    doc = re.sub(
                        r'(tags: \[libro[^\]]*\]\n)',
                        f'archivo: "{best_rel}"\n\\1',
                        doc, count=1
                    )
                else:
                    doc = re.sub(
                        r'(---\n)(?!archivo)',
                        f'---\narchivo: "{best_rel}"\n',
                        doc, count=1
                    )
                md.write_text(doc, encoding="utf-8")
            n_linked += 1
        elif best_n >= 2 and best_n == segundo_n:
            print(f"  AMB {md.name[:45]:45s} -> {best_rel[:60]} (empate)")
            n_amb += 1
        elif best_n == 1:
            print(f"  ??  {md.name[:45]:45s} -> {best_rel[:60]} (1 token, dudoso)")

    print(f"\nEnlazados: {n_linked} | Ya tenian archivo: {n_skip} | Ambiguos: {n_amb}")
    if not APPLY:
        print("[DRY] Nada escrito. Pasa --apply para escribir.")


if __name__ == "__main__":
    main()