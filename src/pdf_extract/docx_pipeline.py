"""Pipeline cho DOCX. Dùng chung tầng template và cổng nguồn gốc với PDF.

Sáu cổng, ít hơn PDF ba cổng — và ba cổng thiếu đó được báo cáo là `null` chứ
KHÔNG báo xanh, vì với DOCX chúng không có gì để kiểm:

| Cổng | PDF | DOCX |
|---|---|---|
| 1. Nhận định dạng | phân biệt text layer / scan | gói ZIP có `word/document.xml` |
| 2. Soát bảng ToUnicode | có nghĩa | **null** — text đã là Unicode, không có bảng map |
| 3. Đọc nội dung | glyph kèm toạ độ | đoạn văn và bảng kèm đường dẫn XML |
| 4. Lọc glyph vẽ trùng | có nghĩa | **null** — đổ bóng là thuộc tính run, không vẽ hai lần |
| 5. Đối chứng chéo | 3 engine, hai chiều | pandoc + docx2txt, **một chiều** |
| 6. Dựng bảng | dò đường kẻ ô | `<w:tbl>` đã có cấu trúc |
| 7. Nhận template | dùng chung | dùng chung |
| 8. Bóc field | dùng chung | dùng chung |
| 9. Cổng nguồn gốc | bbox + chuỗi con | đường dẫn XML + chuỗi con |

Nói ngắn: DOCX dễ bóc hơn nhưng khó chứng minh hơn. Ghi rõ cổng nào không áp
dụng là phần quan trọng của tính trung thực — báo xanh một cổng không chạy sẽ
tạo cảm giác an toàn không có thật.
"""

from __future__ import annotations

from typing import Any

from .build_text_layer_block import build_text_layer_from_lines
from .cross_verify_docx_readers import cross_verify_docx
from .extract_docx_content import canonical_docx_text, extract_docx
from .models import ExtractionResult, ExtractionStatus, InputFormat, SourcedValue
from .parse_docx_sections import parse_docx_document
from .provenance_gate import apply_gate
from .templates.template_base import DocumentContext
from .templates.template_registry import detect_template, extract_with_template


def process_docx(path: str, source: dict[str, Any]) -> ExtractionResult:
    """Chạy pipeline DOCX và trả kết quả cùng dạng với nhánh PDF."""
    errors: list[str] = []

    # Bước 3: đọc nội dung — đoạn văn, bảng, chân trang, kèm đường dẫn XML.
    content = extract_docx(path)
    canonical = canonical_docx_text(content)
    source["paragraphs"] = len(content.paragraphs)
    source["tables"] = len(content.tables)

    # Cổng 5: đối chứng chéo, một chiều — engine khác tìm ra chữ ta không có
    # thì chặn; phần chúng thêm (pandoc vẽ khung bảng) chỉ ghi nhận.
    verify = cross_verify_docx(path, canonical)
    if not verify.char_multiset_match:
        failing = [c.engine for c in verify.comparisons if not c.char_multiset_match]
        errors.append(
            f"Bộ đọc {', '.join(failing)} tìm thấy ký tự mà engine chính không "
            "đọc ra — có nội dung bị bỏ sót. Xem only_in_engine."
        )
    if verify.engine_count == 0:
        errors.append(
            "Không có bộ đọc đối chứng nào khả dụng (cần pandoc hoặc docx2txt), "
            "nên không kiểm được việc bỏ sót nội dung."
        )

    # Bước 6: cấu trúc mục. Bảng đã có sẵn cấu trúc nên chỉ cần tách bảng dữ
    # liệu ra khỏi khối văn bản.
    parsed, data_tables = parse_docx_document(content)

    # Cổng 7: nhận diện template.
    template, confidence = detect_template(canonical)
    if template is None:
        errors.append(
            f"Không nhận ra mẫu tài liệu (điểm cao nhất {confidence:.2f} < ngưỡng). "
            "Cần thêm template cho loại này."
        )
        return ExtractionResult(
            source=source,
            input_format=InputFormat.DOCX,
            pdf_class=None,
            template_id=None,
            status=ExtractionStatus.REJECTED,
            data={},
            cross_verify=verify,
            errors=errors,
        )

    # Bước 8: bóc field — dùng chung tầng template với nhánh PDF.
    raw_data = extract_with_template(
        template, DocumentContext(lines=[], tables=data_tables, document=parsed)
    )
    raw_data["text_layer"] = _text_layer(content)

    # Cổng 9: nguồn gốc. Không có bbox nên chứng minh theo chuỗi con của text
    # chuẩn; bằng chứng vị trí là đường dẫn XML đi kèm từng giá trị.
    data, provenance = apply_gate(raw_data, canonical)
    if provenance.unverified_paths:
        errors.append(
            "Có giá trị không chứng minh được là nguyên văn của tài liệu: "
            f"{', '.join(provenance.unverified_paths)}"
        )

    status = ExtractionStatus.VERIFIED if not errors else ExtractionStatus.NEEDS_REVIEW

    return ExtractionResult(
        source=source,
        input_format=InputFormat.DOCX,
        pdf_class=None,
        template_id=template.template_id,
        status=status,
        data=data,
        cross_verify=verify,
        provenance=provenance,
        errors=errors,
    )


def _text_layer(content) -> dict[str, Any]:
    """Khối text nguyên văn, để độ phủ ký tự đạt 100% như nhánh PDF.

    DOCX không phân trang nên gộp thành một khối duy nhất thay vì chia theo
    trang — số trang chỉ có khi Word mở file.
    """
    return build_text_layer_from_lines(
        [
            SourcedValue(
                value=canonical_docx_text(content),
                page=0,
                source_lines=_source_lines(content),
            )
        ]
    )


def _source_lines(content) -> list[str]:
    """Từng đoạn và từng ô bảng làm mảnh nguồn, để cổng chứng minh theo mảnh."""
    lines = [paragraph.text for paragraph in content.paragraphs]

    for table in content.tables:
        lines.extend(
            cell.value for row in table.rows for cell in row if cell.value.strip()
        )

    lines.extend(footer.value for footer in content.footers)
    return lines
