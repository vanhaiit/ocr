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

from .extract_text_with_coordinates import PositionedChar, TextLine, segment_text
from .models import SourcedValue
from .sourced_value_builders import bbox_of, sourced_value_of

# Ký tự mở đầu một mục con. `●` là bullet trang trí của font ký hiệu.
BULLET_MARKERS = ("-", "–", "+", "●", "•", "*")

# Dấu phân cách nhãn với giá trị.
LABEL_SEPARATOR = ":"

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


def build_field(
    label_groups: list[list[PositionedChar]],
    value_groups: list[list[PositionedChar]],
    page: int,
) -> LabeledField | None:
    """Dựng LabeledField từ các nhóm ký tự đã gom cho nhãn và cho giá trị."""
    label_chars = [c for group in label_groups for c in group]
    label = sourced_value_of(
        label_chars,
        page,
        text=" ".join(segment_text(group) for group in label_groups),
        strip_prefixes=BULLET_MARKERS,
    )
    if label is None:
        return None

    value_chars = [c for group in value_groups for c in group]
    value = sourced_value_of(
        value_chars,
        page,
        text=" ".join(segment_text(group) for group in value_groups),
        strip_prefixes=(LABEL_SEPARATOR,),
    )

    return LabeledField(label=label, value=value)


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
