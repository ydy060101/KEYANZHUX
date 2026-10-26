"""Upload validation (H09)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from fastapi import UploadFile

from ..config import get_settings
from ..errors import InvalidRequest, PayloadTooLarge, UnsupportedMedia

PDF_MAGIC = b"%PDF-"
_UNSAFE = re.compile(r"[^\w.\-()一-鿿 ]+", re.UNICODE)


def clean_filename(name: str) -> str:
    """Strip directory components and characters that invite path traversal."""
    base = Path(name).name
    base = unicodedata.normalize("NFKC", base)
    cleaned = _UNSAFE.sub("_", base).strip(" .")
    if not cleaned:
        cleaned = "document.pdf"
    return cleaned[:180]


def assert_pdf_head(head: bytes) -> None:
    if not head.startswith(PDF_MAGIC):
        raise UnsupportedMedia("文件不是有效的 PDF（缺少 %PDF- 头）", detail={"head": head[:8].hex()})


async def validate_upload(file: UploadFile) -> tuple[str, bytes]:
    """Return the cleaned filename and the file bytes, or raise."""
    settings = get_settings()
    filename = clean_filename(file.filename or "document.pdf")
    if not filename.lower().endswith(".pdf"):
        raise UnsupportedMedia("只接受 .pdf 文件", detail={"filename": filename})

    head = await file.read(8)
    assert_pdf_head(head)
    rest = await file.read()
    data = head + rest
    if len(data) > settings.upload_max_bytes:
        raise PayloadTooLarge(
            f"文件超过 {settings.upload_max_mb}MB 上限",
            detail={"size": len(data), "limit": settings.upload_max_bytes},
        )
    if len(data) < 1024:
        raise InvalidRequest("文件过小，可能已损坏", detail={"size": len(data)})
    return filename, data
