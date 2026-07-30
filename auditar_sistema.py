"""
auditar_sistema.py — chequeo de salud del agente teoría-crítica (read-only, ~segundos).

Inspirado en el /audit de AIS-OS, pero adaptado a NUESTRAS piezas reales: servidor RAG,
frescura del índice de notas, caché de embeddings, inbox, índices de libros, GraphRAG,
espejo en Drive, tareas programadas, autostart y credenciales (.env).

NO carga el modelo ni modifica nada: solo mira y reporta qué está bien y qué arreglar.
Pensado para correr al iniciar sesión con el tutor (te saluda con el estado) o a mano.
Corre con el python del SISTEMA (no necesita el venv):

    python auditar_sistema.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

from config import AQUI, DRIVE, NOTAS, RAG_DIR, utf8

utf8()

OK, WARN, BAD = "ok", "warn", "bad"
ICON = {OK: "✅", WARN: "⚠️", BAD: "❌"}
_res: list[tuple[str, str, str]] = []  # (severidad, título, detalle)


def add(sev: str, titulo: str, detalle: str = "") -> None:
    _res.append((sev, titulo, detalle))


# ── chequeos individuales (cada uno tolerante a fallos) ──────────────────────
def c_servidor() -> None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1.5) as r:
            ok = json.loads(r.read()).get("ok")
        add(OK, "Servidor RAG", "vivo en :8765 — búsquedas instantáneas") if ok else \
            add(WARN, "Servidor RAG", "responde raro en :8765")
    except Exception:
        add(WARN, "Servidor RAG", "apagado — las búsquedas cargan el modelo (~15s). "
            "Arráncalo: .venv-rag\\Scripts\\pythonw.exe rag_server.py")


def c_misnotas() -> None:
    d = RAG_DIR / "mis-notas"
    vp, mp, hp = d / "vectors.npy", d / "meta.json", d / "hashes.json"
    if not vp.exists():
        add(BAD, "Índice mis-notas", "no existe — corre indexar_notas.py")
        return
    vts = vp.stat().st_mtime
    fuentes: list[Path] = []
    for sub in ("conceptos", "libros"):
        fuentes += [p for p in (NOTAS / sub).glob("*.md") if not p.name.startswith("_")]
    for f in (NOTAS / "kindle" / "clippings.json", NOTAS / "neatreader" / "notes.json"):
        if f.exists():
            fuentes.append(f)
    nuevas = [p for p in fuentes if p.stat().st_mtime > vts + 1]
    if nuevas:
        ej = nuevas[0].name
        add(WARN, "Índice mis-notas", f"{len(nuevas)} nota(s) más nuevas que el índice "
            f"(p.ej. {ej}) → reindexa: indexar_notas.py")
    else:
        add(OK, "Índice mis-notas", f"al día (vs {len(fuentes)} fuentes)")
    # caché de embeddings: hashes.json debe existir y su largo igualar n_chunks
    try:
        n = json.loads(mp.read_text(encoding="utf-8")).get("n_chunks")
        if not hp.exists():
            add(WARN, "Caché de embeddings", "sin hashes.json → el próximo reindex re-embebe TODO (lento)")
        else:
            hn = len(json.loads(hp.read_text(encoding="utf-8")))
            if hn == n:
                add(OK, "Caché de embeddings", f"sano ({hn} hashes) → próximo reindex incremental (segundos)")
            else:
                add(WARN, "Caché de embeddings", f"desajuste ({hn} hashes vs {n} trozos) → reindex completo la próxima vez")
    except Exception as e:  # noqa: BLE001
        add(WARN, "Caché de embeddings", f"no verificable ({e})")


def c_inbox() -> None:
    pend = [p for p in (NOTAS / "inbox").rglob("*.md") if p.name != "README.md"]
    add(WARN, "Inbox de notas", f"{len(pend)} sin archivar → corre archivar_inbox.py") if pend \
        else add(OK, "Inbox de notas", "vacío (todo archivado)")


def c_indices() -> None:
    if not RAG_DIR.exists():
        add(BAD, "Índices RAG", "rag_index/ no existe")
        return
    libros = [x for x in RAG_DIR.iterdir() if x.is_dir() and x.name != "mis-notas"]
    add(OK, "Índices de libros", f"{len(libros)} libros citables")
    add(OK, "GraphRAG", "grafo construido") if (RAG_DIR / "graph.json").exists() \
        else add(WARN, "GraphRAG", "sin graph.json → corre graphrag.py build")


def c_drive() -> None:
    add(OK, "Espejo en Drive", f"montado ({DRIVE})") if DRIVE.exists() \
        else add(WARN, "Espejo en Drive", f"{DRIVE} no accesible (¿Drive para Escritorio apagado?)")


def c_tareas() -> None:
    for t in ("AgenteTeoriaCritica-SyncVault",):
        corto = t.split("-")[-1]
        try:
            out = subprocess.run(["schtasks", "/query", "/tn", t, "/fo", "csv", "/nh"],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode != 0 or not out.stdout.strip():
                add(WARN, f"Tarea {corto}", "no registrada — recréala")
                continue
            fila = list(csv.reader(io.StringIO(out.stdout.strip())))[-1]
            estado = (fila[-1] if fila else "?").strip()
            add(WARN, f"Tarea {corto}", f"estado: {estado}") if "disab" in estado.lower() \
                or "deshab" in estado.lower() else add(OK, f"Tarea {corto}", estado)
        except Exception as e:  # noqa: BLE001
            add(WARN, f"Tarea {corto}", f"no verificable ({e})")


def c_autostart() -> None:
    lnk = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" /
           "Start Menu" / "Programs" / "Startup" / "RAG Server (agente).lnk")
    add(OK, "Autostart RAG", "acceso directo en Startup") if lnk.exists() \
        else add(WARN, "Autostart RAG", "sin .lnk en Startup → el servidor no arranca al iniciar Windows")


def c_env() -> None:
    esperadas = ["ANTHROPIC_API_KEY", "ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID"]
    envp = AQUI / ".env"
    if not envp.exists():
        add(BAD, ".env credenciales", "no existe — faltan todas las credenciales")
        return
    claves = set()
    for ln in envp.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            claves.add(ln.split("=", 1)[0].strip())
    faltan = [k for k in esperadas if k not in claves]  # solo nombres, nunca valores
    add(WARN, ".env credenciales", "faltan: " + ", ".join(faltan)) if faltan \
        else add(OK, ".env credenciales", f"{len(esperadas)} claves presentes")


def main() -> None:
    for fn in (c_servidor, c_misnotas, c_inbox, c_indices, c_drive,
               c_tareas, c_autostart, c_env):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — un chequeo roto no debe tumbar la auditoría
            add(WARN, fn.__name__, f"chequeo falló ({e})")

    ancho = max((len(t) for _, t, _ in _res), default=10)
    print(f"\n╭─ Auditoría del sistema · {datetime.now():%Y-%m-%d %H:%M}")
    print("│")
    for sev, titulo, detalle in _res:
        print(f"│  {ICON[sev]}  {titulo.ljust(ancho)}  {detalle}")
    n_ok = sum(s == OK for s, _, _ in _res)
    n_w = sum(s == WARN for s, _, _ in _res)
    n_b = sum(s == BAD for s, _, _ in _res)
    print("│")
    print(f"╰─ {n_ok} ok · {n_w} avisos · {n_b} fallos")
    pendientes = [(t, d) for s, t, d in _res if s != OK]
    if pendientes:
        print("\n  Acciones sugeridas:")
        for t, d in pendientes:
            print(f"   • {t}: {d}")
    else:
        print("\n  Todo en orden. Solo leer, anotar y discutir. ✦")


if __name__ == "__main__":
    main()
