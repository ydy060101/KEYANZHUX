"""Stored file paths must survive a changed working directory (T2.3)."""

from __future__ import annotations

from pathlib import Path

from app.config import REPO_ROOT
from app.ingest import storage


def test_a_relative_path_resolves_against_the_repository_root() -> None:
    """A row written by a process with another cwd must still find its file."""
    resolved = storage.resolve("data/pdf/example.pdf")
    assert resolved == REPO_ROOT / "data" / "pdf" / "example.pdf"


def test_an_absolute_path_is_left_alone() -> None:
    absolute = REPO_ROOT / "data" / "pdf" / "example.pdf"
    assert storage.resolve(str(absolute)) == absolute


def test_a_missing_file_is_rewritten_from_the_uploaded_bytes(tmp_path: Path) -> None:
    """Re-uploading repairs a row whose file went missing."""
    data = b"%PDF-1.4 repaired"
    restored = storage.ensure_pdf("data/pdf/does-not-exist.pdf", data)
    assert restored.is_file()
    assert restored.read_bytes() == data
    assert restored.name == f"{storage.sha256_bytes(data)}.pdf"
    restored.unlink()


def test_an_existing_file_is_returned_unchanged() -> None:
    data = b"%PDF-1.4 existing"
    stored = storage.write_pdf(storage.sha256_bytes(data), data)
    assert storage.ensure_pdf(str(stored), b"%PDF-1.4 other") == stored
    stored.unlink()
