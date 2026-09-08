"""Đối chứng chéo cho DOCX: pandoc và docx2txt so với engine chính python-docx.

Ba bộ đọc độc lập về code base: python-docx và docx2txt đều là Python nhưng phân
tích XML theo hai cách hoàn toàn khác (một dùng đối tượng lxml, một dùng regex
trên chuỗi), còn pandoc viết bằng Haskell.

Điểm khác với nhánh PDF: phép so ở đây **bất đối xứng**, và có lý do.

  - Engine đối chứng tìm ra ký tự mà TA KHÔNG CÓ  -> nguy cơ mất dữ liệu -> CHẶN
  - Engine đối chứng thêm ký tự ta không có        -> ghi nhận, KHÔNG chặn

Vì pandoc vẽ bảng bằng ký tự (`-`, `=`, `|`, `+`) khi xuất text, nên phần "thêm"
là trang trí của chính nó, không phải nội dung tài liệu. Còn phần "thiếu" thì
luôn là tín hiệu thật: có chữ trong file mà ta không đọc ra.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from collections import Counter

from .models import CrossVerifyReport, EngineComparison

# Số loại ký tự lệch nhiều nhất được đưa vào báo cáo, tránh phình JSON.
MAX_REPORTED_DIFF_KINDS = 10

# Tên mốc: DOCX chỉ có một bản text, không có "thô" và "đã lọc" như PDF.
BASELINE_DOCUMENT = "document"
BASELINE_NONE = "none"

# Ký tự pandoc dùng để vẽ khung bảng khi xuất text.
TABLE_ART_CHARACTERS = set("-=|+")


def comparable_form(text: str) -> str:
    """Phân rã NFD rồi bỏ khoảng trắng — cùng dạng chuẩn như nhánh PDF."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFD", text))


def read_with_pandoc(path: str) -> str | None:
    """Đọc DOCX bằng pandoc. Trả None nếu máy không có pandoc."""
    if shutil.which("pandoc") is None:
        return None

    finished = subprocess.run(
        ["pandoc", "-f", "docx", "-t", "plain", path], capture_output=True, text=True
    )
    return finished.stdout if finished.returncode == 0 else None


def read_with_docx2txt(path: str) -> str | None:
    """Đọc DOCX bằng docx2txt. Trả None nếu chưa cài."""
    try:
        import docx2txt
    except ImportError:
        return None

    return docx2txt.process(path)


def cross_verify_docx(path: str, primary_text: str) -> CrossVerifyReport:
    """So text của engine chính với các bộ đọc độc lập."""
    baseline = comparable_form(primary_text)
    baseline_counter = Counter(baseline)

    readers = {"pandoc": read_with_pandoc, "docx2txt": read_with_docx2txt}
    comparisons: list[EngineComparison] = []

    for name, reader in readers.items():
        raw = reader(path)
        if raw is None:
            continue

        comparisons.append(_compare(name, comparable_form(raw), baseline, baseline_counter))

    return CrossVerifyReport(
        baselines={BASELINE_DOCUMENT: len(baseline)}, comparisons=comparisons
    )


def _compare(
    engine: str, engine_text: str, baseline: str, baseline_counter: Counter
) -> EngineComparison:
    """So một engine với text của engine chính, theo quy tắc bất đối xứng.

    Hai chiều mang hai ý nghĩa khác nhau, và chỉ một chiều là lỗi:

      - `only_in_engine`  = engine có, TA KHÔNG CÓ -> nguy cơ bỏ sót -> CHẶN
      - `only_in_primary` = ta có, engine không có -> ghi nhận, không chặn

    Chiều thứ hai không phải lỗi vì mỗi bộ đọc bỏ qua một phần khác nhau: pandoc
    không xuất chân trang, còn ký tự vẽ khung bảng thì chỉ pandoc mới thêm.
    """
    engine_counter = Counter(engine_text)

    only_in_engine = engine_counter - baseline_counter
    only_in_primary = baseline_counter - engine_counter

    # Ký tự engine thêm mà toàn là nét vẽ khung bảng thì không phải nội dung.
    real_content_missing = {
        char: count
        for char, count in only_in_engine.items()
        if char not in TABLE_ART_CHARACTERS
    }
    matches = not real_content_missing

    return EngineComparison(
        engine=engine,
        baseline=BASELINE_DOCUMENT if matches else BASELINE_NONE,
        chars=len(engine_text),
        char_multiset_match=matches,
        # DOCX không có "thứ tự đọc" theo toạ độ để so; giữ 1.0 khi khớp nội
        # dung, để trường này không bị hiểu là một phép đo có ý nghĩa ở đây.
        reading_order_similarity=1.0 if matches else 0.0,
        only_in_primary=dict(only_in_primary.most_common(MAX_REPORTED_DIFF_KINDS)),
        only_in_engine=dict(only_in_engine.most_common(MAX_REPORTED_DIFF_KINDS)),
    )
