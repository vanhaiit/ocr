"""Dựng bản Markdown đọc gần giống bản gốc — cho khách hàng tự đối chiếu.

Không dùng khối `text_layer` làm nguồn: nó trung thành với TỪNG KÝ TỰ nhưng
giữ nguyên thứ tự đọc thô của engine (cột trái/phải bị xen kẽ, nhãn bị ngắt
dòng nối chữ dính nhau) — đọc rối hơn bản giấy gốc. Nhãn, giá trị, bảng, khối
chữ ký trong `data` đã được TÁCH ĐÚNG rồi; dựng lại theo đúng cấu trúc mục —
tiêu đề, gạch đầu dòng, bảng, khối ký — cho ra bản đọc gần với bản gốc hơn.

Dựa trên hình dạng JSON đã ổn định giữa các template (`preface`, `sections`,
`signatures`, `page_footers` — xem README), không đọc tên field tiếng Anh nào.
"""

from __future__ import annotations

from typing import Any


def render_markdown(name: str, result_json: dict[str, Any]) -> str:
    data = result_json.get("data") or {}
    verification = result_json["verification"]
    provenance = verification.get("provenance") or {}
    status = result_json["status"]

    lines = [f"# {name}", ""]

    if status == "verified":
        lines.append(
            f"_Đã đọc và xác minh đủ nội dung — "
            f"{provenance.get('verbatim_values', 0)}/{provenance.get('total_values', 0)} "
            "giá trị chứng minh được là nguyên văn._"
        )
    else:
        lines.append(f"⚠️ **Trạng thái: {status}** — xem lỗi bên dưới trước khi dùng nội dung.")
        for error in result_json.get("errors") or []:
            lines.append(f"- {error}")

    lines += ["", "---", ""]

    lines += _block_lines(data.get("preface") or {})

    for number, section in (data.get("sections") or {}).items():
        title = _text(section.get("title"))
        lines.append("")
        lines.append(f"## {number}. {title}" if title else f"## {number}")
        lines += _block_lines(section)

    signatures = data.get("signatures")
    if signatures:
        lines += ["", "---", ""]
        lines += _signatures_lines(signatures)

    form_fields = data.get("form_fields") or {}
    if form_fields:
        lines += ["", "## Ô điền thông tin (form field)", ""]
        for key, field in form_fields.items():
            text = _text(field)
            if text:
                lines.append(f"- **{key}:** {text}")

    hyperlinks = data.get("hyperlinks") or []
    if hyperlinks:
        lines += ["", "## Đường dẫn (hyperlink)", ""]
        for link in hyperlinks:
            text = _text(link)
            if text:
                lines.append(f"- {text}")

    footers = data.get("page_footers")
    if footers:
        lines.append("")
        lines.append(" · ".join(_text(f) for f in footers if _text(f)))

    return "\n".join(lines).rstrip() + "\n"


def _text(node: Any) -> str:
    """Chuỗi thô của một node (`SourcedValue`/`LabelledValue`) hoặc chuỗi thường."""
    if not node:
        return ""
    if isinstance(node, dict):
        return str(node.get("value") or "").strip()
    return str(node).strip()


def _block_lines(block: dict) -> list[str]:
    """Nội dung một khối (mở đầu hoặc một mục): field, đoạn văn, mục liệt kê, bảng."""
    lines: list[str] = []

    # Đoạn văn trước: đây thường là phần mở đầu/tiêu đề của khối (thư đầu là
    # quốc hiệu và tên chứng thư; mục X là câu dẫn trước bảng) — đọc trước field
    # thì gần thứ tự bản gốc hơn là field trước (JSON không giữ thứ tự xen kẽ
    # thật giữa field và đoạn văn, đây là thứ tự mặc định tốt nhất có thể).
    paragraphs = block.get("paragraphs") or []
    for paragraph in paragraphs:
        text = _text(paragraph)
        if text:
            lines += ["", text]

    fields = {**(block.get("fields") or {}), **(block.get("unmapped_fields") or {})}
    for key, field in fields.items():
        if not field:
            continue
        label = field.get("label", key)
        value = field.get("value")
        # `value: None` là tiêu đề phụ trong khối field (ví dụ "Các phụ lục kèm
        # theo:"), không phải cặp nhãn-giá trị — in như một dòng riêng, không
        # gạch đầu dòng.
        lines.append(f"**{label}:**" if value is None else f"- **{label}:** {value}")

    items = block.get("items") or []
    for item in items:
        text = _text(item)
        if text:
            lines.append(f"- {text}")

    # `value` hợp nhất field/đoạn văn của mục khi mục chỉ có đúng một giá trị
    # (mục không có tiêu đề phụ riêng) — bỏ qua khi field/đoạn văn/mục liệt kê
    # đã có, vì khi đó nó chỉ lặp lại đúng nội dung đã in ở trên.
    if not fields and not paragraphs and not items:
        text = _text(block.get("value"))
        if text:
            lines += ["", text]

    table = block.get("table")
    if table:
        lines.append("")
        lines += _table_lines(table)

    return lines


def _table_lines(table: dict) -> list[str]:
    columns = [_text(c) for c in table.get("columns") or []]
    lines = []
    if columns:
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("|" + "|".join(["---"] * len(columns)) + "|")

    for row in table.get("rows") or []:
        cells = [
            str(cell) if not isinstance(cell, dict) else _text(cell)
            for key, cell in row.items()
        ]
        lines.append("| " + " | ".join(cells) + " |")

    totals = table.get("totals") or {}
    if totals:
        lines.append("")
        for total in totals.values():
            if total:
                lines.append(f"**{total.get('label')}:** {total.get('value')}")


    return lines


def _signatures_lines(signatures: list[dict]) -> list[str]:
    """Khối chữ ký nhiều người, mỗi người một cột — dựng bảng để đọc song song.

    Dòng đầu của `lines` (vai trò) làm tiêu đề cột, tránh lặp lại chính nó ở
    hàng đầu tiên của bảng.
    """
    columns = [[_text(line) for line in (sig.get("lines") or [])] for sig in signatures]
    height = max((len(col) for col in columns), default=0)
    if height == 0:
        return []

    header = [col[0] if col else "" for col in columns]
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for i in range(1, height):
        row = [col[i] if i < len(col) else "" for col in columns]
        lines.append("| " + " | ".join(row) + " |")

    return lines
