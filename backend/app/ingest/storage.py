"""Filesystem storage for uploads, parsed artefacts and renders.

Paths are derived from `data_dir` so nothing depends on the process cwd.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from ..config import get_settings


def _data_dir() -> Path:
    path = get_settings().data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def pdf_dir() -> Path:
    path = _data_dir() / "pdf"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parsed_dir(doc_id: str) -> Path:
    path = _data_dir() / "parsed" / doc_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_dir(doc_id: str) -> Path:
    path = parsed_dir(doc_id) / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def translation_dir(doc_id: str) -> Path:
    path = _data_dir() / "translations" / doc_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def figure_dir() -> Path:
    path = _data_dir() / "figures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dataset_dir() -> Path:
    path = _data_dir() / "datasets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_pdf(sha256: str, data: bytes) -> Path:
    """Content-addressed so re-uploading the same bytes cannot duplicate files."""
    target = pdf_dir() / f"{sha256}.pdf"
    if not target.exists():
        target.write_bytes(data)
    return target


def remove_document(doc_id: str, file_path: str | None) -> None:
    """Delete parsed artefacts and the stored PDF; missing paths are fine."""
    for path in (parsed_dir(doc_id), translation_dir(doc_id)):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    if file_path:
        stored = Path(file_path)
        if stored.is_file():
            stored.unlink(missing_ok=True)
