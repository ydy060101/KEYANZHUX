"""Tests for the golden-set report harness (T3.6).

The synthetic output below imitates the shape printed by
``tools/check_qa.py``; it contains no official expected answer and is never
fed back into the evaluation (H05).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.eval_report import Report, build_report, parse_output, render_markdown, write_report

SAMPLE = """chunks: 45, embedded: 45 in 50s
answerable questions:
  01 q01 ok   expected=[2] pages=[2] points=ok top=0.87 | answer text must not persist
  02 q02 MISS expected=[3] pages=[4] points=no top=0.42 | answer text must not persist
unanswerable questions:
  u01 u01 refused top=0.01 reason=below threshold | answer text must not persist
  u02 u02 ANSWERED top=0.61 reason=- | answer text must not persist

anchor page accuracy: 1/2 = 0.50 (target >= 0.90)
refusal rate: 1/2 = 0.50 (target 1.00)
point hit rate (informational): 1/2 = 0.50

Q1: FAIL — anchor 0.50, refusal 0.50, points 0.50

grounded cells: 1/2 = 0.50 (target >= 0.40)
cells with correct provenance: 2/2 = 1.00 (target 1.00)

C1: PASS — grounded 0.50, provenance 1.00
"""

PASSING = """answerable questions:
  01 q01 ok   expected=[2] pages=[2] points=ok top=0.87
unanswerable questions:
  u01 u01 refused top=0.01 reason=below threshold

anchor page accuracy: 1/1 = 1.00 (target >= 0.90)
refusal rate: 1/1 = 1.00 (target 1.00)
point hit rate (informational): 1/1 = 1.00

Q1: PASS — anchor 1.00, refusal 1.00, points 1.00
"""

MODELS = {"fast": "fake-fast", "strong": "fake-strong", "embed": "fake-embed", "rerank": "fake-rerank"}


def _report(output: str) -> Report:
    return build_report(
        output,
        command="python -I tools/check_qa.py all",
        models=MODELS,
        generated_at="2026-01-02T03:04:05+00:00",
    )


def test_parses_metrics_rows_and_verdicts() -> None:
    parsed = parse_output(SAMPLE)
    assert parsed is not None
    qa, questions, refusals, compare = parsed
    assert qa.anchor_correct == 1
    assert qa.answerable == 2
    assert qa.anchor_rate == pytest.approx(0.5)
    assert qa.refused == 1
    assert qa.unanswerable == 2
    assert qa.point_hits == 1
    assert qa.verdict == "FAIL"
    assert [row.id for row in questions] == ["q01", "q02"]
    assert questions[1].point_ok is False
    assert [row.id for row in refusals] == ["u01", "u02"]
    assert refusals[1].refused is False
    assert compare is not None
    assert compare.grounded == 1
    assert compare.provenance_rate == pytest.approx(1.0)
    assert compare.verdict == "PASS"


def test_a_missing_metric_is_not_defaulted() -> None:
    with pytest.raises(ValueError):
        build_report(
            SAMPLE.replace("anchor page accuracy: 1/2 = 0.50", "anchor page accuracy: missing"),
            command="check",
            models=MODELS,
        )


def test_question_rows_must_match_the_summary_total() -> None:
    without_q02 = "\n".join(line for line in SAMPLE.splitlines() if "q02 MISS" not in line)
    with pytest.raises(ValueError):
        build_report(without_q02, command="check", models=MODELS)


def test_report_keeps_ids_and_pages_but_not_answers() -> None:
    report = _report(SAMPLE)
    rendered = render_markdown(report)
    assert "q01" in rendered
    assert "expected pages" in rendered.lower()
    assert "answer text must not persist" not in rendered
    assert "| Q1 verdict | FAIL |" in rendered
    assert "| C1 verdict | PASS |" in rendered
    assert "Golden review" in rendered
    assert f"{report.golden_entries} answerable" in rendered


def test_passing_output_produces_a_pass_report() -> None:
    report = _report(PASSING)
    assert report.verdict == "PASS"
    assert report.compare is None
    assert report.qa.anchor_rate == pytest.approx(1.0)
    assert report.qa.point_hits == 1


def test_the_committed_golden_set_has_at_least_thirty_entries() -> None:
    report = _report(PASSING)
    total = report.golden_entries + report.golden_unanswerable + report.golden_cross
    assert total >= 30


def test_write_report_creates_both_files(tmp_path: Path) -> None:
    json_path, markdown_path = write_report(_report(PASSING), tmp_path)
    assert json_path.name == "eval-qa.json"
    assert markdown_path.name == "eval-qa.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS"
    assert payload["qa"]["anchor_rate"] == pytest.approx(1.0)
    assert payload["compare"] is None
    assert "answer text must not persist" not in markdown_path.read_text(encoding="utf-8")
