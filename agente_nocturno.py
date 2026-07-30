"""
agente_nocturno.py - Agente de consolidacion nocturna (propone, no escribe).

Analogia: consolidacion de memoria offline del cerebro. Lee lo que entro al vault
hoy (inbox + diario), detecta patrones, y escribe diario/<fecha>-nocturno.md para
que Getulio decida en el repaso.

GUARDARRAIL: NUNCA escribe en conceptos/. Solo propone en nocturno.md.
Ver reference_arquitectura_obsidian_agente.md PARTE 3.

Corre con el venv del agente:
    .venv-rag/Scripts/python.exe agente_nocturno.py
    .venv-rag/Scripts/python.exe agente_nocturno.py --dry
    .venv-rag/Scripts/python.exe agente_nocturno.py --fecha 2026-06-21
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

from config import AQUI, NOTAS, VENV_PY, utf8
from nocturno_config import (
    DIAS_HISTORIAL,
    EJES,
    MAX_TERMINOS_GRAPHRAG,
    MAX_TOKENS_HAIKU,
    MAX_TOKENS_SONNET,
    MIN_EJES_CRUCE,
    MODELO_CLASIFICADOR,
    MODELO_SINTETIZADOR,
    UMBRAL_DENSIDAD_INBOX,
    UMBRAL_HEADINGS,
    UMBRAL_PALABRAS,
)

utf8()

DIARIO    = NOTAS / "diario"
INBOX     = NOTAS / "inbox"
CONCEPTOS = NOTAS / "conceptos"
EXCLUIR   = {".obsidian", "_archivo", ".trash", "templates"}
RE_WIKILINK = re.compile(r"(?<!\!)\[\[([^\]|#]+)")
RE_CODIGO   = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
RE_EXT      = re.compile(r"\.(png|jpe?g|gif|svg|webp|pdf|mp[34]|excalidraw|base)$", re.IGNORECASE)


# ── Tipos de datos ────────────────────────────────────────────────────────────

class LintResultado(NamedTuple):
    gaps: list[tuple[str, int]]   # (nombre_faltante, n_referencias)
    huerfanas: list[str]          # conceptos sin backlinks
    libros_pelados: list[str]     # libros con <=1 enlace saliente

class NotaInbox(NamedTuple):
    path: Path
    palabras: int
    texto: str

class NotaDensa(NamedTuple):
    path: Path
    palabras: int
    headings: int


# ── Fase 1: Recopilar ─────────────────────────────────────────────────────────

def leer_inbox(hoy: date) -> list[NotaInbox]:
    """Lee notas densas de inbox/ y el diario del dia."""
    notas: list[NotaInbox] = []
    if INBOX.exists():
        for p in sorted(INBOX.rglob("*.md")):
            if p.name.startswith("_") or p.name == "README.md":
                continue
            texto = p.read_text(encoding="utf-8", errors="ignore")
            n = len(texto.split())
            if n >= UMBRAL_DENSIDAD_INBOX:
                notas.append(NotaInbox(p, n, texto))
    diario_hoy = DIARIO / f"{hoy}.md"
    if diario_hoy.exists():
        texto = diario_hoy.read_text(encoding="utf-8", errors="ignore")
        notas.append(NotaInbox(diario_hoy, len(texto.split()), texto))
    return notas


def lint_rapido() -> LintResultado:
    """Extrae gaps, huerfanas y libros sin conceptos (logica de lint_vault.py)."""
    todas   = list(NOTAS.rglob("*.md"))
    stems   = {p.stem.lower() for p in todas}
    activas = [
        p for p in todas
        if not any(part in EXCLUIR for part in p.parts)
        and not p.name.startswith("_")
        and not p.name.endswith("-nocturno.md")   # informes propios: no re-contar
    ]

    outlinks: dict[Path, set[str]] = {}
    inlinks:  dict[str, set[Path]] = {s: set() for s in stems}
    faltantes: dict[str, set[Path]] = {}

    for p in activas:
        raw  = p.read_text(encoding="utf-8", errors="ignore")
        raw  = RE_CODIGO.sub("", raw)   # [[links]] citados en backticks no son enlaces
        outs: set[str] = set()
        for m in RE_WIKILINK.findall(raw):
            d = m.split("|")[0].split("#")[0].strip().split("/")[-1].lower()
            if not d or RE_EXT.search(d):
                continue
            outs.add(d)
            if d in inlinks:
                inlinks[d].add(p)
            else:
                faltantes.setdefault(d, set()).add(p)
        outlinks[p] = outs

    gaps = sorted(
        [(k, len(v)) for k, v in faltantes.items()],
        key=lambda x: -x[1],
    )[:15]

    huerfanas = [
        p.stem for p in activas
        if p.parent.name == "conceptos"
        and not (inlinks.get(p.stem.lower(), set()) - {p})
    ]

    libros_pelados = [
        p.stem for p in activas
        if p.parent.name == "libros"
        and len(outlinks.get(p, set())) <= 1
    ][:10]

    return LintResultado(gaps, huerfanas, libros_pelados)


def gaps_ya_reportados(hoy: date) -> set[str]:
    """Gaps listados en nocturnos de los ultimos DIAS_HISTORIAL dias."""
    vistos: set[str] = set()
    re_gap = re.compile(r"^- `\[\[([^\]]+)\]\]`", re.MULTILINE)
    for d in range(1, DIAS_HISTORIAL + 1):
        p = DIARIO / f"{hoy - timedelta(days=d)}-nocturno.md"
        if p.exists():
            texto = p.read_text(encoding="utf-8", errors="ignore")
            vistos.update(m.lower() for m in re_gap.findall(texto))
    return vistos


def check_atomicidad() -> list[NotaDensa]:
    """Detecta notas de conceptos/ que podrian empacar mas de una idea."""
    candidatas: list[NotaDensa] = []
    if not CONCEPTOS.exists():
        return candidatas
    for p in sorted(CONCEPTOS.glob("*.md")):
        if p.name.startswith("_"):
            continue
        texto    = p.read_text(encoding="utf-8", errors="ignore")
        palabras = len(texto.split())
        headings = len(re.findall(r"^#{1,3}\s", texto, re.MULTILINE))
        if palabras > UMBRAL_PALABRAS or headings > UMBRAL_HEADINGS:
            candidatas.append(NotaDensa(p, palabras, headings))
    return sorted(candidatas, key=lambda n: -n.palabras)


# ── Fase 2: Analizar ──────────────────────────────────────────────────────────

def detectar_ejes(texto: str) -> dict[str, list[str]]:
    """Devuelve los terminos de cada eje que aparecen en el texto del dia."""
    lower = texto.lower()
    return {
        eje: [t for t in terminos if t.lower() in lower]
        for eje, terminos in EJES.items()
        if any(t.lower() in lower for t in terminos)
    }


def graphrag_relacionados(terminos: list[str]) -> list[str]:
    """Llama graphrag.py related para los primeros N terminos."""
    resultados: list[str] = []
    for termino in terminos[:MAX_TERMINOS_GRAPHRAG]:
        try:
            out = subprocess.run(
                [str(VENV_PY), str(AQUI / "graphrag.py"), "related", termino],
                capture_output=True, text=True, timeout=30, cwd=str(AQUI),
            )
            if out.returncode == 0 and out.stdout.strip():
                linea = out.stdout.strip().split("\n")[0][:250]
                resultados.append(f"**{termino}**: {linea}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return resultados


def _api_key() -> str:
    """Lee ANTHROPIC_API_KEY del entorno o del .env."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env_path = AQUI / ".env"
        if env_path.exists():
            for ln in env_path.read_text(encoding="utf-8").splitlines():
                if ln.startswith("ANTHROPIC_API_KEY="):
                    key = ln.split("=", 1)[1].strip()
    return key


def llamar_api(sistema: str, usuario: str, modelo: str, max_tokens: int) -> str:
    """Llama a la API de Anthropic. Retorna cadena vacia si falla."""
    try:
        import anthropic  # noqa: PLC0415
        client = anthropic.Anthropic(api_key=_api_key())
        msg = client.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            system=sistema,
            messages=[{"role": "user", "content": usuario}],
        )
        return msg.content[0].text
    except Exception as e:  # noqa: BLE001
        return f"[API no disponible: {e}]"


def analizar_inbox(notas: list[NotaInbox]) -> str:
    """Haiku clasifica que notas del inbox merecen consolidarse."""
    if not notas:
        return ""
    resumen = "\n---\n".join(
        f"[{n.path.name}] ({n.palabras} palabras)\n{n.texto[:500]}"
        for n in notas
    )
    sistema = (
        "Eres un asistente de segundo cerebro Zettelkasten. "
        "Tu tarea es PROPONER candidatos a consolidar, nunca escribir las notas. "
        "Responde en espanol. Conciso: una linea por nota."
    )
    usuario = (
        "Estas son las notas del inbox de hoy. Para cada una, indica en UNA linea:\n"
        "(a) tiene densidad para una nota permanente en conceptos/ — sobre que concepto, o\n"
        "(b) es efimera (archivar), o\n"
        "(c) necesita mas desarrollo.\n\n"
        f"NOTAS:\n{resumen}"
    )
    return llamar_api(sistema, usuario, MODELO_CLASIFICADOR, MAX_TOKENS_HAIKU)


def analizar_crosseje(texto_dia: str, ejes: dict[str, list[str]]) -> str:
    """Sonnet detecta conexiones entre los ejes en el material del dia."""
    if len(ejes) < MIN_EJES_CRUCE:
        return ""
    ejes_str = "\n".join(f"- {eje}: {', '.join(ts)}" for eje, ts in ejes.items())
    sistema = (
        "Eres un asistente de investigacion en economia politica critica "
        "(marxismo, termodinamica, ideologia). Tu rol es socratico: senalas donde "
        "hay una conexion y PREGUNTAS; nunca entregas la conclusion elaborada "
        "(elaborarla es el aprendizaje de Getulio, no el tuyo). "
        "Responde en espanol. Breve y concreto."
    )
    usuario = (
        f"El material de hoy toca estos ejes:\n{ejes_str}\n\n"
        "Donde hay una conexion concreta entre estos ejes? Apuntala en 1-2 "
        "oraciones SIN desarrollarla, y cierra con UNA pregunta abierta dirigida "
        "a Getulio que lo obligue a elaborarla el mismo. La pregunta es lo "
        "importante; no des la respuesta ni escribas la nota."
    )
    return llamar_api(sistema, usuario, MODELO_SINTETIZADOR, MAX_TOKENS_SONNET)


# ── Fase 3: Escribir ──────────────────────────────────────────────────────────

def construir_informe(
    hoy: date,
    lint: LintResultado,
    atomicas: list[NotaDensa],
    inbox: list[NotaInbox],
    inbox_analisis: str,
    graphrag_salida: list[str],
    crosseje_analisis: str,
) -> str:
    L: list[str] = [
        "---",
        f"fecha: {hoy}",
        "tipo: nocturno",
        "---",
        "",
        f"# Nocturno {hoy}",
        "",
        "> Informe del agente nocturno. Solo propuestas - nada escrito en conceptos/.",
        "> Revisar en el repaso y decidir.",
        "",
    ]

    # --- Gaps ---
    L += ["## Gaps - conceptos mencionados sin pagina", ""]
    if lint.gaps:
        previos  = gaps_ya_reportados(hoy)
        nuevos   = [(g, n) for g, n in lint.gaps if g.lower() not in previos]
        antiguos = len(lint.gaps) - len(nuevos)
        if nuevos:
            L += [
                "Wikilinks NUEVOS que apuntan a una nota que no existe. "
                "La mas referenciada primero.",
                "",
            ]
            for nombre, n in nuevos[:10]:
                L.append(f"- `[[{nombre}]]` - mencionado en {n} {'nota' if n == 1 else 'notas'}")
        else:
            L.append("Sin gaps nuevos hoy.")
        if antiguos:
            L.append(f"- ({antiguos} gap(s) ya reportados esta semana siguen abiertos)")
    else:
        L.append("Sin gaps detectados.")
    L.append("")

    # --- Atomicidad ---
    L += ["## Candidatas a atomizar - notas densas en conceptos/", ""]
    if atomicas:
        L += [
            f"Notas con >{UMBRAL_PALABRAS} palabras o >{UMBRAL_HEADINGS} headings. "
            "Podrian empacar mas de una idea.",
            "",
        ]
        for n in atomicas[:8]:
            L.append(f"- `{n.path.stem}` - {n.palabras} palabras, {n.headings} headings")
    else:
        L.append("Todos los conceptos parecen atomicos.")
    L.append("")

    # --- Inbox ---
    L += ["## Inbox del dia - candidatos a consolidar", ""]
    if inbox:
        L += [
            f"{len(inbox)} nota(s) con >{UMBRAL_DENSIDAD_INBOX} palabras:",
            "",
        ]
        for n in inbox:
            L.append(f"- `{n.path.name}` ({n.palabras} palabras)")
        if inbox_analisis:
            L += ["", "**Analisis:**", "", inbox_analisis]
    else:
        L.append("Inbox vacio o solo notas cortas hoy.")
    L.append("")

    # --- Cross-eje ---
    L += ["## Conexiones cross-eje (lambda - epsilon - ideologia)", ""]
    if crosseje_analisis:
        L.append(crosseje_analisis)
        L += [
            "",
            "> Rito diario ([[ZETTELKASTEN]]): responde la pregunta en 3 lineas "
            "en el diario de hoy. Esas 3 lineas son tu entrada de diario.",
        ]
    elif graphrag_salida:
        L += [
            "Conexiones via graphrag (ejes insuficientes para analisis API):",
            "",
        ]
        for r in graphrag_salida:
            L.append(f"- {r}")
    else:
        L.append("Sin conexiones cross-eje detectadas hoy.")
    L.append("")

    # --- Mantenimiento (bonus, baja urgencia) ---
    if lint.huerfanas or lint.libros_pelados:
        L += ["## Mantenimiento (baja urgencia)", ""]
        if lint.huerfanas:
            L.append(f"**Conceptos huerfanos** (sin backlinks): {len(lint.huerfanas)}")
            for h in lint.huerfanas[:5]:
                L.append(f"  - {h}")
            if len(lint.huerfanas) > 5:
                L.append(f"  - ... (+{len(lint.huerfanas) - 5} mas)")
        if lint.libros_pelados:
            L.append(f"**Libros sin conceptos enlazados**: {len(lint.libros_pelados)}")
            for lb in lint.libros_pelados[:5]:
                L.append(f"  - {lb}")

    return "\n".join(L)


def escribir(contenido: str, hoy: date, dry: bool) -> None:
    destino = DIARIO / f"{hoy}-nocturno.md"
    if dry:
        print(contenido)
        print(f"\n[dry-run] Se hubiera escrito: {destino}")
    else:
        DIARIO.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")
        print(f"Nocturno escrito: {destino}")


# ── Entrada ───────────────────────────────────────────────────────────────────

def procesar_inbox_nocturno() -> list[str]:
    """Fase 0: respaldo raw -> OCR de capturas -> enlazar -> archivar.

    El eslabon mecanico del "shortly after" de Ahrens: al amanecer, los subrayados
    de ayer ya estan como citas APA en la hoja del libro. Nunca rompe el nocturno.
    """
    resumen: list[str] = []
    pasos = [
        [sys.executable, str(NOTAS / "scripts" / "respaldar_raw.py")],
        [str(VENV_PY), str(AQUI / "ocr_capturas.py")],
        [str(VENV_PY), str(AQUI / "enlazar_notas.py"), "--no-usb"],
        [str(VENV_PY), str(AQUI / "archivar_inbox.py")],
    ]
    for cmd in pasos:
        nombre = Path(cmd[1]).name
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                 cwd=str(AQUI), encoding="utf-8", errors="replace")
            lineas = (out.stdout or "").strip().splitlines()
            if lineas:
                resumen.append(f"{nombre}: {lineas[-1][:200]}")
            if out.returncode != 0:
                resumen.append(f"{nombre}: ERROR rc={out.returncode} "
                               f"{(out.stderr or '')[:200]}")
        except Exception as e:  # noqa: BLE001
            resumen.append(f"{nombre}: [aviso] {e}")
    return resumen


def main() -> None:
    p = argparse.ArgumentParser(description="Agente nocturno de consolidacion")
    p.add_argument("--dry",   action="store_true", help="Imprime sin escribir")
    p.add_argument("--fecha", default=str(date.today()), help="Fecha YYYY-MM-DD")
    args = p.parse_args()
    hoy  = date.fromisoformat(args.fecha)

    print(f"Agente nocturno - {hoy}")

    fase0: list[str] = []
    if not args.dry:
        print("  [0/4] Procesado del inbox (respaldo + OCR + enlazar + archivar)...")
        fase0 = procesar_inbox_nocturno()

    print("  [1/4] Inbox y diario...")
    inbox = leer_inbox(hoy)

    print("  [2/4] Lint del vault + atomicidad...")
    lint     = lint_rapido()
    atomicas = check_atomicidad()

    print("  [3/4] Ejes y graphrag...")
    texto_dia        = "\n".join(n.texto for n in inbox)
    ejes_detectados  = detectar_ejes(texto_dia)
    terminos         = [t for ts in ejes_detectados.values() for t in ts]
    graphrag_salida  = graphrag_relacionados(terminos) if terminos else []

    print("  [4/4] API Claude...")
    inbox_analisis   = analizar_inbox(inbox)
    crosseje_analisis = analizar_crosseje(texto_dia, ejes_detectados)

    contenido = construir_informe(
        hoy, lint, atomicas, inbox,
        inbox_analisis, graphrag_salida, crosseje_analisis,
    )
    if fase0:
        contenido += ("\n## Procesado nocturno (fase 0)\n\n"
                      + "\n".join(f"- {l}" for l in fase0) + "\n")
    escribir(contenido, hoy, args.dry)

    print(
        f"  Gaps: {len(lint.gaps)}  Huerfanas: {len(lint.huerfanas)}  "
        f"Inbox: {len(inbox)}  Atomicidad: {len(atomicas)}"
    )

    if not args.dry:
        print("  Actualizando hot.md...")
        try:
            import generar_hot  # noqa: PLC0415
            generar_hot.main()
        except Exception as e:  # noqa: BLE001
            print(f"  [aviso] hot.md no actualizado: {e}")

        # Refrescar feeds del today page (Hoy.md). Guardados: si faltan
        # credenciales/URL, cada script avisa y se continua sin romper el nocturno.
        print("  Refrescando feeds (correos + eventos)...")
        vault_scripts = NOTAS / "scripts"   # importar_correos/eventos viven en el vault
        for script in ("importar_correos.py", "importar_eventos.py"):
            try:
                subprocess.run(
                    [sys.executable, str(vault_scripts / script), "--build"],
                    timeout=120, cwd=str(vault_scripts),
                )
            except Exception as e:  # noqa: BLE001
                print(f"  [aviso] {script} no actualizado: {e}")


if __name__ == "__main__":
    main()
