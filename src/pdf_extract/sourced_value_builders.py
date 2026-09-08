"""Nguyên thuỷ dựng `SourcedValue` từ nhóm ký tự.

Tách ra module riêng vì cả tầng phân tích cấu trúc tài liệu và tầng bóc field
của template đều cần — trước đây nằm private trong `template_base` nên tầng
phân tích không dùng được mà phải chép lại.
"""

from __future__ import annotations

from .extract_text_with_coordinates import PositionedChar, segment_text
from .models import BoundingBox, SourcedValue


def bbox_of(chars: list[PositionedChar]) -> BoundingBox | None:
    """Bbox khít nội dung: bỏ ký tự khoảng trắng ở hai đầu trước khi tính."""
    meaningful = [c for c in chars if c.text.strip()]
    if not meaningful:
        return None

    return BoundingBox(
        x0=min(c.x0 for c in meaningful),
        top=min(c.top for c in meaningful),
        x1=max(c.x1 for c in meaningful),
        bottom=max(c.bottom for c in meaningful),
    )


def sourced_value_of(
    chars: list[PositionedChar],
    page: int,
    *,
    text: str | None = None,
    strip_prefixes: tuple[str, ...] = (),
) -> SourcedValue | None:
    """Dựng SourcedValue; trả None nếu nội dung rỗng.

    `text` cho phép bên gọi tự quyết cách ghép (ví dụ ghép nhiều dòng có chèn
    khoảng trắng) trong khi bbox vẫn tính từ toàn bộ ký tự thật.

    `strip_prefixes` bỏ các ký tự dẫn còn sót ở đầu (dấu hai chấm, gạch đầu
    dòng) mà không làm mất phần nội dung.
    """
    raw = segment_text(chars) if text is None else text
    cleaned = " ".join(raw.split())

    for prefix in strip_prefixes:
        cleaned = cleaned.removeprefix(prefix).strip()

    if not cleaned:
        return None

    return SourcedValue(value=cleaned, page=page, bbox=bbox_of(chars))


def join_lines_with_space(groups: list[list[PositionedChar]]) -> str:
    """Ghép nhiều dòng thành một chuỗi, chèn khoảng trắng ở ranh giới dòng.

    Mỗi lần xuống dòng trong văn xuôi là một ranh giới TỪ, nối thẳng ký tự sẽ
    dính hai từ lại. Khác với ô bảng — ở đó ngắt dòng là do hết chỗ ngang nên
    phải nối liền.
    """
    return " ".join(segment_text(group) for group in groups)
