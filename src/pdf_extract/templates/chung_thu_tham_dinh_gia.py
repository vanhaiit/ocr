"""Template: Chứng thư thẩm định giá (bất động sản).

Bóc theo nhãn có thật trong tài liệu, ứng với các mục I..XIII của chứng thư.
Không dùng vị trí tuyệt đối, không dùng LLM — mọi giá trị đều là chuỗi cắt ra
từ text đã trích xuất xác định, nên đi qua được cổng nguồn gốc.
"""

from __future__ import annotations

from typing import Any

from ..extract_text_with_coordinates import TextLine, normalize
from ..models import SourcedValue
from .template_base import (
    DocumentContext,
    rejoin_prose_cell,
    segment_value_containing,
    value_after_label,
    value_from_table_lookup,
)

TEMPLATE_ID = "chung_thu_tham_dinh_gia"

# Các cụm chỉ dấu để nhận diện template. Càng khớp nhiều, điểm tin cậy càng cao.
SIGNATURE_PHRASES = (
    "CHỨNG THƯ THẨM ĐỊNH GIÁ",
    "THÔNG TIN KHÁCH HÀNG",
    "THÔNG TIN VỀ TÀI SẢN THẨM ĐỊNH GIÁ",
    "THỜI ĐIỂM THẨM ĐỊNH GIÁ",
    "GIÁ TRỊ TÀI SẢN THẨM ĐỊNH GIÁ",
)

# Nhãn dòng đơn: tên field JSON -> nhãn xuất hiện trong tài liệu.
SINGLE_LINE_LABELS = {
    "contract_number": "Số HĐ",
    "certificate_number": "Số CTPH",
    "customer_name": "Tên khách hàng",
    "customer_address": "Địa chỉ",
    "asset_type": "Loại hình tài sản",
    "valuation_date": "THỜI ĐIỂM THẨM ĐỊNH GIÁ",
    "valuation_purpose": "MỤC ĐÍCH THẨM ĐỊNH GIÁ",
}

# Nhãn nằm trong bảng hai cột ở mục II.
COMPANY_TABLE_LABELS = {
    "company_branch": "Đơn vị thực hiện",
    "company_address": "Địa chỉ",
    "company_tax_id": "Mã số thuế",
    "company_representative": "Đại diện",
}

# Nhãn giấy tờ định danh khách hàng — tài liệu dùng lẫn "CCCD" và "CCCD/MST".
CUSTOMER_ID_LABELS = ("CCCD/MST", "CCCD")

# Nhãn các dòng tổng ở cuối bảng giá trị.
TOTAL_ROW_LABELS = {
    "total": "Tổng cộng",
    "total_rounded": "Làm tròn",
    "total_in_words": "Bằng chữ",
}

# Cụm mốc cho các field không theo khuôn "nhãn: giá trị".
ISSUE_PLACE_MARKER = "TP.HCM"

# Nhãn tài sản thẩm định — giá trị dài, thường vắt qua nhiều dòng.
# Giữ gạch đầu dòng để không khớp nhầm tiêu đề mục III
# ("THÔNG TIN VỀ TÀI SẢN THẨM ĐỊNH GIÁ") vốn chứa cùng cụm từ.
ASSET_LABEL = "- Tài sản thẩm định"
VALIDITY_MARKER = "tính từ ngày phát hành là"

# Bảng giá trị tài sản có 4 cột: STT | Tên tài sản | Diện tích | Thành tiền.
ASSET_TABLE_COLUMN_COUNT = 4


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
        """Bóc toàn bộ field của chứng thư."""
        lines, tables = context.lines, context.tables

        return {
            "certificate": self._extract_header_fields(lines),
            "customer": self._extract_customer(lines),
            "valuation_company": self._extract_company(lines, tables),
            "asset": self._extract_asset_info(lines),
            "valuation": self._extract_valuation_meta(lines),
            "assets_valued": self._extract_asset_rows(tables),
            "totals": self._extract_totals(tables),
            "validity_months": self._extract_validity(lines),
            # Dữ liệu annotation: không nằm trong content stream nên phải lấy
            # bằng đường riêng, nếu không sẽ mất trắng.
            "form_fields": self._extract_form_fields(context),
            "hyperlinks": self._extract_hyperlinks(context),
        }

    def _extract_form_fields(self, context: DocumentContext) -> dict[str, Any]:
        """Giá trị các ô điền thông tin, khoá theo tên field trong AcroForm."""
        return {field.name: field.value for field in context.form_fields}

    def _extract_hyperlinks(self, context: DocumentContext) -> list[Any]:
        """URL của các liên kết, kèm trang và vùng toạ độ."""
        return [
            SourcedValue(value=link.url, page=link.page, bbox=link.bbox)
            for link in context.hyperlinks
        ]

    def _extract_header_fields(self, lines: list[TextLine]) -> dict[str, Any]:
        return {
            "contract_number": value_after_label(lines, SINGLE_LINE_LABELS["contract_number"]),
            "certificate_number": value_after_label(lines, SINGLE_LINE_LABELS["certificate_number"]),
            # Dòng địa điểm/ngày không theo khuôn "nhãn: giá trị", lấy cả đoạn.
            "issue_place_and_date": segment_value_containing(lines, ISSUE_PLACE_MARKER),
        }

    def _extract_customer(self, lines: list[TextLine]) -> dict[str, Any]:
        customer_id = None
        for label in CUSTOMER_ID_LABELS:
            customer_id = value_after_label(lines, label)
            if customer_id is not None:
                break

        return {
            "name": value_after_label(lines, SINGLE_LINE_LABELS["customer_name"]),
            "address": value_after_label(lines, SINGLE_LINE_LABELS["customer_address"]),
            "identity_number": customer_id,
        }

    def _extract_company(self, lines: list[TextLine], tables: list) -> dict[str, Any]:
        """Mục II trình bày bằng bảng hai cột; rơi về tra theo dòng nếu bảng vắng."""
        result: dict[str, Any] = {}

        for field_name, label in COMPANY_TABLE_LABELS.items():
            value = value_from_table_lookup(tables, label)
            if value is None:
                value = value_after_label(lines, label)
            result[field_name] = value

        return result

    def _extract_asset_info(self, lines: list[TextLine]) -> dict[str, Any]:
        return {
            "asset_type": value_after_label(lines, SINGLE_LINE_LABELS["asset_type"]),
            "asset_under_valuation": value_after_label(
                lines, ASSET_LABEL, multiline=True
            ),
        }

    def _extract_valuation_meta(self, lines: list[TextLine]) -> dict[str, Any]:
        return {
            "valuation_date": value_after_label(lines, SINGLE_LINE_LABELS["valuation_date"]),
            "purpose": value_after_label(
                lines, SINGLE_LINE_LABELS["valuation_purpose"], multiline=True
            ),
        }

    def _extract_asset_rows(self, tables: list) -> list[dict[str, Any]]:
        """Bóc các dòng thửa đất từ bảng 4 cột ở mục X.

        Chỉ nhận dòng có cột STT là số — cách này loại tự nhiên các dòng tiêu đề
        và các dòng tổng, không cần đoán theo chỉ số dòng.
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

    def _extract_totals(self, tables: list) -> dict[str, Any]:
        """Lấy các dòng tổng cộng / làm tròn / bằng chữ.

        Dòng "Bằng chữ" gộp cả nhãn và giá trị trong một ô, nên phải cắt sau nhãn.
        """
        totals: dict[str, Any] = {key: None for key in TOTAL_ROW_LABELS}

        for table in tables:
            for row in table.rows:
                if not row:
                    continue

                first = normalize(row[0].value).strip()

                for field_name, label in TOTAL_ROW_LABELS.items():
                    if totals[field_name] is not None:
                        continue
                    if not first.lower().startswith(label.lower()):
                        continue

                    totals[field_name] = self._value_for_total_row(row, first, label)

        return totals

    def _value_for_total_row(self, row: list[SourcedValue], first: str, label: str) -> SourcedValue | None:
        """Giá trị của dòng tổng: ở ô kế tiếp, hoặc nằm cùng ô sau nhãn."""
        for cell in row[1:]:
            if cell.value.strip():
                return cell

        # Trường hợp "Bằng chữ: <giá trị>" nằm trong cùng một ô.
        separator = first.find(":")
        if separator != -1 and first[separator + 1:].strip():
            return SourcedValue(
                value=first[separator + 1:].strip(),
                page=row[0].page,
                bbox=row[0].bbox,
            )

        return None

    def _extract_validity(self, lines: list[TextLine]) -> SourcedValue | None:
        """Thời hạn hiệu lực nằm sau cụm mốc trong mục XI."""
        return value_after_label(lines, VALIDITY_MARKER)
