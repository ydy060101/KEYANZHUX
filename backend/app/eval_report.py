"""Report model and rendering for the golden-set QA evaluation (T3.6).

`app.eval_qa` runs `tools/check_qa.py` and hands its output here. Parsing and
rendering live in their own module so both stay testable and every file stays
under the project's 400-line limit. A missing metric raises instead of being
defaulted (H02/H05); answer snippets are discarded (H13).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
GOLDEN_PATH = BACKEND / "tests" / "golden_qa.json"
DEFAULT_OUTPUT = REPO / "docs"

_ANCHOR = re.compile(r"anchor page accuracy:\s*(\d+)/(\d+)\s*=\s*([\d.]+)")
_REFUSAL = re.compile(r"refusal rate:\s*(\d+)/(\d+)\s*=\s*([\d.]+)")
_POINTS = re.compile(r"point hit rate \(informational\):\s*(\d+)/(\d+)\s*=\s*([\d.]+)")
_Q1 = re.compile(r"^Q1:\s*(PASS|FAIL)", re.MULTILINE)
_C1 = re.compile(r"^C1:\s*(PASS|FAIL)", re.MULTILINE)
_GROUNDED = re.compile(r"grounded cells:\s*(\d+)/(\d+)\s*=\s*([\d.]+)")
_PROVENANCE = re.compile(r"cells with correct provenance:\s*(\d+)/(\d+)\s*=\s*([\d.]+)")
_QUESTION_ROW = re.compile(
    r"^\s+(?:\d{2}\s+)?(?P<id>q\d{2})\s+(?P<status>ok|MISS|REF)\s+"
    r"expected=(?P<expected>\[[^\]]*\])\s+pages=(?P<pages>\[[^\]]*\])\s+"
    r"points=(?P<points>ok|no)\s+top=(?P<top>\S+)"
)
_REFUSAL_ROW = re.compile(
    r"^\s+u\d{2}\s+(?P<id>u\d{2})\s+(?P<status>refused|ANSWERED)\s+"
    r"top=(?P<top>\S+)\s+reason=(?P<reason>.*)$"
)


@dataclass(frozen=True)
class QuestionRow:
    id: str
    status: str
    expected_pages: str
    pages: str
    point_ok: bool
    top: str


@dataclass(frozen=True)
class RefusalRow:
    id: str
    refused: bool
    top: str
    reason: str


@dataclass(frozen=True)
class QaMetrics:
    anchor_correct: int
    answerable: int
    anchor_rate: float
    refused: int
    unanswerable: int
    refusal_rate: float
    point_hits: int
    point_rate: float
    verdict: str


@dataclass(frozen=True)
class CompareMetrics:
    grounded: int
    total: int
    grounded_rate: float
    provenance: int
    provenance_rate: float
    verdict: str


@dataclass(frozen=True)
class Report:
    generated_at: str
    command: str
    golden_entries: int
    golden_cross: int
    golden_unanswerable: int
    models: dict[str, str]
    qa: QaMetrics
    questions: tuple[QuestionRow, ...]
    refusals: tuple[RefusalRow, ...]
    compare: CompareMetrics | None
    verdict: str

    def as_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "command": self.command,
            "golden": {
                "path": "backend/tests/golden_qa.json",
                "entries": self.golden_entries,
                "cross": self.golden_cross,
                "unanswerable": self.golden_unanswerable,
            },
            "models": dict(self.models),
            "qa": {
                **asdict(self.qa),
                "questions": [asdict(row) for row in self.questions],
                "refusals": [asdict(row) for row in self.refusals],
            },
            "compare": asdict(self.compare) if self.compare else None,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class _Ratio:
    numerator: int
    denominator: int
    rate: float


def _ratio(match: re.Match[str] | None) -> _Ratio | None:
    if match is None:
        return None
    return _Ratio(int(match.group(1)), int(match.group(2)), float(match.group(3)))


def _count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _golden_counts() -> tuple[int, int, int]:
    raw = cast(dict[str, object], json.loads(GOLDEN_PATH.read_text(encoding="utf-8")))
    return (
        _count(raw.get("entries")),
        _count(raw.get("cross")),
        _count(raw.get("unanswerable")),
    )


def _question_rows(output: str) -> tuple[QuestionRow, ...]:
    rows: list[QuestionRow] = []
    for line in output.splitlines():
        match = _QUESTION_ROW.match(line.split(" | ", 1)[0])
        if match:
            rows.append(
                QuestionRow(
                    id=match.group("id"),
                    status=match.group("status"),
                    expected_pages=match.group("expected"),
                    pages=match.group("pages"),
                    point_ok=match.group("points") == "ok",
                    top=match.group("top"),
                )
            )
    return tuple(rows)


def _refusal_rows(output: str) -> tuple[RefusalRow, ...]:
    rows: list[RefusalRow] = []
    for line in output.splitlines():
        match = _REFUSAL_ROW.match(line.split(" | ", 1)[0])
        if match:
            rows.append(
                RefusalRow(
                    id=match.group("id"),
                    refused=match.group("status") == "refused",
                    top=match.group("top"),
                    reason=match.group("reason").strip(),
                )
            )
    return tuple(rows)


def _compare_metrics(output: str) -> CompareMetrics | None:
    grounded = _ratio(_GROUNDED.search(output))
    provenance = _ratio(_PROVENANCE.search(output))
    c1 = _C1.search(output)
    if grounded is None or provenance is None or c1 is None:
        return None
    return CompareMetrics(
        grounded=grounded.numerator,
        total=grounded.denominator,
        grounded_rate=grounded.rate,
        provenance=provenance.numerator,
        provenance_rate=provenance.rate,
        verdict=c1.group(1),
    )


def parse_output(
    output: str,
) -> tuple[QaMetrics, tuple[QuestionRow, ...], tuple[RefusalRow, ...], CompareMetrics | None] | None:
    """Parse the metrics printed by ``tools/check_qa.py``.

    Returns ``None`` when any required QA line is absent, so a partial run can
    never be mistaken for a pass. The answer snippets after `` | `` are
    discarded and never reach a report (H13).
    """
    anchor = _ratio(_ANCHOR.search(output))
    refusal = _ratio(_REFUSAL.search(output))
    points = _ratio(_POINTS.search(output))
    q1 = _Q1.search(output)
    if anchor is None or refusal is None or points is None or q1 is None:
        return None
    qa = QaMetrics(
        anchor_correct=anchor.numerator,
        answerable=anchor.denominator,
        anchor_rate=anchor.rate,
        refused=refusal.numerator,
        unanswerable=refusal.denominator,
        refusal_rate=refusal.rate,
        point_hits=points.numerator,
        point_rate=points.rate,
        verdict=q1.group(1),
    )
    questions = _question_rows(output)
    refusals = _refusal_rows(output)
    if len(questions) != qa.answerable or len(refusals) != qa.unanswerable:
        return None
    return qa, questions, refusals, _compare_metrics(output)


def build_report(
    output: str,
    *,
    command: str,
    models: Mapping[str, str],
    generated_at: str | None = None,
) -> Report:
    parsed = parse_output(output)
    if parsed is None:
        raise ValueError("check_qa output is missing the QA metrics or the Q1 verdict")
    qa, questions, refusals, compare = parsed
    entries, cross, unanswerable = _golden_counts()
    verdict = "PASS" if qa.verdict == "PASS" and (compare is None or compare.verdict == "PASS") else "FAIL"
    return Report(
        generated_at=generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
        command=command,
        golden_entries=entries,
        golden_cross=cross,
        golden_unanswerable=unanswerable,
        models=dict(models),
        qa=qa,
        questions=questions,
        refusals=refusals,
        compare=compare,
        verdict=verdict,
    )


def _qa_section(report: Report) -> list[str]:
    qa = report.qa
    lines = [
        "",
        "## Single-document QA",
        "",
        "| Metric | Result | Target |",
        "|---|---|---|",
        f"| Anchor page accuracy | {qa.anchor_correct}/{qa.answerable} = {qa.anchor_rate:.2f} | ≥ 0.90 |",
        f"| Point hit rate (informational) | {qa.point_hits}/{qa.answerable} = {qa.point_rate:.2f} | — |",
        f"| Refusal rate | {qa.refused}/{qa.unanswerable} = {qa.refusal_rate:.2f} | 1.00 |",
        f"| Q1 verdict | {qa.verdict} | PASS |",
        "",
        "| Question | Anchor | Observed pages | Expected pages | Point | Top score |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.questions:
        anchor = "ok" if row.status == "ok" else ("MISS" if row.status == "MISS" else "REFUSED")
        lines.append(
            f"| {row.id} | {anchor} | {row.pages} | {row.expected_pages} | "
            f"{'ok' if row.point_ok else 'no'} | {row.top} |"
        )
    return lines


def _refusal_section(report: Report) -> list[str]:
    lines = [
        "",
        "## Unanswerable questions",
        "",
        "| Question | Result | Top score | Reason |",
        "|---|---|---|---|",
    ]
    for refusal in report.refusals:
        lines.append(
            f"| {refusal.id} | {'refused' if refusal.refused else 'ANSWERED'} | "
            f"{refusal.top} | {refusal.reason} |"
        )
    return lines


def _compare_section(report: Report) -> list[str]:
    compare = report.compare
    if compare is None:
        return []
    return [
        "",
        "## Multi-document comparison",
        "",
        "| Metric | Result | Target |",
        "|---|---|---|",
        (
            f"| Grounded cells | {compare.grounded}/{compare.total} = "
            f"{compare.grounded_rate:.2f} | ≥ 0.40 |"
        ),
        (
            f"| Cells with correct provenance | {compare.provenance}/{compare.total} = "
            f"{compare.provenance_rate:.2f} | 1.00 |"
        ),
        f"| C1 verdict | {compare.verdict} | PASS |",
    ]


def render_markdown(report: Report) -> str:
    lines = [
        "# QA evaluation report",
        "",
        f"- Generated (UTC): {report.generated_at}",
        f"- Command: `{report.command}`",
        (
            f"- Golden set: {report.golden_entries} answerable + "
            f"{report.golden_unanswerable} unanswerable + {report.golden_cross} cross entries "
            "(`backend/tests/golden_qa.json`)"
        ),
        "- Golden review: every expected point is asserted against its named fixture page by "
        "`backend/tests/test_golden_qa.py`; no model output is used.",
        f"- Models: {', '.join(f'{key}={value}' for key, value in report.models.items())}",
        f"- Verdict: **{report.verdict}**",
    ]
    lines.extend(_qa_section(report))
    lines.extend(_refusal_section(report))
    lines.extend(_compare_section(report))
    lines.extend(
        [
            "",
            "The report stores ids, pages and scores; generated answer text is not persisted (H13).",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: Report, output_dir: Path = DEFAULT_OUTPUT) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "eval-qa.json"
    markdown_path = output_dir / "eval-qa.md"
    json_path.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path
