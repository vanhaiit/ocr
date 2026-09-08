"""Cổng vào: phân loại PDF có text layer hay là bản scan.

Đây là bước quyết định toàn bộ cam kết chất lượng. PDF có text layer cho phép
trích xuất xác định (tra bảng ToUnicode) nên đạt 100%; PDF scan buộc phải OCR
và không bao giờ đạt 100%. Pipeline này chỉ nhận loại thứ nhất, loại thứ hai
bị từ chối tường minh thay vì âm thầm cho ra dữ liệu kém tin cậy.

Dấu hiệu nhận scan là ẢNH CHE PHỦ PHẦN LỚN TRANG mà không có text, chứ không
phải "trang ít chữ". Trang ký tên hay trang bìa vốn chỉ có vài dòng nhưng vẫn
là text layer hoàn chỉnh; lấy số ký tự làm ngưỡng sẽ từ chối oan các trang đó.
"""

from __future__ import annotations

import pdfplumber

from .models import PdfClass

# Tỉ lệ diện tích trang bị ảnh che phủ để coi trang đó là ảnh scan.
SCAN_IMAGE_COVERAGE_RATIO = 0.5

# Số ký tự tối thiểu để coi một trang đã có nội dung text.
# Chỉ dùng khi trang CÓ ảnh che phủ lớn, nhằm phân biệt scan thuần với
# scan đã chạy OCR nhúng text.
MIN_CHARS_ON_IMAGE_PAGE = 20


def classify_pdf(pdf_path: str) -> tuple[PdfClass, dict[str, int]]:
    """Phân loại PDF dựa trên tương quan giữa text và ảnh che phủ từng trang.

    Trả về loại PDF kèm bản đồ {số trang: số ký tự} để đưa vào báo cáo.
    MIXED bị coi là không xử lý được: file trộn text và scan cần con người
    quyết định, không nên để pipeline tự đoán.
    """
    chars_per_page: dict[int, int] = {}
    scan_like_pages: list[int] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            chars_per_page[page_number] = len(page.chars)

            if _is_scan_like(page):
                scan_like_pages.append(page_number)

    total_pages = len(chars_per_page)

    if not scan_like_pages:
        pdf_class = PdfClass.TEXT_LAYER
    elif len(scan_like_pages) == total_pages:
        pdf_class = PdfClass.SCANNED
    else:
        pdf_class = PdfClass.MIXED

    return pdf_class, {str(k): v for k, v in chars_per_page.items()}


def _is_scan_like(page) -> bool:
    """Trang bị coi là scan khi ảnh che phần lớn diện tích mà text gần như không có."""
    if not page.images:
        return False

    page_area = float(page.width) * float(page.height)
    if page_area <= 0:
        return False

    image_area = sum(
        max(0.0, float(img["x1"]) - float(img["x0"]))
        * max(0.0, float(img["bottom"]) - float(img["top"]))
        for img in page.images
    )

    covered = image_area / page_area >= SCAN_IMAGE_COVERAGE_RATIO
    return covered and len(page.chars) < MIN_CHARS_ON_IMAGE_PAGE


def rejection_reason(pdf_class: PdfClass, chars_per_page: dict[str, int]) -> str | None:
    """Thông báo từ chối dễ hiểu, nêu rõ trang nào là ảnh."""
    if pdf_class is PdfClass.TEXT_LAYER:
        return None

    if pdf_class is PdfClass.SCANNED:
        return (
            "PDF không có text layer (bản scan/ảnh). Pipeline này chỉ xử lý PDF "
            "có text nhúng để bảo đảm trích xuất chính xác 100%. File scan cần "
            "đi qua OCR riêng và không đạt được mức chính xác đó."
        )

    image_pages = [p for p, n in chars_per_page.items() if n < MIN_CHARS_ON_IMAGE_PAGE]
    return (
        f"PDF trộn text và ảnh: các trang {', '.join(image_pages) or '(xem báo cáo)'} "
        "là ảnh scan. Cần con người xác nhận trước khi xử lý."
    )
