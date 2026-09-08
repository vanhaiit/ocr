"""Tạo PDF nhân tạo để kiểm các ca hiếm mà file mẫu thật không có.

Viết PDF ở mức byte thay vì dùng thư viện sinh PDF, vì cần điều khiển chính xác
content stream — đúng chỗ tạo ra hiệu ứng đổ bóng và in đậm giả (vẽ cùng một
chuỗi hai lần ở vị trí lệch nhau chút ít).
"""

from __future__ import annotations

from pathlib import Path

# Cỡ trang nhỏ, đủ chứa một dòng chữ.
PAGE_WIDTH = 300
PAGE_HEIGHT = 100

# Độ lệch của lớp bóng so với lớp chữ chính, tính bằng điểm PDF.
# Giá trị điển hình của hiệu ứng đổ bóng và in đậm giả trong Word/LibreOffice.
SHADOW_OFFSET = 0.6


def _assemble_pdf(content_stream: str) -> bytes:
    """Ghép các object PDF và bảng xref với offset tính đúng."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content_stream)} >>\nstream\n{content_stream}\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []

    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")

    xref_start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")

    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    ).encode("latin-1")

    return bytes(out)


def write_shadowed_text_pdf(path: Path, text: str = "SHADOW") -> Path:
    """PDF có chữ đổ bóng: cùng chuỗi được vẽ hai lần, lệch nhau chút ít.

    Đây là cách Word và LibreOffice tạo hiệu ứng đổ bóng cũng như in đậm giả.
    Hệ quả: engine trích xuất đọc ra ký tự BỊ NHÂN ĐÔI, và mọi engine đều nhân
    đôi giống nhau nên đối chứng chéo không phát hiện được.
    """
    shadow_layer = (
        f"BT /F1 12 Tf 0.5 0.5 0.5 rg "
        f"{20 + SHADOW_OFFSET} {50 - SHADOW_OFFSET} Td ({text}) Tj ET\n"
    )
    main_layer = f"BT /F1 12 Tf 0 0 0 rg 20 50 Td ({text}) Tj ET\n"

    path.write_bytes(_assemble_pdf(shadow_layer + main_layer))
    return path


def write_plain_text_pdf(path: Path, text: str = "PLAIN") -> Path:
    """PDF chỉ vẽ chữ một lần — đối chứng để chắc bộ lọc không xoá oan."""
    content = f"BT /F1 12 Tf 0 0 0 rg 20 50 Td ({text}) Tj ET\n"
    path.write_bytes(_assemble_pdf(content))
    return path
