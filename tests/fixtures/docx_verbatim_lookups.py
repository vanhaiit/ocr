"""Tra chi tiết NGUYÊN VĂN từ khối `text_layer` để bản DOCX không lệch bản gốc.

Bốn chi tiết mà JSON có cấu trúc đã tiêu thụ, nên phải tra lại từ text nguyên
văn — nếu tự dựng thì bản DOCX sẽ thêm hoặc thiếu ký tự so với PDF:

  - dấu mở đầu mục liệt kê ("-" hay "+"), và dòng nào vốn KHÔNG có dấu nào
  - dòng tiêu đề mục: có mục kết thúc bằng dấu hai chấm, có mục không
  - nhãn nào vốn viết kèm dấu hai chấm ngay sau nhãn

Chính bốn chỗ này là bốn lỗi của bản chuyển đổi đầu tiên, phát hiện bằng cách
đối chiếu từng ký tự với PDF gốc.
"""

from __future__ import annotations

from pdf_extract.parse_labeled_lines import SECTION_HEADING_PATTERN


def bullet_markers(data: dict) -> dict[str, str]:
    """Dấu mở đầu mục liệt kê của từng dòng, tra từ text nguyên văn.

    Chứng thư dùng cả "-" và "+" ("+ Phụ lục số 01"). Parser tách dấu ra khỏi
    giá trị để JSON gọn, nên muốn bản DOCX giống hệt thì phải tra lại từ khối
    `text_layer` — nơi giữ nguyên văn từng dòng.
    """
    markers: dict[str, str] = {}

    for page in data.get("text_layer", {}).get("pages", []):
        for line in page["text"]["value"].splitlines():
            stripped = line.strip()
            if not stripped or stripped[0] not in "-+•*●–":
                continue
            remainder = stripped[1:].strip()
            marker = stripped[0]

            # Tra được bằng cả nội dung đầy đủ của dòng và bằng riêng phần
            # NHÃN (trước dấu hai chấm) — vì bên gọi có khi chỉ có nhãn.
            markers[remainder] = marker
            markers[remainder.split(":")[0].strip()] = marker

    return markers


def marker_for(markers: dict[str, str], text: str) -> str:
    """Dấu mở đầu của một mục, hoặc rỗng nếu dòng gốc không có dấu nào.

    Tra theo TIỀN TỐ: giá trị trong JSON có thể là chuỗi đã ghép từ nhiều dòng,
    còn khoá tra được lập từ từng dòng riêng — nên khớp tuyệt đối sẽ trượt với
    mọi mục dài. Lấy khoá dài nhất là tiền tố của giá trị.

    Không mặc định "-": thêm một dấu mà tài liệu không có là thêm ký tự vào bản
    DOCX, và khi đó nội dung không còn y nguyên nữa.
    """
    needle = text.strip()
    exact = markers.get(needle)
    if exact is not None:
        return exact

    prefixes = [key for key in markers if key and needle.startswith(key)]
    if not prefixes:
        return ""

    return markers[max(prefixes, key=len)]


def labels_with_colon(data: dict) -> set[str]:
    """Các nhãn mà dòng gốc viết kèm dấu hai chấm ngay sau nhãn.

    Bảng giá trị có dòng "Bằng chữ: VALUE..." (nhãn và giá trị trong cùng một ô)
    bên cạnh "Tổng cộng (đồng)" (nhãn và giá trị ở hai ô). Muốn bản DOCX không
    thêm cũng không thiếu dấu hai chấm thì phải biết dòng nào vốn có.
    """
    labels: set[str] = set()

    for page in data.get("text_layer", {}).get("pages", []):
        for line in page["text"]["value"].splitlines():
            head, separator, _ = line.strip().partition(":")
            if separator:
                labels.add(head.strip())

    return labels


def heading_lines(data: dict) -> dict[str, str]:
    """Dòng tiêu đề nguyên văn của từng mục, tra theo số La Mã.

    Lấy nguyên văn thay vì tự dựng lại `"{số}. {tiêu đề}:"` — có mục kết thúc
    bằng dấu hai chấm, có mục không, và tự thêm dấu là thêm ký tự vào tài liệu.
    """
    headings: dict[str, str] = {}

    for page in data.get("text_layer", {}).get("pages", []):
        for line in page["text"]["value"].splitlines():
            stripped = line.strip()
            match = SECTION_HEADING_PATTERN.match(stripped)
            if match is not None:
                headings.setdefault(match.group(1), stripped)

    return headings

