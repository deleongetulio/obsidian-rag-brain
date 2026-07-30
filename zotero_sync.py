r"""
zotero_sync.py — sincroniza las notas de libro del vault (libros/*.md) con Zotero.

Para cada nota de libro SIN `citekey:` en el frontmatter:
  1) genera un citekey estable estilo Better BibTeX (apellido+anio, p.ej. ahrens2022),
  2) crea el item en Zotero via API web (pyzotero), con el citekey PINNEADO en el campo
     Extra ("Citation Key: ..."), que Better BibTeX respeta al bajar por sync al desktop,
  3) escribe `citekey:` de vuelta en el frontmatter de la nota — esa es la idempotencia:
     la proxima corrida salta todo lo que ya tenga citekey.

Por defecto solo sincroniza libros con status leyendo / en-pausa / leido (los que se
trabajan de verdad; meter el catalogo entero de golpe seria coleccionismo). Con `--todos`
sincroniza el catalogo completo. `--dry` muestra el plan sin tocar nada.

Credenciales en .env: ZOTERO_API_KEY (con write) y ZOTERO_LIBRARY_ID (userID).

Uso:  .venv-rag\Scripts\python.exe zotero_sync.py [--dry] [--todos]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path

from config import AQUI, NOTAS, utf8

utf8()
LIBROS = NOTAS / "libros"
STATUS_SYNC = {"leyendo", "en-pausa", "leido"}


def cargar_env() -> tuple[str, str]:
    env = AQUI / ".env"
    if env.exists():
        for l in env.read_text(encoding="utf-8").splitlines():
            if l.strip() and not l.startswith("#") and "=" in l:
                k, _, v = l.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    key, lib = os.environ.get("ZOTERO_API_KEY"), os.environ.get("ZOTERO_LIBRARY_ID")
    if not key or not lib:
        sys.exit("ERROR: faltan ZOTERO_API_KEY / ZOTERO_LIBRARY_ID en el .env del agente.")
    return key, lib


def _frontmatter(doc: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    if doc.startswith("---"):
        bloque = doc.split("---", 2)[1]
        for ln in bloque.splitlines():
            if ":" in ln and not ln.startswith(" "):
                k, _, v = ln.partition(":")
                fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _citekey(autor: str, titulo: str, anio: str, usados: set[str]) -> str:
    """apellido+anio (estilo Better BibTeX). Fallback: 1ra palabra util del titulo."""
    if autor:
        # "Ahrens, Sonke" -> Ahrens; "Sönke Ahrens" -> Ahrens; varios autores -> el 1ro
        primero = re.split(r"\s+y\s+|\s+and\s+|;|/", autor)[0].strip()
        apellido = primero.split(",")[0].split()[-1] if "," in primero \
            else primero.split()[-1]
    else:
        palabras = [w for w in re.findall(r"[A-Za-z]+", _ascii(titulo)) if len(w) > 3]
        apellido = palabras[0] if palabras else "libro"
    base = re.sub(r"[^a-z0-9]", "", _ascii(apellido).lower()) + (anio or "")
    key = base
    for sufijo in "abcdefgh":
        if key not in usados:
            break
        key = base + sufijo
    usados.add(key)
    return key


def _creators(autor: str) -> list[dict]:
    out = []
    for nombre in re.split(r"\s+y\s+|\s+and\s+|;", autor):
        nombre = nombre.strip()
        if not nombre:
            continue
        if "," in nombre:  # "Ahrens, Sonke"
            ap, _, nom = nombre.partition(",")
            out.append({"creatorType": "author", "firstName": nom.strip(), "lastName": ap.strip()})
        elif " " in nombre:  # "Sonke Ahrens"
            partes = nombre.split()
            out.append({"creatorType": "author",
                        "firstName": " ".join(partes[:-1]), "lastName": partes[-1]})
        else:
            out.append({"creatorType": "author", "name": nombre})
    return out


def _escribir_citekey(p: Path, citekey: str) -> None:
    doc = p.read_text(encoding="utf-8")
    partes = doc.split("---", 2)  # ["", frontmatter, resto]
    if len(partes) < 3:
        return
    partes[1] = partes[1].rstrip("\n") + f"\ncitekey: {citekey}\n"
    p.write_text("---" + partes[1] + "---" + partes[2], encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="mostrar el plan sin crear nada")
    ap.add_argument("--todos", action="store_true", help="catalogo completo (no solo leyendo/leido)")
    a = ap.parse_args()

    key, lib = cargar_env()
    pendientes = []
    usados: set[str] = set()
    for p in sorted(LIBROS.glob("*.md")):
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        if fm.get("citekey"):
            usados.add(fm["citekey"])
            continue
        if not fm.get("titulo"):
            continue
        status = _ascii(fm.get("status", "")).lower()
        if not a.todos and status not in STATUS_SYNC:
            continue
        pendientes.append((p, fm))

    if not pendientes:
        print("(nada que sincronizar: todo tiene citekey o no hay libros en curso)")
        return

    print(f"{len(pendientes)} libro(s) a crear en Zotero" + (" [DRY]" if a.dry else "") + ":")
    if not a.dry:
        from pyzotero import zotero
        zot = zotero.Zotero(lib, "user", key)
        plantilla = zot.item_template("book")

    n_ok = 0
    for p, fm in pendientes:
        titulo, autor = fm["titulo"], fm.get("autor", "")
        anio = re.sub(r"\D", "", str(fm.get("anio", "")))[:4]
        ck = _citekey(autor, titulo, anio, usados)
        print(f"  {ck:<24} {titulo[:60]}")
        if a.dry:
            continue
        item = dict(plantilla)
        item["title"] = titulo
        item["creators"] = _creators(autor) or plantilla["creators"]
        item["date"] = anio
        item["ISBN"] = fm.get("isbn", "")
        item["extra"] = f"Citation Key: {ck}"
        try:
            resp = zot.create_items([item])
            if resp.get("successful"):
                _escribir_citekey(p, ck)
                n_ok += 1
            else:
                print(f"    ⚠ Zotero rechazo el item: {resp.get('failed')}")
        except Exception as e:
            print(f"    ⚠ error: {e}")

    if not a.dry:
        print(f"\n{n_ok}/{len(pendientes)} creados en Zotero (citekey escrito en el frontmatter).")
        print("Abre Zotero en el escritorio y deja que sincronice; Better BibTeX adoptara "
              "los citekeys pinneados en Extra.")


if __name__ == "__main__":
    main()
