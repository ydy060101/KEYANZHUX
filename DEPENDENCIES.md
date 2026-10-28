# Dependencies

New dependencies must be recorded here with their purpose and why the existing stack is insufficient (AGENTS.md §3.1).

## Runtime

| Name | Version | Purpose | Why the existing stack is insufficient |
|---|---|---|---|
| Python | 3.11.17 | Backend runtime | Fixed by the spec. |
| Node.js | 24.22.0 | Frontend tooling | Fixed by the spec. |
| PostgreSQL | 17.6 (portable) | Relational + vector store | Fixed by the spec; Docker is unavailable so a portable build is used. |
| pgvector | 0.8.7 | Vector column type and ANN index | Required for `chunks.embedding` and `doc_fingerprints.title_abs_embedding`. |
| Redis | 5.0.14.1 (portable) | arq job queue and LLM cache | Required by arq. |

## Backend

| Name | Version | Purpose | Why the existing stack is insufficient |
|---|---|---|---|
| fastapi | 0.162.0 | HTTP API | Fixed by the spec. |
| uvicorn | 0.54.0 | ASGI server | Fixed by the spec. |
| pydantic / pydantic-settings | 2.14.1 / — | Contract validation and config | Fixed by the spec. |
| sqlalchemy | 2.0.55 | ORM | Fixed by the spec. |
| alembic | 1.16 | Migrations | Required to version the schema. |
| psycopg[binary] | 3.2 | Async PostgreSQL driver | SQLAlchemy's async engine needs an async driver. |
| pgvector | 0.4.2 | SQLAlchemy `Vector` type | No built-in SQLAlchemy support for pgvector. |
| httpx | 0.28.1 | Async HTTP for LLM and external APIs | Standard library has no async client. |
| redis | 5.3.1 | Async Redis client | Required for the LLM cache and arq. |
| arq | 0.26.3 | Background job queue | Fixed by the spec. |
| python-multipart | 0.0.32 | Multipart uploads | FastAPI requires it for `UploadFile`. |
| pymupdf | 1.28.2 | PDF text, bbox, links, rendering | Fixed by the spec. |
| numpy | 2.4.0 | Vector math | Required by embedding and MinHash. |
| pandas | 2.3.3 | CSV parsing and chart statistics | Fixed by the spec for the data workshop. |
| matplotlib | 3.11.2 | Server-side PNG rendering for data charts and figure scripts | `ChartResult.image_url` and `FigureResult.rendered` need a static image; browsers draw the interactive views from the same data but cannot fill those fields, and matplotlib is the whitelisted sandbox library. |
| psutil | 7.2.2 | RSS sampling for the figure sandbox's 512 MB limit (H09) and the H11 long-book check | `resource` is Unix-only and `tracemalloc` misses native buffers; the parent must watch the child process to terminate it before it exhausts the host. |
| python-dotenv | 1.2.4 | `.env` loading | pydantic-settings reads `.env` through it. |
| sentence-transformers | 5.7.0 | Local bge-m3 embeddings and bge-reranker-v2-m3 | Fixed by the spec; no hosted endpoint serves these models. Pulls torch 2.14.1+cpu. |
| paddlepaddle | 3.2.0 | CPU inference runtime for PaddleOCR | Fixed by the spec (PaddleOCR is the required OCR engine) and it has no other runtime. |
| paddleocr | 3.7.0 | OCR of scanned pages (T2.4) | Fixed by the spec. Version 3.x is required: 2.x aborts on a oneDNN `NotFoundError` against paddle 3.2. |
| paddlex | 3.7.2 | OCR pipeline that paddleocr 3.x delegates to | paddleocr 3.x ships no pipeline code of its own; it calls paddlex. |
| opencv-contrib-python | 4.10.0.84 | Page image decoding and the OCR detectors' backend | paddlex's `is_extra_available('ocr-core')` requires exactly this version; any other is reported as "OCR requires additional dependencies". |
| opencv-python | 5.0.0.93 | Pulled in by paddlex alongside contrib | Required by paddlex's own dependency set; both can coexist. |
| albumentations / albucore | 2.0.8 / 0.0.24 | Image augmentation imported by paddlex's OCR transforms | Import-time dependency of paddlex; albucore 0.0.24 is its exact pin and 0.3.x raises `KeyError: numpy.uint32` on import. |
| shapely | 2.2.0 | Polygon geometry in paddlex's table pipeline | Imported by paddlex at OCR-pipeline construction. |
| numpy | 2.3.5 (OCR env) | Vector math | paddlex 3.7.2 requires `<2.4`; the pinned 2.4.0 was lowered to satisfy it. |

## Backend tooling

| Name | Version | Purpose |
|---|---|---|
| pytest / pytest-asyncio | 8.4.2 / 0.26.0 | Unit tests, async tests |
| ruff | 0.17.2 | Lint and format |
| mypy | 1.19.1 | Static types (strict) |
| pre-commit | 4.4.0 | Pre-commit checks |
| types-psutil | 7.2.2.20260906 | Type stubs for psutil, used by the H11 long-book check (`tools/check_long_book.py`, `tests/test_long_book.py`) and the figure sandbox. |

## Frontend

| Name | Version | Purpose | Why the existing stack is insufficient |
|---|---|---|---|
| react / react-dom | 18.3.1 | UI | Fixed by the spec. |
| react-router-dom | 6.30 | Routing | Fixed by the spec (six routes). |
| vite | 5.4.21 | Dev server and build | Fixed by the spec. |
| typescript | 5.6 | Types (strict) | Fixed by the spec. |
| tailwindcss | 3.4 | Utility styling bound to design tokens | Fixed by the spec. |
| zustand | 5.0 | UI state (theme, shell) | Fixed by the spec. |
| @tanstack/react-query | 5.x | Server state | Fixed by the spec. |
| lucide-react | 0.468 | Icon set | Spec forbids emoji as icons. |
| framer-motion | 11.x | Motion | Fixed by the spec. |
| @radix-ui/* | latest | Accessible primitives behind shadcn-style components | Provides focus management and ARIA behaviour. |
| class-variance-authority / clsx / tailwind-merge | latest | Variant composition for design components | Needed to keep variants token-driven without magic values. |
| pdfjs-dist | 4.8 | PDF rendering with text layer | Fixed by the spec. |
| cytoscape | 3.30 | Citation graph canvas | Fixed by the spec. |
| echarts / echarts-gl | 5.5 / 2.0.9 | Charts incl. 3-D radar | Fixed by the spec. |
| katex | 0.16 | Formula rendering | Fixed by the spec. |
| mermaid | 11.x | Flow diagrams | Fixed by the spec. |
| @monaco-editor/react | 4.6 | Script editor | Fixed by the spec. |
| openapi-fetch | 0.13 | Typed API client | Generated types need a matching runtime client. |

## Frontend tooling

| Name | Version | Purpose |
|---|---|---|
| vitest / jsdom | 2.1.9 / 25.x | Unit tests |
| @testing-library/react + user-event + jest-dom | 16.x / 14.x / 6.x | Component behaviour tests |
| @playwright/test | 1.5x | End-to-end tests |
| eslint + typescript-eslint | 9.39 / 8.72 | Lint with type information |

## Not yet added

These are required by later cards and will be registered when their card starts:
`rank_bm25`, `minhash`, `sickle`, `APScheduler`, `networkx`, `scikit-learn`,
`rapidfuzz`, `openpyxl`, `python-docx`.
