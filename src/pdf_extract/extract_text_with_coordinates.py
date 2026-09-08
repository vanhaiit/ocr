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
    """Một ký tự kèm toạ độ, font, và HƯỚNG VIẾT.

    Hướng viết lấy từ ma trận biến đổi của PDF. Cần thiết vì tiêu đề cột hẹp
    thường được quay 90 độ: với chữ quay, thứ tự đọc chạy theo trục DỌC, nên
    sắp theo x như chữ thường sẽ cho ra chuỗi ĐẢO NGƯỢC ("TTS" thay vì "STT").
    """

    text: str
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    fontname: str
    size: float
    # Vector chỉ hướng đường cơ sở, lấy từ ma trận biến đổi text của PDF.
    # Giữ nguyên vector thay vì chỉ một cờ để còn sắp được chữ quay CHÉO
    # (watermark 45 độ) — với chữ chéo thì cả trục ngang và dọc đều đáng kể.
    direction_x: float = 1.0
    direction_y: float = 0.0

    @property
    def upright(self) -> bool:
        """Chữ thường: thành phần ngang của hướng viết trội hơn hoặc bằng dọc."""
        return abs(self.direction_y) <= abs(self.direction_x)

    @property
    def reads_upward(self) -> bool:
        """Chữ quay dọc đọc từ dưới lên trên trang."""
        return self.direction_y > 0

    @property
    def reading_position(self) -> float:
        """Vị trí của ký tự dọc theo hướng viết, dùng để sắp thứ tự đọc.

        Chiếu tâm ký tự lên vector hướng viết. Trục dọc đảo dấu vì hệ toạ độ
        của pipeline có gốc ở trên (`top` tăng khi đi xuống trang) còn hướng
        viết lấy từ hệ PDF có gốc ở dưới.
        """
        center_x = (self.x0 + self.x1) / 2
        center_y = (self.top + self.bottom) / 2
        return self.direction_x * center_x - self.direction_y * center_y


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
                        **_writing_direction(c.get("matrix")),
                    )
                )

    return fold_combining_marks(chars)


def _writing_direction(matrix) -> dict[str, float]:
    """Lấy vector chỉ hướng đường cơ sở từ ma trận biến đổi text của PDF.

    Hai thành phần đầu của ma trận chính là vector đó. Giữ nguyên cả hai thành
    phần (không rút thành cờ) để còn sắp đúng thứ tự đọc cho chữ quay chéo.
    """
    if not matrix or len(matrix) < 2:
        return {"direction_x": 1.0, "direction_y": 0.0}

    return {"direction_x": float(matrix[0]), "direction_y": float(matrix[1])}


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
            # Giữ NGUYÊN toạ độ của ký tự gốc, không hợp nhất với dấu.
            #
            # Với chữ quay 90 độ, dấu tổ hợp được vẽ lệch sang BÊN cạnh ký tự
            # gốc (thay vì phía trên như chữ thường). Hợp nhất bbox sẽ dịch tâm
            # ngang của ký tự ra khỏi dải cột, làm nó rơi vào nhóm khác khi gom
            # dòng — "Tên tài sản" quay dọc từng ra thành "Tn ti sn" rồi "ảàê".
            #
            # Ký tự gốc là thứ định vị chữ; dấu chỉ là nét phụ vẽ kề bên, nên
            # neo vào gốc cho kết quả ổn định ở cả chữ thường và chữ quay.
            folded[-1] = PositionedChar(
                text=unicodedata.normalize("NFC", base.text + char.text),
                page=base.page,
                x0=base.x0,
                x1=base.x1,
                top=base.top,
                bottom=base.bottom,
                fontname=base.fontname,
                size=base.size,
                direction_x=base.direction_x,
                direction_y=base.direction_y,
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
        upright_chars = [c for c in by_page[page] if c.upright]
        rotated_chars = [c for c in by_page[page] if not c.upright]

        for group in cluster_rotated_chars(rotated_chars):
            lines.append(_line_from(group, page))

        page_chars = sorted(upright_chars, key=lambda c: (c.top, c.x0))
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
            lines.append(_line_from(bucket, page))

    lines.sort(key=lambda ln: (ln.page, ln.top, ln.x0))
    return lines


def _line_from(chars: list[PositionedChar], page: int) -> TextLine:
    """Dựng TextLine từ nhóm ký tự đã sắp đúng thứ tự đọc."""
    return TextLine(
        text="".join(c.text for c in chars),
        page=page,
        x0=min(c.x0 for c in chars),
        x1=max(c.x1 for c in chars),
        top=min(c.top for c in chars),
        bottom=max(c.bottom for c in chars),
        chars=chars,
    )


def cluster_rotated_chars(chars: list[PositionedChar]) -> list[list[PositionedChar]]:
    """Gom chữ QUAY thành từng dòng và sắp theo đúng thứ tự đọc.

    Chữ quay 90 độ chạy theo trục dọc, nên phải làm ngược lại chữ thường: gom
    theo tâm NGANG (mọi glyph của một dòng quay có x gần nhau) và sắp theo trục
    DỌC. Chữ đọc từ dưới lên thì sắp theo `top` giảm dần.

    Không làm vậy thì tiêu đề cột quay dọc ra chuỗi đảo ngược — "STT" thành
    "TTS", "Tên tài sản" thành "nảsiàtnêT".
    """
    if not chars:
        return []

    tolerance = median_font_size(chars) * LINE_CLUSTER_RATIO
    buckets: list[list[PositionedChar]] = []

    for char in sorted(chars, key=lambda c: ((c.x0 + c.x1) / 2, c.top)):
        center = (char.x0 + char.x1) / 2
        if buckets and abs(((buckets[-1][0].x0 + buckets[-1][0].x1) / 2) - center) <= tolerance:
            buckets[-1].append(char)
        else:
            buckets.append([char])

    for bucket in buckets:
        bucket.sort(key=lambda c: c.top, reverse=bucket[0].reads_upward)

    return buckets


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
