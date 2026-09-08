"""Nhận dạng dòng "nhãn : giá trị" và ghép các dòng nối tiếp cho đúng phần.

Điểm khó nằm ở chỗ nối tiếp: một dòng không có gạch đầu dòng có thể là phần
tiếp của NHÃN, cũng có thể là phần tiếp của GIÁ TRỊ. Chứng thư có cả hai:

    - Hồ sơ pháp lý khách      : Chi tiết có nêu tại báo cáo...
      hàng cung cấp                                              <- tiếp NHÃN

    - Tài sản thẩm định        : Giá trị Quyền sử dụng đất, ...
                                 với đất thuộc LAND-LOT-GROUP-001  <- tiếp GIÁ TRỊ

Phân biệt bằng TOẠ ĐỘ: dòng nối tiếp bắt đầu gần cột nhãn thì thuộc nhãn, gần
cột giá trị thì thuộc giá trị. Đây là dữ liệu có sẵn trong PDF, không phải suy
đoán theo ngữ nghĩa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extract_text_with_coordinates import (
    COLUMN_GAP_RATIO,
    PositionedChar,
    TextLine,
    segment_text,
)
from .models import SourcedValue
from .sourced_value_builders import bbox_of, sourced_value_of

# Ký tự mở đầu một mục con. `●` là bullet trang trí của font ký hiệu.
BULLET_MARKERS = ("-", "–", "+", "●", "•", "*")

# Dấu phân cách nhãn với giá trị.
LABEL_SEPARATOR = ":"

# Số ký tự space liền nhau để coi là NGẮT CỘT.
#
# Trình sinh PDF có hai cách tạo khoảng cách giữa hai cột: đặt toạ độ cách nhau
# (khoảng trống hình học), hoặc vẽ một chuỗi space thật. Chứng thư dùng cách thứ
# hai ở dòng "Đại diện", nên chỉ xét khoảng trống hình học sẽ không thấy ranh
# giới cột và hai cặp nhãn-giá trị bị gộp thành một.
#
# Văn xuôi bình thường không có 3 space liền nhau, nên ngưỡng này an toàn.
MIN_SPACES_AS_COLUMN_BREAK = 3

# Dòng mở đầu một mục lớn: số La Mã kèm dấu chấm. Cho phép thiếu khoảng trắng
# sau dấu chấm vì tài liệu có cả "II.THÔNG TIN..." lẫn "I. THÔNG TIN...".
SECTION_HEADING_PATTERN = re.compile(r"^\s*([IVXLCDM]{1,7})\s*\.\s*(.+)$")


@dataclass
class LabeledField:
    """Một cặp nhãn - giá trị, mỗi bên giữ nguyên bằng chứng nguồn gốc."""

    label: SourcedValue
    value: SourcedValue | None


def is_section_heading(line: TextLine) -> re.Match[str] | None:
    """Khớp dòng tiêu đề mục, trả về match để lấy số La Mã và tiêu đề."""
    return SECTION_HEADING_PATTERN.match(line.text.strip())


def starts_with_bullet(line: TextLine) -> bool:
    """Dòng có mở đầu bằng ký tự gạch đầu dòng hay không."""
    stripped = line.text.strip()
    return bool(stripped) and stripped[0] in BULLET_MARKERS


def is_bare_bullet(line: TextLine) -> bool:
    """Dòng chỉ chứa đúng một ký tự bullet, không có nội dung.

    Xuất hiện khi bullet được vẽ bằng font ký hiệu riêng nên cỡ chữ lệch và bị
    tách thành dòng riêng. Nó là ký hiệu trang trí, không mang dữ liệu.
    """
    return line.text.strip() in BULLET_MARKERS


def split_label_and_value(
    line: TextLine,
) -> tuple[list[PositionedChar], list[PositionedChar]] | None:
    """Tách dòng thành (ký tự nhãn, ký tự giá trị) tại dấu hai chấm đầu tiên.

    Trả None nếu dòng không có dấu phân cách — khi đó dòng là mục liệt kê hoặc
    văn xuôi, không phải cặp nhãn-giá trị.
    """
    for index, char in enumerate(line.chars):
        if char.text == LABEL_SEPARATOR:
            return line.chars[:index], line.chars[index + 1:]

    return None


def label_column_x(chars: list[PositionedChar]) -> float:
    """Toạ độ x bắt đầu của phần nhãn, dùng làm mốc so cho dòng nối tiếp."""
    return min((c.x0 for c in chars if c.text.strip()), default=0.0)


def continuation_belongs_to_label(
    line: TextLine, label_x: float, value_x: float
) -> bool:
    """Dòng nối tiếp thuộc nhãn hay giá trị, xét theo khoảng cách cột.

    So khoảng cách tuyệt đối tới hai mốc cột thay vì dùng một ngưỡng cố định,
    nên không phải chỉnh khi tài liệu đổi bề rộng cột.
    """
    start = line.x0
    return abs(start - label_x) <= abs(start - value_x)


def build_fields(
    label_groups: list[list[PositionedChar]],
    value_groups: list[list[PositionedChar]],
    page: int,
) -> list[LabeledField]:
    """Dựng các LabeledField từ một dòng "nhãn : giá trị".

    Trả về DANH SÁCH vì phần giá trị có thể còn chứa thêm cặp nhãn-giá trị ở cột
    kế bên: dòng "- Đại diện: Ông: STAFF-NAME-001    Chức vụ: Giám đốc Chi
    nhánh" là hai cặp nằm cạnh nhau. Gộp chúng thành một giá trị thì không mất
    dữ liệu, nhưng "Chức vụ" đáng có field riêng của nó.
    """
    main, extra = _split_trailing_label_columns(value_groups)
    field = _build_one(label_groups, main, page)

    if field is None:
        return []

    fields = [field]
    for label_part, value_part in extra:
        nested = _build_one([label_part], [value_part], page)
        if nested is not None:
            fields.append(nested)

    return fields


def _split_trailing_label_columns(
    value_groups: list[list[PositionedChar]],
) -> tuple[list[list[PositionedChar]], list[tuple[list[PositionedChar], list[PositionedChar]]]]:
    """Tách phần giá trị thành giá trị chính và các cặp nhãn-giá trị ở cột sau.

    Chỉ tách khi cột sau thật sự có dạng "nhãn: giá trị" — cột chỉ chứa chữ
    thường thì để nguyên trong giá trị chính.
    """
    if len(value_groups) != 1:
        return value_groups, []

    columns = split_into_columns(value_groups[0])
    if len(columns) < 2:
        return value_groups, []

    main = [columns[0]]
    extra: list[tuple[list[PositionedChar], list[PositionedChar]]] = []

    for column in columns[1:]:
        separator = next((i for i, c in enumerate(column) if c.text == LABEL_SEPARATOR), None)
        if separator is None or separator == 0:
            main.append(column)
            continue
        extra.append((column[:separator], column[separator + 1:]))

    return main, extra


def split_into_columns(
    chars: list[PositionedChar], gap_ratio: float = COLUMN_GAP_RATIO
) -> list[list[PositionedChar]]:
    """Chia nhóm ký tự thành các cột theo khoảng trắng ngang lớn."""
    if not chars:
        return []

    sizes = [c.size for c in chars if c.size > 0]
    gap_min = (sizes[len(sizes) // 2] if sizes else 12.0) * gap_ratio

    columns: list[list[PositionedChar]] = []
    buffer: list[PositionedChar] = []
    pending_spaces: list[PositionedChar] = []

    for index, char in enumerate(chars):
        if char.text == " ":
            pending_spaces.append(char)
            continue

        geometric_gap = bool(buffer) and (char.x0 - buffer[-1].x1) >= gap_min
        space_run = len(pending_spaces) >= MIN_SPACES_AS_COLUMN_BREAK

        if buffer and (geometric_gap or space_run):
            columns.append(buffer)
            buffer = []
        elif pending_spaces and buffer:
            buffer.extend(pending_spaces)

        pending_spaces = []
        buffer.append(char)

    if buffer:
        columns.append(buffer)

    return columns


def _build_one(
    label_groups: list[list[PositionedChar]],
    value_groups: list[list[PositionedChar]],
    page: int,
) -> LabeledField | None:
    """Dựng một LabeledField từ các nhóm ký tự đã gom cho nhãn và cho giá trị."""
    label_chars = [c for group in label_groups for c in group]
    label = sourced_value_of(
        label_chars,
        page,
        text=" ".join(segment_text(group) for group in label_groups),
        strip_prefixes=BULLET_MARKERS,
    )
    if label is None:
        return None

    # Ghi lại từng MẢNH NGUỒN. Nhãn và giá trị có thể được ghép từ nhiều dòng
    # không liền nhau trong thứ tự đọc, khi đó cổng nguồn gốc chứng minh theo
    # từng mảnh chứ không theo chuỗi liền mạch.
    label.source_lines = [_fragment_text(group) for group in label_groups]

    value_chars = [c for group in value_groups for c in group]
    value = sourced_value_of(
        value_chars,
        page,
        text=" ".join(segment_text(group) for group in value_groups),
        strip_prefixes=(LABEL_SEPARATOR,),
    )

    if value is not None:
        value.source_lines = [_fragment_text(group) for group in value_groups]

    return LabeledField(label=label, value=value)


def _fragment_text(chars: list[PositionedChar]) -> str:
    """Nội dung một mảnh nguồn, đã bỏ ký tự dẫn và gộp khoảng trắng."""
    text = " ".join(segment_text(chars).split())
    for prefix in (*BULLET_MARKERS, LABEL_SEPARATOR):
        text = text.removeprefix(prefix).strip()
    return text


def column_groups_of(line: TextLine) -> list[list[PositionedChar]]:
    """Các cột độc lập trên cùng một dòng vật lý.

    Dòng đầu chứng thư có tên đơn vị ở cột trái và quốc hiệu ở cột phải; khối
    chữ ký có hai người cạnh nhau. Không tách cột thì hai nội dung dính vào
    nhau thành một chuỗi vô nghĩa.
    """
    return line.segments()


def sourced_line(line: TextLine) -> SourcedValue | None:
    """Cả dòng thành một giá trị có nguồn gốc, bỏ ký tự bullet dẫn đầu."""
    return sourced_value_of(line.chars, line.page, strip_prefixes=BULLET_MARKERS)


def merge_sourced_values(values: list[SourcedValue]) -> SourcedValue | None:
    """Gộp nhiều giá trị thành một, nối bằng khoảng trắng và hợp nhất bbox."""
    present = [v for v in values if v is not None]
    if not present:
        return None

    boxes = [v.bbox for v in present if v.bbox is not None]
    merged_bbox = None
    if boxes:
        merged_bbox = type(boxes[0])(
            x0=min(b.x0 for b in boxes),
            top=min(b.top for b in boxes),
            x1=max(b.x1 for b in boxes),
            bottom=max(b.bottom for b in boxes),
        )

    return SourcedValue(
        value=" ".join(v.value for v in present),
        page=present[0].page,
        bbox=merged_bbox,
    )
