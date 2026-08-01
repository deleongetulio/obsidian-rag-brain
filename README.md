# Obsidian RAG Brain

*Translated version - [original in Spanish](README.es.md)*

A set of scripts that turn an Obsidian vault (a personal knowledge base) into
a system that can be searched, cross-referenced, and maintained with the help
of an LLM - without ever letting the LLM write into the curated, permanent
parts of the vault on its own.

## Architecture

```
Raw capture (inbox/, diario/)
        |
        v
archivar_inbox.py  --  files each note into its right destination
        |
        v
indexar_notas.py  --  embeds curated notes (sentence-transformers) into a
        |              local vector index (incremental: hashes unchanged
        |              content to skip re-embedding)
        v
rag_embed.py / rag_lib.py  --  hybrid search (vector + keyword) over your
        |                      own notes AND a library of indexed books,
        |                      built for citing sources verbatim
        v
rag_server.py  --  keeps the embedding model warm in memory so searches
                    are instant instead of reloading the model every time

graphrag.py       --  builds a concept graph from wikilinks for
                       "what connects to what" queries
enlazar_notas.py,        --  link-maintenance: suggest/verify wikilinks,
enlazar_archivos.py          resolve broken references
etiquetar_generos.py,    --  classify books/notes by topic and detect
construir_temas.py           duplicate concepts across the vault
generar_hot.py    --  surfaces the most-connected notes for review
repaso.py         --  spaced-repetition-style prompt to revisit old notes
kindle_clippings.py,     --  parse highlight exports into vault-ready notes
neat_clippings.py
zotero_sync.py    --  two-way sync between the vault and a Zotero library
ocr_capturas.py   --  OCR handwritten note scans into Markdown (Claude vision)
auditar_sistema.py --  read-only health check: is the RAG server up, is the
                        index stale, is the inbox backed up, etc.
agente_nocturno.py --  nightly "offline memory consolidation" pass: reads
                        what entered the vault that day, detects patterns,
                        and writes PROPOSALS to a review file - it never
                        writes directly into the curated notes
```

## Why this design

- **Propose, don't write.** `agente_nocturno.py` is explicitly forbidden
  (by convention, not just by prompt) from touching the curated `conceptos/`
  folder. Automation surfaces candidates; a human decides what's permanent.
  This is the core guardrail of the whole system: an LLM is good at noticing
  patterns and bad at deciding what should be permanently true.
- **Incremental by design.** The embedding index hashes note content so a
  re-run only re-embeds what changed - reindexing a large vault takes
  seconds instead of minutes once the cache is warm.
- **Two-speed dependencies.** Heavy ML dependencies (`torch`,
  `sentence-transformers`) live in their own virtual environment
  (`requirements-rag.txt`), separate from the lightweight system-Python
  scripts (`requirements.txt`), so running a quick maintenance script doesn't
  require a multi-GB install.

## Setup

1. System scripts: `pip install -r requirements.txt`
2. RAG scripts (heavier): create a separate venv and
   `pip install -r requirements-rag.txt` there.
3. Copy `.env.example` to `.env` and fill in your own `ANTHROPIC_API_KEY`
   (and `ZOTERO_API_KEY`/`ZOTERO_LIBRARY_ID` if you use Zotero sync).
4. Edit `config.py`: point `NOTAS` at your own Obsidian vault path.

These scripts assume a vault with `inbox/`, `diario/` (daily notes),
`conceptos/` (curated atomic notes), and `libros/` folders - adjust the
constants in `config.py` to match your own structure.

## Skills demonstrated

Local embeddings and hybrid search, incremental indexing with content
hashing, LLM-assisted classification with a human-in-the-loop guardrail, and
building a personal knowledge-management pipeline that treats "propose" and
"commit" as separate stages.

---

[getuliodeleon.com](https://getuliodeleon.com/) | [LinkedIn](https://www.linkedin.com/in/getulio-cesar-de-leon-fernandez-05267a3b3/) | [GitHub](https://github.com/deleongetulio)
