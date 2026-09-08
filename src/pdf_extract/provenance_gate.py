"""Cổng nguồn gốc — hạt nhân của cam kết chính xác 100%.

Quy tắc bất biến: mọi giá trị chuỗi xuất ra JSON phải chứng minh được là NGUYÊN
VĂN của PDF. Giá trị nào không chứng minh được thì không được coi là dữ liệu tin
được — nó bị đánh dấu và cả file chuyển sang trạng thái cần người review.

Có hai mức chứng minh, ưu tiên mức mạnh:

  1. Theo toạ độ (mạnh) — giá trị có bbox: so với đúng các ký tự nằm trong vùng
     bbox đó. Đây là bằng chứng chặt nhất: "chuỗi này chính là những gì PDF vẽ
     tại vùng này". Bắt buộc dùng cho ô bảng, vì ô đọc dọc theo cột nên không
     phải substring liền mạch của text đọc ngang.

  2. Theo chuỗi con (yếu hơn) — giá trị không có bbox: phải là substring nguyên
     văn của text đã trích xuất xác định.

Ý nghĩa thực tế: pipeline không có đường nào tạo ra giá trị "tự nghĩ". Nếu sau
này thêm tầng LLM để suy luận field, cổng này tự động bắt mọi giá trị bị bịa,
vì chuỗi bịa không khớp với ký tự PDF vẽ ra.
"""

from __future__ import annotations

from typing import Any

from .extract_text_with_coordinates import PositionedChar, normalize
from .models import LabelledValue, ProvenanceReport, SourcedValue

# Nới bbox vài điểm khi lọc ký tự: biên ô bảng do đường kẻ định nghĩa, có thể
# cắt sát mép glyph nên tâm ký tự vẫn nằm trong nhưng cạnh thì tràn ra.
BBOX_TOLERANCE = 1.5


def _searchable(text: str) -> str:
    """Dạng dùng để so nguyên văn: chuẩn hoá NFC, gộp mọi khoảng trắng về một dấu cách."""
    return " ".join(normalize(text).split())


def _collapsed(text: str) -> str:
    """Bỏ sạch khoảng trắng — dùng khi giá trị bị PDF ngắt dòng giữa từ."""
    return _searchable(text).replace(" ", "")


class CharIndex:
    """Tra ký tự theo trang, phục vụ chứng minh nguồn gốc theo toạ độ."""

    def __init__(self, chars: list[PositionedChar]) -> None:
        self._by_page: dict[int, list[PositionedChar]] = {}
        for char in chars:
            self._by_page.setdefault(char.page, []).append(char)

    def text_in_bbox(self, page: int, x0: float, top: float, x1: float, bottom: float) -> str:
        """Ghép các ký tự có tâm nằm trong vùng, đọc theo thứ tự trên xuống, trái sang."""
        inside = [
            char
            for char in self._by_page.get(page, [])
            if x0 - BBOX_TOLERANCE <= (char.x0 + char.x1) / 2 <= x1 + BBOX_TOLERANCE
            and top - BBOX_TOLERANCE <= (char.top + char.bottom) / 2 <= bottom + BBOX_TOLERANCE
        ]
        inside.sort(key=lambda c: (round(c.top, 1), c.x0))
        return "".join(c.text for c in inside)


def verify_value(value: SourcedValue, canonical: str, index: CharIndex | None) -> SourcedValue:
    """Đánh dấu `verbatim` nếu chứng minh được giá trị là nguyên văn của PDF."""
    needle = _searchable(value.value)
    if not needle:
        value.verbatim = False
        return value

    # Mức 1: chứng minh theo toạ độ.
    if index is not None and value.bbox is not None:
        region_text = index.text_in_bbox(
            value.page,
            value.bbox.x0,
            value.bbox.top,
            value.bbox.x1,
            value.bbox.bottom,
        )
        if _collapsed(region_text) == _collapsed(needle):
            value.verbatim = True
            return value

    # Mức 2: chứng minh theo chuỗi con của text chuẩn.
    haystack = _searchable(canonical)
    if needle in haystack or _collapsed(needle) in _collapsed(haystack):
        value.verbatim = True
        return value

    # Mức 3: chứng minh THEO TỪNG MẢNH NGUỒN.
    #
    # Một giá trị có thể được ghép từ nhiều mảnh KHÔNG liền nhau trong thứ tự
    # đọc — nhãn "Hồ sơ pháp lý khách" + "hàng cung cấp" bị phần giá trị chen
    # vào giữa. Khi đó nó không thể là substring liền mạch, nhưng vẫn chứng minh
    # được: mỗi mảnh phải là nguyên văn của tài liệu, VÀ chuỗi ghép lại phải
    # đúng bằng các mảnh đó nối với nhau. Không có chỗ nào cho ký tự lạ lọt vào.
    value.verbatim = _fragments_prove(value, haystack)
    return value


def _fragments_prove(value: SourcedValue, haystack: str) -> bool:
    """Mọi mảnh nguồn đều nguyên văn, và ghép lại đúng bằng giá trị."""
    if not value.source_lines:
        return False

    if any(_searchable(part) not in haystack for part in value.source_lines):
        return False

    joined = _collapsed(" ".join(value.source_lines))
    return joined == _collapsed(value.value)


def apply_gate(
    data: dict[str, Any],
    canonical: str,
    chars: list[PositionedChar] | None = None,
) -> tuple[dict[str, Any], ProvenanceReport]:
    """Duyệt đệ quy cây dữ liệu, xác thực mọi SourcedValue, trả JSON + báo cáo."""
    index = CharIndex(chars) if chars else None
    total = 0
    verbatim = 0
    unverified: list[str] = []

    def walk(node: Any, path: str) -> Any:
        nonlocal total, verbatim

        if isinstance(node, SourcedValue):
            total += 1
            checked = verify_value(node, canonical, index)
            if checked.verbatim:
                verbatim += 1
            else:
                unverified.append(path)
            return checked.to_json()

        if isinstance(node, LabelledValue):
            # Nhãn cũng là chuỗi cắt ra từ tài liệu nên phải chứng minh nguồn
            # như mọi giá trị khác. Xác thực nhãn trước, rồi làm phẳng thành JSON.
            label = walk(node.label, f"{path}.label")

            if node.value is None:
                return {"label": label["value"], "value": None}

            return {"label": label["value"], **walk(node.value, path)}

        if isinstance(node, dict):
            return {key: walk(child, f"{path}.{key}" if path else key) for key, child in node.items()}

        if isinstance(node, list):
            return [walk(child, f"{path}[{i}]") for i, child in enumerate(node)]

        return node

    verified_data = walk(data, "")
    report = ProvenanceReport(
        total_values=total,
        verbatim_values=verbatim,
        unverified_paths=unverified,
    )
    return verified_data, report
