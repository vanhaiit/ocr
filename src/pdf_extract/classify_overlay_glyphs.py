"""Tách chữ trang trí phủ lên trang (watermark) khỏi chữ nội dung.

Vì sao cần: watermark được vẽ cỡ chữ rất lớn và thường nằm chéo giữa trang, nên
tâm của từng glyph rơi vào bên trong ô bảng và vào giữa các dòng nội dung. Không
tách thì "BAN SAO" lọt vào ô "Tên tài sản", và đó là dạng sai ÂM THẦM tệ nhất:
giá trị vẫn nguyên văn của PDF nên cổng nguồn gốc không bắt được.

Dấu hiệu dùng để tách là CỠ CHỮ so với cỡ chữ chính của tài liệu, không dùng góc
quay: tiêu đề cột quay dọc là dữ liệu thật, nên quay hay không quay không phân
biệt được hai loại.

Glyph trang trí vẫn được giữ trong text dùng cho cổng đối chứng chéo — các engine
đối chứng đều đọc chúng, loại bỏ sẽ làm cổng báo lệch. Chúng chỉ bị loại khỏi
luồng dữ liệu nghiệp vụ.
"""

from __future__ import annotations

from .extract_text_with_coordinates import PositionedChar, median_font_size

# Cỡ chữ vượt bao nhiêu lần cỡ chữ chính thì coi là chữ trang trí.
# Watermark thường 3-5 lần cỡ thân tài liệu; tiêu đề lớn nhất trong chứng thư
# chỉ khoảng 1.25 lần. Ngưỡng 2.2 nằm giữa hai vùng đó với khoảng cách rộng.
OVERLAY_SIZE_RATIO = 2.2


def split_overlay_glyphs(
    chars: list[PositionedChar],
) -> tuple[list[PositionedChar], list[PositionedChar]]:
    """Chia glyph thành (nội dung, trang trí).

    Ngưỡng tính theo cỡ chữ trung vị của chính tài liệu, nên không cần chỉnh khi
    tài liệu dùng cỡ chữ khác.
    """
    if not chars:
        return [], []

    threshold = median_font_size(chars) * OVERLAY_SIZE_RATIO

    body = [c for c in chars if c.size <= threshold]
    overlay = [c for c in chars if c.size > threshold]

    return body, overlay
