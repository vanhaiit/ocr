"""Đọc cấu trúc mục từ nội dung DOCX, cho ra cùng kiểu `ParsedDocument`.

Cùng nhiệm vụ với `parse_document_sections` nhưng dựa vào tín hiệu khác, vì hai
định dạng cho hai loại dữ liệu khác nhau:

| Câu hỏi | PDF | DOCX |
|---|---|---|
| Đâu là một dòng logic? | tự gom glyph theo cao độ | `<w:p>` đã là đoạn HOÀN CHỈNH |
| Dòng sau có nối tiếp dòng trước? | xét khoảng trống dọc | không cần — đoạn đã đủ |
| Hai cột cạnh nhau? | xét khoảng trống ngang | ô bảng, hoặc tab trong đoạn |
| Biên bảng ở đâu? | dò đường kẻ ô | `<w:tbl>` đã có sẵn |

Vì trả về cùng `ParsedDocument`, toàn bộ tầng đặt tên tiếng Anh và cổng nguồn
gốc dùng lại nguyên vẹn — hai định dạng cho ra JSON cùng một hình dạng.
"""

from __future__ import annotations

from .classify_block_lines import LineBlock
from .extract_docx_content import DocxContent, DocxTable, UNPAGINATED
from .models import SourcedValue
from .parse_document_sections import DocumentSection, ParsedDocument
from .parse_labeled_lines import (
    BULLET_MARKERS,
    LABEL_SEPARATOR,
    LabeledField,
    SECTION_HEADING_PATTERN,
)
from .templates.chung_thu_field_names import comparable_label

# Số cột tối thiểu để coi một bảng là BẢNG DỮ LIỆU (giao cho template xử lý).
DATA_TABLE_MIN_COLUMNS = 3

# Số từ tối đa của phần trước dấu hai chấm để coi đoạn đó là cặp nhãn-giá trị.
MAX_LABEL_WORDS = 8


def parse_docx_document(content: DocxContent) -> tuple[ParsedDocument, list[DocxTable]]:
    """Chia tài liệu thành phần mở đầu, các mục, khối chữ ký; trả kèm bảng dữ liệu."""
    document = ParsedDocument()
    document.page_footers = list(content.footers)

    signature_table = _find_signature_table(content)
    data_tables = [
        table
        for table in content.tables
        if table is not signature_table and table.shape[1] >= DATA_TABLE_MIN_COLUMNS
    ]

    if signature_table is not None:
        document.signature_columns = _signature_columns(signature_table)

    _fill_sections(document, content, signature_table)

    return document, data_tables


def _find_signature_table(content: DocxContent) -> DocxTable | None:
    """Bảng chữ ký: bảng CUỐI có nhiều cột mà không cột nào là số thứ tự.

    Bảng dữ liệu luôn có cột số thứ tự chạy 1, 2, 3...; khối chữ ký thì mỗi cột
    là một người. Đây là dấu hiệu tách được hai loại mà không cần biết nội dung
    nghiệp vụ.
    """
    for table in reversed(content.tables):
        if table.shape[1] < 2:
            continue

        first_column = [row[0].value.strip() for row in table.rows if row]
        if any(cell.isdigit() for cell in first_column):
            continue

        return table

    return None


def _signature_columns(table: DocxTable) -> list[list[SourcedValue]]:
    """Từng dòng của khối chữ ký, tách theo cột — mỗi cột là một người.

    Ô của Word chứa nhiều đoạn (vai trò, số thẻ, "(Ký tên)", họ tên) nên phải
    tách theo dòng bên trong ô, rồi xếp lại thành từng hàng ngang.
    """
    columns = [
        [line for line in cell.value.splitlines() if line.strip()]
        for row in table.rows[:1]
        for cell in row
    ]

    if not columns:
        return []

    rows: list[list[SourcedValue]] = []

    for index in range(max(len(column) for column in columns)):
        row: list[SourcedValue] = []

        for position, column in enumerate(columns):
            if index >= len(column):
                continue
            row.append(
                SourcedValue(
                    value=column[index].strip(),
                    page=UNPAGINATED,
                    location=f"{table.location}/tr[1]/tc[{position + 1}]/p[{index + 1}]",
                )
            )

        if row:
            rows.append(row)

    return rows


def _fill_sections(
    document: ParsedDocument, content: DocxContent, signature_table: DocxTable | None
) -> None:
    """Duyệt thân tài liệu, mở mục mới khi gặp tiêu đề số La Mã."""
    current: DocumentSection | None = None

    for kind, index in content.order:
        if kind == "table":
            # Bảng đã được template xử lý riêng; không đưa vào khối văn bản.
            continue

        paragraph = content.paragraphs[index]
        heading = SECTION_HEADING_PATTERN.match(paragraph.text.strip())

        if heading is not None:
            current = _open_section(paragraph, heading)
            document.sections.append(current)
            continue

        block = current.block if current is not None else document.preface
        _classify_paragraph(block, paragraph)


def _open_section(paragraph, heading) -> DocumentSection:
    """Mở một mục mới từ đoạn tiêu đề; giá trị sau dấu hai chấm là `inline_value`."""
    number, remainder = heading.group(1), heading.group(2)
    title, _, inline = remainder.partition(LABEL_SEPARATOR)

    section = DocumentSection(
        number=number,
        title=SourcedValue(
            value=title.strip(), page=UNPAGINATED, location=paragraph.location
        ),
    )

    if inline.strip():
        section.inline_value = SourcedValue(
            value=" ".join(inline.split()),
            page=UNPAGINATED,
            location=paragraph.location,
        )

    return section


def _classify_paragraph(block: LineBlock, paragraph) -> None:
    """Một đoạn là cặp nhãn-giá trị, mục liệt kê, hay đoạn văn.

    Không cần xử lý nối tiếp như bên PDF: một `<w:p>` đã là đơn vị hoàn chỉnh,
    Word chỉ ngắt dòng khi hiển thị.
    """
    text = paragraph.text.strip()
    marker = text[0] if text and text[0] in BULLET_MARKERS else ""
    body = text[1:].strip() if marker else text

    label, separator, value = body.partition(LABEL_SEPARATOR)

    # Nhãn DÀI chỉ được nhận khi ở đầu khối VÀ có giá trị đứng sau dấu hai chấm.
    #
    # Hai ca dễ lẫn, phân biệt đúng bằng điều kiện "có giá trị":
    #   XI: "Thời hạn hiệu lực ... phát hành là: 06 tháng"  -> nhãn dài + có giá trị
    #    X: "Trên cơ sở các hồ sơ ... như sau:"             -> câu văn xuôi, không giá trị
    #
    # Bên PDF ca thứ hai không xảy ra vì câu đó bị ngắt thành bốn dòng nên dấu
    # hai chấm không nằm ở dòng đầu. DOCX thì mỗi `<w:p>` là cả đoạn, nên phải
    # có điều kiện này.
    block_is_empty = not (block.fields or block.paragraphs or block.items)
    allow_long = block_is_empty and bool(value.strip())

    if separator and _looks_like_label(label, allow_long=allow_long):
        block.fields.append(
            LabeledField(
                label=SourcedValue(
                    value=label.strip(), page=UNPAGINATED, location=paragraph.location
                ),
                value=(
                    SourcedValue(
                        value=" ".join(value.split()),
                        page=UNPAGINATED,
                        location=paragraph.location,
                    )
                    if value.strip()
                    else None
                ),
            )
        )
        return

    target = block.items if (marker or paragraph.list_level is not None) else block.paragraphs
    target.append(
        SourcedValue(value=body, page=UNPAGINATED, location=paragraph.location)
    )


def _looks_like_label(label: str, allow_long: bool = False) -> bool:
    """Phần trước dấu hai chấm có giống một nhãn hay không.

    Cùng quy tắc như bên PDF: bắt đầu bằng chữ hoa hoặc chữ số là điều kiện bắt
    buộc; giới hạn độ dài chỉ áp dụng khi khối đã có nội dung phía trước.
    """
    stripped = label.strip()
    if not stripped:
        return False
    if not allow_long and len(stripped.split()) > MAX_LABEL_WORDS:
        return False

    return stripped[0].isupper() or stripped[0].isdigit()


def canonical_label(label: str) -> str:
    """Bí danh cho tầng template, giữ một chỗ nhập duy nhất cho phép chuẩn hoá."""
    return comparable_label(label)
