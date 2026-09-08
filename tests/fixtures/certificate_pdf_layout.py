"""Bố cục chứng thư: các mục I..XI và hai bảng có đường kẻ ô.

Tách khỏi `certificate_pdf_builder` vì đây là phần NỘI DUNG (vẽ cái gì, ở đâu),
còn builder là phần KỸ THUẬT VẼ (in đậm, đổ bóng, chế độ tô). Hai việc thay đổi
vì lý do khác nhau nên tách ra. Phần kẻ bảng nằm ở `certificate_table_layout`.
"""

from __future__ import annotations

from reportlab.lib.colors import blue, grey

from .certificate_expected_values import (
    EXPECTED,
    EXPECTED_ASSET_ROWS,
    EXPECTED_FORM_FIELDS,
    INVISIBLE_LAYER_TEXT,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PORTAL_TEXT,
    PORTAL_URL,
    WATERMARK_TEXT,
)
from .certificate_pdf_builder import (
    BODY_SIZE,
    LABEL_X,
    RENDER_INVISIBLE,
    VALUE_X,
    CertificatePdfBuilder,
)
from .certificate_table_layout import Cell, draw_ruled_table

# Bảng thông tin công ty (mục II): 2 cột.
COMPANY_TABLE_X = (LABEL_X, VALUE_X, 545.0)

# Bảng giá trị tài sản (mục X): 4 cột STT | Tên tài sản | Diện tích | Thành tiền.
# Bề rộng chọn theo chuỗi dài nhất của từng cột; bộ kẻ bảng tự kiểm nên sai sẽ
# raise chứ không âm thầm vẽ đè.
ASSET_TABLE_X = (LABEL_X, 108.0, 330.0, 425.0, 545.0)

# Thụt lề dòng nối tiếp của các mục dài, giống chứng thư thật.
CONTINUATION_INDENT = 13.0


def draw_certificate(builder: CertificatePdfBuilder) -> None:
    """Vẽ toàn bộ chứng thư theo cờ tính năng của builder."""
    flags = builder.flags

    if flags.watermark:
        _draw_watermark(builder)

    if flags.invisible_layer:
        _draw_invisible_layer(builder)

    _draw_header(builder)
    _draw_customer_section(builder)
    _draw_company_section(builder)
    _draw_asset_section(builder)
    _draw_valuation_section(builder)
    _draw_asset_table(builder)
    _draw_validity_section(builder)

    if flags.hyperlink:
        _draw_hyperlink(builder)

    if flags.form_fields:
        _draw_form_fields(builder)


def _draw_header(builder: CertificatePdfBuilder) -> None:
    builder.draw_text(LABEL_X, f"Số HĐ: {EXPECTED['contract_number']}")
    builder.newline()
    builder.draw_text(LABEL_X, f"Số CTPH: {EXPECTED['certificate_number']}")
    builder.newline()
    builder.draw_text(360.0, EXPECTED["issue_place_and_date"])
    builder.newline(2)
    builder.draw_text(170.0, "CHỨNG THƯ THẨM ĐỊNH GIÁ", emphasis="bold", size=15.0)
    builder.newline(2)


def _draw_customer_section(builder: CertificatePdfBuilder) -> None:
    builder.draw_text(LABEL_X, "I. THÔNG TIN KHÁCH HÀNG", emphasis="bold")
    builder.newline()
    builder.label_value("- Tên khách hàng", EXPECTED["customer_name"], value_emphasis="bold")
    builder.label_value("- Địa chỉ", EXPECTED["customer_address"])
    builder.label_value("- CCCD/MST", EXPECTED["customer_id"])


def _draw_company_section(builder: CertificatePdfBuilder) -> None:
    builder.draw_text(
        LABEL_X, "II. THÔNG TIN VỀ CÔNG TY THỰC HIỆN THẨM ĐỊNH GIÁ", emphasis="bold"
    )
    builder.newline()

    rows = [
        [Cell("- Đơn vị thực hiện:"), Cell(EXPECTED["company_branch"])],
        [Cell("- Địa chỉ:"), Cell(EXPECTED["company_address"])],
        [Cell("- Mã số thuế:"), Cell(EXPECTED["company_tax_id"])],
        [Cell("- Đại diện:"), Cell(EXPECTED["company_representative"])],
    ]
    draw_ruled_table(builder, COMPANY_TABLE_X, rows)


def _draw_asset_section(builder: CertificatePdfBuilder) -> None:
    builder.draw_text(LABEL_X, "III. THÔNG TIN VỀ TÀI SẢN THẨM ĐỊNH GIÁ", emphasis="bold")
    builder.newline()
    builder.label_value("- Loại hình tài sản", EXPECTED["asset_type"], value_emphasis="italic")
    builder.label_value("- Tài sản thẩm định", EXPECTED["asset_under_valuation"])


def _draw_valuation_section(builder: CertificatePdfBuilder) -> None:
    builder.draw_text(LABEL_X, f"IV. THỜI ĐIỂM THẨM ĐỊNH GIÁ: {EXPECTED['valuation_date']}")
    builder.newline()
    builder.draw_wrapped(
        LABEL_X,
        f"V. MỤC ĐÍCH THẨM ĐỊNH GIÁ: {EXPECTED['purpose']}",
        continuation_x=LABEL_X + CONTINUATION_INDENT,
    )
    builder.newline()
    builder.draw_text(LABEL_X, "X. GIÁ TRỊ TÀI SẢN THẨM ĐỊNH GIÁ:", emphasis="bold")
    builder.newline()


def _draw_asset_table(builder: CertificatePdfBuilder) -> None:
    """Bảng mục X.

    Các dòng tổng GỘP Ô đúng như chứng thư thật: nhãn chiếm hai cột đầu, giá trị
    chiếm hai cột cuối. Không gộp thì nhãn "Tổng cộng (đồng)" tràn khỏi cột STT
    và đè lên giá trị — lỗi của bản fixture đầu tiên.
    """
    area_header = (
        Cell("Diện tích (m2)", superscript=("Diện tích (m", "2", ")"))
        if builder.flags.superscript
        else Cell("Diện tích (m2)")
    )

    header = [Cell("STT"), Cell("Tên tài sản"), area_header, Cell("Thành tiền (đồng)")]

    body = [
        [
            Cell(str(row["index"])),
            Cell(row["description"]),
            Cell(row["area_sqm"]),
            Cell(row["amount_vnd"]),
        ]
        for row in EXPECTED_ASSET_ROWS
    ]

    totals = [
        [Cell("Tổng cộng (đồng)", colspan=2), Cell(EXPECTED["total"], colspan=2)],
        [Cell("Làm tròn (đồng)", colspan=2), Cell(EXPECTED["total_rounded"], colspan=2)],
        [Cell(f"Bằng chữ: {EXPECTED['total_in_words']}", colspan=4)],
    ]

    draw_ruled_table(
        builder,
        ASSET_TABLE_X,
        [header] + body + totals,
        rotate_header=builder.flags.rotated_header,
    )


def _draw_validity_section(builder: CertificatePdfBuilder) -> None:
    builder.newline()
    builder.draw_wrapped(
        LABEL_X,
        "XI. Thời hạn hiệu lực của kết quả thẩm định giá trong Chứng thư "
        f"tính từ ngày phát hành là: {EXPECTED['validity']}",
        continuation_x=LABEL_X + CONTINUATION_INDENT,
    )


def _draw_hyperlink(builder: CertificatePdfBuilder) -> None:
    """Chữ hiển thị kèm annotation /Link chứa URL.

    URL sống trong annotation, không nằm trong content stream — nên chỉ đọc text
    là mất phần dữ liệu này.
    """
    builder.newline()
    x, y = LABEL_X, builder.y
    builder.draw_text(x, PORTAL_TEXT, color=blue)
    width = builder.canvas.stringWidth(PORTAL_TEXT, "Times", BODY_SIZE)
    builder.canvas.linkURL(
        PORTAL_URL, (x, y - 2.0, x + width, y + BODY_SIZE), relative=0, thickness=0
    )
    builder.newline()


def _draw_form_fields(builder: CertificatePdfBuilder) -> None:
    """Ô điền thông tin tương tác (AcroForm).

    Giá trị nằm trong `/V` của widget annotation, KHÔNG nằm trong content stream
    của trang. Đây là ca duy nhất trong bộ này mà đọc text thuần sẽ mất trắng
    giá trị.
    """
    form = builder.canvas.acroForm
    builder.newline()
    y = builder.y

    for index, (name, value) in enumerate(EXPECTED_FORM_FIELDS.items()):
        field_y = y - index * 26.0
        builder.draw_text(LABEL_X, f"- {name}:", y=field_y + 4.0)
        form.textfield(
            name=name,
            value=value,
            x=VALUE_X,
            y=field_y,
            width=200.0,
            height=16.0,
            # AcroForm chỉ nhận font standard-14. Không sao: giá trị form nằm
            # trong `/V` dạng chuỗi PDF, font chỉ ảnh hưởng phần hiển thị.
            fontName="Times-Roman",
            fontSize=BODY_SIZE,
            borderWidth=0.5,
        )

    builder.y = y - len(EXPECTED_FORM_FIELDS) * 26.0


def _draw_invisible_layer(builder: CertificatePdfBuilder) -> None:
    """Chữ ẩn (chế độ tô 3) — giống lớp text mà OCR nhúng vào bản scan.

    Không hiện trên màn hình nhưng engine trích xuất vẫn đọc được, nên có thể
    lẫn vào dữ liệu nghiệp vụ. Đặt ở lề trên, ngoài vùng nội dung.
    """
    builder.draw_text(
        LABEL_X, INVISIBLE_LAYER_TEXT, y=PAGE_HEIGHT - 30.0, render_mode=RENDER_INVISIBLE
    )


def _draw_watermark(builder: CertificatePdfBuilder) -> None:
    """Watermark chéo trang, cỡ chữ lớn — dễ kéo lệch ngưỡng theo cỡ chữ."""
    canvas = builder.canvas
    canvas.saveState()
    canvas.translate(PAGE_WIDTH / 2.0, PAGE_HEIGHT / 2.0)
    canvas.rotate(45)
    builder.draw_text(-120.0, WATERMARK_TEXT, y=0.0, size=60.0, color=grey)
    canvas.restoreState()
