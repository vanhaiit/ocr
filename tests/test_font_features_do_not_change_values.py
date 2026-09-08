"""Khoá điều quan trọng nhất: tính năng trình bày KHÔNG làm đổi giá trị bóc ra.

Mọi biến thể trong `samples/font-features/` chứa cùng một tập giá trị nghiệp vụ,
chỉ khác cách vẽ chữ — in đậm, in nghiêng, chỉ số trên, hyperlink, đổ bóng, viền
chữ, ô điền thông tin, tiêu đề quay dọc, lớp chữ ẩn, watermark, dấu tiếng Việt
dạng phân rã, và bản trộn tất cả.

Test ở đây so từng giá trị với ground truth trong `certificate_expected_values`,
không so giữa các biến thể với nhau. Lý do: nếu so chéo, một lỗi làm sai đều cả
12 file sẽ lọt qua hết.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.certificate_expected_values import (
    EXPECTED,
    EXPECTED_ASSET_ROWS,
    EXPECTED_FORM_FIELDS,
    INVISIBLE_LAYER_TEXT,
    PORTAL_URL,
    WATERMARK_TEXT,
)
from pdf_extract.models import ExtractionStatus
from pdf_extract.pipeline import process_pdf

FEATURES_DIR = Path(__file__).resolve().parent.parent / "samples" / "font-features"

# Ánh xạ từ khoá ground truth sang đường dẫn trong cây JSON.
FIELD_PATHS = {
    "contract_number": ("certificate", "contract_number"),
    "certificate_number": ("certificate", "certificate_number"),
    "issue_place_and_date": ("certificate", "issue_place_and_date"),
    "customer_name": ("customer", "name"),
    "customer_address": ("customer", "address"),
    "customer_id": ("customer", "identity_number"),
    "company_branch": ("valuation_company", "company_branch"),
    "company_address": ("valuation_company", "company_address"),
    "company_tax_id": ("valuation_company", "company_tax_id"),
    "company_representative": ("valuation_company", "company_representative"),
    "asset_type": ("asset", "asset_type"),
    "asset_under_valuation": ("asset", "asset_under_valuation"),
    "valuation_date": ("valuation", "valuation_date"),
    "purpose": ("valuation", "purpose"),
    "total": ("totals", "total"),
    "total_rounded": ("totals", "total_rounded"),
    "total_in_words": ("totals", "total_in_words"),
}

# Biến thể có dữ liệu nằm trong annotation, cần đường trích xuất riêng.
VARIANTS_WITH_FORM_FIELDS = ("07-form-fields.pdf", "12-kitchen-sink.pdf")
VARIANTS_WITH_HYPERLINK = ("04-hyperlink.pdf", "12-kitchen-sink.pdf")


def variant_names() -> list[str]:
    return sorted(p.name for p in FEATURES_DIR.glob("*.pdf"))


@pytest.fixture(scope="module", params=variant_names())
def extraction(request):
    return request.param, process_pdf(str(FEATURES_DIR / request.param))


def _value_at(data: dict, path: tuple[str, ...]) -> str | None:
    node = data
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
        if node is None:
            return None
    return node.get("value") if isinstance(node, dict) else None


def test_variant_set_is_complete():
    """Phải có đủ bộ biến thể, nếu không test bên dưới mất ý nghĩa."""
    names = variant_names()
    assert names, f"Chưa sinh biến thể trong {FEATURES_DIR}"
    assert len(names) >= 12, f"Chỉ có {len(names)} biến thể: {names}"


def test_every_variant_is_verified(extraction):
    """MỌI biến thể phải đạt `verified` — không tính năng nào được làm đỏ pipeline."""
    name, result = extraction
    assert result.status is ExtractionStatus.VERIFIED, f"{name}: {result.errors}"


def test_all_values_are_traceable(extraction):
    """Mọi giá trị phải chứng minh được là nguyên văn của tài liệu."""
    name, result = extraction
    assert result.provenance is not None
    assert result.provenance.unverified_paths == [], name
    assert result.provenance.ratio == 1.0, name


def test_scalar_fields_match_ground_truth(extraction):
    """Từng field phải đúng bằng giá trị đã đưa vào khi sinh file."""
    name, result = extraction

    for key, path in FIELD_PATHS.items():
        assert _value_at(result.data, path) == EXPECTED[key], (
            f"{name}: {'.'.join(path)} sai"
        )


def test_asset_table_matches_ground_truth(extraction):
    """Bảng mục X phải đúng số dòng và đúng từng ô, kể cả ô bị wrap.

    Cột thành tiền cố ý dài hơn bề rộng cột nên bị ngắt dòng trong ô; ghép lại
    phải LIỀN (không dấu cách), còn cột mô tả là văn xuôi thì ghép CÓ dấu cách.
    """
    name, result = extraction
    rows = result.data["assets_valued"]

    assert len(rows) == len(EXPECTED_ASSET_ROWS), name

    for actual, expected in zip(rows, EXPECTED_ASSET_ROWS):
        assert actual["index"] == expected["index"], name
        for column in ("description", "area_sqm", "amount_vnd"):
            assert actual[column]["value"] == expected[column], (
                f"{name}: thửa {expected['index']} cột {column}"
            )


def test_form_field_values_are_extracted(extraction):
    """Giá trị ô điền thông tin phải có trong JSON.

    Đây là ca mà đọc text thuần mất trắng dữ liệu: giá trị nằm trong `/V` của
    widget annotation, không nằm trong content stream của trang.
    """
    name, result = extraction
    fields = result.data["form_fields"]

    if name not in VARIANTS_WITH_FORM_FIELDS:
        assert fields == {}, f"{name}: không có form field nhưng JSON lại có"
        return

    assert set(fields) == set(EXPECTED_FORM_FIELDS), name
    for field_name, expected_value in EXPECTED_FORM_FIELDS.items():
        assert fields[field_name]["value"] == expected_value, f"{name}: {field_name}"
        assert fields[field_name]["verbatim"] is True
        assert fields[field_name]["bbox"], f"{name}: {field_name} thiếu bbox"


def test_hyperlink_urls_are_extracted(extraction):
    """URL của liên kết phải có trong JSON.

    Phần chữ hiển thị nằm trong content stream, nhưng URL nằm trong `/A /URI`
    của annotation — bỏ qua là mất dữ liệu nghiệp vụ.
    """
    name, result = extraction
    links = result.data["hyperlinks"]

    if name not in VARIANTS_WITH_HYPERLINK:
        assert links == [], f"{name}: không có hyperlink nhưng JSON lại có"
        return

    assert [link["value"] for link in links] == [PORTAL_URL], name
    assert all(link["verbatim"] for link in links), name


def test_hidden_and_decorative_text_never_leaks_into_values(extraction):
    """Chữ ẩn và watermark không được lẫn vào giá trị field nào.

    Hai loại này nằm trong text layer nhưng không phải dữ liệu nghiệp vụ. Lọt
    vào field là dạng sai âm thầm: giá trị vẫn "nguyên văn của PDF" nên cổng
    nguồn gốc không bắt được.
    """
    name, result = extraction

    for key, path in FIELD_PATHS.items():
        value = _value_at(result.data, path) or ""
        assert INVISIBLE_LAYER_TEXT not in value, f"{name}: chữ ẩn lẫn vào {key}"
        assert WATERMARK_TEXT not in value, f"{name}: watermark lẫn vào {key}"

    for row in result.data["assets_valued"]:
        for column in ("description", "area_sqm", "amount_vnd"):
            value = row[column]["value"]
            assert INVISIBLE_LAYER_TEXT not in value, name
            assert WATERMARK_TEXT not in value, name


def test_shadow_variants_report_removed_glyph_layer(extraction):
    """Biến thể đổ bóng phải ghi nhận có lọc glyph trùng.

    Nếu số glyph lọc bằng 0 thì hoặc fixture không thật sự đổ bóng, hoặc bộ lọc
    không chạy — cả hai đều làm biến thể này mất tác dụng kiểm tra.
    """
    name, result = extraction
    if "shadow" not in name and "kitchen" not in name:
        pytest.skip("biến thể không có đổ bóng")

    assert result.glyph_layers is not None
    assert result.glyph_layers.has_duplicate_layer, name
    assert result.glyph_layers.pages_affected == [1], name


def test_documents_without_effects_need_no_glyph_filtering(extraction):
    """Biến thể không có hiệu ứng chữ thì không glyph nào bị lọc.

    Chống bộ lọc xoá oan glyph hợp lệ — dạng mất dữ liệu mà không cổng nào khác
    phát hiện được.
    """
    name, result = extraction
    if "shadow" in name or "kitchen" in name:
        pytest.skip("biến thể có đổ bóng")

    assert result.glyph_layers is not None
    assert result.glyph_layers.duplicate_glyphs_removed == 0, name


def test_at_least_two_engines_confirm_each_variant(extraction):
    """Mỗi biến thể phải có tối thiểu hai engine độc lập xác nhận."""
    name, result = extraction
    assert result.cross_verify is not None
    assert result.cross_verify.engine_count >= 2, name
    assert result.cross_verify.char_multiset_match, name


def test_no_font_is_missing_tounicode(extraction):
    """Font thực dùng phải có đủ bảng ToUnicode ở mọi biến thể."""
    name, result = extraction
    assert result.font_audit is not None
    assert result.font_audit.is_complete, f"{name}: {result.font_audit.missing}"
