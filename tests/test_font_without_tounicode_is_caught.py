"""Khoá hành vi phát hiện PDF bị hỏng font.

`samples/known-issues/Chung_Thu_Tham_Dinh_Gia_Demo.pdf` là ca thật: file được
sinh bằng `/Helvetica` — font base14 không có bảng ToUnicode và không có glyph
tiếng Việt. Kết quả là mọi dấu tiếng Việt bị phá:

    Trong PDF     : "Giá trn Quynn sn dnng nnt LAND-LOT-001"
    Đúng ra là    : "Giá trị Quyền sử dụng đất LAND-LOT-001"

Đây là dạng hỏng đúng bằng thứ mà cổng soát font và cổng đối chứng chéo được
dựng ra để bắt. File này vì vậy được giữ làm FIXTURE ÂM: nó phải KHÔNG bao giờ
được gắn nhãn `verified`. Nếu một ngày nó qua được, tức là các cổng đã hỏng.

Đặt ngoài `samples/` để không lẫn với các file mẫu chuẩn — vốn phải luôn xanh.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_extract.models import ExtractionStatus, PdfClass
from pdf_extract.pipeline import process_pdf

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
CORRUPT_PDF_NAME = "Chung_Thu_Tham_Dinh_Gia_Demo.pdf"

# Tìm ở cả hai vị trí: fixture âm có thể nằm trong `samples/` hoặc được xếp
# riêng vào `samples/known-issues/`. Test không nên phụ thuộc chỗ đặt file.
CANDIDATE_PATHS = (
    SAMPLES_DIR / CORRUPT_PDF_NAME,
    SAMPLES_DIR / "known-issues" / CORRUPT_PDF_NAME,
)


def _locate_corrupt_pdf() -> Path | None:
    return next((path for path in CANDIDATE_PATHS if path.exists()), None)

# Font base14 gây ra lỗi, không có ToUnicode nên không map được sang Unicode.
FONT_WITHOUT_TOUNICODE = "/Helvetica"

# Ký tự mà engine chính đoán ra, trong khi các engine khác trả về ô vuông.
GLYPH_GUESSED_BY_PRIMARY = "n"


@pytest.fixture(scope="module")
def extraction():
    path = _locate_corrupt_pdf()
    if path is None:
        pytest.skip(f"Không tìm thấy {CORRUPT_PDF_NAME} ở {[str(p) for p in CANDIDATE_PATHS]}")
    return process_pdf(str(path))


def test_corrupt_font_document_is_never_verified(extraction):
    """Bảo đảm cốt lõi: file có ký tự không đáng tin không được gắn verified."""
    assert extraction.status is not ExtractionStatus.VERIFIED
    assert extraction.errors


def test_font_audit_names_the_offending_font(extraction):
    """Cổng soát font phải chỉ đúng tên font gây lỗi, không chỉ báo chung."""
    assert extraction.font_audit is not None
    assert not extraction.font_audit.is_complete
    assert FONT_WITHOUT_TOUNICODE in extraction.font_audit.missing
    assert extraction.font_audit.coverage < 1.0


def test_cross_verify_detects_the_disagreeing_characters(extraction):
    """Đối chứng chéo phải chỉ ra chính xác ký tự nào các engine đọc khác nhau.

    Engine chính đoán ra 'n' còn pypdf và Poppler trả về ô vuông — bằng chứng
    trực tiếp rằng glyph không map được sang Unicode.
    """
    assert extraction.cross_verify is not None
    assert not extraction.cross_verify.char_multiset_match

    for comparison in extraction.cross_verify.comparisons:
        assert comparison.baseline == "none"
        assert GLYPH_GUESSED_BY_PRIMARY in comparison.only_in_primary
        assert comparison.only_in_engine, comparison.engine


def test_two_independent_gates_catch_the_same_defect(extraction):
    """Lỗi này phải bị bắt bởi HAI cổng độc lập, không chỉ một.

    Soát font bắt được nguyên nhân (thiếu bảng ToUnicode), đối chứng chéo bắt
    được hậu quả (các engine đọc ra ký tự khác nhau). Có cả hai nghĩa là mạng
    lưới kiểm tra không phụ thuộc vào một điểm duy nhất.
    """
    font_gate_fired = not extraction.font_audit.is_complete
    cross_verify_gate_fired = not extraction.cross_verify.char_multiset_match

    assert font_gate_fired and cross_verify_gate_fired
    assert len(extraction.errors) >= 2


def test_provenance_still_passes_because_it_measures_a_different_thing(extraction):
    """Cổng nguồn gốc vẫn xanh — và đó là đúng, không phải lỗi.

    Cổng nguồn gốc chứng minh "giá trị này khớp với những gì PDF ghi", KHÔNG
    phải "những gì PDF ghi là đúng". Với file hỏng font, các giá trị vẫn là bản
    sao nguyên văn của text (đã hỏng) trong PDF. Phân biệt này quan trọng: tính
    trung thực với nguồn và tính đúng của nguồn là hai việc khác nhau, và chỉ có
    cổng soát font cùng đối chứng chéo mới nói được việc thứ hai.
    """
    assert extraction.provenance is not None
    assert extraction.provenance.ratio == 1.0


def test_document_is_still_recognised_as_text_layer(extraction):
    """Lỗi font không phải lỗi scan — phân loại vẫn phải đúng loại."""
    assert extraction.pdf_class is PdfClass.TEXT_LAYER
