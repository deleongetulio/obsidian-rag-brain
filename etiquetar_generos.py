#!/usr/bin/env python3
"""etiquetar_generos.py
Escribe `genero::` (Dataview inline) en el frontmatter de cada libro del vault,
a partir de la clasificacion manual ya existente en referencias/generos_biblioteca.md.

Metodo:
  1. Parsea generos_biblioteca.md -> mapa autor -> {generos}.
  2. Para cada libro del vault, busca su `autor` en el mapa (match por apellido/tokens).
  3. Detecta manga por lista (el archivo de generos OMITE manga a proposito).
  4. Escribe `genero:: [[Tema]]` debajo del titulo + campo `generos:` en frontmatter.

Uso:
  python etiquetar_generos.py            # DRY: escribe propuesta a _generos_propuesta.txt
  python etiquetar_generos.py --apply    # aplica al frontmatter
"""
import re, sys, io, unicodedata, tempfile
from pathlib import Path
from collections import defaultdict
from generos_suplemento import AUTOR_SUP, TITULO_SUP

VAULT   = Path.home() / "Documents" / "Obsidian" / "Obsidian"  # ajustar a tu propio vault
LIBROS  = VAULT / "libros"
GENEROS = VAULT / "referencias" / "generos_biblioteca.md"
APPLY   = "--apply" in sys.argv

# Codigo -> nombre del tema (nodo en el vault)
NOMBRE = {
    "ECON": "Economia politica", "MARX": "Marxismo", "FILO": "Filosofia",
    "CRIT": "Teoria critica", "PSIC": "Psicoanalisis", "ANTR": "Antropologia",
    "HIST": "Historia", "CARI": "Caribe y Republica Dominicana",
    "RAZA": "Raza y colonialismo", "FEMI": "Feminismo", "ANAR": "Anarquismo",
    "ECOL": "Ecologia politica", "GEOP": "Geopolitica e imperialismo",
    "TECH": "Tecnologia y vigilancia", "LITE": "Literatura", "CIEN": "Ciencia y metodo",
    "MANGA": "Manga",
}

def strip_acc(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", strip_acc(s).lower())).strip()

def last_token(author):
    # ultimo token significativo (apellido) para match laxo
    toks = [t for t in norm(author).split() if len(t) > 2]
    return toks[-1] if toks else ""

# --- Manga: el archivo de generos los omite, los detectamos por autor/titulo ---
MANGA_AUTORES = {"otomo","kishiro","miura","fujimoto","mignola","yamamoto",
                 "spiegelman","yazawa","asano","ito","inoue","yukimura","kobayashi"}
MANGA_TITULOS = {"akira","battle angel alita","berserk","chainsaw man","duranki",
                 "hellboy","homunculus","maus","nana","oyasumi punpun","sayonara eri",
                 "uzumaki","vagabond","vinland saga","v de vendetta"}

def parse_generos():
    """Devuelve autor_norm -> set(codigos)."""
    txt = GENEROS.read_text(encoding="utf-8")
    autor_gen = defaultdict(set)
    cur = None
    for line in txt.splitlines():
        m = re.match(r"^###\s+([A-Z]{4})\b", line)
        if m:
            cur = m.group(1); continue
        if cur and line.startswith("- "):
            body = line[2:]
            # autor = texto antes del primer ' — ' (em dash) o ' - '
            parts = re.split(r"\s[—-]\s", body, maxsplit=1)
            autor = parts[0].strip()
            sec = re.findall(r"\+([A-Z]{4})", line)
            # puede haber varios autores: "A y B", "A & B"
            for a in re.split(r"\s+y\s+|\s*&\s*|\s*/\s*", autor):
                a = a.strip()
                if len(norm(a)) >= 3:
                    autor_gen[norm(a)].add(cur)
                    for s in sec: autor_gen[norm(a)].add(s)
    return autor_gen

def build_lastname_index(autor_gen):
    idx = defaultdict(set)
    for a, gens in autor_gen.items():
        lt = a.split()[-1] if a.split() else ""
        if len(lt) > 2:
            idx[lt] |= gens
    return idx

def book_meta(p):
    t = p.read_text(encoding="utf-8", errors="replace")
    tit = re.search(r'titulo:\s*"([^"]*)"', t)
    aut = re.search(r'autor:\s*"([^"]*)"', t)
    return (aut.group(1) if aut else ""), (tit.group(1) if tit else p.stem), t

def classify(autor, titulo, slug, autor_gen, lastidx):
    nt = norm(titulo); na = norm(autor)
    # manga primero
    if last_token(autor) in MANGA_AUTORES or any(m in nt for m in MANGA_TITULOS):
        return {"MANGA"}, "manga"
    # suplemento por autor (autores ausentes del archivo de generos)
    if na in AUTOR_SUP:
        return set(AUTOR_SUP[na]), "suplemento-autor"
    if not autor or autor == "?":
        # suplemento por titulo/slug
        if slug in TITULO_SUP:
            return set(TITULO_SUP[slug]), "suplemento-titulo"
        return set(), "sin-autor"
    # match exacto autor
    if na in autor_gen:
        return set(autor_gen[na]), "autor-exacto"
    # match por apellido
    lt = last_token(autor)
    if lt and lt in lastidx:
        return set(lastidx[lt]), "apellido"
    # match por subconjunto de tokens
    atoks = set(na.split())
    for a, gens in autor_gen.items():
        if atoks and set(a.split()) & atoks and lt and lt in a:
            return set(gens), "tokens"
    return set(), "SIN-MATCH"

def main():
    autor_gen = parse_generos()
    lastidx = build_lastname_index(autor_gen)
    files = sorted(p for p in LIBROS.glob("*.md") if p.name not in {"_indice.md","test.md"})
    rows = []
    stats = defaultdict(int)
    for p in files:
        autor, titulo, t = book_meta(p)
        gens, how = classify(autor, titulo, p.stem, autor_gen, lastidx)
        stats[how] += 1
        if not gens: stats["_sin_genero"] += 1
        rows.append((p, autor, titulo, sorted(gens), how, t))

    # reporte
    out = Path(tempfile.gettempdir()) / "_generos_propuesta.txt"
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(f"Libros: {len(files)}\n")
        for k in sorted(stats): f.write(f"  {k}: {stats[k]}\n")
        f.write("\n=== SIN-MATCH (necesitan revision manual) ===\n")
        for p,a,ti,g,how,_ in rows:
            if how == "SIN-MATCH":
                f.write(f"  {a} :: {ti}  [{p.name}]\n")
        f.write("\n=== Muestra de clasificados ===\n")
        for p,a,ti,g,how,_ in rows[:40]:
            f.write(f"  {','.join(g) or '-':25s} {how:12s} {a} :: {ti}\n")
    print("Reporte:", out)
    for k in sorted(stats): print(f"  {k}: {stats[k]}")

    if APPLY:
        n = 0
        for p, autor, titulo, gens, how, t in rows:
            if not gens: continue
            codes = sorted(gens)
            generos_yaml = "[" + ", ".join(NOMBRE[c] for c in codes) + "]"
            links = "\n".join(f"genero:: [[{NOMBRE[c]}]]" for c in codes)
            # frontmatter: agrega/reemplaza `generos:`
            if re.search(r'^generos:.*$', t, flags=re.M):
                t = re.sub(r'^generos:.*$', f'generos: {generos_yaml}', t, flags=re.M)
            else:
                t = re.sub(r'(tags: \[libro\]\n)', f'generos: {generos_yaml}\n\\1', t, count=1)
            # inline links: tras la linea `fuente:: [[...]]` (o tras el # titulo)
            if "genero:: [[" not in t:
                if re.search(r'^fuente:: .*$', t, flags=re.M):
                    t = re.sub(r'(^fuente:: .*$)', r'\1\n' + links, t, count=1, flags=re.M)
                else:
                    t = re.sub(r'(^# .*$)', r'\1\n\n' + links, t, count=1, flags=re.M)
            p.write_text(t, encoding="utf-8")
            n += 1
        print(f"[APLICADO] {n} libros etiquetados.")
    else:
        print("[DRY] nada escrito. Revisa el reporte y pasa --apply.")

if __name__ == "__main__":
    main()
