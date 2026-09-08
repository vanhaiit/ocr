# pdf-extract

Chuyển PDF **có text layer** sang JSON, mỗi giá trị kèm bằng chứng nguồn gốc (trang + toạ độ). Thiết kế quanh một câu hỏi: *làm sao chứng minh được dữ liệu đúng, thay vì chỉ tuyên bố là đúng.*

## Cam kết và giới hạn

| | Cơ chế | Đạt 100%? |
|---|---|---|
| PDF → text | Tra bảng `ToUnicode` của font, xác định | **Có** |
| text → JSON có cấu trúc | Cắt chuỗi theo nhãn + dựng bảng theo đường kẻ ô | **Có, trong phạm vi template đã đăng ký** |
| PDF scan (ảnh) | Ngoài phạm vi | **Không** — bị từ chối tường minh |

PDF lưu chữ dưới dạng mã glyph kèm bảng dịch sang Unicode:

```
BT  304.6 39.089 Td  /F1 12 Tf  <01> Tj  ET     <- PDF vẽ mã 01
<01> <0043>                                     <- bảng ToUnicode: 01 = 'C'
```

Đây là phép **tra bảng**, không phải nhận dạng ảnh. Vì vậy trích xuất cho kết quả xác định — chạy bao nhiêu lần cũng như nhau, không có xác suất, không có ngưỡng tin cậy. Đó là nền của cam kết 100%.

Với PDF scan thì phải OCR từ pixel, luôn có sai số (tiếng Việt có dấu thường 92–98%). Pipeline này **không** làm việc đó và từ chối file scan thay vì âm thầm cho ra dữ liệu kém tin cậy.

## Bộ mẫu kiểm tính năng trình bày

`samples/font-features/` — 12 file sinh tự động, **cùng một tập giá trị nghiệp vụ, chỉ khác cách vẽ chữ**. Nhờ vậy test khẳng định được: tính năng trình bày không làm đổi giá trị bóc ra.

| File | Tính năng | Engine đối chứng khớp mốc |
|---|---|---|
| `01-baseline` | không | `raw` |
| `02-bold-italic` | in đậm, nghiêng, đậm-nghiêng | `raw` |
| `03-superscript-subscript` | chỉ số trên `(m²)` | `raw` |
| `04-hyperlink` | annotation `/Link` + URL | `raw` |
| `05-shadow` | đổ bóng (vẽ 2 lần) | Poppler `deduplicated` |
| `06-outline` | viền chữ (chế độ tô 2) | `raw` |
| `07-form-fields` | AcroForm, giá trị trong `/V` | Poppler `with_form_fields` |
| `08-rotated-header` | tiêu đề cột quay 90° | `raw` |
| `09-invisible-layer` | chữ ẩn (chế độ tô 3) | `raw` |
| `10-watermark` | watermark chéo 60pt | `raw` |
| `11-decomposed-diacritics` | tiếng Việt dạng NFD | `raw` |
| `12-kitchen-sink` | trộn tất cả | Poppler `with_form_fields+engine_extra_marks` |

Cả 12 đều `verified`, mọi giá trị `verbatim`. Sinh lại:

```bash
PYTHONPATH=src:tests ./.venv/bin/python3 -m fixtures.generate_font_feature_samples samples/font-features
```

### Điều học được từ từng tính năng

**In đậm / in nghiêng thật: không ảnh hưởng gì.** Chúng là font riêng biệt trong PDF (`TimesNewRomanPS-BoldMT`, `-ItalicMT`), mỗi font có `ToUnicode` riêng, vẽ một lần.

**Chỉ số trên/dưới** dùng cỡ chữ nhỏ hơn và baseline dịch, nên nằm lệch dòng. Xử lý được nhờ ngưỡng gom dòng tính theo *tỉ lệ* cỡ chữ, không phải điểm tuyệt đối.

**Hyperlink**: chữ hiển thị nằm trong content stream nhưng **URL nằm trong `/A /URI` của annotation** — mọi bộ trích xuất text đều bỏ qua. Phải đọc riêng.

**Form field**: giá trị người dùng điền sống trong **`/V` của widget annotation, không nằm trong content stream**. Đọc text thuần là mất trắng. Poppler đọc được (qua appearance stream), pdfplumber và pypdf không — đây là lý do cổng đối chứng cần nhiều mốc.

**Chữ ẩn** (chế độ tô 3) không hiện trên màn hình nhưng engine vẫn đọc, nên có thể lẫn vào dữ liệu. **Watermark** cỡ lớn nằm chéo trang khiến tâm glyph rơi vào trong ô bảng. Cả hai là dạng sai âm thầm tệ nhất: giá trị vẫn *nguyên văn của PDF* nên cổng nguồn gốc không bắt được — phải xử lý bằng tầng riêng và test riêng.

**Chỉ số trên/dưới nằm lệch đường cơ sở** nên bị gom thành dòng riêng —
`H₂O` từng bị đọc thành `HO` rồi `2` ở hai dòng, ghép lại sai thành `HO 2`.
Xử lý bằng cách gom dòng theo **chồng lấn dọc** với ký tự lớn nhất của dòng,
không chỉ theo tâm ký tự.

**Tiếng Việt dạng NFD**: `ồ` được lưu thành `o` + dấu mũ + dấu huyền, mỗi dấu là một glyph. Chuẩn hoá NFC trên *từng ký tự* không ghép được gì — phải gộp dấu tổ hợp vào ký tự gốc trước.

## Cấu trúc JSON

JSON theo đúng cấu trúc tài liệu. **Không có danh sách field định trước** — cấu
trúc được đọc từ chính tài liệu (số La Mã, gạch đầu dòng, dấu hai chấm), rồi mới
gán tên tiếng Anh. Nhờ vậy nhãn nào chưa có tên vẫn xuất ra trong
`unmapped_fields` thay vì bị bỏ im lặng.

```json
{
  "preface": {                       // trước mục I: tiêu đề thư, quốc hiệu, "Kính gửi", "Căn cứ"
    "fields":  { "contract_number": {...}, "certificate_number": {...}, "recipient": {...} },
    "unmapped_fields": {},
    "paragraphs": [ ... ],           // quốc hiệu, địa điểm/ngày, tên chứng thư
    "items": [ ... ]                 // các dòng "- Căn cứ ..."
  },
  "sections": {                      // khóa bằng SỐ LA MÃ như tài liệu
    "I": {
      "name": "customer_info",       // tên tiếng Anh của mục
      "title": { "value": "THÔNG TIN KHÁCH HÀNG", ... },
      "fields": {
        "customer_name": {
          "label": "Tên khách hàng", // nhãn NGUYÊN VĂN trong tài liệu
          "value": "ÔNG: CUSTOMER-NAME-001",
          "page": 1, "bbox": [206.4, 308.04, 372.61, 320.04], "verbatim": true
        },
        "customer_address": {...}, "customer_identity_number": {...}
      },
      "unmapped_fields": {},         // nhãn chưa ánh xạ, khóa tự sinh từ nhãn
      "paragraphs": [], "items": []
    },
    "IV": { "name": "valuation_date", "value": {...} },   // giá trị sau dấu ":" của tiêu đề mục
    "X":  { "name": "asset_values", "table": { "rows": [...], "totals": {...} } },
    "XIII": { "name": "attached_documents", "fields": {...}, "items": [...] }
  },
  "signatures": [                    // gom theo CỘT, mỗi người một object
    { "role": "valuer",           "role_label": "THẨM ĐỊNH VIÊN VỀ GIÁ",
      "card_number": {...}, "name": {...}, "lines": [...] },
    { "role": "branch_director",  "role_label": "GIÁM ĐỐC CHI NHÁNH", ... }
  ],
  "page_footers": [ ... ],
  "form_fields": { ... },            // AcroForm: giá trị trong /V
  "hyperlinks": [ ... ]              // URL trong /A /URI
}
```

Trên `CT-SAMPLE-001`: 13 mục, 3 field ở phần mở đầu, 16 field trong các mục,
5 thửa đất, 3 dòng tổng, 2 người ký, 3 chân trang — **58/58 giá trị chứng minh
được là nguyên văn**, không nhãn nào chưa ánh xạ.

### Vì sao phải đọc cấu trúc trước, đặt tên sau

Bản đầu tiên làm ngược: template đi tìm một danh sách 17 nhãn định trước. Mọi
thứ ngoài danh sách bị bỏ **im lặng** — mất `Kính gửi`, ba dòng `Căn cứ`, quốc
hiệu, toàn bộ mục VI–IX, mục XII, mục XIII kèm danh sách phụ lục, phần
"Một số lưu ý", và cả khối chữ ký.

Giờ `parse_document_sections` đọc cấu trúc trước và **không biết gì về nghiệp
vụ**; template chỉ làm việc đặt tên. Ánh xạ thiếu không còn làm mất dữ liệu.

### Ba quy tắc nhận dạng, đều dựa trên dữ liệu có sẵn trong PDF

| Câu hỏi | Cách quyết |
|---|---|
| Dòng nối tiếp thuộc **nhãn** hay **giá trị**? | Theo toạ độ: gần cột nhãn hay gần cột giá trị hơn (`Hồ sơ pháp lý khách` + `hàng cung cấp` là nhãn; `với đất thuộc...` là giá trị) |
| Dòng có phải **nhãn mới**? | Phải bắt đầu bằng chữ HOA hoặc chữ số. Phần cuối câu bị ngắt dòng bắt đầu bằng chữ thường (`tại thời điểm... như sau:`) nên không bị nhận nhầm |
| Dòng có **nối tiếp** dòng trước? | Phải liền kề theo chiều dọc và cùng trang. Hai câu nằm trước/sau một bảng không được nối — dòng bảng đã bị loại nên chúng trông như liền nhau |

Khối chữ ký nhận ra bằng "nhiều cột + thụt xa lề", dò từ dòng cuối lên — không
theo số trang, vì khối này có thể vắt qua hai trang (vai trò và số thẻ ở trang
trước, họ tên ở trang sau).

## Chín cổng kiểm tra

Mỗi cổng có quyền chặn. Chỉ khi tất cả xanh thì trạng thái mới là `verified`.

| # | Cổng | Chặn khi |
|---|---|---|
| 1 | Phân loại PDF | Trang là ảnh scan (ảnh che >50% diện tích và gần như không có text) |
| 2 | Soát font | Có font thiếu bảng `ToUnicode` |
| 3 | Trích xuất kèm toạ độ | — (tạo nguồn chân lý) |
| 4 | Lọc glyph vẽ trùng + tách chữ trang trí | — (ghi số glyph đã lọc/loại) |
| 5 | Đối chứng chéo | Engine đối chứng không khớp mốc nào của engine chính |
| 6 | Dựng bảng theo đường kẻ | — (ghi lại chiến lược đã dùng) |
| 7 | Nhận diện template | Không mẫu nào đạt ngưỡng tin cậy |
| 8 | Bóc field theo nhãn | — |
| 9 | **Cổng nguồn gốc** | Có giá trị không chứng minh được là nguyên văn của PDF |

### Cổng 4 — chữ đổ bóng và in đậm giả

Word và LibreOffice tạo hiệu ứng đổ bóng, viền chữ và **in đậm giả** bằng cách vẽ *cùng một chuỗi hai lần* ở vị trí lệch nhau chút ít. Engine trích xuất đọc ra ký tự nhân đôi:

| | Chữ đổ bóng | Chữ thường |
|---|---|---|
| pdfplumber | `'SHADOWSHADOW'` | `'PLAIN'` |
| pypdf | `'SHADOWSHADOW'` | `'PLAIN'` |
| Poppler | `'SHADOW'` (tự lọc) | `'PLAIN'` |

Dạng hỏng âm thầm: chữ hiển thị hoàn toàn bình thường trên màn hình. Cổng này lọc lớp trùng, gộp hai glyph khi cùng ký tự, cùng trang và lệch nhau dưới `0.18 × cỡ chữ` (chặn trên 2.5pt). Khoảng an toàn rộng: độ lệch lớp bóng thường dưới `0.15 × cỡ chữ`, còn bước tiến của glyph hẹp nhất vẫn trên `0.25 × cỡ chữ`.

**In đậm và in nghiêng THẬT không ảnh hưởng gì.** Chúng là các font riêng biệt trong PDF (`TimesNewRomanPS-BoldMT`, `-ItalicMT`), mỗi font có bảng `ToUnicode` riêng và chỉ được vẽ một lần. Hai file mẫu đã dùng 8–9 font gồm cả bold, italic và bold-italic — trích xuất không hề bị ảnh hưởng.

### Cổng 5 — vì sao đối chứng chéo có giá trị

`pdfplumber`/`pdfminer` (Python), `pypdf` (Python, code base riêng) và Poppler `pdftotext` (C++, nhánh từ Xpdf) **không dùng chung phần triển khai giải mã**. Khi cả ba cho ra cùng một tập ký tự, xác suất chúng cùng sai giống nhau gần như bằng không. Đây là cách biến "tin tool này" thành "các tool tự xác nhận nhau".

Phép so là trên **multiset ký tự sau khi bỏ khoảng trắng** — bỏ qua khác biệt thứ tự đọc và cách đặt khoảng trắng (mỗi engine một quy ước duyệt cột), nhưng bắt được bất kỳ ký tự nào bị mất hoặc thêm.

Phép so thực hiện ở dạng **NFD (phân rã hết)**, không phải NFC. Lý do: mỗi engine ghép dấu tổ hợp một kiểu khi tài liệu viết ở dạng phân rã — Poppler có thể trả dấu rời, hoặc ghép nhầm dấu sang chữ bên cạnh (`n` + huyền → `ǹ`) vì thứ tự glyph trong content stream khác thứ tự nó duyệt. Phân rã hết làm phép so **độc lập với cách ghép**, nên chênh lệch còn lại đúng là ký tự bị mất hoặc thêm.

Mỗi engine được so với **nhiều mốc** rồi ghi lại nó khớp mốc nào:

| Mốc | Nghĩa |
|---|---|
| `raw` | trước khi lọc glyph trùng |
| `deduplicated` | sau khi lọc |
| `with_form_fields` | sau khi lọc, cộng giá trị các ô điền thông tin |
| `<mốc>+engine_extra_marks` | khớp mốc đó, nhưng engine trả **thừa** bản sao dấu tổ hợp |
| `none` | không khớp mốc nào → có ký tự lệch thật, **chặn** |

Cần nhiều mốc vì các engine bao gồm phần dữ liệu khác nhau: pypdf trả ký tự nhân đôi của lớp bóng và không đọc form field; Poppler tự lọc lớp bóng nhưng lại đọc thêm form field. Một mốc duy nhất thì mọi tài liệu có hiệu ứng chữ hoặc có form field đều bị chặn oan. Cách này cũng tránh gán cứng hành vi engine vào code: engine nào khớp mốc nào là *dữ liệu quan sát được*, không phải giả định — và Poppler tự lọc trở thành phép kiểm chứng độc lập cho bộ lọc glyph của chính chúng ta.

**Phân biệt THIẾU và THỪA.** Engine tìm ra ký tự mà ta không có → nguy cơ mất dữ liệu → **chặn**. Engine trả thừa bản sao của dấu tổ hợp (nó lọc trùng phần chữ gốc nhưng dấu có bước tiến 0 nên lọt qua) → không mất gì → ghi nhận rồi cho qua. Quan sát được ở Poppler với tài liệu vừa đổ bóng vừa viết NFD.

Cổng 2 tồn tại vì đối chứng chéo có đúng một điểm mù: font thiếu `ToUnicode` khiến **mọi** engine cùng đọc sai giống nhau. Phải soát riêng.

### Cổng 9 — hạt nhân của cam kết

Quy tắc bất biến: **mọi giá trị chuỗi xuất ra JSON phải chứng minh được là nguyên văn của PDF.** Hai mức chứng minh, ưu tiên mức mạnh:

1. **Theo toạ độ** (giá trị có `bbox`) — so với đúng các ký tự nằm trong vùng bbox đó. Bằng chứng chặt nhất: *"chuỗi này chính là những gì PDF vẽ tại vùng này"*. Bắt buộc cho ô bảng, vì ô đọc dọc theo cột nên không phải substring liền mạch của text đọc ngang.
2. **Theo chuỗi con** (giá trị không có bbox) — phải là substring nguyên văn của text đã trích xuất.

Giá trị không qua được cổng sẽ bị đánh dấu `verbatim: false`, liệt kê đường dẫn trong `unverified_paths`, và cả file chuyển sang `needs_review`. **Không có đường nào cho ra dữ liệu "trông như đúng" mà không chứng minh được.**

Hệ quả quan trọng: nếu sau này thêm tầng LLM để suy luận field, cổng này tự động bắt mọi giá trị bị bịa — chuỗi bịa không khớp với ký tự PDF vẽ ra. Test `TestProvenanceGateRejectsFabrication` khoá đúng tính chất đó.

## Dùng

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
brew install poppler          # engine đối chứng thứ ba; thiếu vẫn chạy nhưng giảm mức bảo đảm

./.venv/bin/pdf-extract samples --summary-only      # bảng tóm tắt các cổng
./.venv/bin/pdf-extract samples -o out              # ghi JSON
./.venv/bin/pdf-extract file.pdf                    # in JSON ra stdout
```

Mã thoát: `0` mọi file verified · `1` có file needs_review · `2` có file rejected. Dùng được trực tiếp trong CI.

CLI quét thư mục **đệ quy**, nên `pdf-extract samples` cũng gồm cả `samples/known-issues/` và sẽ trả mã thoát 1 — đúng như mong đợi, vì thư mục đó chứa fixture âm cố ý hỏng.

## Kết quả trên hai file mẫu

```
verified | CT-SAMPLE-001   font ToUnicode: 1.0   glyph trùng lọc: 0/4269
           engine khớp: True (pypdf=3528(both), poppler=3528(both))
           nguồn gốc: 33/33 nguyên văn
verified | CT-SAMPLE-002   font ToUnicode: 1.0   glyph trùng lọc: 0/4305
           engine khớp: True (pypdf=3545(both), poppler=3545(both))
           nguồn gốc: 39/39 nguyên văn
```

`(both)` nghĩa là bản thô và bản đã lọc giống nhau — tài liệu không có lớp chữ trùng.

Bảng mục X dựng đúng 5 và 7 thửa, mỗi ô có bbox riêng.

## Cấu trúc

```
src/pdf_extract/
├── classify_pdf_text_layer.py            # cổng 1
├── audit_font_tounicode.py               # cổng 2
├── extract_text_with_coordinates.py      # cổng 3 — nguồn chân lý
├── detect_duplicate_glyph_layers.py      # cổng 4 — lọc lớp bóng
├── classify_overlay_glyphs.py            # cổng 4 — tách watermark
├── extract_annotation_data.py            # form field + hyperlink
├── cross_verify_engines.py               # cổng 5
├── reconstruct_tables_by_ruling_lines.py # cổng 6
├── parse_labeled_lines.py                # nhận dạng "nhãn : giá trị"
├── parse_document_sections.py            # đọc cấu trúc mục (độc lập nghiệp vụ)
├── sourced_value_builders.py             # nguyên thuỷ dựng SourcedValue
├── provenance_gate.py                    # cổng 9
├── pipeline.py                            # điều phối
├── cli.py
├── models.py
└── templates/
    ├── template_base.py                   # tiện ích bóc field theo nhãn
    ├── template_registry.py               # sổ đăng ký + nhận diện
    └── chung_thu_tham_dinh_gia.py         # template đầu tiên
```

## Thêm template mới

1. Tạo `src/pdf_extract/templates/<ten_mau>.py`, dựng class có `template_id`, `matches(canonical_text) -> float`, `extract(lines, tables) -> dict`.
2. Thêm vào `REGISTERED_TEMPLATES` trong `template_registry.py`.
3. Bỏ PDF mẫu vào `samples/`, thêm số dòng kỳ vọng vào `EXPECTED_ASSET_ROW_COUNT` trong test.

Pipeline không cần sửa. Tài liệu không khớp mẫu nào bị từ chối tường minh — thà nói "không nhận ra mẫu này" còn hơn bóc bừa bằng mẫu gần đúng.

### Quy tắc khi viết bộ bóc field

- Bóc theo **nhãn có thật**, không theo vị trí tuyệt đối — vị trí vỡ ngay khi nội dung dài ra và đẩy dòng xuống.
- Giới hạn trong **phạm vi cột** chứa nhãn. Một dòng vật lý có thể chứa nhiều cột độc lập (dòng đầu chứng thư có `Số HĐ` bên trái và quốc hiệu bên phải).
- Nhãn phải **đủ đặc trưng**. `"Tài sản thẩm định"` khớp cả tiêu đề mục III; phải dùng `"- Tài sản thẩm định"`.
- Giá trị dài cần `multiline=True` để ghép các dòng nối tiếp tới trước mốc mở đầu mục mới.
- Chỉ **cắt chuỗi**, không suy luận — nhờ vậy mới qua được cổng 9.
- Cột bảng chứa **văn xuôi** phải gọi `rejoin_prose_cell()`. Mặc định của tầng dựng bảng là ghép liền (đúng cho số và mã); văn xuôi cần dấu cách giữa các dòng.

## Test

```bash
./.venv/bin/pytest -q      # 221 test
```

Test kiểm đúng những điều đã cam kết, không kiểm "chạy được": không mất ký tự giữa các engine, phủ `ToUnicode` 100%, mọi giá trị truy được về nguồn, số dòng bảng và thứ tự STT, và — quan trọng nhất — cổng nguồn gốc thật sự chặn được giá trị bịa cùng giá trị bị sửa một ký tự.

## Ngưỡng hình học tính theo tỉ lệ cỡ chữ

Tài liệu có thể đổi font. Nên **không có ngưỡng nào là điểm tuyệt đối** — tất cả tính theo tỉ lệ cỡ chữ, lấy trung vị (không phải trung bình, để tiêu đề cỡ lớn không kéo lệch phần thân):

| Ngưỡng | Tỉ lệ | Ở cỡ 12pt |
|---|---|---|
| Gom ký tự thành dòng | `0.3 × cỡ chữ` | 3.6pt |
| Tách cột theo khoảng trắng ngang | `0.7 × cỡ chữ` | 8.4pt |
| Gộp glyph vẽ trùng | `0.18 × cỡ chữ`, chặn trên 2.5pt | 2.16pt |

Đổi font hoặc đổi cỡ chữ không cần chỉnh lại code.

## Ô bảng bị ngắt dòng

Cách ghép đúng phụ thuộc **kiểu dữ liệu của cột**, mà tầng dựng bảng không biết — chỉ template biết. Nên:

- Mặc định: **ghép liền, không dấu cách**. Đúng cho cột số và mã — số tiền `1.234.567.000` bị ngắt dòng vẫn ra `"1.234.567.000"` chứ không phải `"1.234. 567.000"`.
- Cột văn xuôi: template gọi `rejoin_prose_cell()` để ghép có dấu cách, tránh `"...sử dụngđất..."`.

`SourcedValue.source_lines` giữ các dòng vật lý gốc để việc ghép lại luôn khả thi (không xuất ra JSON).

## Fixture âm — ca hỏng font thật

`samples/known-issues/Chung_Thu_Tham_Dinh_Gia_Demo.pdf` được sinh bằng `/Helvetica` (font base14, không có bảng `ToUnicode`, không có glyph tiếng Việt). Hậu quả: **mọi dấu tiếng Việt bị phá**.

```
Trong PDF  : "Giá trn Quynn sn dnng nnt LAND-LOT-001"
Đúng ra là : "Giá trị Quyền sử dụng đất LAND-LOT-001"
```

File được giữ làm fixture âm và **phải không bao giờ được gắn nhãn `verified`**. Hai cổng độc lập bắt được nó:

- **Cổng 2** bắt *nguyên nhân*: `/Helvetica` thiếu bảng `ToUnicode`, phủ chỉ 0.6
- **Cổng 5** bắt *hậu quả*: 30 ký tự mà engine chính đoán là `'n'` còn pypdf và Poppler trả về `'■'`

Đáng chú ý: **cổng 9 vẫn xanh 31/31**, và đó là đúng. Cổng nguồn gốc chứng minh *"giá trị khớp với những gì PDF ghi"*, không phải *"những gì PDF ghi là đúng"*. Trung thực với nguồn và tính đúng của nguồn là hai việc khác nhau — chỉ cổng 2 và cổng 5 nói được việc thứ hai. Đặt file ngoài `samples/` để không lẫn với mẫu chuẩn (vốn phải luôn xanh).

Nếu file này vốn định làm mẫu thật thì cần sinh lại bằng font có glyph tiếng Việt và có `ToUnicode` (DejaVu Sans, Noto Sans, Times New Roman nhúng) — ba font `DejaVuSans` trong cùng file đó hoàn toàn ổn, chỉ phần vẽ bằng `/Helvetica` là hỏng.

## Điều đã biết cần lưu ý

**PDF trộn text và scan bị từ chối toàn bộ**, không xử lý phần trang có text. Cố ý: file loại này cần con người xác nhận.

**Giá trị vắt qua trang không được tự ghép** — giữa hai phần còn chèn header/footer.

**Lỗi của nguồn được tái hiện nguyên vẹn.** Hai file mẫu chứa `COMPANY-BRANCH-001ng ty` (tool anonymize ăn mất chữ "Cô" của "Công ty"). Trích xuất trung thực gồm cả trung thực với lỗi của nguồn. "100%" nghĩa là *khớp với text layer trong PDF*, không phải *khớp với tài liệu gốc trước khi bị lỗi*.

## Câu hỏi mở

1. **Template tiếp theo**: báo cáo thẩm định giá, hợp đồng, hay loại nào? Mỗi loại cần vài file mẫu để chốt danh sách nhãn.
2. **Ngưỡng nhận diện template** đang là 0.6. Cần nới hay thắt tuỳ mức khác biệt giữa các biến thể thật.
3. **Nhãn mới của các bản chứng thư khác** sẽ rơi vào `unmapped_fields` — cần rà định kỳ để bổ sung tên tiếng Anh vào `chung_thu_field_names.py`. Hai file mẫu hiện tại không còn nhãn nào chưa ánh xạ.
4. **Cột nào là văn xuôi** trong các template sau: hiện phải khai báo tay bằng `rejoin_prose_cell()`. Với vài template thì ổn; nhiều hơn thì nên gắn kiểu cột vào khai báo template.
5. **Ngưỡng tách chữ trang trí** đang là `2.2 × cỡ chữ trung vị`. Watermark thật thường 3–5 lần, tiêu đề lớn nhất trong chứng thư 1.25 lần — khoảng cách rộng, nhưng cần xác nhận trên tài liệu thật có watermark.
6. **Trạng thái cho lỗi hỏng ký tự**: hiện là `needs_review` (vẫn xuất dữ liệu, mã thoát 1). Có nên nâng lên `rejected` không? Lập luận cho việc nâng: khi cổng 2 hoặc cổng 5 đỏ thì text *đã biết là sai*, khác về bản chất với "bóc thiếu field". Lập luận giữ nguyên: vẫn cần thấy dữ liệu để soi lỗi. CI hiện có thể tự chặn bằng `font_audit.coverage < 1` hoặc `char_multiset_match == false`.
