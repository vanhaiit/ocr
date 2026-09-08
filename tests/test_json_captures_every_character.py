"""Kiểm điều đã cam kết: JSON nhặt HẾT ký tự của tài liệu, không bỏ sót gì.

Đây là phép đo trả lời trực tiếp câu "có thật là nhặt hết chưa": lấy toàn bộ ký
tự trong text layer, lấy toàn bộ ký tự xuất hiện trong JSON (gồm cả khóa dict và
số), rồi so MULTISET. Ký tự nào có trong tài liệu mà không có trong JSON là bị
mất.

Cách đo ở mức KÝ TỰ, không ở mức dòng. Lý do: JSON tách nhãn khỏi giá trị và
ghép các dòng bị ngắt lại, nên so nguyên dòng sẽ báo thiếu hàng loạt dù mọi
mảnh đều có mặt — phép đo sai chứ không phải dữ liệu sai.

Yêu cầu là TUYỆT ĐỐI: không ký tự nào được thiếu, kể cả dấu hai chấm và gạch
đầu dòng mà phần có cấu trúc đã tiêu thụ, và kể cả chữ trang trí bị loại khỏi
luồng nghiệp vụ. Khối `text_layer` giữ nguyên văn text theo từng trang chính là
để bảo đảm điều đó.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

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

def documents_under_test() -> list[Path]:
    """MỌI PDF trong bộ mẫu. Không file nào được miễn phép đo độ phủ.

    Kể cả file hỏng font: ký tự của nó sai từ trong PDF, nhưng JSON vẫn phải
    chứa đủ những ký tự đó — trung thực với nguồn là yêu cầu riêng, khác với
    nguồn có đúng hay không.
    """
    return sorted(SAMPLES_DIR.glob("*.pdf")) + sorted(FEATURES_DIR.glob("*.pdf"))


@pytest.fixture(scope="module", params=[str(p) for p in documents_under_test()])
def coverage(request):
    path = request.param
    result = process_pdf(path)

    # Dùng TOÀN BỘ ký tự, không tách chữ trang trí: watermark cũng là text của
    # tài liệu nên cũng phải có mặt trong JSON.
    deduplicated, _ = deduplicate_glyphs(extract_positioned_chars(path))
    document_text = canonical_text(group_chars_into_lines(deduplicated))

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


def test_no_character_is_lost_at_all(coverage):
    """KHÔNG ký tự nào của tài liệu được thiếu trong JSON. Yêu cầu tuyệt đối.

    Chốt chặn cho lỗi lớn nhất của bản đầu tiên: template đi tìm một danh sách
    nhãn định trước nên mọi thứ ngoài danh sách bị bỏ IM LẶNG — mất cả "Kính
    gửi", các dòng "Căn cứ", mục VI đến IX, mục XII, XIII và khối chữ ký, mà
    không cổng kiểm tra nào báo gì.

    Phép đo gồm cả dấu hai chấm, gạch đầu dòng, và chữ trang trí — không có
    ngoại lệ nào.
    """
    name, document_chars, json_chars = coverage
    lost = document_chars - json_chars

    assert not lost, f"{name}: JSON thiếu {sum(lost.values())} ký tự: {dict(lost)}"


def test_text_layer_block_is_present(coverage):
    """Khối `text_layer` phải có và phủ mọi trang.

    Đây là thứ bảo đảm độ phủ tuyệt đối ở test trên: phần có cấu trúc tiêu thụ
    ký tự phân cách, khối này giữ nguyên văn để không mất gì.
    """
    name, _, _ = coverage
    path = SAMPLES_DIR / name
    if not path.exists():
        path = FEATURES_DIR / name

    result = process_pdf(str(path))
    text_layer = result.data["text_layer"]

    assert text_layer["pages"], f"{name}: text_layer không có trang nào"
    assert [p["page"] for p in text_layer["pages"]] == sorted(
        p["page"] for p in text_layer["pages"]
    ), f"{name}: trang không theo thứ tự"


def test_table_column_headers_are_captured(coverage):
    """Tiêu đề cột của bảng phải có trong JSON.

    Tiêu đề cột mang ĐƠN VỊ ("Diện tích (m2)", "Thành tiền (đồng)") nên là dữ
    liệu, không phải chỉ là hàng để bỏ qua khi tìm các dòng số liệu.
    """
    name, _, _ = coverage
    path = SAMPLES_DIR / name
    if not path.exists():
        path = FEATURES_DIR / name

    sections = process_pdf(str(path)).data["sections"]
    if "X" not in sections or "table" not in sections["X"]:
        pytest.skip(f"{name}: không có bảng ở mục X")

    table = sections["X"]["table"]
    headers = [column["value"] for column in table["columns"]]

    assert headers, f"{name}: bảng không có tiêu đề cột"
    assert any("STT" in header for header in headers), f"{name}: {headers}"


def test_total_rows_keep_their_vietnamese_label(coverage):
    """Dòng tổng nào CÓ trong tài liệu thì phải giữ nhãn tiếng Việt kèm đơn vị.

    Không đòi đủ cả ba dòng: có bản chứng thư chỉ ghi "Tổng cộng" và "Làm tròn"
    mà không có "Bằng chữ". Việc đủ ba dòng ở các file mẫu chuẩn được kiểm riêng
    qua `test_no_required_field_is_null`.
    """
    name, _, _ = coverage
    path = SAMPLES_DIR / name
    if not path.exists():
        path = FEATURES_DIR / name

    sections = process_pdf(str(path)).data["sections"]
    if "X" not in sections or "table" not in sections["X"]:
        pytest.skip(f"{name}: không có bảng ở mục X")

    totals = sections["X"]["table"]["totals"]

    present = {k: v for k, v in totals.items() if v is not None}
    assert present, f"{name}: bảng không có dòng tổng nào"

    for key, entry in present.items():
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
