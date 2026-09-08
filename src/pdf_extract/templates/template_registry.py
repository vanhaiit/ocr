"""Sổ đăng ký template và bộ nhận diện.

Thêm loại tài liệu mới: viết một file template thực hiện giao thức
`DocumentTemplate`, rồi thêm vào `REGISTERED_TEMPLATES` bên dưới. Pipeline
không cần sửa.

Nhận diện dựa trên điểm tin cậy do chính template tự tính. Nếu không template
nào đạt ngưỡng, tài liệu bị từ chối tường minh — thà nói "không nhận ra mẫu này"
còn hơn bóc bừa bằng mẫu gần đúng rồi cho ra dữ liệu sai.
"""

from __future__ import annotations

from .chung_thu_tham_dinh_gia import ChungThuThamDinhGiaTemplate
from .template_base import DocumentContext, DocumentTemplate

# Ngưỡng tin cậy tối thiểu để chấp nhận một template.
# 0.6 nghĩa là phải khớp đa số cụm chỉ dấu, chịu được biến thể nhỏ giữa các bản.
MIN_TEMPLATE_CONFIDENCE = 0.6

REGISTERED_TEMPLATES: list[DocumentTemplate] = [
    ChungThuThamDinhGiaTemplate(),
]


def detect_template(canonical_text: str) -> tuple[DocumentTemplate | None, float]:
    """Chọn template có điểm cao nhất, với điều kiện vượt ngưỡng."""
    if not REGISTERED_TEMPLATES:
        return None, 0.0

    scored = [(template, template.matches(canonical_text)) for template in REGISTERED_TEMPLATES]
    best_template, best_score = max(scored, key=lambda pair: pair[1])

    if best_score < MIN_TEMPLATE_CONFIDENCE:
        return None, best_score

    return best_template, best_score


def extract_with_template(template: DocumentTemplate, context: DocumentContext) -> dict:
    """Gọi bộ bóc field của template đã chọn."""
    return template.extract(context)
