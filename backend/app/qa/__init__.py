"""Evidence-constrained QA with provenance (01 §9, T3.3/T3.4).

The pieces:

  * `prompt` — numbered evidence blocks and the answer/extraction prompts;
  * `extract` — targeted extraction for metadata questions, grounded per field;
  * `verify` — H04 literal verification of numbers, names and formulas;
  * `anchor` — the block inside a cited chunk that holds the claim (H01);
  * `answer` — single-document pipeline: retrieve → refuse (H03) → extract →
    generate → verify → map markers to anchors → SSE events;
  * `compare` — per-dimension, per-document retrieval and one anchored cell at
    a time, assembled into a `CompareTable`.

Generation is buffered rather than token-streamed: H04 must check a whole
sentence before any of it reaches the client, and H06's cache only applies to
non-streaming calls. `run_qa` still emits `token` events, one per verified
sentence; `run_compare` emits one summary token and the table in `done`.
"""
