# Obsidian RAG Brain

*Version original - [traduccion al ingles](README.md)*

Un conjunto de scripts que convierten un vault de Obsidian (una base de
conocimiento personal) en un sistema que se puede buscar, entrelazar y
mantener con ayuda de un LLM - sin dejar que el LLM escriba por su cuenta en
las partes curadas y permanentes del vault.

## Arquitectura

```
Captura cruda (inbox/, diario/)
        |
        v
archivar_inbox.py  --  archiva cada nota en su destino correcto
        |
        v
indexar_notas.py  --  embebe las notas curadas (sentence-transformers) en un
        |              indice vectorial local (incremental: hashea el
        |              contenido sin cambios para saltar el re-embebido)
        v
rag_embed.py / rag_lib.py  --  busqueda hibrida (vectorial + keyword) sobre
        |                      tus propias notas Y una biblioteca de libros
        |                      indexados, pensada para citar fuentes verbatim
        v
rag_server.py  --  mantiene el modelo de embeddings caliente en memoria para
                    que las busquedas sean instantaneas en vez de recargar
                    el modelo cada vez

graphrag.py       --  construye un grafo de conceptos desde los wikilinks
                       para preguntas de "que se conecta con que"
enlazar_notas.py,        --  mantenimiento de enlaces: sugiere/verifica
enlazar_archivos.py          wikilinks, resuelve referencias rotas
etiquetar_generos.py,    --  clasifica libros/notas por tema y detecta
construir_temas.py           conceptos duplicados en el vault
generar_hot.py    --  saca a la luz las notas mas conectadas para revisar
repaso.py         --  prompt estilo repeticion espaciada para revisitar notas
kindle_clippings.py,     --  parsea exports de subrayados en notas listas
neat_clippings.py             para el vault
zotero_sync.py    --  sincronizacion bidireccional entre el vault y Zotero
ocr_capturas.py   --  OCR de capturas manuscritas a Markdown (Claude vision)
auditar_sistema.py --  chequeo de salud read-only: esta vivo el servidor RAG,
                        esta desactualizado el indice, hay inbox sin archivar
agente_nocturno.py --  pasada nocturna de "consolidacion de memoria offline":
                        lee lo que entro al vault ese dia, detecta patrones,
                        y escribe PROPUESTAS a un archivo de revision - nunca
                        escribe directamente en las notas curadas
```

## Por que este diseno

- **Proponer, no escribir.** A `agente_nocturno.py` se le prohibe
  explicitamente (por convencion, no solo por prompt) tocar la carpeta
  curada `conceptos/`. La automatizacion saca candidatos a la luz; una
  persona decide que es permanente. Este es el guardarrail central de todo
  el sistema: un LLM es bueno detectando patrones y malo decidiendo que
  deberia ser permanentemente verdadero.
- **Incremental por diseno.** El indice de embeddings hashea el contenido de
  las notas para que una re-corrida solo re-embeba lo que cambio -
  reindexar un vault grande toma segundos en vez de minutos una vez que el
  cache esta caliente.
- **Dependencias de dos velocidades.** Las dependencias pesadas de ML
  (`torch`, `sentence-transformers`) viven en su propio entorno virtual
  (`requirements-rag.txt`), separado de los scripts livianos del python del
  sistema (`requirements.txt`), asi que correr un script de mantenimiento
  rapido no requiere una instalacion de varios GB.

## Configuracion

1. Scripts del sistema: `pip install -r requirements.txt`
2. Scripts del RAG (mas pesados): crear un venv separado e instalar ahi
   `pip install -r requirements-rag.txt`.
3. Copiar `.env.example` a `.env` y llenar tu propio `ANTHROPIC_API_KEY` (y
   `ZOTERO_API_KEY`/`ZOTERO_LIBRARY_ID` si usas la sincronizacion con Zotero).
4. Editar `config.py`: apuntar `NOTAS` a tu propio vault de Obsidian.

Estos scripts asumen un vault con carpetas `inbox/`, `diario/` (notas
diarias), `conceptos/` (notas atomicas curadas) y `libros/` - ajusta las
constantes en `config.py` a tu propia estructura.

## Habilidades demostradas

Embeddings locales y busqueda hibrida, indexado incremental con hashing de
contenido, clasificacion asistida por LLM con un guardarrail humano-en-el-
circuito, y construccion de un pipeline de gestion de conocimiento personal
que trata "proponer" y "confirmar" como etapas separadas.

---

[getuliodeleon.com](https://getuliodeleon.com/es/) | [LinkedIn](https://www.linkedin.com/in/getuliodeleon/) | [GitHub](https://github.com/deleongetulio)
