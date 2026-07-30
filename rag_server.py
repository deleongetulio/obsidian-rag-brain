"""
rag_server.py — servidor RAG persistente (OPCIONAL) que mantiene el modelo y los vectores
en memoria, para que las búsquedas del tutor sean INSTANTÁNEAS en vez de pagar la carga del
modelo (~1.1 GB / varios segundos) en cada consulta.

Corre en el venv del RAG:
    .venv-rag/Scripts/python.exe rag_server.py        # arranca en 127.0.0.1:8765

El CLI de rag_embed.py (search / hybrid / search-all) intenta este servidor primero y, si no
está corriendo, cae al modo en-proceso (carga el modelo). O sea: es 100% opcional y sin riesgo.

Endpoints (GET, JSON):
    /health
    /search?slug=<slug>&q=<query>&k=5
    /hybrid?slug=<slug>&q=<query>&k=5
    /search-all?q=<query>&k=5
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import rag_embed as R
from config import utf8

HOST, PORT = "127.0.0.1", 8765


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silenciar el log por petición
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        k = int(q.get("k", 5))
        try:
            if u.path == "/health":
                return self._send({"ok": True})
            if u.path == "/search":
                return self._send(R.search(q["slug"], q["q"], k))
            if u.path == "/hybrid":
                return self._send(R.search_hybrid(q["slug"], q["q"], k))
            if u.path == "/search-all":
                temas = {t.strip() for t in q["tema"].split(",")} if q.get("tema") else None
                slugs = {s.strip() for s in q["slugs"].split(",")} if q.get("slugs") else None
                return self._send(R.search_all(q["q"], k, temas, slugs))
            self._send({"error": "ruta desconocida"}, 404)
        except Exception as e:  # noqa: BLE001
            self._send({"error": str(e)}, 500)


def main() -> None:
    utf8()
    print("→ Cargando modelo (1ª vez)…", flush=True)
    R.modelo()  # precarga para que la 1ª consulta ya sea rápida
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"✓ RAG server escuchando en http://{HOST}:{PORT}  (Ctrl-C para parar)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n→ Parando servidor.")
        srv.shutdown()


if __name__ == "__main__":
    main()
