"""Template: Chứng thư thẩm định giá (bất động sản).

Nhận cấu trúc đã đọc từ `parse_document_sections` rồi gán tên tiếng Anh. Vai trò
của template chỉ là ĐẶT TÊN và gom bảng — không đi tìm nhãn, nên không thể bỏ
sót: nhãn nào chưa có tên tiếng Anh vẫn xuất ra trong `unmapped_fields`.

Đây là điểm khác so với bản đầu: trước đây template đi tìm một danh sách nhãn
định trước nên mọi thứ ngoài danh sách bị bỏ im lặng — mất cả "Kính gửi", các
dòng "Căn cứ", mục VI đến IX, mục XII, XIII và khối chữ ký.
"""

from __future__ import annotations

from typing import Any

from ..extract_text_with_coordinates import normalize
from ..models import LabelledValue, SourcedValue
from ..parse_document_sections import DocumentSection, LineBlock, ParsedDocument
from .chung_thu_field_names import (
    SECTION_NAMES,
    SIGNATURE_CARD_LABEL,
    comparable_label,
    field_name_for,
    signature_role_for,
    slugify_label,
)
from .template_base import DocumentContext, rejoin_prose_cell

TEMPLATE_ID = "chung_thu_tham_dinh_gia"

# Các cụm chỉ dấu để nhận diện template. Càng khớp nhiều, điểm tin cậy càng cao.
SIGNATURE_PHRASES = (
    "CHỨNG THƯ THẨM ĐỊNH GIÁ",
    "THÔNG TIN KHÁCH HÀNG",
    "THÔNG TIN VỀ TÀI SẢN THẨM ĐỊNH GIÁ",
    "THỜI ĐIỂM THẨM ĐỊNH GIÁ",
    "GIÁ TRỊ TÀI SẢN THẨM ĐỊNH GIÁ",
)

# Mục chứa bảng giá trị tài sản.
ASSET_TABLE_SECTION = "X"

# Bảng giá trị tài sản có 4 cột: STT | Tên tài sản | Diện tích | Thành tiền.
ASSET_TABLE_COLUMN_COUNT = 4

# Nhãn các dòng tổng ở cuối bảng giá trị, so theo TIỀN TỐ vì nhãn thật còn kèm
# đơn vị trong ngoặc ("Tổng cộng (đồng)").
TOTAL_ROW_LABEL_PREFIXES = {
    "tong cong": "total",
    "lam tron": "total_rounded",
    "bang chu": "total_in_words",
}


class ChungThuThamDinhGiaTemplate:
    """Template chứng thư thẩm định giá."""

    template_id = TEMPLATE_ID

    def matches(self, canonical_text: str) -> float:
        """Điểm tin cậy = tỉ lệ cụm chỉ dấu tìm thấy trong tài liệu."""
        haystack = normalize(canonical_text).replace(" ", "").upper()
        hits = sum(
            1 for phrase in SIGNATURE_PHRASES
            if normalize(phrase).replace(" ", "").upper() in haystack
        )
        return hits / len(SIGNATURE_PHRASES)

    def extract(self, context: DocumentContext) -> dict[str, Any]:
        """Dựng JSON theo đúng cấu trúc mục của tài liệu."""
        document = context.document

        return {
            "preface": _render_block(document.preface, section_number=None),
            "sections": {
                section.number: _render_section(section, context)
                for section in document.sections
            },
            "signatures": _render_signatures(document),
            # Trả về SourcedValue, KHÔNG gọi to_json() ở đây: cổng nguồn gốc
            # chỉ xác thực được node nó nhận ra, chuyển sẵn sang dict là cho giá
            # trị đi vòng qua cổng.
            "page_footers": list(document.page_footers),
            # Dữ liệu annotation: không nằm trong content stream nên phải lấy
            # bằng đường riêng, nếu không sẽ mất trắng.
            "form_fields": {f.name: f.value for f in context.form_fields},
            "hyperlinks": [
                SourcedValue(value=link.url, page=link.page, bbox=link.bbox)
                for link in context.hyperlinks
            ],
        }


def _render_section(section: DocumentSection, context: DocumentContext) -> dict[str, Any]:
    """Một mục: tiêu đề nguyên văn, tên tiếng Anh, các field, đoạn văn, mục liệt kê."""
    rendered: dict[str, Any] = {
        "name": SECTION_NAMES.get(section.number),
        "title": section.title,
        **_render_block(section.block, section_number=section.number),
    }

    # `value` là giá trị chính của mục, hợp nhất hai cách trình bày.
    #
    # Cùng một nội dung nhưng mỗi bản chứng thư đặt một chỗ khác nhau: mục VI
    # của bản 002 ghi giá trị ngay sau dấu hai chấm của tiêu đề, còn bản 001 ghi
    # xuống dòng dưới. Không hợp nhất thì bên tiêu thụ phải kiểm cả `value` lẫn
    # `paragraphs` cho mọi mục. `paragraphs` vẫn giữ nguyên để không mất chi tiết
    # về cách tài liệu chia đoạn.
    value = section.inline_value or _merge_paragraphs(section.block.paragraphs)
    if value is not None:
        rendered["value"] = value

    if section.number == ASSET_TABLE_SECTION:
        rendered["table"] = _render_asset_table(context.tables)

    return rendered


def _merge_paragraphs(paragraphs: list[SourcedValue]) -> SourcedValue | None:
    """Gộp các đoạn văn của mục thành một giá trị, giữ từng đoạn làm mảnh nguồn."""
    if not paragraphs:
        return None

    if len(paragraphs) == 1:
        return paragraphs[0]

    return SourcedValue(
        value=" ".join(p.value for p in paragraphs),
        page=paragraphs[0].page,
        bbox=paragraphs[0].bbox,
        # Mỗi đoạn là một mảnh nguồn: các đoạn có thể không liền nhau trong thứ
        # tự đọc, nên cổng nguồn gốc chứng minh theo từng mảnh.
        source_lines=[p.value for p in paragraphs],
    )


def _render_block(block: LineBlock, *, section_number: str | None) -> dict[str, Any]:
    """Gán tên cho từng field; nhãn chưa ánh xạ đi vào `unmapped_fields`."""
    fields: dict[str, Any] = {}
    unmapped: dict[str, Any] = {}

    for entry in block.fields:
        name = field_name_for(section_number, entry.label.value)
        target, key = (fields, name) if name else (unmapped, slugify_label(entry.label.value))

        # Trả về LabelledValue chứ không phải dict: cổng nguồn gốc chỉ xác thực
        # được các node nó nhận ra, dựng dict ở đây là cho giá trị đi vòng qua
        # cổng. Nhãn không có giá trị (dòng dẫn cho danh sách bên dưới) vẫn xuất
        # ra để không mất thông tin là nhãn đó có mặt trong tài liệu.
        target[key] = LabelledValue(label=entry.label, value=entry.value)

    return {
        "fields": fields,
        "unmapped_fields": unmapped,
        "paragraphs": list(block.paragraphs),
        "items": list(block.items),
    }


def _render_asset_table(tables: list) -> dict[str, Any]:
    """Bảng mục X: tiêu đề cột, các thửa đất, và các dòng tổng.

    Tiêu đề cột cũng là dữ liệu của tài liệu (nó cho biết đơn vị: "Diện tích
    (m2)", "Thành tiền (đồng)"), nên phải xuất ra chứ không chỉ dùng để bỏ qua.
    """
    return {
        "columns": _column_headers(tables),
        "rows": _asset_rows(tables),
        "totals": _totals(tables),
    }


def _column_headers(tables: list) -> list[Any]:
    """Hàng tiêu đề của bảng: hàng đầu tiên mà ô số thứ tự KHÔNG phải chữ số."""
    for table in tables:
        if table.shape[1] != ASSET_TABLE_COLUMN_COUNT:
            continue

        for row in table.rows:
            filled = [cell for cell in row if cell.value.strip()]
            if len(filled) < 2 or row[0].value.strip().isdigit():
                continue
            return list(filled)

    return []


def _asset_rows(tables: list) -> list[dict[str, Any]]:
    """Các dòng thửa đất từ bảng 4 cột.

    Chỉ nhận dòng có cột STT là số — cách này loại tự nhiên dòng tiêu đề và các
    dòng tổng, không cần đoán theo chỉ số dòng.
    """
    rows: list[dict[str, Any]] = []

    for table in tables:
        if table.shape[1] != ASSET_TABLE_COLUMN_COUNT:
            continue

        for row in table.rows:
            index_cell = row[0].value.strip()
            if not index_cell.isdigit():
                continue

            rows.append(
                {
                    "index": int(index_cell),
                    # Cột mô tả là văn xuôi -> ghép các dòng có dấu cách.
                    # Hai cột còn lại là số/mã -> giữ cách ghép liền.
                    "description": rejoin_prose_cell(row[1]),
                    "area_sqm": row[2],
                    "amount_vnd": row[3],
                }
            )

    return rows


def _totals(tables: list) -> dict[str, Any]:
    """Các dòng tổng cộng / làm tròn / bằng chữ ở cuối bảng."""
    totals: dict[str, Any] = {name: None for name in TOTAL_ROW_LABEL_PREFIXES.values()}

    for table in tables:
        for row in table.rows:
            if not row:
                continue

            first = row[0].value.strip()
            key = comparable_label(first.split(":")[0])
            name = next(
                (
                    value
                    for prefix, value in TOTAL_ROW_LABEL_PREFIXES.items()
                    if key.startswith(prefix)
                ),
                None,
            )

            if name is None or totals[name] is not None:
                continue

            # Giữ cả nhãn tiếng Việt: nó mang đơn vị ("Tổng cộng (đồng)") nên
            # là dữ liệu, không phải chỉ là mốc để nhận ra dòng.
            totals[name] = LabelledValue(
                label=SourcedValue(
                    value=first.split(":")[0].strip(), page=row[0].page, bbox=row[0].bbox
                ),
                value=_total_row_value(row, first),
            )

    return totals


def _total_row_value(row: list[SourcedValue], first_cell: str) -> SourcedValue | None:
    """Giá trị của dòng tổng: ở ô kế tiếp, hoặc nằm cùng ô sau dấu hai chấm."""
    for cell in row[1:]:
        if cell.value.strip():
            return cell

    separator = first_cell.find(":")
    if separator != -1 and first_cell[separator + 1:].strip():
        return SourcedValue(
            value=first_cell[separator + 1:].strip(), page=row[0].page, bbox=row[0].bbox
        )

    return None


def _render_signatures(document: ParsedDocument) -> list[dict[str, Any]]:
    """Khối chữ ký: gom theo CỘT để mỗi người thành một object.

    Khối này xếp hai người cạnh nhau — vai trò, số thẻ, "(Ký tên)", rồi họ tên,
    mỗi thứ một dòng. Đọc theo dòng thì hai người dính vào nhau, nên phải gom
    theo cột: cột thứ i của mọi dòng thuộc cùng một người.
    """
    if not document.signature_columns:
        return []

    people = max(len(row) for row in document.signature_columns)
    signatures: list[dict[str, Any]] = []

    for index in range(people):
        column = [row[index] for row in document.signature_columns if index < len(row)]
        if not column:
            continue

        signatures.append(_signature_from_column(column))

    return signatures


def _signature_from_column(column: list[SourcedValue]) -> dict[str, Any]:
    """Một người ký: vai trò, số thẻ, họ tên, cùng các dòng còn lại."""
    entry: dict[str, Any] = {
        "role": None,
        "role_label": None,
        "card_number": None,
        "name": None,
        # Giữ SourcedValue để cổng nguồn gốc xác thực; xem ghi chú ở page_footers.
        "lines": list(column),
    }

    for value in column:
        text = value.value
        key = comparable_label(text)

        if entry["role"] is None and signature_role_for(text) is not None:
            entry["role"] = signature_role_for(text)
            entry["role_label"] = text
        elif key.startswith(SIGNATURE_CARD_LABEL) and ":" in text:
            entry["card_number"] = SourcedValue(
                value=text.split(":", 1)[1].strip(), page=value.page, bbox=value.bbox
            )

    # Họ tên là dòng cuối của cột: các dòng trên đã là vai trò, số thẻ, chỉ dẫn ký.
    tail = column[-1]
    if signature_role_for(tail.value) is None and not comparable_label(
        tail.value
    ).startswith(SIGNATURE_CARD_LABEL):
        entry["name"] = tail

    return entry
