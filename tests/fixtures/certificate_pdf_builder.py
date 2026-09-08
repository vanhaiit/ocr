"""Dựng PDF chứng thư nhân tạo với các tính năng trình bày bật/tắt được.

Mục đích: mọi biến thể chứa CÙNG MỘT tập giá trị, chỉ khác CÁCH VẼ chữ. Nhờ vậy
test có thể khẳng định điều quan trọng nhất — tính năng trình bày (in đậm, chỉ
số trên, đổ bóng, hyperlink, form field...) không làm đổi giá trị bóc ra.

Dùng chính bố cục và nhãn của chứng thư thật để template hiện có nhận diện được,
thay vì dựng một tài liệu giả không liên quan.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.colors import Color, black, blue, grey
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .certificate_expected_values import EXPECTED, PAGE_HEIGHT, PAGE_WIDTH

SYSTEM_FONT_DIR = Path("/System/Library/Fonts/Supplemental")
FONT_FILES = {
    "Times": "Times New Roman.ttf",
    "Times-Bold": "Times New Roman Bold.ttf",
    "Times-Italic": "Times New Roman Italic.ttf",
    "Times-BoldItalic": "Times New Roman Bold Italic.ttf",
}

# Bố cục: cột nhãn bên trái, cột giá trị bên phải. Khoảng cách hai cột phải lớn
# hơn ngưỡng tách cột của pipeline (0.7 x cỡ chữ) để mô phỏng đúng cách chứng
# thư thật căn lề bằng khoảng trắng.
LABEL_X = 77.0
VALUE_X = 198.0
BODY_SIZE = 12.0
LINE_HEIGHT = 13.8

# Độ lệch lớp bóng, bằng giá trị điển hình của Word/LibreOffice.
SHADOW_OFFSET = 0.6

# Lề phải. Chữ vẽ vượt qua mốc này nằm ngoài vùng in: một số engine (Poppler)
# cắt bỏ, số khác (pdfplumber) vẫn đọc — sinh ra lệch giữa các engine. Tài liệu
# thật luôn wrap trong lề, nên fixture phải làm đúng như vậy.
RIGHT_MARGIN_X = 545.0

# Chỉ số trên/dưới: giảm cỡ chữ và dịch baseline, đúng cách trình xử lý văn bản
# tạo ra chúng (không dùng ký tự Unicode superscript vì font thiếu glyph).
SCRIPT_SIZE_RATIO = 0.6
SUPERSCRIPT_RISE = 4.5
SUBSCRIPT_RISE = -2.5

# Chế độ tô chữ của PDF (toán tử Tr).
RENDER_FILL = 0
RENDER_STROKE = 1  # viền chữ
RENDER_FILL_STROKE = 2
RENDER_INVISIBLE = 3  # chữ ẩn, thường thấy ở lớp OCR


@dataclass
class FeatureFlags:
    """Bật/tắt từng tính năng trình bày cần kiểm."""

    bold_italic: bool = False
    superscript: bool = False
    hyperlink: bool = False
    shadow: bool = False
    outline: bool = False
    form_fields: bool = False
    rotated_header: bool = False
    invisible_layer: bool = False
    watermark: bool = False
    decomposed_diacritics: bool = False  # viết tiếng Việt ở dạng NFD


def register_fonts() -> None:
    """Nạp 4 biến thể Times New Roman. Đều có glyph tiếng Việt và ToUnicode."""
    for name, filename in FONT_FILES.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(SYSTEM_FONT_DIR / filename)))


def _encode(text: str, flags: FeatureFlags) -> str:
    """Chuẩn bị chuỗi để vẽ. NFD tách dấu tiếng Việt thành ký tự tổ hợp riêng.

    Pipeline chuẩn hoá về NFC nên hai dạng phải cho ra cùng giá trị; đây là
    cách kiểm tra điều đó.
    """
    form = "NFD" if flags.decomposed_diacritics else "NFC"
    return unicodedata.normalize(form, text)


class CertificatePdfBuilder:
    """Vẽ một chứng thư hoàn chỉnh theo các cờ tính năng đã chọn."""

    def __init__(self, path: Path, flags: FeatureFlags) -> None:
        register_fonts()
        self.path = path
        self.flags = flags
        self.canvas = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
        self.y = PAGE_HEIGHT - 60.0

    # ---- các nguyên thuỷ vẽ chữ -------------------------------------------

    def _font_for(self, emphasis: str) -> str:
        """Chọn biến thể font. Chỉ đổi khi cờ in đậm/nghiêng được bật."""
        if not self.flags.bold_italic:
            return "Times"
        return {
            "bold": "Times-Bold",
            "italic": "Times-Italic",
            "bold_italic": "Times-BoldItalic",
        }.get(emphasis, "Times")

    def draw_text(
        self,
        x: float,
        text: str,
        *,
        emphasis: str = "",
        size: float = BODY_SIZE,
        y: float | None = None,
        render_mode: int = RENDER_FILL,
        color: Color = black,
    ) -> None:
        """Vẽ một chuỗi, áp dụng đổ bóng và viền chữ nếu được bật.

        Đổ bóng được tạo bằng cách vẽ CHÍNH CHUỖI ĐÓ hai lần ở vị trí lệch nhau
        — đúng cách Word tạo hiệu ứng, và là nguồn sinh ra glyph nhân đôi.
        """
        y = self.y if y is None else y
        font = self._font_for(emphasis)
        payload = _encode(text, self.flags)

        # Không đổ bóng cho chữ ẩn: bóng vẽ ở chế độ hiện sẽ làm lớp chữ ẩn
        # lộ ra, phá đúng tính chất mà biến thể này cần kiểm.
        if self.flags.shadow and render_mode != RENDER_INVISIBLE:
            self._draw_run(x + SHADOW_OFFSET, y - SHADOW_OFFSET, payload, font, size,
                           RENDER_FILL, grey)

        # Viền chữ chỉ áp cho chữ vẽ bình thường. Không được ghi đè chế độ tô
        # đã chỉ định rõ (ví dụ chữ ẩn mode 3) — nếu không, bật cờ viền sẽ làm
        # lớp chữ ẩn hiện ra.
        mode = RENDER_FILL_STROKE if self.flags.outline and render_mode == RENDER_FILL else render_mode
        self._draw_run(x, y, payload, font, size, mode, color)

    def _draw_run(
        self,
        x: float,
        y: float,
        text: str,
        font: str,
        size: float,
        render_mode: int,
        color: Color,
    ) -> None:
        # Bọc trong save/restore state. Bắt buộc: chế độ tô chữ (toán tử `Tr`)
        # thuộc TEXT STATE của PDF và TỒN TẠI XUYÊN QUA các khối BT/ET, nhưng
        # reportlab giả định mỗi khối text bắt đầu ở mode 0 nên không phát lại
        # toán tử. Không bọc thì `3 Tr` của lớp chữ ẩn rò rỉ sang mọi chữ vẽ
        # sau đó và cả trang thành trắng — lỗi của bản fixture đầu tiên.
        self.canvas.saveState()
        text_object = self.canvas.beginText(x, y)
        text_object.setFont(font, size)
        text_object.setTextRenderMode(render_mode)
        self.canvas.setFillColor(color)
        self.canvas.setStrokeColor(color)
        self.canvas.setLineWidth(0.25)
        text_object.textOut(text)
        self.canvas.drawText(text_object)
        self.canvas.restoreState()

    def draw_with_script(self, x: float, before: str, script: str, after: str,
                         *, superscript: bool = True) -> None:
        """Vẽ chuỗi có chỉ số trên hoặc dưới, ví dụ "m2" thành m vuông.

        Phần chỉ số dùng cỡ chữ nhỏ hơn và baseline dịch — nên nó nằm lệch dòng
        so với phần còn lại. Đây chính là ca thử ngưỡng gom dòng của pipeline.
        """
        cursor = x
        self.draw_text(cursor, before)
        cursor += self.canvas.stringWidth(_encode(before, self.flags), self._font_for(""), BODY_SIZE)

        rise = SUPERSCRIPT_RISE if superscript else SUBSCRIPT_RISE
        script_size = BODY_SIZE * SCRIPT_SIZE_RATIO
        self.draw_text(cursor, script, size=script_size, y=self.y + rise)
        cursor += self.canvas.stringWidth(_encode(script, self.flags), self._font_for(""), script_size)

        if after:
            self.draw_text(cursor, after)

    def draw_wrapped(
        self,
        x: float,
        text: str,
        *,
        emphasis: str = "",
        continuation_x: float | None = None,
    ) -> None:
        """Vẽ chuỗi dài, tự ngắt dòng trong lề phải.

        Dòng nối tiếp KHÔNG được bắt đầu bằng mốc mở đầu mục mới (số La Mã,
        gạch đầu dòng) — nếu không, bộ ghép nhiều dòng của pipeline sẽ dừng sớm
        và cắt mất phần cuối giá trị.
        """
        font = self._font_for(emphasis)
        indent = x if continuation_x is None else continuation_x
        words = text.split(" ")
        line: list[str] = []
        first_line = True

        for word in words:
            candidate = " ".join(line + [word])
            left = x if first_line else indent
            if line and left + self.canvas.stringWidth(
                _encode(candidate, self.flags), font, BODY_SIZE
            ) > RIGHT_MARGIN_X:
                self.draw_text(left, " ".join(line), emphasis=emphasis)
                self.newline()
                line = [word]
                first_line = False
            else:
                line.append(word)

        if line:
            self.draw_text(x if first_line else indent, " ".join(line), emphasis=emphasis)
            self.newline()

    def label_value(self, label: str, value: str, *, value_emphasis: str = "") -> None:
        """Vẽ một dòng "nhãn : giá trị" theo đúng cách căn cột của chứng thư."""
        self.draw_text(LABEL_X, label)
        self.draw_wrapped(VALUE_X, f": {value}", emphasis=value_emphasis)

    def newline(self, count: int = 1) -> None:
        self.y -= LINE_HEIGHT * count

    def save(self) -> Path:
        self.canvas.save()
        return self.path
