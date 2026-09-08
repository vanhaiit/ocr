"""Kiểu dữ liệu dùng chung cho toàn pipeline.

Nguyên tắc thiết kế: mọi giá trị xuất ra JSON đều phải mang theo nguồn gốc
(trang + toạ độ). Không có chỗ nào trong pipeline được tạo ra một giá trị
"tự nghĩ" mà không truy được về text đã trích xuất xác định.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class InputFormat(str, Enum):
    """Định dạng đầu vào. Quyết định tầng đọc nào chạy và cổng nào áp dụng.

    PDF lưu chữ dưới dạng mã glyph nên cần soát bảng ToUnicode, lọc lớp glyph
    vẽ trùng, và dựng bảng theo đường kẻ ô. DOCX lưu text đã là Unicode và bảng
    đã có cấu trúc, nên ba cổng đó KHÔNG áp dụng — chúng được báo cáo là `null`
    thay vì báo xanh, để không tạo cảm giác đã kiểm mà thật ra không có gì kiểm.
    """

    PDF = "pdf"
    DOCX = "docx"


class PdfClass(str, Enum):
    """Loại PDF, quyết định pipeline có chạy tiếp hay không."""

    TEXT_LAYER = "text_layer"  # có text nhúng -> trích xuất xác định, đạt 100%
    SCANNED = "scanned"  # chỉ có ảnh -> ngoài phạm vi, phải reject
    MIXED = "mixed"  # một số trang có text, số khác không -> reject để an toàn


class ExtractionStatus(str, Enum):
    """Kết quả cuối. Chỉ VERIFIED mới được coi là dữ liệu tin được."""

    VERIFIED = "verified"  # mọi cổng kiểm tra đều xanh
    NEEDS_REVIEW = "needs_review"  # có giá trị không chứng minh được nguồn
    REJECTED = "rejected"  # không đủ điều kiện xử lý (scan, engine lệch nhau...)


@dataclass(frozen=True)
class BoundingBox:
    """Toạ độ vùng chứa giá trị, theo hệ toạ độ điểm của PDF (gốc trên-trái)."""

    x0: float
    top: float
    x1: float
    bottom: float

    def as_list(self) -> list[float]:
        return [round(self.x0, 2), round(self.top, 2), round(self.x1, 2), round(self.bottom, 2)]


@dataclass
class SourcedValue:
    """Một giá trị kèm bằng chứng nguồn gốc.

    `verbatim=True` nghĩa là chuỗi này đã được chứng minh tồn tại nguyên văn
    trong text trích xuất xác định. Đây là điều kiện để đạt cam kết 100%.

    `source_lines` giữ các dòng vật lý mà giá trị được ghép từ đó. Ô bảng bị
    ngắt dòng cần thông tin này để bên gọi chọn cách ghép phù hợp với kiểu dữ
    liệu của cột (số tiền ghép liền, văn xuôi ghép có dấu cách). Không xuất ra
    JSON vì chỉ dùng nội bộ khi bóc field.
    """

    value: str
    page: int
    bbox: BoundingBox | None = None
    verbatim: bool = False
    source_lines: list[str] = field(default_factory=list)
    # Vị trí trong tài liệu nguồn khi KHÔNG có toạ độ: DOCX không phân trang và
    # không có bbox, nên bằng chứng vị trí là đường dẫn XML
    # ("body/p[12]", "body/tbl[1]/tr[3]/tc[2]").
    location: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"value": self.value, "page": self.page, "verbatim": self.verbatim}
        if self.bbox is not None:
            out["bbox"] = self.bbox.as_list()
        if self.location is not None:
            out["location"] = self.location
        return out


@dataclass
class LabelledValue:
    """Một giá trị kèm NHÃN NGUYÊN VĂN của nó trong tài liệu.

    Phải là một kiểu riêng, không phải dict dựng sẵn: cổng nguồn gốc chỉ duyệt
    và xác thực các node mà nó NHẬN RA. Bản trước dựng dict ngay tại tầng
    template nên mọi giá trị trong `fields` đi vòng qua cổng — chúng ra JSON với
    `verbatim: false` và không được tính vào báo cáo, đúng những giá trị quan
    trọng nhất của tài liệu.
    """

    label: SourcedValue
    value: SourcedValue | None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"label": self.label.value}

        if self.value is None:
            out["value"] = None
            return out

        out.update(self.value.to_json())
        return out


@dataclass
class FontAudit:
    """Kết quả soát bảng ToUnicode của font.

    Font thiếu ToUnicode vẫn hiển thị đúng trên màn hình nhưng copy ra sẽ sai,
    và mọi engine đều sai giống nhau -> đối chứng chéo không phát hiện được.
    Vì vậy phải soát riêng.
    """

    total_fonts: int
    fonts_with_tounicode: int
    missing: list[str] = field(default_factory=list)
    # Số ký tự mà mỗi font thiếu ToUnicode đã vẽ. Cần con số này để thông báo
    # nói được mức độ: "1 ký tự" và "1240 ký tự" là hai tình huống khác nhau.
    affected_characters: dict[str, int] = field(default_factory=dict)
    # Font khai báo trong /Resources nhưng không vẽ ký tự nào. Không phải lỗi —
    # trình sinh PDF hay khai sẵn font mặc định rồi không dùng. Ghi lại để người
    # đọc biết vì sao chúng không bị tính vào.
    declared_but_unused: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return 1.0 if self.total_fonts == 0 else self.fonts_with_tounicode / self.total_fonts

    @property
    def is_complete(self) -> bool:
        return not self.missing

    def to_json(self) -> dict[str, Any]:
        return {
            "total_fonts": self.total_fonts,
            "fonts_with_tounicode": self.fonts_with_tounicode,
            "coverage": round(self.coverage, 4),
            "missing": self.missing,
            "affected_characters": self.affected_characters,
            "declared_but_unused": self.declared_but_unused,
        }


@dataclass
class GlyphLayerReport:
    """Kết quả lọc glyph bị vẽ trùng.

    Hiệu ứng đổ bóng và in đậm giả được tạo bằng cách vẽ cùng một chuỗi hai lần
    ở vị trí lệch nhau chút ít. Engine trích xuất đọc ra ký tự nhân đôi, nên
    phải lọc trước khi dùng. Ghi lại số glyph đã lọc để việc này không âm thầm.
    """

    total_glyphs: int
    duplicate_glyphs_removed: int
    pages_affected: list[int] = field(default_factory=list)
    # Glyph chữ trang trí (watermark) bị loại khỏi luồng dữ liệu nghiệp vụ.
    # Ghi lại để việc loại bỏ không im lặng — chúng vẫn nằm trong text dùng cho
    # cổng đối chứng chéo.
    overlay_glyphs_excluded: int = 0

    @property
    def has_duplicate_layer(self) -> bool:
        return self.duplicate_glyphs_removed > 0

    def to_json(self) -> dict[str, Any]:
        return {
            "total_glyphs": self.total_glyphs,
            "duplicate_glyphs_removed": self.duplicate_glyphs_removed,
            "overlay_glyphs_excluded": self.overlay_glyphs_excluded,
            "pages_affected": self.pages_affected,
        }


@dataclass
class EngineComparison:
    """So sánh engine chính với một engine đối chứng.

    `baseline` cho biết đối chiếu với bản nào của engine chính:
      - "raw"               : trước khi lọc glyph trùng
      - "deduplicated"      : sau khi lọc
      - "with_form_fields"  : sau khi lọc, cộng giá trị các ô điền thông tin
      - "none"              : không khớp mốc nào -> có ký tự lệch thật

    Cần nhiều mốc vì các engine bao gồm phần dữ liệu khác nhau: pypdf trả về ký
    tự nhân đôi của lớp bóng, Poppler tự lọc lớp bóng NHƯNG lại đọc thêm giá trị
    form field. Nếu chỉ có một mốc thì mọi tài liệu có hiệu ứng chữ hoặc có form
    field đều bị chặn oan. Ghi lại engine nào khớp mốc nào biến hành vi của
    engine thành DỮ LIỆU QUAN SÁT ĐƯỢC thay vì giả định gán cứng trong code.
    """

    engine: str
    baseline: str
    chars: int
    char_multiset_match: bool
    reading_order_similarity: float
    only_in_primary: dict[str, int] = field(default_factory=dict)
    only_in_engine: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "baseline": self.baseline,
            "chars": self.chars,
            "char_multiset_match": self.char_multiset_match,
            "reading_order_similarity": round(self.reading_order_similarity, 4),
            "only_in_primary": self.only_in_primary,
            "only_in_engine": self.only_in_engine,
        }


@dataclass
class CrossVerifyReport:
    """Đối chứng giữa các engine trích xuất độc lập."""

    # Tên mốc -> số ký tự của mốc đó (đã bỏ khoảng trắng).
    baselines: dict[str, int] = field(default_factory=dict)
    comparisons: list[EngineComparison] = field(default_factory=list)

    @property
    def char_multiset_match(self) -> bool:
        return all(c.char_multiset_match for c in self.comparisons)

    @property
    def engine_count(self) -> int:
        return len(self.comparisons)

    @property
    def primary_raw_chars(self) -> int:
        return self.baselines.get("raw", 0)

    @property
    def primary_deduplicated_chars(self) -> int:
        return self.baselines.get("deduplicated", 0)

    def to_json(self) -> dict[str, Any]:
        return {
            "baselines": self.baselines,
            "char_multiset_match": self.char_multiset_match,
            "comparisons": [c.to_json() for c in self.comparisons],
        }


@dataclass
class ProvenanceReport:
    """Thống kê cổng nguồn gốc: bao nhiêu giá trị chứng minh được là nguyên văn."""

    total_values: int
    verbatim_values: int
    unverified_paths: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return 1.0 if self.total_values == 0 else self.verbatim_values / self.total_values

    def to_json(self) -> dict[str, Any]:
        return {
            "total_values": self.total_values,
            "verbatim_values": self.verbatim_values,
            "ratio": round(self.ratio, 4),
            "unverified_paths": self.unverified_paths,
        }


@dataclass
class ExtractionResult:
    """Kết quả hoàn chỉnh của một file PDF."""

    source: dict[str, Any]
    input_format: InputFormat
    # Chỉ có nghĩa với PDF (phân biệt text layer / bản scan). Với DOCX là None —
    # báo `text_layer` ở đó sẽ ngụ ý một cổng đã chạy mà thật ra không.
    pdf_class: PdfClass | None
    template_id: str | None
    status: ExtractionStatus
    data: dict[str, Any]
    font_audit: FontAudit | None = None
    glyph_layers: GlyphLayerReport | None = None
    cross_verify: CrossVerifyReport | None = None
    provenance: ProvenanceReport | None = None
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "template": self.template_id,
            "status": self.status.value,
            "verification": {
                "input_format": self.input_format.value,
                "pdf_class": self.pdf_class.value if self.pdf_class else None,
                "font_audit": self.font_audit.to_json() if self.font_audit else None,
                "glyph_layers": self.glyph_layers.to_json() if self.glyph_layers else None,
                "cross_verify": self.cross_verify.to_json() if self.cross_verify else None,
                "provenance": self.provenance.to_json() if self.provenance else None,
            },
            "data": self.data,
            "errors": self.errors,
        }
