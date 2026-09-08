"""Engine trích xuất chính: lấy text kèm toạ độ từng ký tự qua pdfplumber.

Đây là "nguồn chân lý" của toàn pipeline. Mọi giá trị xuất ra JSON về sau đều
phải truy được về text ở tầng này. Giữ toạ độ từng ký tự là điều kiện để dựng
lại bảng và để ghi lại bằng chứng nguồn gốc (page + bbox) cho từng giá trị.
"""

from __future__ import annotations

import statistics
import unicodedata
from dataclasses import dataclass

import pdfplumber

# Các ngưỡng hình học đều tính theo TỈ LỆ cỡ chữ, không phải điểm tuyệt đối,
# để tài liệu đổi font hoặc đổi cỡ chữ vẫn gom dòng và tách cột đúng.

# Hai ký tự thuộc cùng dòng nếu tâm theo trục dọc lệch nhau dưới ngưỡng này.
# Nới hơn khoảng cách giữa các đường cơ sở của cùng một dòng, nhưng chặt hơn
# khoảng cách giữa hai dòng liền nhau (thường từ 1.15 lần cỡ chữ trở lên).
LINE_CLUSTER_RATIO = 0.3

# Tỉ lệ chồng lấn dọc tối thiểu để một ký tự thuộc cùng dòng với ký tự lớn nhất
# của dòng đó. Cần cho CHỈ SỐ TRÊN/DƯỚI: chúng nhỏ hơn và lệch đường cơ sở nên
# tâm nằm ngoài ngưỡng gom theo tâm, nhưng hộp của chúng vẫn chồng lên dải chữ
# chính. Không có phép này thì "H₂O" bị tách thành "HO" và "2" ở hai dòng, rồi
# ghép lại sai thành "HO 2".
MIN_VERTICAL_OVERLAP_RATIO = 0.35

# Khoảng trắng ngang tối thiểu để coi là ngắt cột thay vì khoảng cách chữ.
# Dấu cách thường rộng khoảng 0.25-0.35 lần cỡ chữ, nên ngưỡng này tương đương
# khoảng hai dấu cách liền nhau.
COLUMN_GAP_RATIO = 0.7

# Cỡ chữ dùng khi không đo được (trang rỗng), để công thức tỉ lệ vẫn có mốc.
FALLBACK_FONT_SIZE = 12.0


@dataclass
class PositionedChar:
    """Một ký tự kèm toạ độ và font gốc."""

    text: str
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    fontname: str
    size: float


@dataclass
class TextLine:
    """Một dòng text đã gom từ các ký tự cùng cao độ."""

    text: str
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    chars: list[PositionedChar]

    @property
    def font_size(self) -> float:
        """Cỡ chữ đại diện của dòng — dùng trung vị để chịu được chữ lẫn cỡ."""
        return median_font_size(self.chars)

    def segments(self, gap_min: float | None = None) -> list[list[PositionedChar]]:
        """Tách dòng thành các đoạn theo khoảng trắng ngang lớn.

        Cần thiết vì một dòng vật lý trong PDF có thể chứa nhiều cột độc lập —
        ví dụ dòng đầu chứng thư có "Số HĐ: ..." ở cột trái và quốc hiệu ở cột
        phải. Cắt theo khoảng trắng ngang giúp lấy đúng giá trị của cột mang
        nhãn, thay vì nuốt luôn nội dung cột bên cạnh.

        Trả về nhóm ký tự (không phải chuỗi) để bên gọi còn tính được bbox.
        """
        if not self.chars:
            return []

        if gap_min is None:
            gap_min = self.font_size * COLUMN_GAP_RATIO

        segments: list[list[PositionedChar]] = []
        buffer = [self.chars[0]]

        for prev, cur in zip(self.chars, self.chars[1:]):
            if cur.x0 - prev.x1 >= gap_min:
                segments.append(buffer)
                buffer = [cur]
            else:
                buffer.append(cur)

        segments.append(buffer)
        return segments


def median_font_size(chars: list[PositionedChar]) -> float:
    """Trung vị cỡ chữ. Dùng trung vị thay vì trung bình để tiêu đề cỡ lớn
    không kéo lệch ngưỡng của phần thân tài liệu."""
    sizes = [c.size for c in chars if c.size > 0]
    return statistics.median(sizes) if sizes else FALLBACK_FONT_SIZE


def segment_text(chars: list[PositionedChar]) -> str:
    """Nội dung text của một nhóm ký tự."""
    return "".join(c.text for c in chars)


def normalize(text: str) -> str:
    """Chuẩn hoá NFC — bắt buộc với tiếng Việt.

    Ký tự `ế` có thể được lưu thành một code point (U+1EBF) hoặc hai
    (`e` + dấu tổ hợp). Không chuẩn hoá thì mọi phép so sánh chuỗi sẽ báo
    lệch giả và cổng nguồn gốc sẽ từ chối oan các giá trị đúng.
    """
    return unicodedata.normalize("NFC", text)


def extract_positioned_chars(pdf_path: str) -> list[PositionedChar]:
    """Đọc toàn bộ ký tự kèm toạ độ từ mọi trang."""
    chars: list[PositionedChar] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for c in page.chars:
                chars.append(
                    PositionedChar(
                        text=normalize(c["text"]),
                        page=page_number,
                        x0=float(c["x0"]),
                        x1=float(c["x1"]),
                        top=float(c["top"]),
                        bottom=float(c["bottom"]),
                        fontname=str(c.get("fontname", "")),
                        size=float(c.get("size", 0.0)),
                    )
                )

    return fold_combining_marks(chars)


def fold_combining_marks(chars: list[PositionedChar]) -> list[PositionedChar]:
    """Gộp dấu tổ hợp vào ký tự gốc đứng trước, rồi chuẩn hoá NFC.

    Bắt buộc với tiếng Việt viết ở dạng NFD: `ồ` được lưu thành `o` + dấu mũ +
    dấu huyền, mỗi dấu là một glyph riêng trong PDF. Chuẩn hoá NFC trên TỪNG
    ký tự không ghép được gì — phải ghép cả chùm rồi mới chuẩn hoá.

    Không gộp thì canonical text mang dấu rời, còn pypdf và Poppler tự ghép,
    dẫn tới cổng đối chứng báo lệch dù nội dung y hệt nhau.

    Sau khi gộp, mỗi PositionedChar ứng với một ký tự NHÌN THẤY được, nên chỉ
    số ký tự trong dòng vẫn dùng được để cắt chuỗi ở tầng template.
    """
    folded: list[PositionedChar] = []

    for char in chars:
        is_mark = bool(char.text) and unicodedata.combining(char.text[0]) != 0

        if is_mark and folded:
            base = folded[-1]
            # Dấu tổ hợp chiếm cùng vùng với ký tự gốc; hợp nhất bbox để bằng
            # chứng toạ độ vẫn khoanh đúng ký tự hoàn chỉnh.
            folded[-1] = PositionedChar(
                text=unicodedata.normalize("NFC", base.text + char.text),
                page=base.page,
                x0=min(base.x0, char.x0),
                x1=max(base.x1, char.x1),
                top=min(base.top, char.top),
                bottom=max(base.bottom, char.bottom),
                fontname=base.fontname,
                size=base.size,
            )
            continue

        folded.append(char)

    return folded


def group_chars_into_lines(chars: list[PositionedChar]) -> list[TextLine]:
    """Gom ký tự thành dòng theo cao độ, rồi sắp trong dòng theo trục ngang.

    Không dùng text-extraction sẵn của thư viện vì cần giữ liên kết ngược
    từ dòng về từng ký tự để lấy bbox chính xác cho giá trị con.
    """
    lines: list[TextLine] = []

    by_page: dict[int, list[PositionedChar]] = {}
    for c in chars:
        by_page.setdefault(c.page, []).append(c)

    for page in sorted(by_page):
        page_chars = sorted(by_page[page], key=lambda c: (c.top, c.x0))
        # Ngưỡng gom dòng tính theo cỡ chữ của chính trang đó.
        tolerance = median_font_size(page_chars) * LINE_CLUSTER_RATIO
        buckets: list[list[PositionedChar]] = []
        # Ký tự lớn nhất của mỗi nhóm, dùng làm mốc so — nó đại diện dải chữ
        # chính của dòng, còn chỉ số trên/dưới thì nhỏ và lệch khỏi dải đó.
        anchors: list[PositionedChar] = []

        for c in page_chars:
            placed = False
            for index, bucket in enumerate(buckets):
                anchor = anchors[index]
                same_line = (
                    abs(_vertical_center(anchor) - _vertical_center(c)) <= tolerance
                    or _vertical_overlap_ratio(anchor, c) >= MIN_VERTICAL_OVERLAP_RATIO
                )
                if same_line:
                    bucket.append(c)
                    if c.size > anchor.size:
                        anchors[index] = c
                    placed = True
                    break
            if not placed:
                buckets.append([c])
                anchors.append(c)

        for bucket in buckets:
            bucket.sort(key=lambda c: c.x0)
            lines.append(
                TextLine(
                    text="".join(c.text for c in bucket),
                    page=page,
                    x0=min(c.x0 for c in bucket),
                    x1=max(c.x1 for c in bucket),
                    top=min(c.top for c in bucket),
                    bottom=max(c.bottom for c in bucket),
                    chars=bucket,
                )
            )

    lines.sort(key=lambda ln: (ln.page, ln.top, ln.x0))
    return lines


def _vertical_center(c: PositionedChar) -> float:
    return (c.top + c.bottom) / 2.0


def _vertical_overlap_ratio(anchor: PositionedChar, other: PositionedChar) -> float:
    """Phần chồng lấn dọc giữa hai ký tự, chia theo chiều cao ký tự NHỎ hơn.

    Chia theo ký tự nhỏ hơn để chỉ số trên/dưới — vốn chỉ cao khoảng 60% chữ
    thường — vẫn đạt tỉ lệ cao khi nó nằm trong dải chữ chính.
    """
    overlap = min(anchor.bottom, other.bottom) - max(anchor.top, other.top)
    if overlap <= 0:
        return 0.0

    shorter = min(anchor.bottom - anchor.top, other.bottom - other.top)
    return overlap / shorter if shorter > 0 else 0.0


def canonical_text(lines: list[TextLine]) -> str:
    """Text chuẩn dùng làm căn cứ đối chứng và kiểm tra nguồn gốc."""
    return "\n".join(ln.text for ln in lines)
