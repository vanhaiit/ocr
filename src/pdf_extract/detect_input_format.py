"""Nhận dạng định dạng đầu vào từ NỘI DUNG file, không từ phần mở rộng.

Phần mở rộng có thể sai hoặc bị đổi tên; chữ ký byte thì không. PDF mở đầu bằng
`%PDF-`, còn DOCX là một file ZIP (`PK\\x03\\x04`) chứa `word/document.xml`.

Kiểm cả cấu trúc bên trong với DOCX: một file ZIP bất kỳ (hoặc XLSX, PPTX) cũng
có chữ ký ZIP, nên phải xác nhận đúng phần thân Word mới nhận.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .models import InputFormat

PDF_SIGNATURE = b"%PDF-"
ZIP_SIGNATURE = b"PK\x03\x04"

# Phần thân của tài liệu Word trong gói DOCX.
DOCX_BODY_ENTRY = "word/document.xml"


class UnsupportedInputFormat(ValueError):
    """File không phải PDF cũng không phải DOCX."""


def detect_format(path: str) -> InputFormat:
    """Trả về định dạng, hoặc raise nếu không nhận ra."""
    header = Path(path).open("rb").read(len(ZIP_SIGNATURE) + len(PDF_SIGNATURE))

    if header.startswith(PDF_SIGNATURE):
        return InputFormat.PDF

    if header.startswith(ZIP_SIGNATURE) and _is_word_package(path):
        return InputFormat.DOCX

    raise UnsupportedInputFormat(
        f"{Path(path).name}: không phải PDF (%PDF-) cũng không phải DOCX "
        f"(gói ZIP có {DOCX_BODY_ENTRY}). Pipeline chỉ nhận hai định dạng này."
    )


def _is_word_package(path: str) -> bool:
    """Gói ZIP có chứa phần thân tài liệu Word hay không."""
    try:
        with zipfile.ZipFile(path) as package:
            return DOCX_BODY_ENTRY in package.namelist()
    except zipfile.BadZipFile:
        return False
