# Open questions and environment constraints

Per AGENTS.md §2.4, ambiguities are recorded here rather than guessed at.

## Environment constraints

- **Docker is not installed and will not be installed.** T0.6's `docker compose up` acceptance cannot be run on this host. The portable runtime under `D:\科研助手-runtime` (PostgreSQL 17.6 + pgvector 0.8.7 + Redis 5.0.14.1) plays that role; `tools.ps1 db-up` starts it.
- **GNU Make is not installed.** `tools.ps1` is the single entry point (`dev | test | lint | typecheck | build | accept | db-up | db-down | db-reset | eval-qa | gen-api`). Every card's acceptance command is `.\tools.ps1 accept` plus that card's specific checks.
- **Portable PostgreSQL must live on an ASCII path.** `initdb` fails with `invalid byte sequence for encoding "UTF8": 0xbf` when its binaries sit under `D:\科研助手`. The runtime therefore lives at `D:\科研助手-runtime`. The application code and repository are unaffected.
- **Windows event loop.** psycopg's async mode cannot run on `ProactorEventLoop`; `app/db.py` sets `WindowsSelectorEventLoopPolicy` at import.
- **No DeepSeek API key.** The `DEEPSEEK_API_KEY` environment variable is empty. Instead, a local OpenAI-compatible endpoint at `127.0.0.1:3425` serves `workbuddy-ai/deepseek-v4.1-flash` (fast) and `workbuddy/deepseek-v4-pro` (strong); both were verified for chat, SSE streaming and JSON mode. `LLM_BASE_URL` points there. If the endpoint is unavailable, LLM-dependent features must degrade rather than return 500 (H08).
- **Embeddings and reranking are not served by that endpoint.** `bge-m3` and `bge-reranker-v2-m3` must run locally. `huggingface.co` is unreachable from this host; `hf-mirror.com` and ModelScope respond, so `HF_ENDPOINT` defaults to the mirror. First run downloads several GB of weights.
- **Test PDFs are not in the repository.** `C:\Users\ydy24\Downloads\Documents` holds `1706.03762v1.pdf`, `1706.03762v7.pdf`, `1810.04805_bert.pdf`, `2005.14165_gpt3.pdf` and the 541-page `UnderstandingDeepLearning_02_09_26_C.pdf`. `1706.03762v1_img.pdf` (the scanned variant needed for case B2) is **not** present in that folder and must be obtained before T2.4. Copies are staged into `data/pdf/` by `tools.ps1`, not committed (04 §1).

## Contract questions

- 01 §4 lists table fields but not nullability or defaults. T0.2 chose: ids are uuid strings, `documents.status` starts at `uploading`, `blocks.confidence` defaults to 1.0, `assets.bbox` is a 4-float array. These need confirmation before any shape change.
- 01 §5 marks several path/field cells as `\`...\`` alternatives inside table cells (e.g. `POST /documents/{id}/dedup/resolve`), which the source renders ambiguously. T0.2 keeps every literal path string exactly as written.
- `datasets` and `figures` have descriptive rather than exact column lists. Their ORM columns are the minimum needed to preserve the uploaded data, scripts, render paths, caption and stats.
- 01 §3 shows `anchor` objects but not whether `bbox` is `[x0,y0,x1,y1]` or an object. T0.2 uses a 4-element array everywhere, matching `blocks.bbox`.

## Decisions taken during T0.1–T0.3

- `tools.ps1` replaces `Makefile` (environment constraint above).
- Package name is `research-agent-backend`; the module is `app`.
- The LLM gateway caches only deterministic (`temperature == 0`) non-streaming calls; the key is a hash of resolved model, messages, schema, temperature and tools. `cache_prefix` is prepended to messages and is therefore part of the key.
- A system prompt carrying the prompt-injection guard (H10) is injected into every request if the caller did not supply one.
- `LLM_FAST` / `LLM_STRONG` are read from config and never hard-coded in business code.
- Ruff `line-length` is 120 rather than the default 88 to accommodate the ORM's declarative columns without meaningless wrapping.
