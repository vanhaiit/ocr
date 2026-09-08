"""Khoá nhánh DOCX: cùng tài liệu, hai định dạng, PHẢI ra cùng giá trị.

Đây là test có giá trị nhất của nhánh DOCX. Hai tầng đọc hoàn toàn khác nhau —
một bên gom glyph theo toạ độ, một bên đọc `<w:p>` và `<w:tbl>` — nhưng vì dùng
chung tầng template và cổng nguồn gốc, JSON phải giống nhau. Lệch một giá trị
nghĩa là một trong hai tầng đọc sai.

Kèm theo là các test về những điều DOCX làm khác PDF, để chúng không bị hiểu
nhầm thành lỗi:

  - Ba cổng của PDF (loại PDF, soát ToUnicode, lọc glyph trùng) là `None` với
    DOCX vì không có gì để kiểm. Báo xanh chúng sẽ tạo cảm giác an toàn giả.
  - Bằng chứng vị trí là ĐƯỜNG DẪN XML chứ không phải bbox — DOCX không có toạ
    độ, và cũng không có số trang (Word tính lúc mở file).
  - Phép đối chứng chéo là MỘT CHIỀU: bộ đọc khác tìm ra chữ ta không có mới là
    lỗi; phần chúng thêm là trang trí của chính chúng.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from certificate_json_paths import FIELD_PATHS, asset_rows, field_value
from pdf_extract.detect_input_format import UnsupportedInputFormat, detect_format
from pdf_extract.models import ExtractionStatus, InputFormat
from pdf_extract.pipeline import process_document

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "samples" / "CT-SAMPLE-001 - CHUNG-THU-TDG-ANONYMIZED.pdf"
DOCX_PATH = ROOT / "samples" / "docx" / "CT-SAMPLE-001 - CHUNG-THU-TDG-ANONYMIZED.docx"

# Cột của bảng giá trị tài sản, so từng ô một.
ASSET_COLUMNS = ("description", "area_sqm", "amount_vnd")


@pytest.fixture(scope="module")
def pair():
    for path in (PDF_PATH, DOCX_PATH):
        if not path.exists():
            pytest.skip(f"Không có {path}")

    return process_document(str(PDF_PATH)), process_document(str(DOCX_PATH))


def test_format_is_detected_from_content(pair):
    """Định dạng nhận từ chữ ký byte, không từ phần mở rộng."""
    assert detect_format(str(PDF_PATH)) is InputFormat.PDF
    assert detect_format(str(DOCX_PATH)) is InputFormat.DOCX

    pdf_result, docx_result = pair
    assert pdf_result.input_format is InputFormat.PDF
    assert docx_result.input_format is InputFormat.DOCX


def test_unsupported_format_is_rejected_with_reason(tmp_path):
    """File không phải PDF/DOCX bị từ chối kèm lý do, không xử lý bừa."""
    junk = tmp_path / "khong-phai-tai-lieu.bin"
    junk.write_bytes(b"day khong phai PDF cung khong phai DOCX")

    with pytest.raises(UnsupportedInputFormat) as raised:
        detect_format(str(junk))

    assert "PDF" in str(raised.value) and "DOCX" in str(raised.value)


def test_both_formats_are_verified(pair):
    """Cả hai nhánh phải đạt `verified` trên cùng tài liệu."""
    for result in pair:
        assert result.status is ExtractionStatus.VERIFIED, (
            f"{result.input_format.value}: {result.errors}"
        )


def test_both_formats_detect_the_same_template(pair):
    pdf_result, docx_result = pair
    assert pdf_result.template_id == docx_result.template_id


def test_scalar_fields_are_identical(pair):
    """MỌI field phải giống nhau giữa hai định dạng.

    Đây là chốt chặn chính: hai tầng đọc độc lập cho ra cùng giá trị nghĩa là
    không tầng nào đọc sai.
    """
    pdf_result, docx_result = pair
    mismatched = {
        name: (field_value(pdf_result.data, name), field_value(docx_result.data, name))
        for name in FIELD_PATHS
        if field_value(pdf_result.data, name) != field_value(docx_result.data, name)
    }

    assert not mismatched, f"Lệch giữa PDF và DOCX: {mismatched}"


def test_asset_table_is_identical(pair):
    """Bảng giá trị tài sản phải khớp từng ô, kể cả ô bị wrap trong bản PDF."""
    pdf_result, docx_result = pair
    pdf_rows = asset_rows(pdf_result.data)
    docx_rows = asset_rows(docx_result.data)

    assert len(pdf_rows) == len(docx_rows) > 0

    for pdf_row, docx_row in zip(pdf_rows, docx_rows):
        assert pdf_row["index"] == docx_row["index"]
        for column in ASSET_COLUMNS:
            assert pdf_row[column]["value"] == docx_row[column]["value"], (
                f"thửa {pdf_row['index']} cột {column}"
            )


def test_totals_are_identical(pair):
    """Các dòng tổng phải khớp cả nhãn tiếng Việt và giá trị."""
    pdf_result, docx_result = pair
    pdf_totals = pdf_result.data["sections"]["X"]["table"]["totals"]
    docx_totals = docx_result.data["sections"]["X"]["table"]["totals"]

    assert set(pdf_totals) == set(docx_totals)

    for key, pdf_entry in pdf_totals.items():
        docx_entry = docx_totals[key]
        if pdf_entry is None or docx_entry is None:
            assert pdf_entry == docx_entry, key
            continue

        assert pdf_entry["label"] == docx_entry["label"], key
        assert pdf_entry["value"] == docx_entry["value"], key


def test_signatures_are_identical(pair):
    """Khối chữ ký phải ra cùng vai trò, số thẻ, họ tên."""
    pdf_result, docx_result = pair

    def summary(result):
        return [
            (
                entry["role"],
                (entry["card_number"] or {}).get("value"),
                (entry["name"] or {}).get("value"),
            )
            for entry in result.data["signatures"]
        ]

    assert summary(pdf_result) == summary(docx_result)
    assert len(summary(pdf_result)) == 2


def test_section_numbers_are_identical(pair):
    """Cùng bộ mục La Mã, cùng thứ tự."""
    pdf_result, docx_result = pair
    assert list(pdf_result.data["sections"]) == list(docx_result.data["sections"])


def test_no_unmapped_label_in_either_format(pair):
    """Không nhãn nào chưa ánh xạ ở cả hai định dạng."""
    for result in pair:
        blocks = [result.data["preface"], *result.data["sections"].values()]
        unmapped = {
            key for block in blocks for key in block["unmapped_fields"]
        }
        assert not unmapped, f"{result.input_format.value}: {unmapped}"


def test_docx_gates_that_do_not_apply_are_null(pair):
    """Cổng của PDF không áp dụng cho DOCX phải là `None`, không phải "xanh".

    Báo xanh một cổng không chạy là tạo cảm giác an toàn không có thật: người
    đọc sẽ tin rằng bảng ToUnicode đã được soát, trong khi DOCX không có bảng
    nào để soát.
    """
    _, docx_result = pair

    assert docx_result.pdf_class is None
    assert docx_result.font_audit is None
    assert docx_result.glyph_layers is None

    verification = docx_result.to_json()["verification"]
    assert verification["pdf_class"] is None
    assert verification["font_audit"] is None
    assert verification["glyph_layers"] is None


def test_docx_values_carry_xml_location_instead_of_bbox(pair):
    """Bằng chứng vị trí của DOCX là đường dẫn XML, không phải bbox."""
    _, docx_result = pair
    node = docx_result.data["sections"]["I"]["fields"]["customer_name"]

    assert "bbox" not in node, "DOCX không có toạ độ nên không được có bbox"
    assert node["location"].startswith("body/"), node
    # DOCX không phân trang: Word tính số trang lúc mở file.
    assert node["page"] == 0


def test_docx_cross_verify_uses_independent_readers(pair):
    """Phải có tối thiểu hai bộ đọc độc lập xác nhận, và cả hai đều khớp."""
    _, docx_result = pair
    report = docx_result.cross_verify

    assert report is not None
    assert report.engine_count >= 2
    assert report.char_multiset_match

    engines = {comparison.engine for comparison in report.comparisons}
    assert {"pandoc", "docx2txt"} <= engines


def test_docx_cross_verify_is_asymmetric_by_design(pair):
    """pandoc thêm ký tự vẽ khung bảng — được ghi nhận nhưng KHÔNG làm đỏ cổng.

    Chiều ngược lại mới là lỗi: bộ đọc khác tìm ra chữ mà engine chính không
    đọc ra. Test này khoá đúng sự bất đối xứng đó, để không ai "sửa" nó thành
    phép so hai chiều rồi làm mọi tài liệu có bảng bị chặn oan.
    """
    _, docx_result = pair
    pandoc = next(
        c for c in docx_result.cross_verify.comparisons if c.engine == "pandoc"
    )

    assert pandoc.char_multiset_match
    # pandoc vẽ khung bảng nên nó có thêm ký tự; toàn bộ phải là nét vẽ.
    assert set(pandoc.only_in_engine) <= set("-=|+"), pandoc.only_in_engine


def test_docx_json_has_text_layer(pair):
    """Khối `text_layer` phải có, để độ phủ ký tự đo được như nhánh PDF."""
    _, docx_result = pair
    text_layer = docx_result.data["text_layer"]

    assert text_layer["pages"], "text_layer rỗng"
    assert "CHỨNG THƯ THẨM ĐỊNH GIÁ" in text_layer["pages"][0]["text"]["value"]
