"""Kiểm bộ lọc glyph trùng — ca chữ đổ bóng và in đậm giả.

File mẫu thật không có hiệu ứng chữ, nên các ca này dùng PDF nhân tạo dựng ở
mức byte để có ground truth chính xác: biết trước chuỗi đúng phải là gì.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest

from build_synthetic_pdf_fixtures import write_plain_text_pdf, write_shadowed_text_pdf
from pdf_extract.cross_verify_engines import cross_verify
from pdf_extract.detect_duplicate_glyph_layers import deduplicate_glyphs
from pdf_extract.extract_text_with_coordinates import (
    PositionedChar,
    canonical_text,
    extract_positioned_chars,
    group_chars_into_lines,
)

SHADOWED_TEXT = "SHADOW"
PLAIN_TEXT = "PLAIN"


@pytest.fixture(scope="module")
def shadowed_pdf(tmp_path_factory) -> Path:
    return write_shadowed_text_pdf(tmp_path_factory.mktemp("pdf") / "shadowed.pdf", SHADOWED_TEXT)


@pytest.fixture(scope="module")
def plain_pdf(tmp_path_factory) -> Path:
    return write_plain_text_pdf(tmp_path_factory.mktemp("pdf") / "plain.pdf", PLAIN_TEXT)


def test_shadow_effect_really_duplicates_glyphs(shadowed_pdf):
    """Ghi nhận vấn đề gốc: engine đọc chữ đổ bóng ra ký tự nhân đôi.

    Test này khẳng định rủi ro là thật, không phải giả định — nếu thư viện sau
    này tự lọc thì test đỏ và bộ lọc của chúng ta trở nên không cần thiết.
    """
    with pdfplumber.open(shadowed_pdf) as pdf:
        raw = "".join(c["text"] for c in pdf.pages[0].chars)

    assert raw == SHADOWED_TEXT * 2


def test_deduplication_restores_correct_text(shadowed_pdf):
    """Sau khi lọc, chuỗi phải đúng bằng nội dung thật của tài liệu."""
    raw_chars = extract_positioned_chars(str(shadowed_pdf))
    kept, report = deduplicate_glyphs(raw_chars)

    assert canonical_text(group_chars_into_lines(kept)).strip() == SHADOWED_TEXT
    assert report.duplicate_glyphs_removed == len(SHADOWED_TEXT)
    assert report.has_duplicate_layer
    assert report.pages_affected == [1]


def test_plain_document_is_left_untouched(plain_pdf):
    """Tài liệu không có hiệu ứng chữ phải không bị xoá glyph nào."""
    raw_chars = extract_positioned_chars(str(plain_pdf))
    kept, report = deduplicate_glyphs(raw_chars)

    assert canonical_text(group_chars_into_lines(kept)).strip() == PLAIN_TEXT
    assert report.duplicate_glyphs_removed == 0
    assert not report.has_duplicate_layer


def _char(text: str, x0: float, top: float, size: float = 12.0) -> PositionedChar:
    """Dựng nhanh một glyph để kiểm ranh giới của ngưỡng gộp."""
    return PositionedChar(
        text=text,
        page=1,
        x0=x0,
        x1=x0 + size * 0.5,
        top=top,
        bottom=top + size,
        fontname="Test",
        size=size,
    )


def test_repeated_letters_side_by_side_are_kept():
    """Chữ lặp hợp lệ ('oo' trong 'look') phải được giữ nguyên.

    Đây là ca nguy hiểm nhất của bộ lọc: xoá quá tay sẽ làm mất chữ thật mà
    không cổng nào khác phát hiện được.
    """
    size = 12.0
    advance = size * 0.5  # bước tiến thực tế của một glyph, rộng hơn ngưỡng gộp
    chars = [_char("o", 100.0, 50.0, size), _char("o", 100.0 + advance, 50.0, size)]

    kept, report = deduplicate_glyphs(chars)

    assert len(kept) == 2
    assert report.duplicate_glyphs_removed == 0


def test_same_letter_on_different_lines_is_kept():
    """Cùng ký tự ở cùng cột nhưng khác dòng không phải là trùng lặp."""
    chars = [_char("A", 100.0, 50.0), _char("A", 100.0, 68.0)]

    kept, _ = deduplicate_glyphs(chars)

    assert len(kept) == 2


def test_threshold_scales_with_font_size():
    """Ngưỡng gộp theo tỉ lệ cỡ chữ, nên chữ nhỏ có ngưỡng chặt hơn.

    Cùng độ lệch 1.2pt: với chữ 24pt là lớp bóng (ngưỡng 2.5pt sau khi chặn
    trên), với chữ 6pt là hai glyph khác nhau (ngưỡng 1.08pt).
    """
    offset = 1.2

    large = [_char("X", 100.0, 50.0, size=24.0), _char("X", 100.0 + offset, 50.0, size=24.0)]
    small = [_char("X", 100.0, 50.0, size=6.0), _char("X", 100.0 + offset, 50.0, size=6.0)]

    assert len(deduplicate_glyphs(large)[0]) == 1
    assert len(deduplicate_glyphs(small)[0]) == 2


def test_cross_verify_accepts_shadowed_document(shadowed_pdf):
    """Tài liệu đổ bóng vẫn phải qua được cổng đối chứng.

    Đây là lý do phép đối chứng so với HAI mốc. Các engine xử lý lớp bóng khác
    nhau — pypdf trả ký tự nhân đôi (khớp mốc thô), Poppler tự lọc (khớp mốc đã
    lọc). Nếu chỉ so với một mốc thì mọi tài liệu có hiệu ứng chữ đều bị chặn
    oan, dù nội dung hoàn toàn đọc đúng.
    """
    raw_chars = extract_positioned_chars(str(shadowed_pdf))
    raw_text = canonical_text(group_chars_into_lines(raw_chars))
    kept, _ = deduplicate_glyphs(raw_chars)
    deduplicated_text = canonical_text(group_chars_into_lines(kept))

    report = cross_verify(str(shadowed_pdf), raw_text, deduplicated_text)

    assert report.char_multiset_match, [c.to_json() for c in report.comparisons]
    assert report.primary_raw_chars == len(SHADOWED_TEXT) * 2
    assert report.primary_deduplicated_chars == len(SHADOWED_TEXT)

    matched = {c.engine: c.baseline for c in report.comparisons}
    assert matched["pypdf"] == "raw"
    assert matched["poppler"] == "deduplicated"
