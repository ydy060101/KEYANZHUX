"""Evidence-constrained QA with provenance (01 §9, T3.3).

The pieces:

  * `prompt` — numbered evidence blocks and the two prompt pairs;
  * `extract` — targeted extraction for metadata questions, grounded per field;
  * `verify` — H04 literal verification of numbers, names and formulas;
  * `answer` — the pipeline: retrieve → refuse (H03) → extract → generate →
    verify → map markers to anchors (H01) → SSE events.

Generation is buffered rather than token-streamed: H04 must check a whole
sentence before any of it reaches the client, and H06's cache only applies to
non-streaming calls. `answer_stream` still emits `token` events, one per
verified sentence.
"""
