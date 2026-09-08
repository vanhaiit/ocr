"""Đối chứng chéo giữa các engine trích xuất độc lập.

Đây là cơ chế biến "tôi tin tool này" thành "các tool tự xác nhận nhau".
pdfplumber/pdfminer (Python), pypdf (Python, code base riêng) và Poppler
pdftotext (C++, nhánh từ Xpdf) không dùng chung phần triển khai giải mã. Khi
tất cả cho ra cùng một tập ký tự thì xác suất chúng cùng sai giống nhau gần
như bằng không.

Phép so là trên MULTISET ký tự sau khi bỏ khoảng trắng: bỏ qua khác biệt về
thứ tự đọc và cách đặt khoảng trắng (mỗi engine một quy ước duyệt cột) nhưng
vẫn bắt được bất kỳ ký tự nào bị mất hoặc thêm.

Mỗi engine được so với NHIỀU MỐC rồi ghi lại nó khớp mốc nào. Cần thiết vì các
engine bao gồm phần dữ liệu khác nhau:

  - pypdf     : trả về ký tự nhân đôi của lớp bóng, không đọc form field
  - Poppler   : tự lọc lớp bóng, NHƯNG đọc thêm giá trị form field

Chỉ có một mốc thì mọi tài liệu có hiệu ứng chữ hoặc có form field đều bị chặn
oan dù nội dung đọc đúng hoàn toàn. Nhiều mốc cũng tránh gán cứng hành vi engine
vào code: engine nào khớp mốc nào là dữ liệu quan sát được, không phải giả định.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import pypdf

from .extract_text_with_coordinates import normalize
from .models import CrossVerifyReport, EngineComparison

# Số loại ký tự lệch nhiều nhất được đưa vào báo cáo, tránh phình JSON.
MAX_REPORTED_DIFF_KINDS = 10

# Tên các mốc đối chiếu, theo thứ tự từ ít xử lý đến nhiều xử lý nhất.
BASELINE_RAW = "raw"
BASELINE_DEDUPLICATED = "deduplicated"
BASELINE_WITH_FORM_FIELDS = "with_form_fields"

# Hậu tố ghi nhận: khớp mốc, nhưng engine trả THỪA bản sao của dấu tổ hợp.
# Quan sát được ở Poppler với tài liệu vừa có lớp bóng vừa viết tiếng Việt ở
# dạng phân rã: dấu tổ hợp có bước tiến bằng 0 nên một phần không rơi vào phép
# lọc trùng theo vị trí của nó, và số lượng lọt qua không đoán trước được.
#
# Đây KHÔNG phải mất dữ liệu: phần thừa nằm ở phía engine, còn phía ta không
# thiếu ký tự nào. Vì vậy vẫn tính là khớp, nhưng ghi rõ để không im lặng.
ENGINE_EXTRA_MARKS_SUFFIX = "+engine_extra_marks"

# Không khớp mốc nào -> có ký tự lệch thật, không phải khác biệt về phạm vi.
BASELINE_NONE = "none"


def comparable_form(text: str) -> str:
    """Dạng để so giữa các engine: PHÂN RÃ NFD rồi bỏ mọi khoảng trắng.

    Dùng NFD chứ không NFC vì mỗi engine ghép dấu tổ hợp một kiểu khác nhau khi
    tài liệu được viết ở dạng phân rã. Với tiếng Việt, Poppler có thể trả về dấu
    rời, hoặc ghép nhầm dấu sang chữ bên cạnh ('n' + huyền -> 'ǹ') vì thứ tự
    glyph trong content stream khác thứ tự nó duyệt.

    Phân rã hết về NFD làm phép so ĐỘC LẬP VỚI CÁCH GHÉP: tập code point sau
    phân rã là như nhau dù engine có ghép hay không, nên chênh lệch còn lại
    đúng là ký tự bị mất hoặc thêm — thứ mà cổng này cần bắt.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFD", text))



def extract_with_pypdf(pdf_path: str) -> str:
    reader = pypdf.PdfReader(pdf_path)
    return "".join(page.extract_text() or "" for page in reader.pages)


def extract_with_poppler(pdf_path: str) -> str | None:
    """Trích xuất bằng Poppler pdftotext. Trả None nếu máy không có Poppler.

    Engine này viết bằng C++, độc lập hoàn toàn với nhánh Python, nên là đối
    chứng có giá trị nhất. Thiếu nó pipeline vẫn chạy nhưng mức bảo đảm giảm.
    """
    if shutil.which("pdftotext") is None:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "out.txt"
        subprocess.run(
            ["pdftotext", "-layout", pdf_path, str(out_path)],
            check=True,
            capture_output=True,
        )
        return out_path.read_text(encoding="utf-8", errors="strict")


def _residual_is_only_extra_marks(
    baseline_counter: Counter, engine_counter: Counter
) -> bool:
    """Chênh lệch còn lại có phải CHỈ là dấu tổ hợp engine trả thừa?

    Điều kiện: phía ta không thiếu ký tự nào (`baseline - engine` rỗng), và mọi
    thứ engine có thêm đều là dấu tổ hợp mà ta đã có ít nhất một bản.

    Phân biệt này là điểm cốt lõi: THIẾU ký tự nghĩa là có thể mất dữ liệu, phải
    chặn. THỪA bản sao của dấu tổ hợp là đặc tính của engine, không làm mất gì —
    ghi nhận rồi cho qua, thay vì chặn oan.
    """
    if baseline_counter - engine_counter:
        return False

    extra = engine_counter - baseline_counter
    if not extra:
        return False

    return all(
        unicodedata.combining(char) != 0 and baseline_counter[char] > 0
        for char in extra
    )


def _compare(engine: str, engine_text: str, baselines: dict[str, str]) -> EngineComparison:
    """So một engine với mọi mốc, ghi lại mốc đầu tiên khớp.

    Khớp mốc nào cũng được coi là đạt: các mốc chỉ khác nhau về PHẠM VI dữ liệu
    (có lọc lớp bóng chưa, có gồm form field chưa), không khác về nội dung ký
    tự. Không khớp mốc nào mới là lệch thật.
    """
    engine_counter = Counter(engine_text)

    baseline = BASELINE_NONE
    for name, text in baselines.items():
        if engine_counter == Counter(text):
            baseline = name
            break

    # Không khớp tuyệt đối: xét tiếp xem chênh lệch có phải chỉ là dấu tổ hợp
    # engine trả thừa. Nếu đúng thì vẫn tính khớp, có ghi chú.
    if baseline is BASELINE_NONE:
        for name, text in baselines.items():
            if _residual_is_only_extra_marks(Counter(text), engine_counter):
                baseline = name + ENGINE_EXTRA_MARKS_SUFFIX
                break

    # Khi không khớp mốc nào, báo cáo chênh lệch so với mốc đầy đủ nhất — đây là
    # bản gần nhất với dữ liệu pipeline thực sự dùng, nên chênh lệch với nó mới
    # là thông tin hữu ích để soi lỗi.
    reference_name = baseline.removesuffix(ENGINE_EXTRA_MARKS_SUFFIX)
    reference = baselines.get(reference_name) or list(baselines.values())[-1]
    reference_counter = Counter(reference)

    return EngineComparison(
        engine=engine,
        baseline=baseline,
        chars=len(engine_text),
        char_multiset_match=baseline != BASELINE_NONE,
        reading_order_similarity=difflib.SequenceMatcher(
            None, reference, engine_text, autojunk=False
        ).ratio(),
        only_in_primary=dict(
            (reference_counter - engine_counter).most_common(MAX_REPORTED_DIFF_KINDS)
        ),
        only_in_engine=dict(
            (engine_counter - reference_counter).most_common(MAX_REPORTED_DIFF_KINDS)
        ),
    )


def cross_verify(
    pdf_path: str,
    raw_primary_text: str,
    deduplicated_primary_text: str,
    form_field_values: list[str] | None = None,
) -> CrossVerifyReport:
    """So text của engine chính với các engine đối chứng.

    Ba mốc, dựng theo mức xử lý tăng dần:
      - `raw`              : trước khi lọc glyph trùng
      - `deduplicated`     : sau khi lọc
      - `with_form_fields` : cộng thêm giá trị các ô điền thông tin

    Tài liệu không có hiệu ứng chữ và không có form field thì cả ba mốc giống
    nhau, và mọi engine khớp mốc đầu tiên.

    URL của hyperlink KHÔNG được đưa vào mốc nào: không engine nào xuất nó ra
    text, nên thêm vào sẽ làm mọi engine lệch. URL vẫn được kiểm ở cổng nguồn
    gốc bằng đường riêng.
    """
    sources: dict[str, str] = {
        BASELINE_RAW: raw_primary_text,
        BASELINE_DEDUPLICATED: deduplicated_primary_text,
    }

    if form_field_values:
        sources[BASELINE_WITH_FORM_FIELDS] = deduplicated_primary_text + "".join(
            form_field_values
        )

    baselines = {name: comparable_form(text) for name, text in sources.items()}

    candidates: dict[str, str] = {"pypdf": comparable_form(extract_with_pypdf(pdf_path))}

    poppler_raw = extract_with_poppler(pdf_path)
    if poppler_raw is not None:
        candidates["poppler"] = comparable_form(poppler_raw)

    return CrossVerifyReport(
        baselines={name: len(text) for name, text in baselines.items()},
        comparisons=[
            _compare(engine, text, baselines) for engine, text in candidates.items()
        ],
    )
