"""Dựng khối `text_layer` — nguyên văn toàn bộ text của PDF, theo từng trang.

Vì sao cần: phần dữ liệu có cấu trúc (`sections`, `fields`, `table`...) TIÊU THỤ
một số ký tự để dựng cấu trúc — dấu hai chấm tách nhãn với giá trị, gạch đầu
dòng mở đầu mục liệt kê — nên chúng không xuất hiện lại trong bất kỳ giá trị nào.
Chữ trang trí (watermark) cũng bị loại khỏi luồng nghiệp vụ để không lẫn vào
field.

Kết quả là JSON tuy không mất DỮ LIỆU nào nhưng vẫn không chứa đủ MỌI KÝ TỰ của
tài liệu. Khối này lấp đúng khoảng đó: text nguyên văn theo từng trang, cộng
phần chữ trang trí để riêng. Nhờ vậy độ phủ ký tự đạt đúng 100% và điều đó kiểm
tra được bằng máy, không phải bằng lời hứa.

Khối này KHÔNG thay thế phần có cấu trúc — nó là bản đối chiếu để không mất gì.
"""

from __future__ import annotations

from typing import Any

from .extract_text_with_coordinates import PositionedChar, TextLine
from .models import SourcedValue
from .sourced_value_builders import bbox_of


def build_text_layer_from_lines(pages: list[SourcedValue]) -> dict[str, Any]:
    """Khối text nguyên văn khi nguồn KHÔNG có toạ độ (DOCX).

    DOCX không phân trang nên chỉ có một khối; số trang do Word tính lúc mở
    file. Không có chữ trang trí riêng vì watermark trong Word là thuộc tính
    trang, không phải glyph cỡ lớn lẫn vào nội dung.
    """
    return {
        "pages": [
            {"page": value.page, "text": value} for value in pages if value.value.strip()
        ],
        "decorative": [],
    }


def build_text_layer(
    lines: list[TextLine], decorative_chars: list[PositionedChar]
) -> dict[str, Any]:
    """Text nguyên văn theo trang, và phần chữ trang trí để riêng."""
    return {
        "pages": _pages_from_lines(lines),
        "decorative": _pages_from_chars(decorative_chars),
    }


def _pages_from_lines(lines: list[TextLine]) -> list[dict[str, Any]]:
    """Mỗi trang một mục: text ghép từ các dòng, kèm bbox phủ toàn bộ nội dung."""
    by_page: dict[int, list[TextLine]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    pages: list[dict[str, Any]] = []

    for page in sorted(by_page):
        page_lines = by_page[page]
        chars = [c for line in page_lines for c in line.chars]

        pages.append(
            {
                "page": page,
                # Giữ từng dòng làm mảnh nguồn: cổng nguồn gốc chứng minh theo
                # mảnh, nên text cả trang vẫn truy được về nguồn dù nó là chuỗi
                # ghép từ nhiều dòng.
                "text": SourcedValue(
                    value="\n".join(line.text for line in page_lines),
                    page=page,
                    bbox=bbox_of(chars),
                    source_lines=[line.text for line in page_lines],
                ),
            }
        )

    return pages


def _pages_from_chars(chars: list[PositionedChar]) -> list[dict[str, Any]]:
    """Chữ trang trí theo trang, đọc theo thứ tự trên xuống rồi trái sang phải."""
    by_page: dict[int, list[PositionedChar]] = {}
    for char in chars:
        by_page.setdefault(char.page, []).append(char)

    pages: list[dict[str, Any]] = []

    for page in sorted(by_page):
        # Sắp theo HƯỚNG VIẾT, không theo (top, x0). Watermark quay 45 độ có x
        # tăng nhưng top giảm, nên sắp theo top trước sẽ cho ra chuỗi đảo ngược
        # ("OAS NAB" thay vì "BAN SAO").
        ordered = sorted(by_page[page], key=lambda c: c.reading_position)
        text = "".join(c.text for c in ordered).strip()

        if not text:
            continue

        pages.append(
            {
                "page": page,
                "text": SourcedValue(value=text, page=page, bbox=bbox_of(ordered)),
            }
        )

    return pages
