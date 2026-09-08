"""Kiểm bản thân các file fixture có ĐÚNG không, trước khi dùng chúng kết luận.

Bộ fixture đầu tiên có ba lỗi bố cục mà chỉ phát hiện được bằng cách mở file ra
xem: nhãn đè lên giá trị, tiêu đề quay dọc tràn ra ngoài bảng, và cả trang mất
chữ vì chế độ tô của lớp chữ ẩn rò rỉ sang phần còn lại.

Fixture sai âm thầm là tình huống tệ nhất: mọi kết luận rút ra từ nó đều sai
theo, mà lại trông như đã kiểm tra cẩn thận. Các test ở đây biến ba lỗi đó
thành kiểm tra máy chạy được, để không phải soi mắt lần nữa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.certificate_expected_values import (
    EXPECTED,
    EXPECTED_ASSET_ROWS,
    INVISIBLE_LAYER_TEXT,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    WATERMARK_TEXT,
)
from fixtures.certificate_pdf_layout import ASSET_TABLE_X
from pdf_extract.detect_duplicate_glyph_layers import deduplicate_glyphs
from pdf_extract.extract_text_with_coordinates import (
    PositionedChar,
    extract_positioned_chars,
    normalize,
)

FEATURES_DIR = Path(__file__).resolve().parent.parent / "samples" / "font-features"

# Cỡ chữ ngưỡng để nhận watermark: watermark vẽ 60pt, thân tài liệu 12-15pt.
# Watermark cố ý phủ lên nội dung nên phải loại khỏi phép kiểm đè chữ.
WATERMARK_MIN_SIZE = 30.0

# Hai glyph khác nội dung mà tâm cách nhau dưới ngưỡng này là dấu hiệu ĐÈ CHỮ.
# Bước tiến của glyph hẹp nhất ở 12pt vẫn trên 3pt, nên 2pt là khoảng an toàn.
OVERLAP_DISTANCE = 2.0

# Lề tối thiểu. Chữ vẽ ngoài mốc này bị một số engine cắt bỏ, sinh lệch giữa
# các engine mà không phải lỗi của pipeline.
MARGIN = 20.0


def variant_paths() -> list[Path]:
    return sorted(FEATURES_DIR.glob("*.pdf"))


@pytest.fixture(scope="module", params=[p.name for p in variant_paths()])
def variant(request):
    path = FEATURES_DIR / request.param
    raw = extract_positioned_chars(str(path))
    deduplicated, _ = deduplicate_glyphs(raw)
    return request.param, deduplicated


def _document_text(chars: list[PositionedChar]) -> str:
    """Chuỗi phẳng dùng để kiểm sự hiện diện của giá trị, bỏ mọi khoảng trắng."""
    ordered = sorted(chars, key=lambda c: (c.page, round(c.top, 1), c.x0))
    return "".join(c.text for c in ordered).replace(" ", "")


def _column_band_text(chars: list[PositionedChar], left: float, right: float) -> str:
    """Chuỗi đọc theo MỘT DẢI CỘT, trên xuống dưới.

    Cần thiết vì giá trị dài bị wrap thành nhiều dòng trong ô: đọc theo dòng
    ngang thì hai nửa của "VALUE-VND-LOT-901" bị nội dung cột khác chen vào
    giữa. Đọc theo dải cột thì chúng liền nhau.

    Tự dựng lại từ toạ độ cột của fixture, không dùng bộ dựng bảng của pipeline
    — để phép kiểm fixture độc lập với thứ nó đang dùng để kết luận.
    """
    inside = [c for c in chars if left <= (c.x0 + c.x1) / 2 <= right]
    ordered = sorted(inside, key=lambda c: (c.page, round(c.top, 1), c.x0))
    return "".join(c.text for c in ordered).replace(" ", "")


def test_fixture_set_exists():
    """Không có fixture thì mọi test dưới đây vô nghĩa."""
    assert variant_paths(), f"Chưa sinh fixture trong {FEATURES_DIR}"


def test_every_expected_value_is_present(variant):
    """Mọi giá trị kỳ vọng phải có mặt trong text layer của MỌI biến thể.

    Đây là chốt chặn cho lỗi "mất nội dung": bản fixture đầu tiên có biến thể
    mất sạch chữ vì chế độ tô rò rỉ, mà vẫn sinh ra file trông bình thường.
    """
    name, chars = variant
    text = _document_text(chars)

    # Giá trị form field nằm trong annotation, không nằm trong content stream —
    # kiểm riêng ở bộ test của pipeline.
    for key, value in EXPECTED.items():
        assert normalize(value).replace(" ", "") in text, f"{name}: thiếu {key} = {value!r}"

    # Cột bảng: đọc theo dải cột vì giá trị dài bị wrap trong ô.
    column_bands = {
        "description": (ASSET_TABLE_X[1], ASSET_TABLE_X[2]),
        "area_sqm": (ASSET_TABLE_X[2], ASSET_TABLE_X[3]),
        "amount_vnd": (ASSET_TABLE_X[3], ASSET_TABLE_X[4]),
    }

    for column, (left, right) in column_bands.items():
        band = _column_band_text(chars, left, right)
        for row in EXPECTED_ASSET_ROWS:
            expected = normalize(row[column]).replace(" ", "")
            assert expected in band, (
                f"{name}: thiếu thửa {row['index']} cột {column} = {row[column]!r}"
            )


def test_no_visible_text_collision(variant):
    """Không glyph nào đè lên glyph khác — chốt chặn cho lỗi nhãn đè giá trị.

    Bỏ qua watermark (cố ý phủ lên nội dung) và các glyph cùng nội dung (đã do
    bộ lọc lớp bóng xử lý).
    """
    name, chars = variant
    body = [c for c in chars if c.size < WATERMARK_MIN_SIZE and c.text.strip()]

    by_page: dict[int, list[PositionedChar]] = {}
    for char in body:
        by_page.setdefault(char.page, []).append(char)

    for page, page_chars in by_page.items():
        page_chars.sort(key=lambda c: (c.x0, c.top))

        for index, char in enumerate(page_chars):
            for other in page_chars[index + 1:]:
                if other.x0 - char.x0 > OVERLAP_DISTANCE:
                    break
                if other.text == char.text:
                    continue
                if abs(_center_y(other) - _center_y(char)) > OVERLAP_DISTANCE:
                    continue

                pytest.fail(
                    f"{name} trang {page}: {char.text!r} và {other.text!r} đè lên nhau "
                    f"tại x={char.x0:.1f} y={char.top:.1f} — bố cục fixture sai"
                )


def test_all_text_inside_page_margins(variant):
    """Chữ phải nằm trong lề.

    Chữ vẽ ngoài vùng in bị Poppler cắt còn pdfplumber vẫn đọc, sinh lệch giữa
    các engine — lệch do fixture, không phải do pipeline, nên phải chặn từ đây.
    """
    name, chars = variant
    # Watermark quay 45 độ nên bbox của nó tràn lề một cách hợp lệ.
    body = [c for c in chars if c.size < WATERMARK_MIN_SIZE]

    for char in body:
        assert char.x0 >= MARGIN - 1.0, f"{name}: {char.text!r} tràn lề trái (x={char.x0:.1f})"
        assert char.x1 <= PAGE_WIDTH - MARGIN + 1.0, (
            f"{name}: {char.text!r} tràn lề phải (x={char.x1:.1f})"
        )
        assert 0.0 <= char.top and char.bottom <= PAGE_HEIGHT, (
            f"{name}: {char.text!r} nằm ngoài trang (top={char.top:.1f})"
        )


def test_invisible_layer_variants_keep_hidden_text_extractable(variant):
    """Biến thể có lớp chữ ẩn: chuỗi ẩn vẫn phải đọc được từ text layer.

    Chữ ẩn (chế độ tô 3) không hiện trên màn hình nhưng engine vẫn đọc — đúng
    tính chất cần kiểm. Nếu nó biến mất hẳn thì fixture không còn kiểm được gì.
    """
    name, chars = variant
    if "invisible" not in name:
        pytest.skip("biến thể không có lớp chữ ẩn")

    assert INVISIBLE_LAYER_TEXT.replace(" ", "") in _document_text(chars)


def test_watermark_variants_have_oversized_glyphs(variant):
    """Biến thể watermark phải thật sự có glyph cỡ lớn.

    Kiểm rằng cờ watermark có tác dụng, thay vì im lặng không vẽ gì.
    """
    name, chars = variant
    if "watermark" not in name and "kitchen" not in name:
        pytest.skip("biến thể không có watermark")

    oversized = [c for c in chars if c.size >= WATERMARK_MIN_SIZE]
    assert oversized, f"{name}: không thấy glyph watermark"
    assert WATERMARK_TEXT.replace(" ", "") in "".join(c.text for c in oversized).replace(" ", "")


def _center_y(char: PositionedChar) -> float:
    return (char.top + char.bottom) / 2
