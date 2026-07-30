"""
archivar_inbox.py — archiva AUTOMÁTICAMENTE las notas de notas/inbox/ en la nota que
corresponde, sin intervención humana ni LLM.

Decide el destino así, en este orden:
  1) ¿Coincide con un LIBRO de notas/libros/?  (solapamiento de palabras clave del campo
     `libro:` contra título + autor + nombre de archivo). Si hay un ganador claro → ahí.
  2) ¿Es un TEMA general (racismo, política, ideología…) y NO coincidió con ningún libro?
     → a notas/conceptos/<Tema>.md, en una sección "## Notas de lectura".
  3) ¿Empate entre varios libros parecidos (p. ej. dos libros de Hegel y solo escribiste
     "hegel")? → NO adivina: cae en un cubo genérico con lo que escribiste y te avisa para
     que añadas una palabra distintiva.
  4) Si no encaja en nada → crea la nota de libro nueva.

La nota del inbox siempre se mueve a _archivo (no se pierde; además el correo es respaldo).
Pensado para correr en el sync (tras revisar_notas, antes del reindex) o a mano.

Uso:  python archivar_inbox.py
"""
from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

from config import NOTAS, slug_libro, utf8

utf8()
INBOX = NOTAS / "inbox"
LIBROS = NOTAS / "libros"
CONCEPTOS = NOTAS / "conceptos"
ARCH = NOTAS / "_archivo" / "inbox-procesadas"

# Palabras de bajo valor para el emparejamiento (artículos, preps, comodines de título).
STOP = {"the", "and", "for", "una", "uno", "los", "las", "del", "con", "por", "very",
        "a", "an", "of", "to", "in", "el", "la", "de", "y", "un"}

# Temas generales que NO son libros: si una nota no coincide con ningún libro y su asunto
# es uno de estos, se archiva en conceptos/ en vez de crear un "libro" espurio.
# Edítalos a gusto (minúscula, sin tildes — se comparan normalizados).
TEMAS_CONCEPTO = {
    "racismo", "politica", "ideologia", "nacionalismo", "estado", "clase",
    "feminismo", "genero", "raza", "ecologia", "antihaitianismo",
    "hegemonia", "necropoder", "entropia", "colonialismo", "capitalismo",
}


def _toks(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]+", s) if len(w) > 2 and w not in STOP}


def _frontmatter(doc: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    if doc.startswith("---"):
        bloque = doc.split("---", 2)[1]
        for ln in bloque.splitlines():
            if ":" in ln:
                k, _, v = ln.partition(":")
                fm[k.strip()] = v.strip().strip('"')
    return fm


def _tokens_nota(p: Path) -> set[str]:
    """Tokens de una nota destino: título (frontmatter) + autor + nombre de archivo + 1er '# H'."""
    doc = p.read_text(encoding="utf-8")
    fm = _frontmatter(doc)
    toks = _toks(fm.get("titulo", "")) | _toks(fm.get("autor", "")) | _toks(p.stem)
    m = re.search(r"(?m)^#\s+(.+)$", doc)  # las notas de concepto no tienen 'titulo:' pero sí '# H'
    if m:
        toks |= _toks(m.group(1))
    return toks


def _candidatos(carpeta: Path) -> list[tuple[Path, set[str]]]:
    if not carpeta.exists():
        return []
    return [(p, _tokens_nota(p)) for p in sorted(carpeta.glob("*.md")) if not p.name.startswith("_")]


def _emparejar(libro: str, cands: list[tuple[Path, set[str]]]) -> tuple[Path | None, str]:
    """Devuelve (mejor|None, estado). estado ∈ {ok, ambiguo, sin-match}.

    'ok'        → un único ganador claro.
    'ambiguo'   → dos o más candidatos empatan en lo más alto (no se debe adivinar cuál).
    'sin-match' → nadie supera el umbral mínimo de confianza.
    """
    objetivo = _toks(libro)
    if not objetivo or not cands:
        return None, "sin-match"
    puntuados = sorted((len(objetivo & toks), p) for p, toks in cands)
    mejor_n, mejor = puntuados[-1]
    # umbral: ≥2 palabras en común, o ≥1 que cubra la mitad de lo escrito.
    if not (mejor_n >= 2 or mejor_n / max(1, len(objetivo)) >= 0.5):
        return None, "sin-match"
    segundo_n = puntuados[-2][0] if len(puntuados) > 1 else -1
    if segundo_n == mejor_n:  # empate arriba → títulos difusos indistinguibles
        return None, "ambiguo"
    return mejor, "ok"


def _tema_concepto(libro: str) -> str | None:
    """Si lo escrito es esencialmente un tema general (1-2 palabras), devuelve el tema."""
    toks = _toks(libro)
    hit = toks & TEMAS_CONCEPTO
    return sorted(hit)[0] if hit and len(toks) <= 2 else None


def _cuerpo_inbox(doc: str) -> str:
    cuerpo = doc.split("---", 2)[2] if doc.startswith("---") else doc
    lineas = [l for l in cuerpo.splitlines()]
    # quita el encabezado "# Título" inicial
    while lineas and (not lineas[0].strip() or lineas[0].lstrip().startswith("#")):
        lineas.pop(0)
    return "\n".join(lineas).strip()


def _bloque(fecha: str, cuerpo: str) -> str:
    return f"**(nota móvil · {fecha})** {cuerpo}\n"


SEC_LECTURA = "## Lectura (subrayados y notas)"


def _insertar_lectura(target: Path, fecha: str, cuerpo: str) -> None:
    """Cascada cronologica de la hoja del libro: agrega el cuerpo (quotes + notas
    breves, tal como llegaron) bajo '### <fecha>' de la seccion Lectura, apendizando
    al FINAL (orden de lectura). Crea la seccion y/o la fecha si no existen."""
    fecha = fecha or "(sin fecha)"
    doc = target.read_text(encoding="utf-8")
    if SEC_LECTURA not in doc:
        doc = doc.rstrip() + f"\n\n{SEC_LECTURA}\n"
    m = re.search(rf"(?m)^### {re.escape(fecha)}\s*$", doc)
    if m:  # final del bloque de esa fecha = proximo encabezado ###/## (o EOF)
        resto = doc[m.end():]
        fin = re.search(r"(?m)^#{2,3} ", resto)
        i = m.end() + (fin.start() if fin else len(resto))
    else:  # fecha nueva al final de la seccion Lectura (antes del proximo ## si lo hay)
        s = doc.index(SEC_LECTURA) + len(SEC_LECTURA)
        resto = doc[s:]
        fin = re.search(r"(?m)^## ", resto)
        i = s + (fin.start() if fin else len(resto))
        cuerpo = f"### {fecha}\n\n" + cuerpo.strip()
    doc = doc[:i].rstrip() + "\n\n" + cuerpo.strip() + "\n\n" + doc[i:].lstrip("\n")
    target.write_text(doc, encoding="utf-8")


def _insertar(target: Path, patron: str, seccion: str, bloque: str) -> None:
    """Inserta el bloque bajo la sección dada (creándola si no existe)."""
    doc = target.read_text(encoding="utf-8")
    m = re.search(patron, doc)
    if m:  # entrada más reciente al inicio de la sección
        i = m.end()
        doc = doc[:i] + "\n" + bloque + "\n" + doc[i:]
    elif seccion != "## Subrayados" and "## Subrayados" in doc:
        doc = doc.replace("## Subrayados", seccion + "\n\n" + bloque + "\n## Subrayados", 1)
    else:
        doc = doc.rstrip() + "\n\n" + seccion + "\n\n" + bloque
    target.write_text(doc, encoding="utf-8")


def _crear_libro(target: Path, titulo: str) -> None:
    fm = (f'---\ntitulo: "{titulo.replace(chr(34), chr(39))}"\nautor: ""\ntipo: book\n'
          f"status: leyendo\ngeneros: []\ntags: [libro]\n---\n\n# {titulo}\n\n"
          f"fuente:: [[ ]]\n\n> [!note] Conceptos\n> (enlaza aquí: [[ ]])\n\n"
          f"## Mis notas (digeridas)\n\n\n{SEC_LECTURA}\n\n"
          f"> Cascada cronologica (raw, no borrar): cada sesion de lectura bajo su fecha.\n")
    target.write_text(fm, encoding="utf-8")


def _crear_ideas(target: Path, bloque: str) -> None:
    contenido = ("---\ntags: [ideas]\n---\n\n# Ideas de Getulio\n\n"
                 "## Brainfarts\n\n" + bloque)
    target.write_text(contenido, encoding="utf-8")


def _crear_concepto(target: Path, titulo: str, bloque: str) -> None:
    fm = (f"---\ntags: [concepto]\n---\n\n# {titulo}\n\n"
          f"(definición pendiente — capturada desde el móvil; el tutor la pulirá)\n\n"
          f"## Notas de lectura\n\n{bloque}")
    target.write_text(fm, encoding="utf-8")


# (los destinos libro usan _insertar_lectura / SEC_LECTURA — cascada por fecha)
PAT_CONCEPTO = r"## Notas de lectura[^\n]*\n"
SEC_CONCEPTO = "## Notas de lectura"
PAT_IDEAS = r"## Brainfarts[^\n]*\n"
SEC_IDEAS = "## Brainfarts"
IDEAS = NOTAS / "ideas-getulio.md"


def main() -> None:
    # inbox/ideas/ NO se archiva automaticamente: su triage (convertir a concepto,
    # archivar o borrar) es de Getulio en el repaso (Linea Sagrada del Zettelkasten).
    notas = [p for p in sorted(INBOX.rglob("*.md"))
             if p.name != "README.md" and "ideas" not in p.parent.parts]
    if not notas:
        print("(inbox vacío)")
        return
    cands_libros = _candidatos(LIBROS)
    cands_concep = _candidatos(CONCEPTOS)
    ARCH.mkdir(parents=True, exist_ok=True)
    n_ok = n_amb = 0
    for p in notas:
        doc = p.read_text(encoding="utf-8")
        fm = _frontmatter(doc)
        libro = fm.get("libro", "") or p.stem
        fecha = fm.get("fecha", "")
        cuerpo = _cuerpo_inbox(doc)
        if not cuerpo:
            p.unlink(missing_ok=True)
            continue
        if re.search(r"!\[\[[^\]]+\.(?:jpg|jpeg|png)", cuerpo, re.IGNORECASE):
            # capturas sin transcribir: NO archivar a ciegas (los embeds crudos
            # ensucian la hoja del libro). Las procesa ocr_capturas.py primero.
            print(f"  ⚠ «{p.stem[:40]}» tiene imagenes sin OCR - se queda en el inbox")
            continue
        bloque = _bloque(fecha, cuerpo)  # para destinos concepto/ideas (con prefijo de fecha)

        if not fm.get("libro", "").strip():  # inbox libre → brainfart
            if IDEAS.exists():
                _insertar(IDEAS, PAT_IDEAS, SEC_IDEAS, bloque)
            else:
                _crear_ideas(IDEAS, bloque)
            print(f"  ✓ «{p.stem}» → ideas-getulio.md (brainfart)")
            n_ok += 1
            shutil.move(str(p), str(ARCH / p.name))
            continue

        target, estado = _emparejar(libro, cands_libros)
        tema = _tema_concepto(libro)

        if estado == "ok":  # 1) libro con ganador claro -> cascada por fecha
            _insertar_lectura(target, fecha, cuerpo)
            print(f"  ✓ «{libro[:40]}» → {target.name}  (match)")
            n_ok += 1

        elif tema:  # 2) tema general sin libro que encaje → conceptos/
            CONCEPTOS.mkdir(parents=True, exist_ok=True)
            ctarget, cestado = _emparejar(tema, cands_concep)
            if cestado != "ok":
                ctarget = CONCEPTOS / f"{tema.capitalize()}.md"
            if ctarget.exists():
                _insertar(ctarget, PAT_CONCEPTO, SEC_CONCEPTO, bloque)
            else:
                _crear_concepto(ctarget, tema.capitalize(), bloque)
                cands_concep.append((ctarget, _toks(tema)))
            print(f"  ✓ «{libro[:40]}» → conceptos/{ctarget.name}  (tema)")
            n_ok += 1

        elif estado == "ambiguo":  # 3) varios libros parecidos → no adivinar
            target = LIBROS / f"{slug_libro(Path(libro + '.x'))}.md"
            if not target.exists():
                _crear_libro(target, libro)
                cands_libros.append((target, _toks(libro)))
            _insertar_lectura(target, fecha, cuerpo)
            print(f"  ⚠ «{libro[:40]}» es ambiguo (varios libros encajan) → {target.name}. "
                  f"Añade una palabra distintiva (autor o palabra del título) en la próxima nota.")
            n_amb += 1

        else:  # 4) sin-match y no es tema → nota de libro nueva
            target = LIBROS / f"{slug_libro(Path(libro + '.x'))}.md"
            _crear_libro(target, libro)
            _insertar_lectura(target, fecha, cuerpo)
            cands_libros.append((target, _toks(libro)))
            print(f"  ✓ «{libro[:40]}» → {target.name}  (nota de libro creada)")
            n_ok += 1

        shutil.move(str(p), str(ARCH / p.name))

    resumen = f"\n{n_ok} nota(s) archivada(s)."
    if n_amb:
        resumen += f" {n_amb} ambigua(s) — mira el aviso ⚠ de arriba."
    print(resumen + " (Originales en _archivo/inbox-procesadas/.)")


if __name__ == "__main__":
    main()
