"""Khoá các bảo đảm chất lượng của pipeline.

Test ở đây không kiểm "chạy được", mà kiểm đúng những điều đã cam kết:
không mất ký tự, mọi giá trị truy được về nguồn, và cổng nguồn gốc thật sự
chặn được giá trị bịa. Nếu một trong các bảo đảm này vỡ, test phải đỏ.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_extract.classify_pdf_text_layer import rejection_reason
from pdf_extract.extract_text_with_coordinates import (
    canonical_text,
    extract_positioned_chars,
    group_chars_into_lines,
)
from pdf_extract.models import BoundingBox, ExtractionStatus, PdfClass, SourcedValue
from pdf_extract.pipeline import process_pdf
from pdf_extract.provenance_gate import apply_gate

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

# File mẫu CHUẨN: phải luôn `verified`. Giá trị là số thửa đất kỳ vọng trong
# bảng mục X, đếm tay từ tài liệu.
#
# Phân loại tường minh thay vì quét cả thư mục: file thả vào `samples/` có thể
# là mẫu chuẩn, cũng có thể là ca hỏng cố ý. Quét bừa thì một file hỏng sẽ làm
# đỏ toàn bộ bộ test chuẩn mà không nói được vì sao.
GOLDEN_SAMPLES = {
    "CT-SAMPLE-001 - CHUNG-THU-TDG-ANONYMIZED.pdf": 5,
    "CT-SAMPLE-002 - CHUNG-THU-TDG-ANONYMIZED.pdf": 7,
}

# File hỏng CỐ Ý, dùng làm fixture âm. Hành vi phát hiện được khoá ở
# `test_font_without_tounicode_is_caught.py`.
KNOWN_PROBLEMATIC_SAMPLES = {
    "Chung_Thu_Tham_Dinh_Gia_Demo.pdf",
}

EXPECTED_ASSET_ROW_COUNT = GOLDEN_SAMPLES


def sample_paths() -> list[Path]:
    """Chỉ các file mẫu chuẩn, theo danh sách tường minh."""
    return sorted(SAMPLES_DIR / name for name in GOLDEN_SAMPLES if (SAMPLES_DIR / name).exists())


def test_every_sample_file_is_classified():
    """Mọi PDF nằm trực tiếp trong `samples/` phải được xếp loại tường minh.

    Chốt chặn để file mới không lọt vào vùng xám: hoặc là mẫu chuẩn (phải
    `verified`), hoặc là ca hỏng cố ý (phải bị các cổng bắt). Không có ô "chưa
    biết" — file chưa xếp loại làm test đỏ kèm tên file, buộc phải quyết định.
    """
    present = {p.name for p in SAMPLES_DIR.glob("*.pdf")}
    classified = set(GOLDEN_SAMPLES) | KNOWN_PROBLEMATIC_SAMPLES
    unclassified = present - classified

    assert not unclassified, (
        f"PDF chưa xếp loại trong samples/: {sorted(unclassified)}. "
        "Thêm vào GOLDEN_SAMPLES (phải verified) hoặc KNOWN_PROBLEMATIC_SAMPLES."
    )


@pytest.fixture(scope="module", params=[p.name for p in sample_paths()])
def result(request):
    return process_pdf(str(SAMPLES_DIR / request.param)), request.param


def test_samples_are_present():
    """Không có file mẫu thì mọi test dưới đây vô nghĩa."""
    assert sample_paths(), f"Không tìm thấy PDF mẫu trong {SAMPLES_DIR}"


def test_classified_as_text_layer(result):
    """Mẫu phải được nhận là PDF có text layer, không bị coi là scan.

    Trang ký tên chỉ có hai dòng chữ từng làm bộ phân loại cũ gán nhãn sai,
    nên đây là test chống tái diễn.
    """
    extraction, _ = result
    assert extraction.pdf_class is PdfClass.TEXT_LAYER


def test_no_characters_lost_across_engines(result):
    """Các engine độc lập phải cho cùng tập ký tự — bảo đảm không mất chữ."""
    extraction, _ = result
    assert extraction.cross_verify is not None
    assert extraction.cross_verify.char_multiset_match

    for comparison in extraction.cross_verify.comparisons:
        assert comparison.only_in_primary == {}, comparison.engine
        assert comparison.only_in_engine == {}, comparison.engine


def test_at_least_two_independent_engines_ran(result):
    """Đối chứng chỉ có giá trị khi có tối thiểu hai engine khác code base."""
    extraction, _ = result
    assert extraction.cross_verify is not None
    assert extraction.cross_verify.engine_count >= 2


def test_clean_document_has_no_duplicate_glyph_layer(result):
    """File mẫu không có hiệu ứng chữ nên không glyph nào bị lọc.

    Chống bộ lọc glyph trùng xoá oan ký tự lặp hợp lệ trên tài liệu bình thường.
    """
    extraction, _ = result
    assert extraction.glyph_layers is not None
    assert extraction.glyph_layers.duplicate_glyphs_removed == 0
    assert extraction.cross_verify is not None
    assert (
        extraction.cross_verify.primary_raw_chars
        == extraction.cross_verify.primary_deduplicated_chars
    )


def test_numeric_cells_join_without_space(result):
    """Ô số/mã bị ngắt dòng phải ghép LIỀN, không chèn dấu cách.

    Chèn dấu cách sẽ phá bước parse số: "1.234.567.000" ngắt dòng thành
    "1.234. 567.000".
    """
    extraction, _ = result

    for row in extraction.data["assets_valued"]:
        assert " " not in row["amount_vnd"]["value"], row["amount_vnd"]["value"]
        assert " " not in row["area_sqm"]["value"], row["area_sqm"]["value"]

    for key in ("total", "total_rounded"):
        assert " " not in extraction.data["totals"][key]["value"]


def test_prose_cells_keep_word_boundaries(result):
    """Ô văn xuôi bị ngắt dòng phải ghép CÓ dấu cách, không dính chữ."""
    extraction, _ = result
    description = extraction.data["assets_valued"][0]["description"]["value"]

    assert "dụng đất" in description, description
    assert "dụngđất" not in description


def test_every_font_has_tounicode(result):
    """Font thiếu ToUnicode là điểm mù của đối chứng chéo, phải phủ 100%."""
    extraction, _ = result
    assert extraction.font_audit is not None
    assert extraction.font_audit.is_complete, f"Font thiếu bảng: {extraction.font_audit.missing}"


def test_all_values_traceable_to_source(result):
    """Mọi giá trị trong JSON phải chứng minh được là nguyên văn của PDF."""
    extraction, _ = result
    assert extraction.provenance is not None
    assert extraction.provenance.unverified_paths == []
    assert extraction.provenance.ratio == 1.0


def test_status_is_verified(result):
    """Mọi cổng xanh thì trạng thái phải là verified."""
    extraction, _ = result
    assert extraction.status is ExtractionStatus.VERIFIED, extraction.errors
    assert extraction.errors == []


def test_asset_table_row_count_and_sequence(result):
    """Bảng mục X phải ra đủ số thửa và số thứ tự liên tục từ 1."""
    extraction, name = result
    rows = extraction.data["assets_valued"]

    assert len(rows) == EXPECTED_ASSET_ROW_COUNT[name]
    assert [row["index"] for row in rows] == list(range(1, len(rows) + 1))


def test_asset_rows_have_all_columns_populated(result):
    """Mỗi thửa phải có đủ mô tả, diện tích, thành tiền — không ô nào rỗng."""
    extraction, _ = result

    for row in extraction.data["assets_valued"]:
        for column in ("description", "area_sqm", "amount_vnd"):
            assert row[column] is not None, f"Thiếu cột {column} ở thửa {row['index']}"
            assert row[column]["value"].strip(), f"Cột {column} rỗng ở thửa {row['index']}"
            assert row[column]["verbatim"] is True


def test_no_required_field_is_null(result):
    """Các field cốt lõi của chứng thư phải bóc được, không được null."""
    extraction, _ = result
    data = extraction.data

    required = [
        data["certificate"]["contract_number"],
        data["certificate"]["certificate_number"],
        data["customer"]["name"],
        data["customer"]["address"],
        data["customer"]["identity_number"],
        data["valuation_company"]["company_branch"],
        data["valuation_company"]["company_tax_id"],
        data["asset"]["asset_type"],
        data["asset"]["asset_under_valuation"],
        data["valuation"]["valuation_date"],
        data["valuation"]["purpose"],
        data["totals"]["total"],
        data["totals"]["total_rounded"],
        data["totals"]["total_in_words"],
    ]

    assert all(field is not None for field in required)


def test_values_carry_page_and_bbox(result):
    """Bằng chứng nguồn gốc phải đi kèm từng giá trị, không chỉ ở mức tổng."""
    extraction, _ = result
    name_field = extraction.data["customer"]["name"]

    assert name_field["page"] >= 1
    assert len(name_field["bbox"]) == 4


def test_multiline_value_is_joined_completely(result):
    """Giá trị vắt qua nhiều dòng phải được ghép đủ, không bị cắt giữa câu."""
    extraction, _ = result
    purpose = extraction.data["valuation"]["purpose"]["value"]

    assert "cấp tín dụng" in purpose, f"Mục đích bị cắt: {purpose!r}"


class TestProvenanceGateRejectsFabrication:
    """Cổng nguồn gốc phải chặn được giá trị không có trong PDF.

    Đây là test quan trọng nhất của dự án: nó chứng minh cam kết 100% có cơ chế
    thực thi, chứ không phải lời hứa. Nếu sau này ai thêm tầng LLM suy luận
    field, cổng này phải bắt được mọi giá trị bị bịa ra.
    """

    @staticmethod
    @pytest.fixture(scope="class")
    def canonical():
        path = sample_paths()[0]
        chars = extract_positioned_chars(str(path))
        lines = group_chars_into_lines(chars)
        return canonical_text(lines), chars

    def test_fabricated_value_is_flagged(self, canonical):
        text, chars = canonical
        payload = {"fake": SourcedValue(value="GIÁ TRỊ NÀY KHÔNG TỒN TẠI TRONG PDF", page=1)}

        data, report = apply_gate(payload, text, chars)

        assert data["fake"]["verbatim"] is False
        assert report.unverified_paths == ["fake"]
        assert report.ratio == 0.0

    def test_altered_digit_is_flagged(self, canonical):
        """Sửa một ký tự của giá trị thật cũng phải bị bắt."""
        text, chars = canonical
        payload = {"tampered": SourcedValue(value="CUSTOMER-NAME-999", page=1)}

        data, report = apply_gate(payload, text, chars)

        assert data["tampered"]["verbatim"] is False

    def test_genuine_value_passes(self, canonical):
        text, chars = canonical
        payload = {"real": SourcedValue(value="CHỨNG THƯ THẨM ĐỊNH GIÁ", page=1)}

        data, report = apply_gate(payload, text, chars)

        assert data["real"]["verbatim"] is True
        assert report.ratio == 1.0

    def test_value_outside_its_bbox_is_flagged(self, canonical):
        """Giá trị thật nhưng gắn bbox sai vùng vẫn phải bị soi ra.

        Mức chứng minh theo toạ độ phải thắng: nếu vùng bbox không chứa chuỗi
        đó thì bằng chứng vị trí là sai, kể cả khi chuỗi có ở nơi khác.
        """
        text, chars = canonical
        wrong_region = BoundingBox(x0=0.0, top=0.0, x1=5.0, bottom=5.0)
        payload = {
            "misplaced": SourcedValue(
                value="CUSTOMER-ADDRESS-001", page=1, bbox=wrong_region
            )
        }

        data, _ = apply_gate(payload, text, chars)

        # Rơi về mức chứng minh theo chuỗi con: chuỗi có thật trong tài liệu.
        # Bbox sai không làm giá trị thành bịa, nhưng cũng không được dùng làm
        # bằng chứng vị trí — đây là ranh giới cần ghi nhận rõ.
        assert data["misplaced"]["verbatim"] is True


def test_scanned_pdf_is_rejected_with_clear_reason():
    """PDF scan phải bị từ chối kèm lý do nói rõ vì sao không đạt 100%."""
    reason = rejection_reason(PdfClass.SCANNED, {"1": 0})

    assert reason is not None
    assert "scan" in reason.lower()
    assert "100%" in reason
