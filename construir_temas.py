#!/usr/bin/env python3
"""construir_temas.py
1. Crea las 17 notas-hub de tema en temas/<Nombre>.md (dominios anchos).
2. Etiqueta cada autor con `generos` derivado de los generos de sus libros
   (via los enlaces `fuente:: [[<autor>]]` que ya existen en libros/).

Uso:
  python construir_temas.py            # DRY
  python construir_temas.py --apply
"""
import re, sys
from pathlib import Path
from collections import defaultdict

VAULT   = Path.home() / "Documents" / "Obsidian" / "Obsidian"  # ajustar a tu propio vault
LIBROS  = VAULT / "libros"
AUTORES = VAULT / "autores"
TEMAS   = VAULT / "temas"
APPLY   = "--apply" in sys.argv

NOMBRE = {
    "ECON": "Economia politica", "MARX": "Marxismo", "FILO": "Filosofia",
    "CRIT": "Teoria critica", "PSIC": "Psicoanalisis", "ANTR": "Antropologia",
    "HIST": "Historia", "CARI": "Caribe y Republica Dominicana",
    "RAZA": "Raza y colonialismo", "FEMI": "Feminismo", "ANAR": "Anarquismo",
    "ECOL": "Ecologia politica", "GEOP": "Geopolitica e imperialismo",
    "TECH": "Tecnologia y vigilancia", "LITE": "Literatura", "CIEN": "Ciencia y metodo",
    "MANGA": "Manga",
}
DESC = {
    "ECON": "Economia politica heterodoxa, finanzas, dinero, banca central, desarrollo.",
    "MARX": "Marx/Engels, El Capital, teoria del valor-trabajo, marxismo computacional.",
    "FILO": "Filosofia clasica, moderna, existencialismo, etica, metafisica.",
    "CRIT": "Escuela de Frankfurt, Zizek, ideologia, hegemonia, critica cultural.",
    "PSIC": "Freud, Lacan, teoria del sujeto y del deseo.",
    "ANTR": "Etnografia, antropologia politica, Graeber, el Estado.",
    "HIST": "Historia general, historiografia, imperios.",
    "CARI": "Historia y politica dominicana y caribena.",
    "RAZA": "Tradicion negra radical, poscolonial, decolonial, antirracismo.",
    "FEMI": "Feminismo, genero, teoria queer.",
    "ANAR": "Anarquismo, ayuda mutua, abolicionismo, izquierda radical.",
    "ECOL": "Decrecimiento, clima, emergy, capital fosil, termodinamica economica.",
    "GEOP": "Imperio, Guerra Fria, politica exterior, intervencion.",
    "TECH": "Big data, plataformas, IA, vigilancia, cibernetica socialista.",
    "LITE": "Novela, poesia, cuento, teatro.",
    "CIEN": "Matematica, logica, epistemologia, metodo cientifico.",
    "MANGA": "Manga y novela grafica.",
}

def hub_note(code):
    n = NOMBRE[code]
    return f"""---
nombre: "{n}"
tipo: tema
codigo: {code}
tags: [tema]
---

# {n}

> [!info] Tema (dominio)
> {DESC[code]} Es una de las redes anchas que clasifican libros, autores y conceptos.

## Conceptos de este tema
```dataview
LIST FROM "conceptos" WHERE contains(generos, "{n}") SORT file.name ASC
```

## Autores de este tema
```dataview
LIST FROM "autores" WHERE contains(generos, "{n}") SORT file.name ASC
```

## Libros en la biblioteca
```dataview
TABLE autor AS "Autor", status AS "Estado"
FROM "libros" WHERE contains(generos, "{n}") SORT file.name ASC
```
"""

def libro_meta(p):
    t = p.read_text(encoding="utf-8", errors="replace")
    fuentes = re.findall(r'fuente:: \[\[([^\]]+)\]\]', t)
    m = re.search(r'^generos:\s*\[([^\]]*)\]', t, re.M)
    gens = [g.strip() for g in m.group(1).split(",")] if m else []
    return fuentes, gens

def main():
    # --- 1. hubs ---
    created = 0
    if APPLY:
        TEMAS.mkdir(exist_ok=True)
    for code in NOMBRE:
        path = TEMAS / (NOMBRE[code] + ".md")
        if APPLY:
            path.write_text(hub_note(code), encoding="utf-8")
        created += 1
    print(f"Hubs de tema: {created} ({'creados' if APPLY else 'dry'})")

    # --- 2. autor -> generos (union de sus libros) ---
    autor_gen = defaultdict(set)
    for p in LIBROS.glob("*.md"):
        if p.name in {"_indice.md", "test.md"}: continue
        fuentes, gens = libro_meta(p)
        for autor in fuentes:
            autor_gen[autor].update(gens)

    tagged = missing = 0
    sample = []
    for af in sorted(AUTORES.glob("*.md")):
        canon = af.stem
        gens = sorted(autor_gen.get(canon, []))
        if not gens:
            missing += 1
            continue
        if APPLY:
            t = af.read_text(encoding="utf-8", errors="replace")
            yaml = "[" + ", ".join(gens) + "]"
            if re.search(r'^generos:.*$', t, re.M):
                t = re.sub(r'^generos:.*$', f'generos: {yaml}', t, flags=re.M)
            else:
                t = re.sub(r'(tags: \[autor\]\n)', f'generos: {yaml}\n\\1', t, count=1)
            links = "\n".join(f"genero:: [[{g}]]" for g in gens)
            if "genero:: [[" not in t:
                t = re.sub(r'(^# .*$)', r'\1\n' + links, t, count=1, flags=re.M)
            af.write_text(t, encoding="utf-8")
        tagged += 1
        if len(sample) < 12:
            sample.append(f"  {canon}: {', '.join(gens)}")
    print(f"Autores etiquetados: {tagged}  | sin libros enlazados: {missing}")
    print("Muestra:")
    print("\n".join(sample))
    if not APPLY:
        print("\n[DRY] nada escrito. Pasa --apply.")

if __name__ == "__main__":
    main()
