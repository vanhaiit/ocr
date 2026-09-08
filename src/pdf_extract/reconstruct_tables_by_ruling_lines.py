"""Dựng lại bảng theo đường kẻ ô (lattice) thay vì suy đoán theo khoảng trắng.

Tài liệu chứng thư có đường kẻ ô thật trong PDF, nên biên ô là dữ liệu có sẵn —
không phải thứ phải phỏng đoán. Đây là điều kiện để bảng cũng đạt mức xác định
như text: mỗi ô có bbox riêng, giá trị trong ô truy được về đúng vùng toạ độ đó.

Quan trọng: nội dung ô được lấy từ DANH SÁCH KÝ TỰ ĐÃ QUA XỬ LÝ mà pipeline
truyền vào, không phải từ bộ trích xuất text riêng của thư viện. Nếu để thư viện
tự đọc lại PDF thì ô bảng sẽ bỏ qua các bước đã làm ở tầng trên — lọc glyph vẽ
trùng và gộp dấu tổ hợp — khiến tài liệu có chữ đổ bóng cho ra ô bảng chứa chữ
nhân đôi. Chỉ dùng thư viện để tìm BIÊN ô; nội dung luôn lấy từ nguồn chân lý.

Chỉ khi PDF không có đường kẻ mới phải rơi về suy luận theo khoảng trắng, và
khi đó độ tin cậy giảm — pipeline ghi rõ chiến lược đã dùng để người đọc biết.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pdfplumber

from .extract_text_with_coordinates import (
    LINE_CLUSTER_RATIO,
    PositionedChar,
    cluster_rotated_chars,
    median_font_size,
)
from .models import BoundingBox, SourcedValue

# Chiến lược lattice: dùng đường kẻ có thật. Là mặc định vì cho biên ô chính xác.
LATTICE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}

# Chiến lược dự phòng khi không có đường kẻ: gom theo khoảng trắng.
# Kém tin cậy hơn, chỉ dùng khi lattice không tìm được bảng nào.
STREAM_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}

# Nới biên ô khi lọc ký tự: đường kẻ có thể cắt sát mép glyph.
CELL_BBOX_TOLERANCE = 1.5


def join_cell_lines(physical_lines: list[str]) -> str:
    """Ghép các dòng trong một ô LIỀN NHAU, không chèn dấu cách.

    Lý do: PDF ngắt dòng trong ô là do hết chỗ ngang, không phải do có ranh giới
    từ. Chèn dấu cách sẽ phá các giá trị bị ngắt giữa token — số tiền
    "1.234.567.000" ngắt thành hai dòng sẽ thành "1.234. 567.000" và làm vỡ
    bước parse số. Đây là mặc định an toàn cho cột số và mã.

    Cột chứa văn xuôi cần cách ghép khác (giữa các dòng có ranh giới từ thật);
    template dùng `source_lines` để ghép lại theo cách của mình.
    """
    return "".join(physical_lines)


@dataclass
class TableRegion:
    """Một bảng trên một trang."""

    page: int
    bbox: BoundingBox
    strategy: str
    rows: list[list[SourcedValue]] = field(default_factory=list)

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.rows), max((len(r) for r in self.rows), default=0))


class _PageCharIndex:
    """Tra ký tự theo trang để dựng nội dung ô từ nguồn chân lý."""

    def __init__(self, chars: list[PositionedChar]) -> None:
        self._by_page: dict[int, list[PositionedChar]] = {}
        for char in chars:
            self._by_page.setdefault(char.page, []).append(char)

    def physical_lines_in(self, page: int, bbox: tuple[float, ...]) -> list[str]:
        """Các dòng vật lý bên trong một ô, đọc trên xuống rồi trái sang phải."""
        x0, top, x1, bottom = bbox
        inside = [
            char
            for char in self._by_page.get(page, [])
            if x0 - CELL_BBOX_TOLERANCE <= (char.x0 + char.x1) / 2 <= x1 + CELL_BBOX_TOLERANCE
            and top - CELL_BBOX_TOLERANCE <= (char.top + char.bottom) / 2 <= bottom + CELL_BBOX_TOLERANCE
        ]
        if not inside:
            return []

        return _group_into_physical_lines(inside)


def _group_into_physical_lines(chars: list[PositionedChar]) -> list[str]:
    """Gom ký tự trong một ô thành các dòng, theo cùng ngưỡng như tầng trích xuất.

    Chữ QUAY được gom riêng theo trục dọc: tiêu đề cột hẹp thường quay 90 độ, và
    sắp theo x như chữ thường sẽ cho ra chuỗi đảo ngược ("TTS" thay vì "STT").
    """
    upright = [c for c in chars if c.upright]
    rotated = [c for c in chars if not c.upright]

    lines: list[str] = []
    for group in cluster_rotated_chars(rotated):
        text = " ".join("".join(c.text for c in group).split())
        if text:
            lines.append(text)

    if not upright:
        return lines

    chars = upright
    tolerance = median_font_size(chars) * LINE_CLUSTER_RATIO
    buckets: list[list[PositionedChar]] = []

    for char in sorted(chars, key=lambda c: ((c.top + c.bottom) / 2, c.x0)):
        center = (char.top + char.bottom) / 2
        if buckets and abs(_center_of(buckets[-1][0]) - center) <= tolerance:
            buckets[-1].append(char)
        else:
            buckets.append([char])

    for bucket in buckets:
        bucket.sort(key=lambda c: c.x0)
        text = " ".join("".join(c.text for c in bucket).split())
        if text:
            lines.append(text)

    return lines


def _center_of(char: PositionedChar) -> float:
    return (char.top + char.bottom) / 2


def extract_tables(pdf_path: str, chars: list[PositionedChar]) -> list[TableRegion]:
    """Trích mọi bảng trên mọi trang, nội dung lấy từ `chars` đã qua xử lý."""
    index = _PageCharIndex(chars)
    regions: list[TableRegion] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            found = page.find_tables(table_settings=LATTICE_SETTINGS)
            strategy = "lattice"

            if not found:
                found = page.find_tables(table_settings=STREAM_SETTINGS)
                strategy = "stream"

            for table in found:
                regions.append(_build_region(table, page_number, strategy, index))

    return regions


def _build_region(table, page_number: int, strategy: str, index: _PageCharIndex) -> TableRegion:
    """Chuyển biên ô của pdfplumber thành TableRegion, nội dung từ nguồn chân lý."""
    region = TableRegion(
        page=page_number,
        bbox=BoundingBox(*[float(v) for v in table.bbox]),
        strategy=strategy,
    )

    for row in table.rows:
        row_values: list[SourcedValue] = []

        for cell_bbox in row.cells:
            if cell_bbox is None:
                row_values.append(SourcedValue(value="", page=page_number))
                continue

            box = tuple(float(v) for v in cell_bbox)
            physical_lines = index.physical_lines_in(page_number, box)

            row_values.append(
                SourcedValue(
                    value=join_cell_lines(physical_lines),
                    page=page_number,
                    bbox=BoundingBox(*box),
                    source_lines=physical_lines,
                )
            )

        region.rows.append(row_values)

    return region


def merge_continued_tables(regions: list[TableRegion]) -> list[TableRegion]:
    """Nối các bảng bị vắt qua nhiều trang.

    Bảng giá trị tài sản trong chứng thư có phần tiêu đề ở cuối trang trước và
    phần thân ở trang sau. Ghép khi số cột trùng nhau và hai bảng nằm ở hai
    trang liên tiếp — dấu hiệu đủ chắc cho họ tài liệu này.
    """
    if not regions:
        return []

    merged: list[TableRegion] = [regions[0]]

    for current in regions[1:]:
        previous = merged[-1]
        same_width = previous.shape[1] == current.shape[1] and previous.shape[1] > 1
        consecutive_pages = current.page == previous.page + 1

        if same_width and consecutive_pages:
            previous.rows.extend(current.rows)
        else:
            merged.append(current)

    return merged
