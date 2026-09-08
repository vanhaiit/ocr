"""Điều phối toàn bộ pipeline PDF -> JSON.

Trình tự các cổng, mỗi cổng có quyền chặn:

  1. Phân loại    — chỉ nhận PDF có text layer, scan bị từ chối
  3. Trích xuất   — pdfplumber, giữ toạ độ từng ký tự (nguồn chân lý)
  2. Soát font    — font THỰC DÙNG phải có bảng ToUnicode (chạy sau bước 3 để
                    biết font nào thực sự vẽ chữ)
  4. Lọc glyph    — bỏ lớp vẽ trùng của chữ đổ bóng / in đậm giả
  5. Đối chứng    — pypdf + Poppler phải khớp một trong hai mốc (thô / đã lọc)
  6. Dựng bảng    — theo đường kẻ ô có thật
  7. Nhận template
  8. Bóc field    — cắt chuỗi theo nhãn, không suy luận
  9. Cổng nguồn gốc — mọi giá trị phải là nguyên văn của text đã lọc

Chỉ khi tất cả cổng xanh thì trạng thái mới là VERIFIED. Bất kỳ cổng nào đỏ đều
làm kết quả chuyển sang NEEDS_REVIEW hoặc REJECTED — không có đường nào cho ra
dữ liệu "trông như đúng" mà không chứng minh được.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .audit_font_tounicode import audit_fonts
from .detect_input_format import detect_format
from .docx_pipeline import process_docx
from .build_text_layer_block import build_text_layer
from .extract_annotation_data import extract_form_fields, extract_hyperlinks
from .classify_overlay_glyphs import split_overlay_glyphs
from .classify_pdf_text_layer import classify_pdf, rejection_reason
from .cross_verify_engines import cross_verify
from .detect_duplicate_glyph_layers import deduplicate_glyphs
from .extract_text_with_coordinates import (
    canonical_text,
    extract_positioned_chars,
    group_chars_into_lines,
)
from .models import ExtractionResult, ExtractionStatus, InputFormat, PdfClass
from .provenance_gate import apply_gate
from .parse_document_sections import DATA_TABLE_MIN_COLUMNS, parse_document
from .reconstruct_tables_by_ruling_lines import extract_tables, merge_continued_tables
from .templates.template_base import DocumentContext
from .templates.template_registry import detect_template, extract_with_template


def _file_fingerprint(pdf_path: str) -> dict[str, object]:
    """Thông tin nhận dạng file, để kết quả JSON truy được về đúng bản PDF đã xử lý."""
    path = Path(pdf_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"file": path.name, "sha256": digest, "bytes": path.stat().st_size}


def process_document(path: str) -> ExtractionResult:
    """Điểm vào duy nhất: nhận dạng định dạng rồi chạy nhánh tương ứng.

    PDF và DOCX có hai tầng đọc khác nhau nhưng dùng chung tầng template và cổng
    nguồn gốc, nên JSON trả về cùng một hình dạng — bên tiêu thụ không cần biết
    đầu vào là định dạng nào.
    """
    source = _file_fingerprint(path)
    fmt = detect_format(path)

    if fmt is InputFormat.DOCX:
        return process_docx(path, source)

    return process_pdf(path, source)


def process_pdf(pdf_path: str, source: dict | None = None) -> ExtractionResult:
    """Chạy nhánh PDF và trả kết quả kèm báo cáo kiểm chứng."""
    source = _file_fingerprint(pdf_path) if source is None else source

    # Cổng 1: loại PDF.
    pdf_class, chars_per_page = classify_pdf(pdf_path)
    source["pages"] = len(chars_per_page)

    reason = rejection_reason(pdf_class, chars_per_page)
    if reason is not None:
        return ExtractionResult(
            source=source,
            input_format=InputFormat.PDF,
            pdf_class=pdf_class,
            template_id=None,
            status=ExtractionStatus.REJECTED,
            data={},
            errors=[reason],
        )

    errors: list[str] = []

    # Bước 3: trích xuất kèm toạ độ — nguồn chân lý cho mọi bước sau.
    raw_chars = extract_positioned_chars(pdf_path)

    # Cổng 2: bảng ToUnicode của font.
    # Chạy sau bước trích xuất để biết font nào THỰC SỰ vẽ chữ; font chỉ được
    # khai báo mà không dùng thì không thể làm sai ký tự nào.
    usage: dict[str, int] = {}
    for char in raw_chars:
        usage[char.fontname] = usage.get(char.fontname, 0) + 1

    font_audit = audit_fonts(pdf_path, set(usage), usage)
    if not font_audit.is_complete:
        affected = ", ".join(
            f"{name} ({font_audit.affected_characters.get(name, 0)} ký tự)"
            for name in font_audit.missing
        )
        errors.append(
            f"Font thiếu bảng ToUnicode: {affected}. Ký tự do các font này vẽ "
            "KHÔNG đọc được đúng, và không tool nào sửa được từ chính file — "
            "bảng dịch mã glyph sang Unicode không nằm trong PDF. Phải sinh lại "
            "PDF với font có nhúng ToUnicode (DejaVu Sans, Noto Sans, hoặc Times "
            "New Roman nhúng)."
        )

    raw_canonical = canonical_text(group_chars_into_lines(raw_chars))


    # Bước 4: lọc lớp glyph vẽ trùng (chữ đổ bóng, in đậm giả).
    # Phải làm trước khi gom dòng, vì glyph nhân đôi làm sai cả text lẫn bbox.
    deduplicated_chars, glyph_layers = deduplicate_glyphs(raw_chars)
    deduplicated_canonical = canonical_text(group_chars_into_lines(deduplicated_chars))

    # Bước 4c: tách chữ trang trí (watermark) khỏi luồng dữ liệu nghiệp vụ.
    # Watermark cỡ lớn nằm chéo trang nên tâm glyph rơi vào trong ô bảng và giữa
    # các dòng; để lẫn thì "BAN SAO" lọt vào giá trị field mà cổng nguồn gốc
    # không bắt được (nó vẫn là chữ nguyên văn của PDF).
    chars, overlay_chars = split_overlay_glyphs(deduplicated_chars)
    glyph_layers.overlay_glyphs_excluded = len(overlay_chars)
    lines = group_chars_into_lines(chars)
    canonical = canonical_text(lines)

    # Bước 4b: dữ liệu annotation — form field và hyperlink.
    # Nằm ngoài content stream nên mọi bộ trích xuất text đều bỏ qua; không đọc
    # riêng thì mất trắng giá trị người dùng đã điền.
    form_fields = extract_form_fields(pdf_path)
    hyperlinks = extract_hyperlinks(pdf_path)

    # Cổng 5: đối chứng chéo giữa các engine độc lập.
    # So với nhiều mốc vì các engine bao gồm phần dữ liệu khác nhau (lớp bóng,
    # form field); engine nào khớp mốc nào được ghi lại trong báo cáo.
    # Mốc đối chứng dùng text CÒN CHỮ TRANG TRÍ: các engine đối chứng đều đọc
    # watermark, loại bỏ sẽ làm cổng báo lệch oan.
    verify = cross_verify(
        pdf_path,
        raw_canonical,
        deduplicated_canonical,
        form_field_values=[field.value.value for field in form_fields],
    )
    if not verify.char_multiset_match:
        failing = [c.engine for c in verify.comparisons if not c.char_multiset_match]
        errors.append(
            f"Engine {', '.join(failing)} không khớp mốc nào của engine chính — "
            "không thể bảo đảm không mất chữ. Xem only_in_primary / only_in_engine."
        )

    # Bước 6: dựng bảng theo đường kẻ ô.
    # Nội dung ô lấy từ `chars` đã lọc glyph và gộp dấu, không để thư viện đọc
    # lại PDF — nếu không, ô bảng sẽ bỏ qua các bước xử lý ở tầng trên.
    table_regions = extract_tables(pdf_path, chars)
    tables = merge_continued_tables(table_regions)

    # Bước 6b: đọc cấu trúc mục của tài liệu. Loại các vùng bảng DỮ LIỆU khỏi
    # parser cấu trúc (dùng vùng CHƯA ghép qua trang, vì bản đã ghép chỉ giữ
    # bbox trang đầu) — bảng đã được dựng theo biên ô ở bước trên.
    parsed = parse_document(
        lines,
        [
            (region.page, region.bbox)
            for region in table_regions
            if region.shape[1] >= DATA_TABLE_MIN_COLUMNS
        ],
    )

    # Cổng 7: nhận diện template.
    template, confidence = detect_template(canonical)
    if template is None:
        errors.append(
            f"Không nhận ra mẫu tài liệu (điểm cao nhất {confidence:.2f} < ngưỡng). "
            "Cần thêm template cho loại này."
        )
        return ExtractionResult(
            source=source,
            input_format=InputFormat.PDF,
            pdf_class=pdf_class,
            template_id=None,
            status=ExtractionStatus.REJECTED,
            data={},
            font_audit=font_audit,
            glyph_layers=glyph_layers,
            cross_verify=verify,
            errors=errors,
        )

    # Bước 8: bóc field theo nhãn.
    raw_data = extract_with_template(
        template,
        DocumentContext(
            lines=lines,
            tables=tables,
            document=parsed,
            form_fields=form_fields,
            hyperlinks=hyperlinks,
        ),
    )

    # Bước 8b: khối text nguyên văn theo trang.
    #
    # Phần có cấu trúc tiêu thụ dấu hai chấm và gạch đầu dòng để dựng cấu trúc,
    # còn chữ trang trí bị loại khỏi luồng nghiệp vụ — nên nếu chỉ có phần cấu
    # trúc thì JSON không chứa đủ MỌI ký tự của tài liệu. Khối này lấp đúng
    # khoảng đó, để độ phủ ký tự đạt 100% và kiểm được bằng máy.
    raw_data["text_layer"] = build_text_layer(lines, overlay_chars)

    # Cổng 9: nguồn gốc — mọi giá trị phải nguyên văn.
    # Truyền cả danh sách ký tự kèm toạ độ để cổng dùng được mức chứng minh mạnh
    # (so với ký tự trong bbox) cho các giá trị lấy từ ô bảng.
    # Text để chứng minh nguồn gốc gồm cả dữ liệu annotation: giá trị form field
    # và URL là nội dung THẬT của tài liệu, chỉ không nằm trong content stream.
    # Không đưa vào thì cổng sẽ từ chối oan chính những giá trị nó cần bảo vệ.
    # Căn cứ gồm text thân LIỀN MẠCH, rồi mới tới chữ trang trí và dữ liệu
    # annotation. Không dùng bản trộn sẵn: glyph watermark cỡ 60pt chen vào giữa
    # các dòng thân và phá tính liền mạch của tiêu đề mục.
    decorative_text = [
        entry["text"].value for entry in raw_data["text_layer"]["decorative"]
    ]
    provenance_text = "\n".join(
        [canonical, *decorative_text]
        + [field.value.value for field in form_fields]
        + [link.url for link in hyperlinks]
    )
    data, provenance = apply_gate(raw_data, provenance_text, chars)
    if provenance.unverified_paths:
        errors.append(
            "Có giá trị không chứng minh được là nguyên văn của PDF: "
            f"{', '.join(provenance.unverified_paths)}"
        )

    status = ExtractionStatus.VERIFIED if not errors else ExtractionStatus.NEEDS_REVIEW

    return ExtractionResult(
        source=source,
        input_format=InputFormat.PDF,
        pdf_class=pdf_class,
        template_id=template.template_id,
        status=status,
        data=data,
        font_audit=font_audit,
        glyph_layers=glyph_layers,
        cross_verify=verify,
        provenance=provenance,
        errors=errors,
    )
