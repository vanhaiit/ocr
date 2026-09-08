"""Giá trị kỳ vọng dùng chung cho mọi biến thể PDF nhân tạo.

Đây là ground truth: mọi biến thể — dù vẽ bằng in đậm, chỉ số trên, đổ bóng hay
form field — đều phải bóc ra ĐÚNG những giá trị này. Đặt tập giá trị ở một chỗ
duy nhất để không có đường nào cho biến thể "tự định nghĩa" kết quả của nó.
"""

from __future__ import annotations

# Khổ A4 tính bằng điểm PDF.
PAGE_WIDTH = 595.28
PAGE_HEIGHT = 841.89

# URL của hyperlink. Là dữ liệu nghiệp vụ thật (cổng tra cứu chứng thư), nên
# pipeline phải lấy được — không chỉ lấy phần chữ hiển thị.
PORTAL_URL = "https://tra-cuu.example.vn/chung-thu/CERT-NO-900"
PORTAL_TEXT = "Tra cứu trực tuyến"

# Giá trị các field cốt lõi. Trùng khuôn placeholder của file mẫu thật để dễ đối
# chiếu, nhưng đánh số 900 để không lẫn với hai file mẫu gốc.
EXPECTED = {
    "contract_number": "CONTRACT-NO-900",
    "certificate_number": "CERT-NO-900",
    "issue_place_and_date": "TP.HCM, ISSUE-DATE-900",
    "recipient": "ÔNG: CUSTOMER-NAME-900",
    "customer_name": "ÔNG: CUSTOMER-NAME-900",
    "customer_address": "CUSTOMER-ADDRESS-900",
    "customer_id": "CUSTOMER-ID-900",
    "company_branch": "COMPANY-BRANCH-FULL-900",
    "company_address": "COMPANY-ADDRESS-900",
    "company_tax_id": "COMPANY-TAX-ID-900",
    "company_representative": "Ông: STAFF-NAME-900 Chức vụ: Giám đốc Chi nhánh",
    "asset_type": "Bất động sản.",
    "asset_under_valuation": "Giá trị Quyền sử dụng đất thuộc LAND-LOT-GROUP-900, PROPERTY-DISTRICT-900.",
    "valuation_date": "VALUATION-DATE-900",
    "purpose": "Tư vấn giá trị tài sản để BANK-NAME-900 tham khảo, xem xét quyết định hạn mức để cấp tín dụng.",
    "total": "VALUE-VND-TOTAL-900",
    "total_rounded": "VALUE-VND-TOTAL-ROUNDED-900",
    "total_in_words": "VALUE-VND-TOTAL-TEXT-900",
    "validity": "06 tháng",
}

# Các thửa đất trong bảng mục X. Cột diện tích cố ý mang chỉ số trên (m2) để
# kiểm ngưỡng gom dòng khi trong ô có chữ lệch baseline.
EXPECTED_ASSET_ROWS = [
    {
        "index": 1,
        "description": "Giá trị Quyền sử dụng đất LAND-LOT-901",
        "area_sqm": "AREA-SQM-901",
        "amount_vnd": "VALUE-VND-LOT-901",
    },
    {
        "index": 2,
        "description": "Giá trị Quyền sử dụng đất LAND-LOT-902",
        "area_sqm": "AREA-SQM-902",
        "amount_vnd": "VALUE-VND-LOT-902",
    },
    {
        "index": 3,
        "description": "Giá trị Quyền sử dụng đất LAND-LOT-903",
        "area_sqm": "AREA-SQM-903",
        "amount_vnd": "VALUE-VND-LOT-903",
    },
]

# Giá trị nằm trong form field tương tác (AcroForm). Chỗ này khác bản chất với
# text thường: giá trị sống trong `/V` của annotation, KHÔNG nằm trong content
# stream của trang. Không đọc AcroForm thì mất trắng các giá trị này.
EXPECTED_FORM_FIELDS = {
    "so_to_ban_do": "MAP-SHEET-900",
    "nguoi_kiem_tra": "STAFF-NAME-901",
}

# Chữ ẩn (chế độ tô 3) và watermark là nội dung KHÔNG thuộc dữ liệu nghiệp vụ.
# Chúng phải không lọt vào giá trị field nào.
INVISIBLE_LAYER_TEXT = "BAN NHAP KHONG SU DUNG"
WATERMARK_TEXT = "BAN SAO"
