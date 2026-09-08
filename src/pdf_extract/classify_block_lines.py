"""Phân loại các dòng trong MỘT khối văn bản thành field, đoạn văn, mục liệt kê.

Tách khỏi `parse_document_sections` vì đây là hai việc khác nhau: module kia
chia tài liệu thành khối (mở đầu, từng mục, khối chữ ký), còn module này quyết
định từng dòng trong một khối thuộc loại gì.

Ba câu hỏi khó, đều trả lời bằng dữ liệu có sẵn trong PDF chứ không bằng suy
đoán ngữ nghĩa:

  1. Dòng nối tiếp thuộc NHÃN hay GIÁ TRỊ? -> theo toạ độ cột.
  2. Dòng có phải NHÃN MỚI? -> phải bắt đầu bằng chữ hoa hoặc chữ số.
  3. Dòng có NỐI TIẾP dòng trước? -> phải liền kề theo chiều dọc, cùng trang.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .extract_text_with_coordinates import TextLine
from .models import BoundingBox, SourcedValue
from .parse_labeled_lines import (
    BULLET_MARKERS,
    LabeledField,
    build_fields,
    continuation_belongs_to_label,
    label_column_x,
    sourced_line,
    split_label_and_value,
    starts_with_bullet,
)
from .sourced_value_builders import sourced_value_of

# Số từ tối đa của phần trước dấu hai chấm để coi dòng đó là NHÃN.
# Câu văn xuôi có chứa dấu hai chấm (ví dụ "... và ÔNG: CUSTOMER-NAME") thì
# phần đứng trước dài hơn nhiều, nên ngưỡng này phân biệt được hai loại.
MAX_LABEL_WORDS = 6

# Dòng nối tiếp phải bắt đầu gần cột nhãn hoặc cột giá trị của phần đang dựng.
# Xa cả hai thì nó là dòng độc lập (tiêu đề căn giữa, ngày căn phải), không
# phải phần tiếp của nội dung trước. Ngưỡng theo tỉ lệ cỡ chữ.
CONTINUATION_COLUMN_RATIO = 3.0

# Khoảng trống dọc tối đa (theo tỉ lệ cỡ chữ) để hai dòng còn được coi là liền
# kề. Vượt ngưỡng này thì dòng sau MỞ ĐOẠN MỚI thay vì nối tiếp đoạn trước.
#
# Cần thiết vì các dòng của bảng dữ liệu đã bị loại khỏi parser cấu trúc: hai
# câu nằm trước và sau bảng trở thành "liền nhau" trong danh sách dòng, nối
# chúng lại sẽ tạo ra một đoạn không hề tồn tại trong tài liệu — và cổng nguồn
# gốc sẽ từ chối nó, đúng như đã xảy ra.
MAX_CONTINUATION_GAP_RATIO = 1.0


class _ContinuationEnded(Exception):
    """Tín hiệu nội bộ: dòng vừa xét không thuộc phần đang dựng, phần đó đã hết."""


@dataclass
class LineBlock:
    """Nhóm ba loại nội dung mà một khối văn bản có thể chứa."""

    fields: list[LabeledField] = field(default_factory=list)
    paragraphs: list[SourcedValue] = field(default_factory=list)
    items: list[SourcedValue] = field(default_factory=list)


def classify_lines(lines: list[TextLine], inline_start: str | None = None) -> LineBlock:
    """Phân loại từng dòng thành field, mục liệt kê, hoặc đoạn văn xuôi.

    Dòng không mở đầu bằng gạch đầu dòng là NỐI TIẾP phần trước đó. Nếu phần
    trước là một cặp nhãn-giá trị thì còn phải chọn nối vào nhãn hay vào giá
    trị — xét theo cột, xem `continuation_belongs_to_label`.
    """
    block = LineBlock()
    pending_field: LabeledField | None = None
    pending_columns: tuple[float, float] | None = None
    pending_text: SourcedValue | None = None
    previous: TextLine | None = None

    if inline_start is not None:
        pending_text = SourcedValue(value=" ".join(inline_start.split()), page=0)
        block.paragraphs.append(pending_text)

    for line in lines:
        if previous is not None and not _lines_are_adjacent(previous, line):
            pending_field = None
            pending_columns = None
            pending_text = None

        previous = line
        split = split_label_and_value(line)
        no_pending = pending_field is None and pending_text is None

        if starts_with_bullet(line) or (
            split is not None and _looks_like_label(split[0], allow_long=no_pending)
        ):
            if split is not None:
                label_chars, value_chars = split
                built = build_fields([label_chars], [value_chars], line.page)
                # Dòng nối tiếp gắn vào field CUỐI: một dòng có thể sinh nhiều
                # field khi phần giá trị còn chứa cặp nhãn-giá trị ở cột kế bên.
                pending_field = built[-1] if built else None
                if pending_field is not None:
                    block.fields.extend(built)
                    pending_columns = (
                        label_column_x(label_chars),
                        label_column_x(value_chars),
                    )
                    pending_text = None
                    continue

            value = sourced_line(line)
            if value is not None:
                block.items.append(value)
            pending_field = None
            pending_text = value
            continue

        try:
            started = _append_continuation(
                block, line, pending_field, pending_columns, pending_text
            )
            if started is not None:
                # Đoạn văn mới bắt đầu: ghi nhận để các dòng sau nối tiếp vào
                # nó, thay vì mỗi dòng thành một đoạn rời.
                pending_text = started
        except _ContinuationEnded:
            pending_field = None
            pending_columns = None
            pending_text = None

    return block


def classify_single_column(block: LineBlock, group, page: int) -> None:
    """Phân loại nội dung của MỘT cột: cặp nhãn-giá trị hoặc đoạn văn."""
    separator = next((i for i, c in enumerate(group) if c.text == ":"), None)

    if separator is not None and _looks_like_label(group[:separator]):
        entries = build_fields([group[:separator]], [group[separator + 1:]], page)
        if entries:
            block.fields.extend(entries)
            return

    value = sourced_value_of(group, page)
    if value is not None:
        block.paragraphs.append(value)


def _lines_are_adjacent(previous: TextLine, current: TextLine) -> bool:
    """Hai dòng có liền kề nhau trong tài liệu hay không.

    Khác trang thì không liền kề: giữa chúng còn chân trang và tiêu đề trang.
    Cùng trang thì khoảng trống dọc phải nhỏ hơn ngưỡng — vượt ngưỡng nghĩa là
    ở giữa có nội dung khác (bảng, khoảng trắng phân đoạn) đã bị loại ra.
    """
    if previous.page != current.page:
        return False

    gap = current.top - previous.bottom
    return gap <= current.font_size * MAX_CONTINUATION_GAP_RATIO


def _looks_like_label(label_chars, allow_long: bool = False) -> bool:
    """Phần trước dấu hai chấm có giống một nhãn hay không.

    Điều kiện BẮT BUỘC: bắt đầu bằng CHỮ HOA hoặc CHỮ SỐ. Nhãn trong tài liệu
    hành chính luôn viết hoa chữ đầu ("Số CTPH", "Kính gửi", "Phụ lục số 01"),
    còn phần cuối một câu bị ngắt dòng thì bắt đầu bằng chữ thường ("tại thời
    điểm thẩm định giá như sau:") — đây là dấu hiệu tách được hai loại.

    Điều kiện về ĐỘ DÀI chỉ áp dụng khi đang có nội dung dở dang phía trước.
    Ở đầu một khối thì không có gì để nối tiếp nên nhãn dài vẫn hợp lệ — mục XI
    dùng cả câu làm nhãn ("Thời hạn hiệu lực ... tính từ ngày phát hành là").
    """
    from .extract_text_with_coordinates import segment_text

    text = segment_text(label_chars).strip().lstrip("".join(BULLET_MARKERS)).strip()
    words = text.split()

    if not words:
        return False
    if not allow_long and len(words) > MAX_LABEL_WORDS:
        return False

    first = text[0]
    return first.isupper() or first.isdigit()


def _append_continuation(
    block: LineBlock,
    line: TextLine,
    pending_field: LabeledField | None,
    pending_columns: tuple[float, float] | None,
    pending_text: SourcedValue | None,
) -> SourcedValue | None:
    """Nối dòng vào đúng chỗ: nhãn, giá trị, đoạn đang dựng, hay đoạn mới.

    Trả về đoạn văn MỚI vừa mở (nếu có) để bên gọi tiếp tục nối các dòng sau
    vào chính đoạn đó.
    """
    if pending_field is not None and pending_columns is not None:
        label_x, value_x = pending_columns
        tolerance = line.font_size * CONTINUATION_COLUMN_RATIO

        # Xa cả hai cột thì đây là dòng độc lập (tiêu đề căn giữa, ngày căn
        # phải), không phải phần tiếp của cặp nhãn-giá trị đang dựng.
        if min(abs(line.x0 - label_x), abs(line.x0 - value_x)) > tolerance:
            value = sourced_line(line)
            if value is not None:
                block.paragraphs.append(value)
            # Dòng nằm ngoài cả hai cột đã KẾT THÚC phần nối tiếp; báo cho vòng
            # lặp biết để dòng sau không bị nối oan vào cặp nhãn-giá trị này.
            raise _ContinuationEnded

        if continuation_belongs_to_label(line, label_x, value_x):
            pending_field.label = _extend(pending_field.label, line)
        elif pending_field.value is not None:
            pending_field.value = _extend(pending_field.value, line)
        else:
            pending_field.value = sourced_line(line)
        return None

    if pending_text is not None:
        extended = _extend(pending_text, line)
        pending_text.value = extended.value
        pending_text.bbox = extended.bbox
        return None

    value = sourced_line(line)
    if value is not None:
        block.paragraphs.append(value)
    return value


def _extend(target: SourcedValue, line: TextLine) -> SourcedValue:
    """Nối nội dung một dòng vào giá trị đang dựng, hợp nhất bbox.

    Chèn khoảng trắng vì mỗi lần xuống dòng trong văn xuôi là một ranh giới TỪ.
    """
    line_value = sourced_value_of(line.chars, line.page)
    if line_value is None:
        return target

    box = target.bbox
    if box is not None and line_value.bbox is not None:
        other = line_value.bbox
        box = BoundingBox(
            x0=min(box.x0, other.x0),
            top=min(box.top, other.top),
            x1=max(box.x1, other.x1),
            bottom=max(box.bottom, other.bottom),
        )
    elif box is None:
        box = line_value.bbox

    return SourcedValue(
        value=f"{target.value} {line_value.value}".strip(),
        page=target.page,
        bbox=box,
        # Cộng dồn mảnh nguồn: giá trị ghép từ nhiều dòng không liền nhau chỉ
        # chứng minh được nguồn gốc khi biết nó gồm những mảnh nào.
        source_lines=[*(target.source_lines or [target.value]), line_value.value],
    )
