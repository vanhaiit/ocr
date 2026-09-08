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
        "khach hang": "customer_name",
        "ten khach hang/don vi": "customer_name",
        "dia chi": "customer_address",
        "dia chi lien he": "customer_address",
        # Giấy tờ định danh: các bản chứng thư dùng nhiều cách gọi cho cùng một
        # thứ, gom hết về một khóa để bên tiêu thụ không phải phân nhánh.
        "cccd/mst": "customer_identity_number",
        "cccd": "customer_identity_number",
        "cmnd": "customer_identity_number",
        "cmnd/cccd": "customer_identity_number",
        "so cccd": "customer_identity_number",
        "so cmnd": "customer_identity_number",
        "cccd/cmnd/mst": "customer_identity_number",
        "mst": "customer_tax_id",
        "ma so thue": "customer_tax_id",
        "ngay cap": "customer_identity_issued_on",
        "noi cap": "customer_identity_issued_by",
        "dien thoai": "customer_phone",
        "so dien thoai": "customer_phone",
        "email": "customer_email",
    },
    "II": {
        "don vi thuc hien": "company_branch",
        "dia chi": "company_address",
        "ma so thue": "company_tax_id",
        "dai dien": "company_representative",
        "nguoi dai dien": "company_representative",
        # Nằm ở cột kế bên trên cùng dòng "Đại diện", tách ra thành field riêng.
        "chuc vu": "company_representative_position",
        "chuc danh": "company_representative_position",
        "dien thoai": "company_phone",
        "so dien thoai": "company_phone",
        "email": "company_email",
        "so giay phep": "company_licence_number",
    },
    "III": {
        "loai hinh tai san": "asset_type",
        "tai san tham dinh": "asset_under_valuation",
        "ho so phap ly khach hang cung cap": "legal_documents_provided",
        "dac diem kinh te - ky thuat va hien trang": "technical_and_condition_notes",
        "dac diem kinh te ky thuat va hien trang": "technical_and_condition_notes",
        "ho so phap ly": "legal_documents_provided",
        "giay chung nhan": "land_certificate",
        "so to ban do": "map_sheet_number",
        "so thua dat": "land_lot_number",
        "vi tri": "asset_location",
        "tong dien tich": "total_area",
    },
    "XI": {
        "thoi han hieu luc cua ket qua tham dinh gia trong chung thu "
        "tinh tu ngay phat hanh la": "validity_duration",
        "thoi han hieu luc": "validity_duration",
        "so to ban do": "map_sheet_number",
        "nguoi kiem tra": "checked_by",
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


# Độ dài tối thiểu của nhãn khi khớp theo tiền tố, tránh khớp bừa vì trùng vài
# ký tự đầu.
MIN_PREFIX_MATCH_LENGTH = 8


def field_name_for(section_number: str | None, label: str) -> str | None:
    """Tên tiếng Anh của nhãn, hoặc None nếu chưa được ánh xạ.

    Khớp tuyệt đối trước. Không có thì khớp theo TIỀN TỐ: nhãn thực tế có thể
    dài hơn nhãn trong bảng vì bố cục làm nó dính thêm phần sau ("Tài sản thẩm
    định thuộc LAND-LOT-GROUP-001..."). Yêu cầu tiền tố dài và kết thúc ở ranh
    giới TỪ để không khớp bừa.
    """
    table = PREFACE_FIELD_NAMES if section_number is None else SECTION_FIELD_NAMES.get(
        section_number, {}
    )
    key = comparable_label(label)

    exact = table.get(key)
    if exact is not None:
        return exact

    candidates = [
        (mapped_key, name)
        for mapped_key, name in table.items()
        if len(mapped_key) >= MIN_PREFIX_MATCH_LENGTH
        and key.startswith(mapped_key)
        and key[len(mapped_key):].startswith(" ")
    ]

    if not candidates:
        return None

    # Tiền tố dài nhất là khớp cụ thể nhất.
    return max(candidates, key=lambda item: len(item[0]))[1]


def signature_role_for(text: str) -> str | None:
    """Tên tiếng Anh của vai trò người ký, hoặc None nếu chưa được ánh xạ."""
    return SIGNATURE_ROLE_NAMES.get(comparable_label(text))
