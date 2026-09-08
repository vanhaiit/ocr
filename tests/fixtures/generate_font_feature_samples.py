"""Sinh bộ PDF mẫu, mỗi file bật một nhóm tính năng trình bày.

Chạy:
    ./.venv/bin/python3 -m fixtures.generate_font_feature_samples samples/font-features

Mọi file chứa CÙNG một tập giá trị nghiệp vụ, chỉ khác cách vẽ chữ. Nhờ vậy
đối chiếu được: tính năng trình bày không được làm đổi giá trị bóc ra.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .certificate_pdf_builder import CertificatePdfBuilder, FeatureFlags
from .certificate_pdf_layout import draw_certificate

# Tên file -> nhóm tính năng. Mỗi biến thể cô lập một nhóm để khi test đỏ là
# biết ngay tính năng nào gây ra, thay vì phải mò trong file trộn tất cả.
VARIANTS: dict[str, FeatureFlags] = {
    "01-baseline": FeatureFlags(),
    "02-bold-italic": FeatureFlags(bold_italic=True),
    "03-superscript-subscript": FeatureFlags(superscript=True),
    "04-hyperlink": FeatureFlags(hyperlink=True),
    "05-shadow": FeatureFlags(shadow=True),
    "06-outline": FeatureFlags(outline=True),
    "07-form-fields": FeatureFlags(form_fields=True),
    "08-rotated-header": FeatureFlags(rotated_header=True),
    "09-invisible-layer": FeatureFlags(invisible_layer=True),
    "10-watermark": FeatureFlags(watermark=True),
    "11-decomposed-diacritics": FeatureFlags(decomposed_diacritics=True),
    # Trộn tất cả: ca xấu nhất, kiểm các tính năng không phá nhau khi cộng dồn.
    "12-kitchen-sink": FeatureFlags(
        bold_italic=True,
        superscript=True,
        hyperlink=True,
        shadow=True,
        outline=True,
        form_fields=True,
        rotated_header=True,
        invisible_layer=True,
        watermark=True,
        decomposed_diacritics=True,
    ),
}


def generate_all(output_dir: Path) -> list[Path]:
    """Sinh mọi biến thể vào thư mục đã cho, trả danh sách đường dẫn."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name, flags in VARIANTS.items():
        path = output_dir / f"{name}.pdf"
        builder = CertificatePdfBuilder(path, flags)
        draw_certificate(builder)
        written.append(builder.save())

    return written


def main(argv: list[str]) -> int:
    output_dir = Path(argv[1]) if len(argv) > 1 else Path("samples/font-features")

    for path in generate_all(output_dir):
        print(f"  {path}  ({path.stat().st_size:,} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
