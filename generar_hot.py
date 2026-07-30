"""
generar_hot.py - Genera hot.md: cache de actividad reciente del vault (~500 palabras).

hot.md se carga al inicio de cada sesion del tutor (teoria-critica) para no arrancar
frio. Equivale al "hipocampo reciente" del sistema: lo que cambio en los ultimos dias,
sin tener que leer el vault entero.

Se regenera automaticamente:
  - Al final de cada agente_nocturno.py
  - Al terminar cualquier sesion de Claude Code (hook Stop en settings.json)

Corre con el python del sistema (no necesita venv):
    python generar_hot.py
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from config import AQUI, NOTAS, utf8

utf8()

DIARIO    = NOTAS / "diario"
CONCEPTOS = NOTAS / "conceptos"
INBOX     = NOTAS / "inbox"
LIBROS    = NOTAS / "libros"
HOT       = AQUI / "hot.md"

DIAS_CONCEPTOS = 7
DIAS_LIBROS    = 14
MAX_ITEMS      = 6


def _recientes(carpeta: Path, dias: int) -> list[Path]:
    """Archivos .md modificados en los ultimos N dias, ordenados por fecha desc."""
    corte = datetime.now().timestamp() - dias * 86400
    return sorted(
        [p for p in carpeta.glob("*.md")
         if not p.name.startswith("_") and p.stat().st_mtime > corte],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _ultimo_nocturno() -> tuple[str, str]:
    """Retorna (fecha_str, resumen) del ultimo nocturno.md en diario/."""
    if not DIARIO.exists():
        return "", ""
    nocturnos = sorted(DIARIO.glob("*-nocturno.md"), reverse=True)
    if not nocturnos:
        return "", ""
    p = nocturnos[0]
    fecha = p.name.replace("-nocturno.md", "")
    texto = p.read_text(encoding="utf-8", errors="ignore")
    # Extraer gaps (primera seccion con contenido util)
    lineas: list[str] = []
    en_gaps = False
    for ln in texto.splitlines():
        if "## Gaps" in ln:
            en_gaps = True
            continue
        if en_gaps:
            if ln.startswith("##"):
                break
            if ln.strip().startswith("-"):
                lineas.append(ln.strip())
                if len(lineas) >= 5:
                    break
    return fecha, "\n".join(lineas) if lineas else "(sin gaps)"


def _inbox_actual() -> list[str]:
    if not INBOX.exists():
        return []
    return [
        f"`{p.name}` ({len(p.read_text(encoding='utf-8', errors='ignore').split())} palabras)"
        for p in sorted(INBOX.rglob("*.md"))
        if not p.name.startswith("_")
    ][:MAX_ITEMS]


def _diarios_recientes() -> list[str]:
    if not DIARIO.exists():
        return []
    entradas = sorted(
        [p for p in DIARIO.glob("????-??-??.md")],
        reverse=True,
    )[:3]
    return [p.stem for p in entradas]


def generar() -> str:
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    hoy   = date.today()

    conceptos_recientes = _recientes(CONCEPTOS, DIAS_CONCEPTOS)
    libros_recientes    = _recientes(LIBROS, DIAS_LIBROS)
    inbox_items         = _inbox_actual()
    diarios             = _diarios_recientes()
    fecha_nocturno, gaps_nocturno = _ultimo_nocturno()

    L: list[str] = [
        "---",
        f"actualizado: {ahora}",
        "---",
        "",
        "# Hot cache - actividad reciente del vault",
        "",
        "> Cache auto-generado. No editar a mano - se sobreescribe en cada sesion.",
        "",
    ]

    # --- Ultimo nocturno ---
    L += ["## Ultimo nocturno", ""]
    if fecha_nocturno:
        L += [
            f"Fecha: {fecha_nocturno}",
            f"Top gaps detectados:",
            gaps_nocturno,
        ]
    else:
        L.append("Sin nocturnos generados todavia.")
    L.append("")

    # --- Conceptos activos ---
    L += [f"## Conceptos modificados (ultimos {DIAS_CONCEPTOS} dias)", ""]
    if conceptos_recientes:
        for p in conceptos_recientes[:MAX_ITEMS]:
            dias = int((datetime.now().timestamp() - p.stat().st_mtime) / 86400)
            L.append(f"- `{p.stem}` (hace {dias}d)")
    else:
        L.append("Sin cambios recientes en conceptos/.")
    L.append("")

    # --- Inbox ---
    L += ["## Inbox actual", ""]
    if inbox_items:
        for item in inbox_items:
            L.append(f"- {item}")
    else:
        L.append("Inbox vacio.")
    L.append("")

    # --- Libros recientes ---
    L += [f"## Libros registrados (ultimos {DIAS_LIBROS} dias)", ""]
    if libros_recientes:
        for p in libros_recientes[:MAX_ITEMS]:
            L.append(f"- `{p.stem}`")
    else:
        L.append("Sin libros nuevos recientes.")
    L.append("")

    # --- Diarios ---
    L += ["## Ultimas entradas de diario", ""]
    if diarios:
        for d in diarios:
            L.append(f"- {d}")
    else:
        L.append("Sin entradas de diario.")

    return "\n".join(L)


def main() -> None:
    contenido = generar()
    HOT.write_text(contenido, encoding="utf-8")
    lineas = contenido.count("\n")
    print(f"hot.md generado ({lineas} lineas) -> {HOT}")


if __name__ == "__main__":
    main()
