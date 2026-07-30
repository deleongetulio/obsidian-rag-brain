"""
rag_lib.py — RAG léxico (BM25) + utilidades de extracción/troceado, en Python puro.

Extrae el texto de EPUBs CONSERVANDO sección y página (para citas precisas tipo
"§3.4, p. 48"), salta el material no-contenido (portada, créditos, índice, bibliografía,
notas) y trocea por sección. Lo usan tanto el BM25 (aquí) como el RAG semántico
(rag_embed.py), de modo que ambos comparten exactamente los mismos trozos.

Índice BM25:  rag_index/<slug>/chunks.jsonl  (un trozo por línea, con metadatos).
"""
from __future__ import annotations

import html as _html
import json
import math
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

RAG_DIR = Path(__file__).with_name("rag_index")

# Archivos que NO son contenido (front/back matter). Se saltan al indexar.
_SKIP = re.compile(r"(cover|title|copy|cont|half|biblo|biblio|notes?|index|abt|toc|_fm\d)",
                   re.IGNORECASE)
_HEADING_SRC = r"<h[1-6][^>]*>.*?</h[1-6]>"
_HEADING = re.compile(_HEADING_SRC, re.IGNORECASE | re.DOTALL)
_PAGE_ANCHOR = re.compile(r'(?i)<a[^>]*id="page[_-](\d+)"[^>]*>')
_TAG = re.compile(r"(?s)<[^>]+>")
_SCRIPT = re.compile(r"(?s)<(script|style).*?</\1>")
_PAGE_TOK = re.compile(r"⟦P:(\d+)⟧")
_WORD = re.compile(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ]+", re.UNICODE)


def _clean(s: str) -> str:
    s = _SCRIPT.sub(" ", s)
    s = _TAG.sub(" ", s)
    s = _html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _clean_heading(h: str) -> str:
    h = h.replace("<br/>", " ").replace("<br>", " ")
    h = _PAGE_ANCHOR.sub(" ", h)
    return re.sub(r"\s+", " ", _clean(h)).strip()


# ───────────────────────── extracción por unidades (sección) ─────────────────────────

# Mínimo de caracteres alfabéticos para aceptar un PDF como "tiene texto real".
# Por debajo de esto asumimos que es un escaneo sin OCR y lo rechazamos (no indexar basura).
PDF_MIN_ALPHA = 3000


def unidades(path: Path) -> list[tuple[str, str, str]]:
    """
    Devuelve [(capitulo, seccion, texto), ...]. Despacha por formato:
    - .epub  → extracción rica (sección + tokens de página ⟦P:n⟧) vía zipfile.
    - .pdf   → texto plano vía MarkItDown (born-digital; sin página/sección — citas toscas).
    - .md/.txt → texto plano directo.
    El `texto` de EPUB conserva tokens de página ⟦P:n⟧; el de PDF/MD no (no hay locus fino).
    """
    ext = path.suffix.lower()
    if ext == ".epub":
        return _unidades_epub(path)
    if ext == ".pdf":
        return _unidades_pdf(path)
    if ext in (".md", ".markdown", ".txt"):
        return _unidades_texto(path)
    raise ValueError(f"Formato no soportado para indexar: {ext}")


def _unidades_epub(path: Path) -> list[tuple[str, str, str]]:
    """Extracción rica de EPUB (conserva sección y página). Salta front/back matter; si eso
    dejara el libro vacío (contenido tipo 'index_split_*'), reprocesa SIN filtro."""
    z = zipfile.ZipFile(path)
    todos = sorted(n for n in z.namelist()
                   if n.lower().endswith((".xhtml", ".html", ".htm")))
    filtrados = [n for n in todos if not _SKIP.search(Path(n).stem)]
    out = _procesar(z, filtrados)
    if not out:  # el filtro se comió todo el contenido -> usar todos los archivos
        out = _procesar(z, todos)
    return out


def _pdf_a_texto(path: Path) -> str:
    """PDF → texto vía MarkItDown. Devuelve '' si parece escaneo (sin capa de texto)."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise RuntimeError(
            "Falta MarkItDown para indexar PDF. Instálalo en el venv del RAG:\n"
            "  .venv-rag/Scripts/python.exe -m pip install \"markitdown[pdf]\"")
    texto = (MarkItDown().convert(str(path)).text_content or "")
    alpha = sum(c.isalpha() for c in texto)
    if alpha < PDF_MIN_ALPHA:
        # Escaneo sin OCR (o PDF protegido): no hay texto que indexar.
        return ""
    return texto


def _unidades_pdf(path: Path) -> list[tuple[str, str, str]]:
    texto = _pdf_a_texto(path)
    if not texto:
        return []  # ingest() lo reportará como "0 trozos" (necesita OCR).
    # Sin encabezados ni páginas fiables: un solo bloque; el troceador lo parte en chunks.
    return [(path.stem[:60], "", _norm_txt(texto))]


def _unidades_texto(path: Path) -> list[tuple[str, str, str]]:
    texto = path.read_text(encoding="utf-8", errors="replace")
    # Markdown: usamos los encabezados (#..) como secciones para citas más útiles.
    out: list[tuple[str, str, str]] = []
    cap = path.stem[:60]
    sec = ""
    buf: list[str] = []
    def _flush():
        if buf:
            t = _norm_txt("\n".join(buf))
            if len(t) > 120:
                out.append((cap, sec, t))
    for ln in texto.splitlines():
        if ln.lstrip().startswith("#"):
            _flush(); buf = []
            sec = ln.lstrip("# ").strip()[:70]
        else:
            buf.append(ln)
    _flush()
    if not out:  # sin encabezados: un solo bloque
        t = _norm_txt(texto)
        if len(t) > 120:
            out = [(cap, "", t)]
    return out


def _norm_txt(s: str) -> str:
    """Normaliza espacios para texto plano (PDF/MD), sin tocar el contenido."""
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _procesar(z: zipfile.ZipFile, nombres: list[str]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for n in nombres:
        cap = Path(n).stem
        try:
            raw = z.read(n).decode("utf-8", "replace")
        except Exception:
            continue
        raw = _PAGE_ANCHOR.sub(r" ⟦P:\1⟧ ", raw)
        partes = re.split(f"({_HEADING_SRC})", raw, flags=re.IGNORECASE | re.DOTALL)
        sec = ""
        for parte in partes:
            if not parte:
                continue
            if _HEADING.fullmatch(parte):
                sec = _clean_heading(parte)
            else:
                texto = _clean(parte)
                # conserva los tokens de página aunque _clean colapse espacios
                if len(re.sub(_PAGE_TOK, "", texto).strip()) > 120:
                    out.append((cap, sec, texto))
    return out


def trocear_seq(seq: list[tuple[str, int | None]], palabras: int, solape: int):
    paso = max(1, palabras - solape)
    for s in range(0, len(seq), paso):
        win = seq[s:s + palabras]
        if not win:
            break
        texto = " ".join(w for w, _ in win)
        page = next((p for _, p in win if p is not None), None)
        yield texto, page
        if s + palabras >= len(seq):
            break


def chunks_de(path: Path, palabras: int = 180, solape: int = 40) -> list[dict]:
    """Trozos con metadatos: {id, cap, sec, page, i, texto}. Compartido BM25 ↔ semántico."""
    out: list[dict] = []
    n = 0
    for cap, sec, texto in unidades(path):
        seq: list[tuple[str, int | None]] = []
        cur: int | None = None
        for w in texto.split():
            m = _PAGE_TOK.fullmatch(w)
            if m:
                cur = int(m.group(1))
                continue
            seq.append((w, cur))
        if not seq:
            continue
        for i, (txt, page) in enumerate(trocear_seq(seq, palabras, solape)):
            out.append({"id": n, "cap": cap, "sec": sec, "page": page, "i": i, "texto": txt})
            n += 1
    return out


# Compat: extracción plana (sin secciones) por si algo la usa.
def extraer(path: Path) -> list[tuple[str, str]]:
    if path.suffix.lower() == ".epub":
        return [(c, _PAGE_TOK.sub("", t)) for c, s, t in unidades(path)]
    if path.suffix.lower() == ".txt":
        return [(path.stem, path.read_text(encoding="utf-8", errors="replace"))]
    raise ValueError(f"Formato no soportado: {path.suffix}")


# ───────────────────────── índice BM25 ─────────────────────────

def construir_indice(libro: Path, slug: str, palabras: int = 180, solape: int = 40) -> Path:
    destino = RAG_DIR / slug
    destino.mkdir(parents=True, exist_ok=True)
    chunks = chunks_de(libro, palabras, solape)
    p = destino / "chunks.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (destino / "meta.json").write_text(json.dumps(
        {"slug": slug, "libro": libro.name, "n_chunks": len(chunks)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ───────────────────────── BM25 ─────────────────────────

def _tok(s: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(s)]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.N = len(docs)
        self.k1, self.b = k1, b
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / self.N) if self.N else 0.0
        self.tf = [Counter(d) for d in docs]
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def puntuar(self, query: str) -> list[tuple[int, float]]:
        q = _tok(query)
        scores = []
        for i in range(self.N):
            tf, dl = self.tf[i], self.len[i]
            s = sum(self.idf.get(t, 0.0) * (tf[t] * (self.k1 + 1)) /
                    (tf[t] + self.k1 * (1 - self.b + self.b * dl / self.avg))
                    for t in q if t in tf)
            if s > 0:
                scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores


def cargar_chunks(slug: str) -> list[dict]:
    p = RAG_DIR / slug / "chunks.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"No hay índice para '{slug}'.")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def buscar(slug: str, query: str, k: int = 5) -> list[dict]:
    chunks = cargar_chunks(slug)
    bm = BM25([_tok(c["texto"]) for c in chunks])
    res = []
    for idx, score in bm.puntuar(query)[:k]:
        c = dict(chunks[idx]); c["score"] = round(score, 3); res.append(c)
    return res
