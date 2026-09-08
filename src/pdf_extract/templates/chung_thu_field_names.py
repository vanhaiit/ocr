"""Ánh xạ nhãn tiếng Việt trong chứng thư sang khóa tiếng Anh.

Nguyên tắc quan trọng nhất: **ánh xạ thiếu KHÔNG được làm mất dữ liệu.** Nhãn
nào chưa có trong bảng vẫn được xuất ra, dưới khóa tự sinh từ chính nhãn đó và
nằm trong `unmapped_fields`. Nhờ vậy JSON luôn chứa mọi thứ tài liệu có, còn
bảng ánh xạ chỉ làm việc đặt tên cho dễ tiêu thụ.

So nhãn ở dạng đã chuẩn hoá (bỏ dấu, hạ chữ, gộp khoảng trắng, bỏ dấu câu cuối)
nên biến thể nhỏ giữa các bản chứng thư vẫn khớp cùng một khóa.
"""

from __future__ import annotations

import re
import unicodedata

# Tên tiếng Anh cho từng mục La Mã, để người đọc JSON biết mục đó là gì.
SECTION_NAMES = {
    "I": "customer_info",
    "II": "valuation_company",
    "III": "asset_info",
    "IV": "valuation_date",
    "V": "valuation_purpose",
    "VI": "value_basis",
    "VII": "assumptions",
    "VIII": "valuation_approach",
    "IX": "valuation_method",
    "X": "asset_values",
    "XI": "validity_period",
    "XII": "exclusions_and_limitations",
    "XIII": "attached_documents",
}

# Nhãn ở phần mở đầu (trước mục I).
PREFACE_FIELD_NAMES = {
    "so hd": "contract_number",
    "so ctph": "certificate_number",
    "kinh gui": "recipient",
}

# Nhãn trong từng mục. Khóa ngoài là số La Mã của mục.
SECTION_FIELD_NAMES = {
    "I": {
        "ten khach hang": "customer_name",
        "dia chi": "customer_address",
        "cccd/mst": "customer_identity_number",
        "cccd": "customer_identity_number",
        "cmnd": "customer_identity_number",
        "mst": "customer_tax_id",
    },
    "II": {
        "don vi thuc hien": "company_branch",
        "dia chi": "company_address",
        "ma so thue": "company_tax_id",
        "dai dien": "company_representative",
    },
    "III": {
        "loai hinh tai san": "asset_type",
        "tai san tham dinh": "asset_under_valuation",
        "ho so phap ly khach hang cung cap": "legal_documents_provided",
        "dac diem kinh te - ky thuat va hien trang": "technical_and_condition_notes",
    },
    "XI": {
        "thoi han hieu luc cua ket qua tham dinh gia trong chung thu "
        "tinh tu ngay phat hanh la": "validity_duration",
    },
    "XIII": {
        "cac phu luc chi tiet kem theo": "appendix_list_heading",
        "phu luc so 01": "appendix_01",
        "phu luc so 02": "appendix_02",
        "mot so luu y": "notes_heading",
    },
}

# Vai trò người ký, nhận ra từ dòng đầu của mỗi cột trong khối chữ ký.
SIGNATURE_ROLE_NAMES = {
    "tham dinh vien ve gia": "valuer",
    "giam doc chi nhanh": "branch_director",
    "giam doc": "director",
    "tong giam doc": "general_director",
}

# Nhãn số thẻ trong khối chữ ký.
SIGNATURE_CARD_LABEL = "so the"


def comparable_label(label: str) -> str:
    """Dạng chuẩn để so nhãn: bỏ dấu, hạ chữ, gộp khoảng trắng, bỏ dấu câu cuối."""
    without_marks = "".join(
        char
        for char in unicodedata.normalize("NFD", label)
        if unicodedata.combining(char) == 0
    )
    # `đ` không phải ký tự tổ hợp nên phải thay riêng.
    lowered = without_marks.lower().replace("đ", "d")
    collapsed = " ".join(lowered.split())
    return collapsed.strip(" .:;,-")


def slugify_label(label: str) -> str:
    """Khóa tự sinh cho nhãn chưa có tên tiếng Anh: snake_case không dấu."""
    base = comparable_label(label)
    slug = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return slug or "unnamed_field"


def field_name_for(section_number: str | None, label: str) -> str | None:
    """Tên tiếng Anh của nhãn, hoặc None nếu chưa được ánh xạ."""
    key = comparable_label(label)

    if section_number is None:
        return PREFACE_FIELD_NAMES.get(key)

    return SECTION_FIELD_NAMES.get(section_number, {}).get(key)


def signature_role_for(text: str) -> str | None:
    """Tên tiếng Anh của vai trò người ký, hoặc None nếu chưa được ánh xạ."""
    return SIGNATURE_ROLE_NAMES.get(comparable_label(text))
