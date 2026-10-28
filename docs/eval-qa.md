# QA evaluation report

- Generated (UTC): 2026-10-28T04:16:33+00:00
- Command: `python -I tools/check_qa.py all`
- Golden set: 20 answerable + 5 unanswerable + 10 cross entries (`backend/tests/golden_qa.json`)
- Golden review: every expected point is asserted against its named fixture page by `backend/tests/test_golden_qa.py`; no model output is used.
- Models: fast=workbuddy/deepseek-v4.1-flash, strong=workbuddy/deepseek-v4-pro, embed=BAAI/bge-m3, rerank=BAAI/bge-reranker-v2-m3
- Verdict: **PASS**

## Single-document QA

| Metric | Result | Target |
|---|---|---|
| Anchor page accuracy | 20/20 = 1.00 | ≥ 0.90 |
| Point hit rate (informational) | 20/20 = 1.00 | — |
| Refusal rate | 5/5 = 1.00 | 1.00 |
| Q1 verdict | PASS | PASS |

| Question | Anchor | Observed pages | Expected pages | Point | Top score |
|---|---|---|---|---|---|
| q01 | ok | [7] | [7] | ok | 0.9437 |
| q02 | ok | [7] | [7] | ok | 0.7514 |
| q03 | ok | [4] | [4] | ok | 0.7204 |
| q04 | ok | [7] | [7] | ok | 0.9874 |
| q05 | ok | [2] | [2] | ok | 0.9992 |
| q06 | ok | [5] | [5, 7] | ok | 0.8838 |
| q07 | ok | [8, 1] | [8] | ok | 0.9954 |
| q08 | ok | [7, 8] | [7] | ok | 0.9962 |
| q09 | ok | [7] | [7] | ok | 0.7895 |
| q10 | ok | [7] | [7] | ok | 0.9947 |
| q11 | ok | [7, 7, 1] | [7] | ok | 0.9849 |
| q12 | ok | [7] | [7] | ok | 0.9886 |
| q13 | ok | [8, 9] | [8] | ok | 0.9717 |
| q14 | ok | [8, 9] | [8] | ok | 0.9742 |
| q15 | ok | [5] | [5] | ok | 0.9936 |
| q16 | ok | [6] | [6] | ok | 0.9998 |
| q17 | ok | [7] | [7] | ok | 0.9996 |
| q18 | ok | [7] | [7] | ok | 0.9981 |
| q19 | ok | [7] | [7] | ok | 0.8687 |
| q20 | ok | [5] | [5] | ok | 0.8772 |

## Unanswerable questions

| Question | Result | Top score | Reason |
|---|---|---|---|
| u01 | refused | 0.001 | 最高重排分 0.001 低于阈值 0.35 |
| u02 | refused | 0.0358 | 最高重排分 0.036 低于阈值 0.35 |
| u03 | refused | 0.0005 | 最高重排分 0.001 低于阈值 0.35 |
| u04 | refused | 0.0031 | 最高重排分 0.003 低于阈值 0.35 |
| u05 | refused | 0.0051 | 最高重排分 0.005 低于阈值 0.35 |

## Multi-document comparison

| Metric | Result | Target |
|---|---|---|
| Grounded cells | 6/12 = 0.50 | ≥ 0.40 |
| Cells with correct provenance | 12/12 = 1.00 | 1.00 |
| C1 verdict | PASS | PASS |

The report stores ids, pages and scores; generated answer text is not persisted (H13).
