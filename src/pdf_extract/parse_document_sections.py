"""Chia tài liệu thành phần mở đầu, các mục lớn, và khối chữ ký.

Tầng này KHÔNG biết gì về nghiệp vụ chứng thư: nó chỉ đọc cấu trúc mà tài liệu
tự khai bằng số La Mã và gạch đầu dòng. Nhờ vậy nó nhặt được MỌI dòng, kể cả
nhãn mà chưa ai đặt tên tiếng Anh cho — tầng template phía sau mới gán tên.

Đây là điểm khác cốt lõi so với cách làm cũ: trước đây template đi tìm một danh
sách nhãn định trước, nên mọi thứ ngoài danh sách bị bỏ im lặng. Giờ cấu trúc
được đọc trước, đầy đủ; việc đặt tên là bước riêng và không làm mất dữ liệu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .extract_text_with_coordinates import TextLine
from .models import BoundingBox, SourcedValue
from .classify_block_lines import LineBlock, classify_lines, classify_single_column
from .parse_labeled_lines import (
    column_groups_of,
    is_bare_bullet,
    is_section_heading,
    sourced_line,
)
from .sourced_value_builders import sourced_value_of

# Dòng chân trang, nhận ra để không lẫn vào nội dung mục.
PAGE_FOOTER_PREFIX = "trang"

# Bảng từ bao nhiêu cột trở lên thì coi là BẢNG DỮ LIỆU và giao cho tầng dựng
# bảng xử lý. Bảng hai cột chỉ là cách căn lề cho cặp nhãn-giá trị, đọc theo
# dòng vẫn đúng nên giữ lại cho parser cấu trúc.
DATA_TABLE_MIN_COLUMNS = 3

# Khối chữ ký thụt vào ít nhất bao nhiêu lần cỡ chữ so với lề trái của thân bài.
# Khối này luôn căn giữa/căn phải theo cột người ký, khác hẳn thân bài căn lề
# trái — đây là dấu hiệu tách được nó mà không phụ thuộc số trang.
SIGNATURE_INDENT_RATIO = 2.0


@dataclass
class DocumentSection:
    """Một mục lớn của tài liệu, ví dụ "I. THÔNG TIN KHÁCH HÀNG"."""

    number: str
    title: SourcedValue
    inline_value: SourcedValue | None = None
    block: LineBlock = field(default_factory=LineBlock)


@dataclass
class ParsedDocument:
    """Toàn bộ tài liệu sau khi đọc cấu trúc."""

    preface_columns: list[list[SourcedValue]] = field(default_factory=list)
    preface: LineBlock = field(default_factory=LineBlock)
    sections: list[DocumentSection] = field(default_factory=list)
    signature_columns: list[list[SourcedValue]] = field(default_factory=list)
    page_footers: list[SourcedValue] = field(default_factory=list)


def parse_document(
    lines: list[TextLine],
    data_table_regions: list[tuple[int, BoundingBox]] | None = None,
) -> ParsedDocument:
    """Đọc cấu trúc tài liệu từ danh sách dòng đã gom.

    `data_table_regions` là các vùng bảng dữ liệu, mỗi vùng gồm SỐ TRANG và
    bbox. Dòng nằm trong đó bị loại khỏi parser cấu trúc vì đã được tầng dựng
    bảng xử lý theo biên ô — để lẫn vào đây thì các ô bảng dính thành một chuỗi
    dài vô nghĩa. Phải truyền vùng CHƯA GHÉP QUA TRANG: bảng đã ghép chỉ giữ
    bbox của trang đầu nên phần thân ở trang sau sẽ không bị loại.
    """
    document = ParsedDocument()
    body_lines = _keep_content_lines(document, lines, data_table_regions or [])

    first_section = next(
        (i for i, line in enumerate(body_lines) if is_section_heading(line)), len(body_lines)
    )

    section_lines, signature_lines = _split_signature_block(body_lines[first_section:])

    _parse_preface(document, body_lines[:first_section])
    _parse_sections(document, section_lines)
    document.signature_columns = [_columns_to_values(line) for line in signature_lines]

    return document


def _keep_content_lines(
    document: ParsedDocument,
    lines: list[TextLine],
    table_regions: list[tuple[int, BoundingBox]],
) -> list[TextLine]:
    """Bỏ chân trang, bullet trang trí và dòng nằm trong bảng dữ liệu."""
    kept: list[TextLine] = []

    for line in lines:
        if is_bare_bullet(line):
            # Bullet vẽ bằng font ký hiệu riêng nên bị tách thành dòng riêng.
            # Là ký hiệu trang trí, không mang dữ liệu.
            continue

        if line.text.strip().lower().startswith(PAGE_FOOTER_PREFIX):
            value = sourced_line(line)
            if value is not None:
                document.page_footers.append(value)
            continue

        if any(_line_inside(line, page, box) for page, box in table_regions):
            continue

        kept.append(line)

    return kept


def _line_inside(line: TextLine, page: int, box: BoundingBox) -> bool:
    """Dòng thuộc cùng trang, tâm dọc nằm trong vùng bảng, và chồng ngang."""
    if line.page != page:
        return False

    center = (line.top + line.bottom) / 2
    return box.top <= center <= box.bottom and line.x1 >= box.x0 and line.x0 <= box.x1


def _split_signature_block(lines: list[TextLine]) -> tuple[list[TextLine], list[TextLine]]:
    """Tách phần thân mục và khối chữ ký ở cuối tài liệu.

    Dò từ DÒNG CUỐI ngược lên, lấy vào khối chữ ký các dòng vừa có NHIỀU CỘT
    vừa THỤT XA lề trái của thân bài; gặp dòng đầu tiên không thoả thì dừng.

    Không tách theo số trang vì khối chữ ký có thể vắt qua hai trang — vai trò
    và số thẻ ở trang trước, họ tên ở trang sau. Tách theo trang sẽ để lại phần
    trên trong mục cuối và làm hỏng cả hai.
    """
    if not lines:
        return [], []

    left_margin = min(
        (line.x0 for line in lines if is_section_heading(line)),
        default=min(line.x0 for line in lines),
    )

    boundary = len(lines)
    while boundary > 0:
        line = lines[boundary - 1]
        indent = line.x0 - left_margin

        if indent < line.font_size * SIGNATURE_INDENT_RATIO:
            break
        if len(column_groups_of(line)) < 2:
            break

        boundary -= 1

    return lines[:boundary], lines[boundary:]


def _columns_to_values(line: TextLine) -> list[SourcedValue]:
    """Từng cột của một dòng vật lý thành một giá trị riêng.

    Cần cho dòng tiêu đề thư (đơn vị bên trái, quốc hiệu bên phải) và khối chữ
    ký (hai người cạnh nhau) — gộp lại thì hai nội dung dính thành chuỗi vô nghĩa.
    """
    values: list[SourcedValue] = []

    for group in column_groups_of(line):
        value = sourced_value_of(group, line.page)
        if value is not None:
            values.append(value)

    return values


def _parse_preface(document: ParsedDocument, lines: list[TextLine]) -> None:
    """Phần mở đầu: dòng nhiều cột phân loại THEO TỪNG CỘT.

    Dòng đầu chứng thư có tên đơn vị bên trái và quốc hiệu bên phải, dòng sau
    có "Số HĐ: ..." bên trái và "Độc lập – Tự do – Hạnh phúc" bên phải. Xét cả
    dòng thì hai nội dung dính nhau; xét theo cột thì "Số HĐ" thành cặp
    nhãn-giá trị đúng nghĩa còn quốc hiệu thành đoạn riêng.

    Dòng một cột đi qua bộ phân loại thường để giữ được phần nối tiếp của các
    dòng "Căn cứ" dài.
    """
    single_column: list[TextLine] = []

    for line in lines:
        groups = column_groups_of(line)
        if len(groups) == 1:
            single_column.append(line)
            continue

        for group in groups:
            classify_single_column(document.preface, group, line.page)

    merged = classify_lines(single_column)
    document.preface.fields.extend(merged.fields)
    document.preface.paragraphs.extend(merged.paragraphs)
    document.preface.items.extend(merged.items)



def _parse_sections(document: ParsedDocument, lines: list[TextLine]) -> None:
    """Duyệt các mục La Mã, mỗi mục lấy phần thân tới trước tiêu đề kế tiếp."""
    starts = [i for i, line in enumerate(lines) if is_section_heading(line)]

    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        document.sections.append(_build_section(lines[start], lines[start + 1:end]))


def _build_section(heading_line: TextLine, body: list[TextLine]) -> DocumentSection:
    """Dựng một mục từ dòng tiêu đề và các dòng thân."""
    match = is_section_heading(heading_line)
    number, remainder = match.group(1), match.group(2)
    title_text, _, inline_text = remainder.partition(":")

    section = DocumentSection(
        number=number,
        title=sourced_value_of(heading_line.chars, heading_line.page, text=title_text)
        or SourcedValue(value=title_text.strip(), page=heading_line.page),
    )

    # Tiêu đề mang giá trị ngay sau dấu hai chấm: các dòng văn xuôi tiếp theo là
    # phần nối tiếp của giá trị đó, không phải đoạn độc lập.
    if inline_text.strip():
        block = classify_lines(body, inline_start=inline_text)
        section.inline_value = block.paragraphs.pop(0) if block.paragraphs else None
        section.block = block
    else:
        section.block = classify_lines(body)

    return section






