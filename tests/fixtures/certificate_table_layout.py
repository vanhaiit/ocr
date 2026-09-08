"""Vẽ bảng có đường kẻ ô: gộp ô, wrap trong ô, và tự kiểm tra chiều rộng.

Ba điều bắt buộc, học từ lần đầu làm sai:

  1. **Gộp ô**: dòng "Tổng cộng (đồng)" trong chứng thư thật chiếm ngang hai cột
     đầu. Không gộp thì nhãn tràn khỏi cột STT và ĐÈ LÊN giá trị — file sinh ra
     trông vẫn "có chữ" nhưng nội dung chồng nhau, vô dụng làm fixture.

  2. **Wrap trong ô**: placeholder dài hơn bề rộng cột ở khổ A4. Tài liệu thật
     ngắt dòng trong ô, kể cả ngắt giữa token tại dấu gạch nối
     ("VALUE-VND-" / "LOT-901"). Fixture phải làm đúng vậy — đây cũng chính là
     ca sinh ra bài toán ghép dòng trong ô mà pipeline phải xử lý.

  3. **Tự kiểm tra**: một TỪ đơn không thể wrap mà vẫn rộng hơn ô thì raise ngay.
     Fixture sai âm thầm còn tệ hơn fixture không sinh được, vì mọi kết luận rút
     ra từ nó đều sai theo.
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.colors import grey

from .certificate_pdf_builder import BODY_SIZE, CertificatePdfBuilder

# Đệm trong ô, để chữ không dính đường kẻ.
CELL_PADDING_X = 3.0
CELL_PADDING_Y = 5.0

# Chiều cao một dòng chữ trong ô.
CELL_LINE_HEIGHT = 13.0

# Chiều cao tối thiểu của một hàng.
MIN_ROW_HEIGHT = 20.0

# Chiều cao hàng tiêu đề khi chữ được quay 90 độ: phải đủ chứa chuỗi tiêu đề
# DÀI NHẤT theo chiều dọc, nếu không chữ tràn ra ngoài bảng và đè lên nội dung
# phía trên — lỗi của bản fixture đầu tiên.
ROTATED_HEADER_HEIGHT = 108.0


@dataclass
class Cell:
    """Một ô bảng: nội dung, số cột chiếm ngang, và cách vẽ đặc biệt nếu có."""

    text: str
    colspan: int = 1
    superscript: tuple[str, str, str] | None = None  # (trước, chỉ số, sau)


class CellOverflowError(AssertionError):
    """Một từ đơn rộng hơn ô chứa nó — fixture sai, phải sửa bố cục."""


def wrap_cell_text(builder: CertificatePdfBuilder, text: str, available: float) -> list[str]:
    """Ngắt nội dung ô thành các dòng vừa bề rộng.

    Ngắt ở khoảng trắng trước; từ nào vẫn quá rộng thì ngắt tiếp SAU DẤU GẠCH
    NỐI, đúng cách trình xử lý văn bản ngắt các mã dài như "VALUE-VND-LOT-901".
    """
    font = builder._font_for("")
    width = lambda s: builder.canvas.stringWidth(s, font, BODY_SIZE)

    lines: list[str] = []
    current = ""

    for token in _breakable_tokens(text):
        candidate = current + token
        if current and width(candidate.strip()) > available:
            lines.append(current.strip())
            current = token.lstrip()
        else:
            current = candidate

    if current.strip():
        lines.append(current.strip())

    for line in lines:
        if width(line) > available:
            raise CellOverflowError(
                f"Đoạn {line!r} cần {width(line):.1f}pt nhưng ô chỉ có "
                f"{available:.1f}pt và không ngắt nhỏ hơn được. Nới cột hoặc gộp ô."
            )

    return lines


def _breakable_tokens(text: str) -> list[str]:
    """Chia chuỗi thành các mảnh được phép ngắt: sau khoảng trắng và sau gạch nối."""
    tokens: list[str] = []
    buffer = ""

    for char in text:
        buffer += char
        if char in (" ", "-"):
            tokens.append(buffer)
            buffer = ""

    if buffer:
        tokens.append(buffer)

    return tokens


def draw_ruled_table(
    builder: CertificatePdfBuilder,
    column_x: tuple[float, ...],
    rows: list[list[Cell]],
    *,
    rotate_header: bool = False,
) -> None:
    """Vẽ bảng; mỗi hàng có cách gộp ô và chiều cao riêng theo nội dung.

    Đường kẻ dọc được vẽ THEO TỪNG HÀNG dựa trên cách gộp ô của hàng đó, không
    vẽ một lượt cho cả bảng — nhờ vậy ô gộp không bị đường kẻ cắt qua giữa.
    """
    canvas = builder.canvas
    canvas.setStrokeColor(grey)
    canvas.setLineWidth(0.5)

    row_top = builder.y + BODY_SIZE

    for row_index, row in enumerate(rows):
        rotated = row_index == 0 and rotate_header
        wrapped = _wrap_row(builder, column_x, row)
        height = (
            ROTATED_HEADER_HEIGHT
            if rotated
            else max(
                MIN_ROW_HEIGHT,
                max((len(lines) for lines in wrapped), default=1) * CELL_LINE_HEIGHT
                + CELL_PADDING_Y * 2,
            )
        )
        row_bottom = row_top - height

        canvas.line(column_x[0], row_top, column_x[-1], row_top)
        for boundary in _column_boundaries(column_x, row):
            canvas.line(boundary, row_top, boundary, row_bottom)

        _draw_row_cells(builder, column_x, row, wrapped, row_top, row_bottom, rotated)
        row_top = row_bottom

    canvas.line(column_x[0], row_top, column_x[-1], row_top)
    builder.y = row_top - BODY_SIZE


def _cell_bounds(column_x: tuple[float, ...], row: list[Cell]) -> list[tuple[float, float]]:
    """Biên trái/phải của từng ô trong hàng, tính theo colspan."""
    bounds: list[tuple[float, float]] = []
    cursor = 0

    for cell in row:
        right_index = min(cursor + cell.colspan, len(column_x) - 1)
        bounds.append((column_x[cursor], column_x[right_index]))
        cursor = right_index

    return bounds


def _wrap_row(
    builder: CertificatePdfBuilder, column_x: tuple[float, ...], row: list[Cell]
) -> list[list[str]]:
    """Ngắt dòng cho mọi ô trong hàng, để tính chiều cao hàng trước khi vẽ."""
    wrapped: list[list[str]] = []

    for cell, (left, right) in zip(row, _cell_bounds(column_x, row)):
        available = right - left - CELL_PADDING_X * 2

        if cell.superscript is not None:
            wrapped.append([cell.text])
            continue

        wrapped.append(wrap_cell_text(builder, cell.text, available) if cell.text else [])

    return wrapped


def _column_boundaries(column_x: tuple[float, ...], row: list[Cell]) -> list[float]:
    """Các mốc x cần kẻ dọc cho một hàng, theo cách gộp ô của hàng đó."""
    boundaries = [left for left, _ in _cell_bounds(column_x, row)]
    boundaries.append(column_x[-1])
    return boundaries


def _draw_row_cells(
    builder: CertificatePdfBuilder,
    column_x: tuple[float, ...],
    row: list[Cell],
    wrapped: list[list[str]],
    row_top: float,
    row_bottom: float,
    rotated: bool,
) -> None:
    """Vẽ nội dung từng ô, đặt các dòng từ trên xuống trong ô."""
    for cell, (left, _right), lines in zip(row, _cell_bounds(column_x, row), wrapped):
        x = left + CELL_PADDING_X

        if rotated:
            if cell.text:
                _draw_rotated_cell(builder, x, row_bottom, cell.text, row_top - row_bottom)
            continue

        if cell.superscript is not None:
            before, script, after = cell.superscript
            builder.y = row_bottom + CELL_PADDING_Y
            builder.draw_with_script(x, before, script, after)
            continue

        for line_index, line in enumerate(lines):
            baseline = row_top - CELL_PADDING_Y - CELL_LINE_HEIGHT * (line_index + 1) + 3.5
            builder.draw_text(x, line, y=baseline)


def _draw_rotated_cell(
    builder: CertificatePdfBuilder,
    x: float,
    bottom: float,
    text: str,
    cell_height: float,
) -> None:
    """Vẽ chữ quay 90 độ, nằm gọn trong chiều cao ô."""
    length = builder.canvas.stringWidth(text, builder._font_for(""), BODY_SIZE)
    if length > cell_height - CELL_PADDING_Y * 2:
        raise CellOverflowError(
            f"Tiêu đề quay dọc {text!r} dài {length:.1f}pt nhưng ô chỉ cao "
            f"{cell_height:.1f}pt. Tăng ROTATED_HEADER_HEIGHT."
        )

    canvas = builder.canvas
    canvas.saveState()
    canvas.translate(x + BODY_SIZE, bottom + CELL_PADDING_Y)
    canvas.rotate(90)
    builder.draw_text(0.0, text, y=0.0)
    canvas.restoreState()
