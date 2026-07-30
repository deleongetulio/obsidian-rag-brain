"""
nocturno_config.py - Configuracion editable del agente nocturno.

Cambiar aqui sin tocar agente_nocturno.py.
"""
from __future__ import annotations

# ── Atomicidad ───────────────────────────────────────────────────────────────
# Nota de conceptos/ con MAS palabras o headings -> candidata a dividir
UMBRAL_PALABRAS  = 500
UMBRAL_HEADINGS  = 3

# ── Densidad de inbox ────────────────────────────────────────────────────────
# Nota de inbox con MENOS palabras que esto -> ignorar (demasiado corta)
UMBRAL_DENSIDAD_INBOX = 150

# ── Ejes de investigacion (cross-eje lambda / epsilon / ideologia) ───────────
# Terminos que activan cada eje al aparecer en inbox o diario del dia
EJES: dict[str, list[str]] = {
    "valor-lambda": [
        "valor", "trabajo", "plusvalia", "MIP", "lambda", "coeficiente",
        "Heinrich", "Shaikh", "Marx", "capital", "explotacion", "precio",
        "salario", "tasa de ganancia",
    ],
    "termodinamica-epsilon": [
        "emergy", "energia", "exergia", "termodinamica", "epsilon",
        "Odum", "Georgescu-Roegen", "entropia", "metabolismo", "disipacion",
        "recursos naturales", "biofisica",
    ],
    "ideologia": [
        "ideologia", "Zizek", "Lacan", "Fanon", "colonialismo", "raza",
        "necrocapitalismo", "Mbembe", "fantasia", "antagonismo", "Han",
        "hegemonia", "discurso", "sujeto", "interpelacion",
    ],
}

# Minimo de ejes tocados en el dia para llamar a Sonnet con cross-eje
MIN_EJES_CRUCE = 2

# ── Graphrag ─────────────────────────────────────────────────────────────────
# Cuantos terminos del dia pasar a graphrag related (evitar llamadas excesivas)
MAX_TERMINOS_GRAPHRAG = 3

# ── Historial ────────────────────────────────────────────────────────────────
# Dias hacia atras para no repetir notas ya reportadas en nocturnos previos
DIAS_HISTORIAL = 7

# ── Modelos API ──────────────────────────────────────────────────────────────
MODELO_CLASIFICADOR = "claude-haiku-4-5-20251001"  # clasifica densidad inbox
MODELO_SINTETIZADOR = "claude-sonnet-4-6"           # conexiones cross-eje

MAX_TOKENS_HAIKU  = 1024
MAX_TOKENS_SONNET = 2048
