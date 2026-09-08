"""Soát bảng ToUnicode của các font THỰC SỰ ĐƯỢC DÙNG để vẽ chữ.

Lý do phải có tầng này: PDF lưu chữ dưới dạng mã glyph (`<01> Tj`), và bảng
ToUnicode của font mới là thứ dịch mã đó ra Unicode (`<01> -> U+0043 = 'C'`).
Font thiếu bảng này vẫn hiển thị đúng khi in ra, nhưng khi copy sẽ ra ký tự
rác — và MỌI engine đều ra rác giống nhau, nên đối chứng chéo không phát hiện
được. Đây là điểm mù duy nhất của phép đối chứng, phải bịt bằng kiểm tra riêng.

Chỉ xét font thực dùng, không xét font chỉ được KHAI BÁO trong `/Resources`.
Trình sinh PDF thường khai báo sẵn font mặc định rồi không dùng đến (reportlab
khai `/Helvetica` trong mọi trang). Font không vẽ ký tự nào thì không thể làm
sai ký tự nào, nên tính nó vào là báo động giả và làm loãng tín hiệu thật.
"""

from __future__ import annotations

import re

import pypdf

from .models import FontAudit

# Font chỉ chứa ký hiệu trang trí (bullet, icon) thường không ảnh hưởng nội dung
# nghiệp vụ; vẫn báo cáo nhưng không tính là lỗi chặn.
DECORATIVE_FONT_MARKERS = ("Symbol", "Dingbat", "Wingding")

# Tiền tố 6 chữ in hoa + dấu cộng mà PDF thêm vào tên font khi nhúng bản rút gọn
# (subset), ví dụ `BAAAAA+TimesNewRomanPSMT`. Phải bỏ để so được tên font giữa
# bảng khai báo và tên mà engine trích xuất trả về.
SUBSET_PREFIX_PATTERN = re.compile(r"^[A-Z]{6}\+")


def normalize_font_name(name: str) -> str:
    """Đưa tên font về dạng so sánh được: bỏ dấu gạch chéo, tiền tố subset, hạ chữ."""
    cleaned = name.lstrip("/")
    cleaned = SUBSET_PREFIX_PATTERN.sub("", cleaned)
    return cleaned.lower()


def audit_fonts(pdf_path: str, used_font_names: set[str] | None = None) -> FontAudit:
    """Trả về tỉ lệ font có ToUnicode và danh sách font thiếu.

    `used_font_names` là tên font mà engine trích xuất thực sự gặp khi đọc glyph.
    Truyền vào thì chỉ những font đó bị soát; bỏ trống thì soát mọi font khai báo
    (chặt hơn, dùng khi chưa trích xuất xong).
    """
    reader = pypdf.PdfReader(pdf_path)
    fonts_seen: dict[str, bool] = {}

    for page in reader.pages:
        resources = page.get("/Resources") or {}
        font_dict = resources.get("/Font") or {}

        for font_ref in font_dict.values():
            font = font_ref.get_object()
            base_font = str(font.get("/BaseFont", "<unknown>"))
            has_tounicode = "/ToUnicode" in font
            # Nếu cùng base font xuất hiện nhiều lần, chỉ cần một lần thiếu là đáng lo.
            fonts_seen[base_font] = fonts_seen.get(base_font, True) and has_tounicode

    used = (
        {normalize_font_name(name) for name in used_font_names}
        if used_font_names is not None
        else None
    )

    considered = {
        name: ok
        for name, ok in fonts_seen.items()
        if used is None or normalize_font_name(name) in used
    }

    missing = [
        name
        for name, ok in sorted(considered.items())
        if not ok and not _is_decorative(name)
    ]

    return FontAudit(
        total_fonts=len(considered),
        fonts_with_tounicode=sum(1 for ok in considered.values() if ok),
        missing=missing,
        declared_but_unused=sorted(set(fonts_seen) - set(considered)),
    )


def _is_decorative(base_font: str) -> bool:
    """Font ký hiệu trang trí: thiếu ToUnicode không ảnh hưởng nội dung nghiệp vụ."""
    return any(marker.lower() in base_font.lower() for marker in DECORATIVE_FONT_MARKERS)
