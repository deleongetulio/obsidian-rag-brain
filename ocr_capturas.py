r"""
ocr_capturas.py - OCR automatico de capturas Kindle del inbox -> citas APA.

Eslabon nocturno del procesado continuo (Ahrens p. 29, "shortly after"). Por cada
nota del inbox con embeds de imagen y campo `libro:` que matchee una hoja de libros/:
  1) renombra la imagen ({nota}-{N}.ext) y la manda a la API (vision) para extraer
     SOLO el texto subrayado + el numero de pagina visible,
  2) reemplaza el embed por callouts [!quote] con cita APA:
        > [!quote] <Titulo corto>
        > "texto subrayado" (Apellido, año, p. N).
     (autor/año del frontmatter de la hoja del libro; pagina de la captura,
      fallback el `loc:` de la nota),
  3) mueve la imagen a _archivo/capturas-procesadas/.

Si la captura no es pagina Kindle con subrayado, es ilegible, o el libro no matchea:
se deja INTACTA y se reporta (mejor pendiente que inventado). archivar_inbox.py no
archiva notas con embeds pendientes, asi que nada crudo llega a las hojas de libro.

Uso:  .venv-rag\Scripts\python.exe ocr_capturas.py [--dry]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
from pathlib import Path

from config import AQUI, NOTAS, utf8
import archivar_inbox as ai

utf8()
INBOX = NOTAS / "inbox"
ADJUNTOS = NOTAS / "adjuntos"
ARCH_IMG = NOTAS / "_archivo" / "capturas-procesadas"
MODELO = "claude-sonnet-5"
EMBED_RE = re.compile(r"!\[\[([^\]|]+\.(?:jpg|jpeg|png))(?:\|[^\]]*)?\]\]", re.IGNORECASE)
MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

PROMPT = (
    "Esta imagen deberia ser una foto de una pagina de libro (Kindle O libro fisico "
    "en papel) con pasajes RESALTADOS: sombreado gris de Kindle, resaltador de color, "
    "subrayado a lapiz/tinta o corchetes al margen. Devuelve SOLO JSON valido, sin markdown:\n"
    '{"es_pagina_libro": true|false, "legible": true|false, '
    '"pagina": <numero de pagina visible ("Page N" del Kindle o el impreso en papel), si no null>, '
    '"subrayados": ["texto exacto de cada pasaje resaltado/subrayado"], '
    '"notas_margen": ["texto de anotaciones MANUSCRITAS del lector al margen, si las hay"]}\n'
    "Reglas: en subrayados transcribe SOLO lo resaltado, tal cual, sin parafrasear; un "
    "elemento por bloque contiguo (aunque cruce parrafos); si queda cortado por el borde, "
    "transcribe lo visible y cierra con [...]; si no hay nada resaltado, subrayados=[]. "
    "Las notas manuscritas del lector van SIEMPRE en notas_margen, nunca en subrayados."
)


def _api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env = AQUI / ".env"
        if env.exists():
            for ln in env.read_text(encoding="utf-8").splitlines():
                if ln.startswith("ANTHROPIC_API_KEY="):
                    key = ln.partition("=")[2].strip()
    if not key:
        sys.exit("ERROR: falta ANTHROPIC_API_KEY (.env del agente)")
    return key


def _apellido(autor: str) -> str:
    primero = re.split(r"\s+y\s+|\s+and\s+|;|/", autor)[0].strip()
    return (primero.split(",")[0] if "," in primero else primero.split()[-1]).strip()


def _titulo_corto(titulo: str) -> str:
    return re.split(r"\s+-\s+|:", titulo)[0].strip()


def _info_libro(nombre_libro: str, cands) -> dict | None:
    """Apellido, año y titulo corto desde la hoja del libro (o None si no matchea)."""
    target, estado = ai._emparejar(nombre_libro, cands)
    if estado != "ok":
        return None
    fm = ai._frontmatter(target.read_text(encoding="utf-8"))
    autor = fm.get("autor", "")
    return {
        "apellido": _apellido(autor) if autor else None,
        "anio": re.sub(r"\D", "", str(fm.get("anio", "")))[:4] or None,
        "titulo": _titulo_corto(fm.get("titulo") or target.stem),
    }


def _localizar(nombre_img: str) -> Path | None:
    directo = ADJUNTOS / nombre_img
    if directo.exists():
        return directo
    for p in NOTAS.rglob(nombre_img):
        if "_archivo" not in p.parts and ".git" not in p.parts:
            return p
    return None


def _ocr(cliente, img: Path) -> dict | None:
    data = base64.standard_b64encode(img.read_bytes()).decode()
    try:
        resp = cliente.messages.create(
            model=MODELO, max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": MEDIA[img.suffix.lower()], "data": data}},
                {"type": "text", "text": PROMPT},
            ]}],
        )
        crudo = resp.content[0].text.strip()
        crudo = re.sub(r"^```(?:json)?\s*|\s*```$", "", crudo)
        return json.loads(crudo)
    except Exception as e:  # noqa: BLE001 - una captura mala no debe romper la corrida
        print(f"    [aviso] OCR fallo en {img.name}: {e}")
        return None


def _callout(texto: str, info: dict, pagina, loc: str) -> str:
    texto = texto.strip().strip('"')
    if not texto.endswith(("?", "!", "]")):
        texto = texto.rstrip(".")
    partes = [p for p in (info["apellido"], info["anio"]) if p]
    if pagina:
        partes.append(f"p. {pagina}")
    elif loc:
        partes.append(f"loc. {loc}")
    cita = ", ".join(partes)
    return f'> [!quote] {info["titulo"]}\n> "{texto}"' + (f" ({cita})." if cita else ".")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="listar pendientes sin llamar a la API")
    args = p.parse_args()

    notas = [n for n in sorted(INBOX.rglob("*.md"))
             if n.name != "README.md" and EMBED_RE.search(n.read_text(encoding="utf-8"))]
    if not notas:
        print("0 capturas pendientes de OCR.")
        return
    if args.dry:
        for n in notas:
            print(f"  pendiente: {n.relative_to(NOTAS)}")
        print(f"{len(notas)} nota(s) con imagenes por transcribir [DRY].")
        return

    import anthropic
    cliente = anthropic.Anthropic(api_key=_api_key())
    cands = ai._candidatos(ai.LIBROS)
    ARCH_IMG.mkdir(parents=True, exist_ok=True)
    ok = dejadas = 0

    for nota in notas:
        doc = nota.read_text(encoding="utf-8")
        fm = ai._frontmatter(doc)
        info = _info_libro(fm.get("libro", ""), cands) if fm.get("libro", "").strip() else None
        if not info:
            print(f"  ⚠ {nota.name}: sin libro claro - imagen(es) intactas para revision manual")
            dejadas += 1
            continue

        n_img = 0
        for m in list(EMBED_RE.finditer(doc)):
            img = _localizar(m.group(1))
            if not img:
                print(f"  ⚠ {nota.name}: no encuentro {m.group(1)}")
                continue
            res = _ocr(cliente, img)
            if not res or not res.get("es_pagina_libro") or not res.get("legible") \
               or not res.get("subrayados"):
                print(f"  ⚠ {nota.name}: {img.name} sin subrayado legible - se deja intacta")
                dejadas += 1
                continue
            n_img += 1
            nuevo_nombre = f"{nota.stem.strip()}-{n_img}{img.suffix.lower()}"
            callouts = "\n\n".join(
                _callout(t, info, res.get("pagina"), str(fm.get("loc", "")).strip())
                for t in res["subrayados"])
            # notas manuscritas al margen = palabras del LECTOR -> texto plano (va a raw)
            margen = [t.strip() for t in res.get("notas_margen") or [] if t.strip()]
            if margen:
                pag = f", p. {res['pagina']}" if res.get("pagina") else ""
                callouts += "\n\n" + "\n".join(
                    f"(nota al margen{pag}) {t}" for t in margen)
            doc = doc.replace(m.group(0), callouts, 1)
            shutil.move(str(img), str(ARCH_IMG / nuevo_nombre))
            ok += 1

        nota.write_text(doc, encoding="utf-8")

    print(f"{ok} captura(s) transcritas a cita APA; {dejadas} dejadas para revision manual.")


if __name__ == "__main__":
    main()
