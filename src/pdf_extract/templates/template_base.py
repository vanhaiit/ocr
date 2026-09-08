"""Giao diện chung cho mọi template và các tiện ích lấy field theo nhãn.

Mô hình: mỗi loại tài liệu là một template có hai việc — tự nhận diện
(`matches`) và tự bóc field (`extract`). Thêm loại tài liệu mới chỉ cần thêm
một file template rồi ghi tên vào registry, không sửa pipeline.

Ba nguyên tắc của các hàm bóc field ở đây:

  1. Theo NHÃN CÓ THẬT, không theo vị trí tuyệt đối — vị trí vỡ ngay khi nội
     dung dài ra và đẩy dòng xuống, còn nhãn thì ổn định.
  2. Giới hạn trong PHẠM VI CỘT chứa nhãn, để không nuốt nội dung cột bên cạnh
     nằm cùng dòng vật lý (ví dụ quốc hiệu ở cột phải dòng đầu chứng thư).
  3. Chỉ CẮT CHUỖI, không suy luận — nhờ vậy mọi giá trị đều đi qua được cổng
     nguồn gốc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ..extract_text_with_coordinates import (
    PositionedChar,
    TextLine,
    normalize,
    segment_text,
)
from ..extract_annotation_data import FormField, Hyperlink
from ..parse_document_sections import ParsedDocument
from ..models import BoundingBox, SourcedValue

# Các dấu phân cách nhãn/giá trị dùng trong họ tài liệu này.
LABEL_SEPARATORS = (":",)

# Dòng mở đầu một mục mới: số La Mã, gạch đầu dòng, dấu cộng, bullet.
# Dùng làm mốc DỪNG khi ghép giá trị vắt qua nhiều dòng.
SECTION_START_PATTERN = re.compile(r"^\s*(?:[IVXLCDM]{1,7}\.|[-–+●•*])")


@dataclass
class DocumentContext:
    """Mọi thứ template cần để bóc field.

    Gói lại thành một kiểu thay vì thêm dần tham số: dữ liệu annotation (form
    field, hyperlink) không nằm trong content stream nên phải đi đường riêng,
    và sau này còn có thể thêm nguồn khác.
    """

    lines: list[TextLine]
    tables: list
    # Cấu trúc mục đã đọc từ tài liệu. Template dựa vào đây để không phải đi
    # tìm nhãn — nhờ vậy nhãn lạ vẫn được xuất ra thay vì bỏ im lặng.
    document: ParsedDocument = field(default_factory=ParsedDocument)
    form_fields: list[FormField] = field(default_factory=list)
    hyperlinks: list[Hyperlink] = field(default_factory=list)


class DocumentTemplate(Protocol):
    """Hợp đồng mà mỗi template phải thực hiện."""

    template_id: str

    def matches(self, canonical_text: str) -> float:
        """Trả điểm tin cậy 0..1 cho việc tài liệu này thuộc template."""
        ...

    def extract(self, context: DocumentContext) -> dict:
        """Bóc field thành cây dict chứa SourcedValue."""
        ...


def _comparable(text: str) -> str:
    """Dạng để so nhãn: chuẩn hoá NFC, bỏ khoảng trắng, hạ chữ thường.

    Bỏ khoảng trắng vì PDF hay chèn khoảng cách bất thường giữa các chữ trong
    tiêu đề; nhãn vẫn nhận ra được.
    """
    return normalize(text).replace(" ", "").lower()


def find_line_containing(lines: list[TextLine], needle: str) -> TextLine | None:
    """Tìm dòng đầu tiên chứa chuỗi nhãn."""
    target = _comparable(needle)
    for line in lines:
        if target in _comparable(line.text):
            return line
    return None


def _locate_label(lines: list[TextLine], label: str) -> tuple[int, int] | None:
    """Tìm nhãn, trả (chỉ số dòng, chỉ số đoạn) để bên gọi ghép tiếp được."""
    target = _comparable(label)

    for line_index, line in enumerate(lines):
        for segment_index, segment in enumerate(line.segments()):
            if target in _comparable(segment_text(segment)):
                return line_index, segment_index

    return None


def _bbox_of(chars: list[PositionedChar]) -> BoundingBox | None:
    """Bbox khít nội dung: bỏ ký tự khoảng trắng ở hai đầu trước khi tính."""
    meaningful = [c for c in chars if c.text.strip()]
    if not meaningful:
        return None

    return BoundingBox(
        x0=min(c.x0 for c in meaningful),
        top=min(c.top for c in meaningful),
        x1=max(c.x1 for c in meaningful),
        bottom=max(c.bottom for c in meaningful),
    )


def _sourced_value_of(
    chars: list[PositionedChar], page: int, text: str | None = None
) -> SourcedValue | None:
    """Dựng SourcedValue từ nhóm ký tự; bỏ dấu phân cách còn sót ở đầu.

    `text` cho phép bên gọi tự quyết cách ghép (ví dụ ghép nhiều dòng có chèn
    khoảng trắng) trong khi bbox vẫn tính từ toàn bộ ký tự thật.
    """
    raw = segment_text(chars) if text is None else text
    cleaned = " ".join(raw.split())
    for separator in LABEL_SEPARATORS:
        cleaned = cleaned.removeprefix(separator).strip()

    if not cleaned:
        return None

    return SourcedValue(value=cleaned, page=page, bbox=_bbox_of(chars))


def value_after_label(
    lines: list[TextLine],
    label: str,
    separators: tuple[str, ...] = LABEL_SEPARATORS,
    multiline: bool = False,
) -> SourcedValue | None:
    """Lấy giá trị đứng sau nhãn, trong phạm vi cột chứa nhãn.

    Xử lý được hai cách trình bày cùng tồn tại trong chứng thư:
      - "Số HĐ: CONTRACT-NO-001"      -> nhãn và giá trị cùng một đoạn
      - "- Tên khách hàng   : ÔNG ..." -> nhãn bị khoảng trắng căn cột đẩy tách
        khỏi dấu hai chấm, giá trị nằm ở đoạn kế tiếp

    `multiline=True` ghép thêm các dòng tiếp theo cho tới khi gặp mốc mở đầu
    mục mới, dùng cho các giá trị dài bị xuống dòng (mục đích thẩm định giá).
    """
    located = _locate_label(lines, label)
    if located is None:
        return None

    line_index, segment_index = located
    line = lines[line_index]
    segments = line.segments()
    label_segment = segments[segment_index]

    value_chars = _chars_after_separator(label_segment, label, separators)

    if value_chars is None:
        # Dấu phân cách nằm ở đoạn sau: gom các đoạn còn lại của dòng.
        value_chars = [c for segment in segments[segment_index + 1:] for c in segment]

    if not value_chars:
        return None

    page = line.page

    if not multiline:
        return _sourced_value_of(value_chars, page)

    # Ghép nhiều dòng: mỗi dòng là một ranh giới TỪ, phải chèn khoảng trắng.
    # Nối thẳng ký tự sẽ dính hai từ ("...GROUP-900," + "PROPERTY-..." thành
    # "...GROUP-900,PROPERTY-..."). Khác với ô bảng — ở đó ngắt dòng là do hết
    # chỗ ngang nên phải nối liền.
    continuation = _continuation_lines(lines, line_index)
    all_chars = value_chars + [c for group in continuation for c in group]
    text_parts = [segment_text(value_chars)] + [segment_text(group) for group in continuation]

    return _sourced_value_of(all_chars, page, text=" ".join(text_parts))


def _chars_after_separator(
    segment: list[PositionedChar],
    label: str,
    separators: tuple[str, ...],
) -> list[PositionedChar] | None:
    """Cắt đoạn tại dấu phân cách đầu tiên SAU nhãn. None nếu đoạn không có dấu."""
    text = normalize(segment_text(segment))
    search_from = _label_end_index(text, label)

    for separator in separators:
        position = text.find(separator, search_from)
        if position != -1:
            return segment[position + len(separator):]

    return None


def _continuation_lines(
    lines: list[TextLine], line_index: int
) -> list[list[PositionedChar]]:
    """Các dòng nối tiếp, tới trước dòng mở đầu mục mới.

    Trả về TỪNG DÒNG riêng (không gộp sẵn) để bên gọi chèn được khoảng trắng ở
    ranh giới dòng.

    Chỉ nối trong cùng một trang: giá trị vắt sang trang khác cần xử lý riêng
    vì còn chèn header/footer, không nên tự ghép.
    """
    collected: list[list[PositionedChar]] = []
    current_page = lines[line_index].page

    for line in lines[line_index + 1:]:
        if line.page != current_page:
            break
        if SECTION_START_PATTERN.match(line.text):
            break
        if not line.text.strip():
            break
        collected.append(line.chars)

    return collected


def _label_end_index(text: str, label: str) -> int:
    """Vị trí kết thúc của nhãn trong text gốc.

    So trên bản đã bỏ khoảng trắng rồi ánh xạ chỉ số về bản gốc, vì khoảng
    trắng trong nhãn và trong PDF có thể khác nhau.
    """
    index = _comparable(text).find(_comparable(label))
    if index == -1:
        return 0

    target = index + len(_comparable(label))
    consumed = 0

    for position, char in enumerate(text):
        if not char.isspace():
            consumed += 1
        if consumed >= target:
            return position + 1

    return len(text)


def segment_value_containing(lines: list[TextLine], needle: str) -> SourcedValue | None:
    """Lấy toàn bộ đoạn chứa chuỗi mốc, không cắt theo dấu phân cách.

    Dùng cho field mà nhãn và giá trị dính liền không theo khuôn "nhãn: giá trị",
    ví dụ dòng địa điểm và ngày phát hành.
    """
    located = _locate_label(lines, needle)
    if located is None:
        return None

    line_index, segment_index = located
    line = lines[line_index]
    return _sourced_value_of(line.segments()[segment_index], line.page)


def rejoin_prose_cell(cell: SourcedValue) -> SourcedValue:
    """Ghép lại ô bảng chứa VĂN XUÔI, quyết định dấu cách theo TỪNG CHỖ NGẮT.

    Một ô văn xuôi có thể chứa cả hai kiểu ngắt dòng:

        "Giá trị Quyền sử dụng" + "đất LAND-LOT-001"   -> ranh giới TỪ, cần dấu cách
        "PROPERTY-" + "DISTRICT-001"                    -> ngắt GIỮA token, không dấu cách

    Phân biệt bằng quy tắc gạch nối cuối dòng: dòng kết thúc bằng "-" nghĩa là
    token bị cắt làm đôi, nối liền; ngược lại là ranh giới từ, chèn dấu cách.
    Chọn theo cột (một chính sách cho cả ô) thì sai một trong hai kiểu —
    "PROPERTY- DISTRICT-001" là kết quả của cách làm đó.

    Mặc định của tầng dựng bảng là ghép liền — đúng cho cột số và cột mã, nhưng
    sai cho văn xuôi: "Giá trị Quyền sử dụng" + "đất LAND-LOT-001" ghép liền sẽ
    thành "...sử dụngđất...". Chỉ template biết cột nào là văn xuôi, nên việc
    ghép lại được đặt ở đây và phải gọi tường minh cho từng cột.

    Không đổi bbox: vùng toạ độ vẫn là vùng ô, nên cổng nguồn gốc vẫn kiểm được
    (phép so của cổng bỏ qua khoảng trắng).
    """
    if len(cell.source_lines) <= 1:
        return cell

    return SourcedValue(
        value=_join_prose_lines(cell.source_lines),
        page=cell.page,
        bbox=cell.bbox,
        source_lines=cell.source_lines,
    )


def _join_prose_lines(lines: list[str]) -> str:
    """Nối các dòng, chèn dấu cách trừ khi dòng trước kết thúc bằng gạch nối."""
    joined = lines[0]

    for line in lines[1:]:
        separator = "" if joined.endswith("-") else " "
        joined = f"{joined}{separator}{line}"

    return joined


def value_from_table_lookup(tables: list, label: str) -> SourcedValue | None:
    """Tìm giá trị trong bảng nhãn-giá trị hai cột.

    Một số mục (thông tin công ty) được trình bày bằng bảng hai cột chứ không
    phải dòng text, nên cần đường tra riêng.
    """
    target = _comparable(label)

    for table in tables:
        for row in table.rows:
            if len(row) < 2:
                continue
            if target in _comparable(row[0].value) and row[1].value.strip():
                return row[1]

    return None
