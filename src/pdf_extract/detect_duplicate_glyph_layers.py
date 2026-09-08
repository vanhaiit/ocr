"""Lọc glyph bị vẽ trùng — xử lý chữ đổ bóng và in đậm giả.

Vì sao cần tầng này: Word và LibreOffice tạo hiệu ứng đổ bóng, viền chữ và in
đậm giả bằng cách vẽ CÙNG MỘT CHUỖI hai lần ở vị trí lệch nhau chút ít. Trong
content stream đó là hai khối `Tj` riêng biệt, nên engine trích xuất đọc ra ký
tự nhân đôi:

    Chữ đổ bóng  ->  pdfplumber: 'SHADOWSHADOW'   (12 glyph)
                     pypdf:      'SHADOWSHADOW'
                     Poppler:    'SHADOW'          (tự lọc)

Đây là dạng hỏng âm thầm: chữ hiển thị hoàn toàn bình thường trên màn hình.
Poppler tự lọc còn hai engine kia thì không, nên nếu để nguyên thì cổng đối
chứng sẽ báo lệch và chặn oan mọi tài liệu có hiệu ứng chữ.

Lưu ý về in đậm và in nghiêng THẬT: chúng là các font riêng biệt trong PDF
(`TimesNewRomanPS-BoldMT`, `-ItalicMT`), mỗi font có bảng ToUnicode riêng và chỉ
được vẽ một lần — không ảnh hưởng gì đến trích xuất. Chỉ in đậm GIẢ (fake bold,
do phần mềm vẽ hai lần vì font không có bản đậm) mới sinh ra glyph trùng.
"""

from __future__ import annotations

from .extract_text_with_coordinates import PositionedChar
from .models import GlyphLayerReport

# Ngưỡng coi hai glyph là một, tính theo TỈ LỆ cỡ chữ thay vì điểm tuyệt đối,
# để không phải chỉnh lại khi tài liệu đổi font hoặc đổi cỡ chữ.
# Độ lệch của lớp bóng thường dưới 0.15 lần cỡ chữ; trong khi bước tiến của
# ký tự hẹp nhất (dấu chấm, chữ i) vẫn trên 0.25 lần cỡ chữ, nên khoảng an
# toàn giữa hai đại lượng là đủ rộng.
DUPLICATE_OFFSET_RATIO = 0.18

# Chặn trên tuyệt đối, phòng trường hợp cỡ chữ rất lớn (tiêu đề, watermark)
# khiến ngưỡng tỉ lệ nới quá rộng và xoá oan ký tự lặp hợp lệ.
DUPLICATE_OFFSET_MAX = 2.5


def _tolerance_for(char: PositionedChar) -> float:
    """Ngưỡng gộp cho một glyph, theo cỡ chữ của chính nó."""
    if char.size <= 0:
        return DUPLICATE_OFFSET_MAX
    return min(char.size * DUPLICATE_OFFSET_RATIO, DUPLICATE_OFFSET_MAX)


def deduplicate_glyphs(
    chars: list[PositionedChar],
) -> tuple[list[PositionedChar], GlyphLayerReport]:
    """Bỏ các glyph vẽ trùng, giữ lần vẽ đầu tiên.

    Hai glyph bị coi là trùng khi CÙNG ký tự, CÙNG trang, và lệch nhau dưới
    ngưỡng theo cả hai trục. Không xét màu: lớp bóng thường khác màu lớp chính,
    nhưng in đậm giả thì cùng màu, nên màu không phải dấu hiệu đáng tin.

    Giữ lần vẽ đầu tiên chứ không phải lần đậm nhất, vì thứ tự trong content
    stream không bảo đảm lớp nào là lớp chính — và nội dung text thì giống nhau
    nên lấy lần nào cũng cho cùng chuỗi.
    """
    kept: list[PositionedChar] = []
    # Gom theo (trang, ký tự) để mỗi glyph chỉ phải so với các glyph cùng loại,
    # thay vì so đôi một trên toàn tài liệu.
    seen: dict[tuple[int, str], list[PositionedChar]] = {}
    pages_affected: set[int] = set()
    removed = 0

    for char in chars:
        key = (char.page, char.text)
        candidates = seen.setdefault(key, [])

        tolerance = _tolerance_for(char)
        is_duplicate = any(
            abs(char.x0 - other.x0) <= tolerance and abs(char.top - other.top) <= tolerance
            for other in candidates
        )

        if is_duplicate:
            removed += 1
            pages_affected.add(char.page)
            continue

        candidates.append(char)
        kept.append(char)

    report = GlyphLayerReport(
        total_glyphs=len(chars),
        duplicate_glyphs_removed=removed,
        pages_affected=sorted(pages_affected),
    )
    return kept, report
