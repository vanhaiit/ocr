"""Trích dữ liệu nằm trong annotation: form field tương tác và hyperlink.

Vì sao cần tầng riêng: hai loại dữ liệu này KHÔNG nằm trong content stream của
trang, nên mọi bộ trích xuất text đều bỏ qua.

  - **Form field (AcroForm)**: giá trị người dùng điền sống trong `/V` của
    widget annotation. Đọc text thuần là mất trắng.
  - **Hyperlink**: phần chữ hiển thị thì có trong content stream, nhưng URL nằm
    trong `/A /URI` của annotation `/Link`. Bỏ qua là mất phần dữ liệu đó —
    với chứng thư, URL tra cứu trực tuyến là thông tin nghiệp vụ thật.

Các engine đối chứng xử lý phần này khác nhau: Poppler đọc được giá trị form
field (qua appearance stream), pypdf thì không. Vì vậy pipeline phải khai báo
tường minh một mốc đối chiếu "đã gồm form field" để cổng đối chứng không báo
lệch oan — xem `cross_verify_engines`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pypdf

from .extract_text_with_coordinates import normalize
from .models import BoundingBox, SourcedValue

# Loại annotation.
WIDGET_SUBTYPE = "/Widget"
LINK_SUBTYPE = "/Link"

# Loại form field: chỉ lấy field văn bản; nút bấm và chữ ký không mang giá trị text.
TEXT_FIELD_TYPE = "/Tx"


@dataclass
class FormField:
    """Một ô điền thông tin cùng giá trị đang giữ."""

    name: str
    value: SourcedValue


@dataclass
class Hyperlink:
    """Một liên kết: URL cùng vùng toạ độ nó phủ lên."""

    url: str
    page: int
    bbox: BoundingBox | None


def _bbox_from_rect(rect) -> BoundingBox | None:
    """Chuyển `/Rect` của annotation (gốc dưới-trái) sang bbox gốc trên-trái.

    Annotation dùng hệ toạ độ PDF gốc ở góc dưới-trái, còn toàn pipeline dùng
    gốc trên-trái theo pdfplumber. Phải đổi để bbox so được với nhau.
    """
    if rect is None or len(rect) != 4:
        return None

    x0, y0, x1, y1 = (float(v) for v in rect)
    return BoundingBox(x0=min(x0, x1), top=min(y0, y1), x1=max(x0, x1), bottom=max(y0, y1))


def extract_form_fields(pdf_path: str) -> list[FormField]:
    """Đọc giá trị mọi field văn bản trong AcroForm, kèm trang và toạ độ."""
    reader = pypdf.PdfReader(pdf_path)
    fields: list[FormField] = []

    for page_number, page in enumerate(reader.pages, start=1):
        for annotation_ref in page.get("/Annots") or []:
            annotation = annotation_ref.get_object()

            if str(annotation.get("/Subtype")) != WIDGET_SUBTYPE:
                continue
            if str(annotation.get("/FT")) != TEXT_FIELD_TYPE:
                continue

            raw_value = annotation.get("/V")
            if raw_value is None:
                continue

            value = normalize(str(raw_value)).strip()
            if not value:
                continue

            fields.append(
                FormField(
                    name=str(annotation.get("/T", "")),
                    value=SourcedValue(
                        value=value,
                        page=page_number,
                        bbox=_bbox_from_rect(annotation.get("/Rect")),
                    ),
                )
            )

    return fields


def extract_hyperlinks(pdf_path: str) -> list[Hyperlink]:
    """Đọc URL của mọi annotation /Link, kèm trang và vùng toạ độ."""
    reader = pypdf.PdfReader(pdf_path)
    links: list[Hyperlink] = []

    for page_number, page in enumerate(reader.pages, start=1):
        for annotation_ref in page.get("/Annots") or []:
            annotation = annotation_ref.get_object()

            if str(annotation.get("/Subtype")) != LINK_SUBTYPE:
                continue

            action = annotation.get("/A")
            if action is None:
                continue

            uri = action.get_object().get("/URI")
            if uri is None:
                continue

            links.append(
                Hyperlink(
                    url=str(uri),
                    page=page_number,
                    bbox=_bbox_from_rect(annotation.get("/Rect")),
                )
            )

    return links
