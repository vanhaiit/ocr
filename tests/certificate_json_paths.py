"""Đường dẫn tới từng giá trị trong JSON theo cấu trúc mục, dùng chung cho test.

JSON được tổ chức theo đúng cấu trúc tài liệu: `preface` cho phần mở đầu, rồi
`sections` khóa bằng số La Mã. Một giá trị có thể nằm ở hai chỗ tuỳ cách trình
bày của từng bản chứng thư:

  - `sections.XI.fields.validity_duration` khi mục có tiêu đề riêng rồi tới dòng
    "Thời hạn hiệu lực ... là: 06 tháng"
  - `sections.XI.value` khi giá trị viết ngay sau dấu hai chấm của tiêu đề mục

Vì vậy mỗi tên logic ứng với MỘT DANH SÁCH đường dẫn ứng viên, và phép tra lấy
đường dẫn đầu tiên có giá trị. Cách này để test dùng được cho cả hai cách trình
bày mà không phải viết riêng hai bộ.
"""

from __future__ import annotations

from typing import Any

# Tên logic -> các đường dẫn ứng viên, xét theo thứ tự.
FIELD_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "contract_number": ((("preface", "fields", "contract_number"),)),
    "certificate_number": ((("preface", "fields", "certificate_number"),)),
    "recipient": ((("preface", "fields", "recipient"),)),
    "customer_name": ((("sections", "I", "fields", "customer_name"),)),
    "customer_address": ((("sections", "I", "fields", "customer_address"),)),
    "customer_id": ((("sections", "I", "fields", "customer_identity_number"),)),
    "company_branch": ((("sections", "II", "fields", "company_branch"),)),
    "company_address": ((("sections", "II", "fields", "company_address"),)),
    "company_tax_id": ((("sections", "II", "fields", "company_tax_id"),)),
    "company_representative": (
        (("sections", "II", "fields", "company_representative"),)
    ),
    "asset_type": ((("sections", "III", "fields", "asset_type"),)),
    "asset_under_valuation": (
        (("sections", "III", "fields", "asset_under_valuation"),)
    ),
    "valuation_date": (
        ("sections", "IV", "value"),
        ("sections", "IV", "fields", "valuation_date"),
    ),
    "purpose": (
        ("sections", "V", "value"),
        ("sections", "V", "fields", "valuation_purpose"),
    ),
    # Các dòng tổng giữ cả nhãn tiếng Việt, nên node là {label, value, ...} —
    # `value_at` lấy khoá "value" của node là đúng chỗ.
    "total": ((("sections", "X", "table", "totals", "total"),)),
    "total_rounded": ((("sections", "X", "table", "totals", "total_rounded"),)),
    "total_in_words": ((("sections", "X", "table", "totals", "total_in_words"),)),
    "validity": (
        ("sections", "XI", "fields", "validity_duration"),
        ("sections", "XI", "value"),
    ),
}

# Đường dẫn tới bảng giá trị tài sản.
ASSET_ROWS_PATH = ("sections", "X", "table", "rows")


def _normalise(paths) -> tuple[tuple[str, ...], ...]:
    """Cho phép khai báo một đường dẫn đơn lẻ hoặc nhiều ứng viên."""
    if paths and isinstance(paths[0], str):
        return (tuple(paths),)
    return tuple(tuple(path) for path in paths)


def value_at(data: dict[str, Any], path: tuple[str, ...]) -> str | None:
    """Giá trị chuỗi tại một đường dẫn, hoặc None nếu không có."""
    node: Any = data

    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None

    return node.get("value") if isinstance(node, dict) else None


def field_value(data: dict[str, Any], name: str) -> str | None:
    """Giá trị của một tên logic, lấy đường dẫn ứng viên đầu tiên có dữ liệu."""
    for path in _normalise(FIELD_PATHS[name]):
        found = value_at(data, path)
        if found is not None:
            return found

    return None


def node_at(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Node thô tại một đường dẫn, để kiểm các thuộc tính như bbox hay verbatim."""
    node: Any = data

    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None

    return node


def asset_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Các dòng thửa đất trong bảng mục X."""
    return node_at(data, ASSET_ROWS_PATH) or []
