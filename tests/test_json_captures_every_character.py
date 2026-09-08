"""Kiểm điều đã cam kết: JSON nhặt HẾT ký tự của tài liệu, không bỏ sót gì.

Đây là phép đo trả lời trực tiếp câu "có thật là nhặt hết chưa": lấy toàn bộ ký
tự trong text layer, lấy toàn bộ ký tự xuất hiện trong JSON (gồm cả khóa dict và
số), rồi so MULTISET. Ký tự nào có trong tài liệu mà không có trong JSON là bị
mất.

Cách đo ở mức KÝ TỰ, không ở mức dòng. Lý do: JSON tách nhãn khỏi giá trị và
ghép các dòng bị ngắt lại, nên so nguyên dòng sẽ báo thiếu hàng loạt dù mọi
mảnh đều có mặt — phép đo sai chứ không phải dữ liệu sai.

Ngoại lệ duy nhất là các ký tự CẤU TRÚC: dấu hai chấm tách nhãn với giá trị, và
gạch đầu dòng mở đầu mục liệt kê. Parser tiêu thụ chúng để dựng cấu trúc, và
chính cấu trúc đó đã mang thông tin chúng biểu đạt.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from pdf_extract.classify_overlay_glyphs import split_overlay_glyphs
from pdf_extract.detect_duplicate_glyph_layers import deduplicate_glyphs
from pdf_extract.extract_text_with_coordinates import (
    canonical_text,
    extract_positioned_chars,
    group_chars_into_lines,
)
from pdf_extract.pipeline import process_pdf

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "samples"
FEATURES_DIR = SAMPLES_DIR / "font-features"

# Ký tự cấu trúc: parser dùng chúng để tách nhãn/giá trị và nhận mục liệt kê,
# nên chúng không xuất hiện lại trong giá trị. Thông tin chúng biểu đạt đã nằm
# trong chính cấu trúc JSON (nhãn riêng, giá trị riêng, danh sách `items`).
STRUCTURAL_CHARACTERS = set(":-–+●•* ")

# File có text layer hỏng font: ký tự đã sai từ trong PDF và các cột bảng đan
# xen nhau, nên phép đo này không có ý nghĩa. Hành vi phát hiện nó được khoá ở
# `test_font_without_tounicode_is_caught.py`.
EXCLUDED_FROM_COVERAGE = {"Chung_Thu_Tham_Dinh_Gia_Demo.pdf"}


def documents_under_test() -> list[Path]:
    """Mọi PDF được kỳ vọng nhặt hết: mẫu thật và các biến thể tính năng."""
    paths = [p for p in SAMPLES_DIR.glob("*.pdf") if p.name not in EXCLUDED_FROM_COVERAGE]
    return sorted(paths) + sorted(FEATURES_DIR.glob("*.pdf"))


@pytest.fixture(scope="module", params=[str(p) for p in documents_under_test()])
def coverage(request):
    path = request.param
    result = process_pdf(path)

    deduplicated, _ = deduplicate_glyphs(extract_positioned_chars(path))
    body, _ = split_overlay_glyphs(deduplicated)
    document_text = canonical_text(group_chars_into_lines(body))

    return Path(path).name, _characters(document_text), _characters(
        "".join(_all_text(result.data, []))
    )


def _characters(text: str) -> Counter:
    """Đếm ký tự, bỏ khoảng trắng và chuẩn hoá NFC."""
    return Counter(re.sub(r"\s+", "", unicodedata.normalize("NFC", text)))


def _all_text(node: Any, collected: list[str]) -> list[str]:
    """Mọi chuỗi trong cây JSON, GỒM CẢ khóa dict và giá trị số.

    Số La Mã của mục là khóa của `sections`, còn số thứ tự dòng bảng là số
    nguyên — bỏ hai loại này thì phép đo báo thiếu oan.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            collected.append(str(key))
            _all_text(value, collected)
    elif isinstance(node, list):
        for value in node:
            _all_text(value, collected)
    elif node is not None:
        collected.append(str(node))

    return collected


def test_documents_under_test_exist():
    """Không có file thì phép đo bên dưới vô nghĩa."""
    assert documents_under_test(), "Không tìm thấy PDF nào để đo độ phủ"


def test_no_data_character_is_lost(coverage):
    """MỌI ký tự dữ liệu của tài liệu phải xuất hiện trong JSON.

    Đây là chốt chặn cho lỗi lớn nhất của bản đầu tiên: template đi tìm một
    danh sách nhãn định trước nên mọi thứ ngoài danh sách bị bỏ IM LẶNG — mất
    cả "Kính gửi", các dòng "Căn cứ", mục VI đến IX, mục XII, XIII và khối chữ
    ký, mà không cổng kiểm tra nào báo gì.
    """
    name, document_chars, json_chars = coverage
    lost = document_chars - json_chars
    data_lost = {c: n for c, n in lost.items() if c not in STRUCTURAL_CHARACTERS}

    assert not data_lost, f"{name}: JSON thiếu ký tự dữ liệu {data_lost}"


def test_structural_loss_stays_small(coverage):
    """Phần ký tự cấu trúc bị tiêu thụ phải nhỏ.

    Dấu hai chấm và gạch đầu dòng biến thành cấu trúc JSON nên không xuất hiện
    lại — chấp nhận được. Nhưng nếu tỉ lệ này phình lên thì có thể parser đang
    ăn cả nội dung thật, nên vẫn phải có ngưỡng.
    """
    name, document_chars, json_chars = coverage
    total = sum(document_chars.values())
    lost = sum((document_chars - json_chars).values())

    assert total > 0, name
    assert lost / total <= 0.05, f"{name}: mất {lost}/{total} ký tự"


def test_table_column_headers_are_captured(coverage):
    """Tiêu đề cột của bảng phải có trong JSON.

    Tiêu đề cột mang ĐƠN VỊ ("Diện tích (m2)", "Thành tiền (đồng)") nên là dữ
    liệu, không phải chỉ là hàng để bỏ qua khi tìm các dòng số liệu.
    """
    name, _, _ = coverage
    path = SAMPLES_DIR / name
    if not path.exists():
        path = FEATURES_DIR / name

    table = process_pdf(str(path)).data["sections"]["X"]["table"]
    headers = [column["value"] for column in table["columns"]]

    assert headers, f"{name}: bảng không có tiêu đề cột"
    assert any("STT" in header for header in headers), f"{name}: {headers}"


def test_total_rows_keep_their_vietnamese_label(coverage):
    """Các dòng tổng phải giữ nhãn tiếng Việt kèm đơn vị."""
    name, _, _ = coverage
    path = SAMPLES_DIR / name
    if not path.exists():
        path = FEATURES_DIR / name

    totals = process_pdf(str(path)).data["sections"]["X"]["table"]["totals"]

    for key, entry in totals.items():
        assert entry is not None, f"{name}: thiếu dòng tổng {key}"
        assert entry["label"], f"{name}: dòng tổng {key} không có nhãn"


def _value_nodes(node: Any, collected: list[dict]) -> list[dict]:
    """Mọi node trong JSON MANG MỘT GIÁ TRỊ chuỗi.

    Nhận ra bằng khóa `value` có nội dung chuỗi. Node chỉ có nhãn mà giá trị
    rỗng (`{"label": ..., "value": None}`) không mang giá trị nên không tính.
    """
    if isinstance(node, dict):
        if isinstance(node.get("value"), str):
            collected.append(node)
        for value in node.values():
            _value_nodes(value, collected)
    elif isinstance(node, list):
        for value in node:
            _value_nodes(value, collected)

    return collected


def test_every_value_in_json_passed_the_provenance_gate(coverage):
    """MỌI node giá trị trong JSON phải đã đi qua cổng nguồn gốc.

    Chốt chặn cho một lỗi từng lọt: tầng template dựng sẵn dict cho các field
    thay vì trả về kiểu mà cổng nhận ra, nên toàn bộ `fields` ĐI VÒNG qua cổng —
    ra JSON với `verbatim: false` và không được tính vào báo cáo. Báo cáo vẫn
    ghi "101/101" nên nhìn từ bên ngoài không thấy gì sai.

    Bất biến được kiểm: MỌI node mang giá trị chuỗi đều phải có khóa `verbatim`
    và bằng True. Node đi vòng qua cổng sẽ thiếu khóa đó, hoặc mang False — cả
    hai trường hợp đều làm test đỏ.
    """
    name, _, _ = coverage
    path = SAMPLES_DIR / name
    if not path.exists():
        path = FEATURES_DIR / name

    result = process_pdf(str(path))
    nodes = _value_nodes(result.data, [])

    assert nodes, f"{name}: JSON không có node giá trị nào"

    missing_gate = [n for n in nodes if "verbatim" not in n]
    assert not missing_gate, (
        f"{name}: {len(missing_gate)} node không có bằng chứng nguồn gốc, "
        f"ví dụ {missing_gate[0]}"
    )

    not_verbatim = [n for n in nodes if not n["verbatim"]]
    assert not not_verbatim, (
        f"{name}: {len(not_verbatim)} node chưa chứng minh được nguồn, "
        f"ví dụ {not_verbatim[0]}"
    )

    assert result.provenance is not None
    assert result.provenance.unverified_paths == [], name
