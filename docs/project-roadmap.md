# Lộ trình và chi phí

> Kèm `system-architecture.md`. Mọi số tiền là **ước lượng có giả định nêu rõ**, để làm cơ sở thương lượng — không phải báo giá.

## 1. Điểm xuất phát (đã có, đã đo)

| | |
|---|---|
| Code | 4.661 dòng `src/`, 2.866 dòng `tests/`, 28 module |
| Test | 312 pass / 33 skip |
| Định dạng | PDF (text layer), DOCX |
| Template | 1 (chứng thư thẩm định giá) |
| Cổng bảo đảm | 6, có 3 cổng `null` cho DOCX (khai báo tường minh, không báo xanh giả) |
| Đã chứng minh | 1019/1019 giá trị qua cổng nguồn gốc; coverage ký tự 100.00% trên 15 file; PDF vs DOCX cùng tài liệu → cùng JSON |

Nghĩa là: **phần khó nhất — mô hình bảo đảm — đã xong và đã được chứng minh.** Phần còn lại là công việc hạ tầng và mở rộng, rủi ro kỹ thuật thấp hơn nhiều.

## 2. Bốn giai đoạn

### P0 — Demo (xong)
Mô hình bảo đảm, 2 định dạng, 1 template, corpus test.

### P1 — Đưa lên production (12–14 tuần, ~6 FTE)

| Hạng mục | Ghi chú |
|---|---|
| `intake-api` + blob store + queue + DLQ | sha256 dedupe, chữ ký byte |
| `extract-worker` đóng gói từ code hiện tại | + sandbox, cap tài nguyên |
| **`xlsx_reader`** | Phần code mới lớn nhất của P1. Chốt 3 quyết định ở mục 5 của architecture doc trước khi code. |
| `record-store` + đóng dấu version + event stream | append-only |
| `template-registry` = config có version trong git | + CI golden corpus, đây là quality gate của mọi PR |
| `review-console` v1 | render file gốc cạnh JSON |
| CI/CD, IaC (Terraform), môi trường staging | |

**Điều kiện xong**: upload 1 file qua API → JSON có provenance đầy đủ trong DB, hoặc bị chặn kèm lý do cụ thể; corpus hồi quy chạy trong CI; deploy được bằng một lệnh.

### P2 — Quy mô và tìm kiếm (6–8 tuần, ~4 FTE)

Multi-tenant (tenant_id + RLS + tách blob prefix) · embedding + pgvector · API truy vấn RAG · **LLM triage** (gợi ý template, ngoài đường tin cậy) · **LLM ops-assist** (đọc `unmapped_fields` → đề xuất PR field map) · dashboard `blocked_rate` / coverage / gate failures · 3–5 template mới do BA làm để kiểm nghiệm quy trình onboard.

### P3 — Làm cứng (4–6 tuần, ~3 FTE)

Sandbox parser hoàn chỉnh (defusedxml, giới hạn giải nén, kill on overrun) · KMS + retention + audit log · anonymize pipeline cho corpus · load test + SLO + alert · DR/backup có tập diễn.

**Tổng: ~5–6 tháng lịch** tới trạng thái vận hành được cho khách doanh nghiệp.

## 3. Chi phí phát triển

**Giả định**: đội in-house tại Việt Nam, chi phí *fully loaded* (lương + bảo hiểm + thiết bị + overhead), không phải giá bán.

| Vai trò | $/người/tháng | P1 | P2 | P3 |
|---|---|---|---|---|
| Tech lead / SA | 4.000–5.500 | 1,0 | 0,5 | 0,5 |
| Senior BE Python | 3.000–4.000 | 2,0 | 1,5 | 1,0 |
| DevOps / Platform | 3.000–4.000 | 1,0 | 0,5 | 1,0 |
| FE (review console) | 2.500–3.500 | 0,5 | 0,5 | — |
| QA / BA làm template | 2.000–3.000 | 0,5 | 1,0 | 0,5 |
| PM | 3.000–4.000 | 0,5 | 0,5 | — |
| **FTE** | | **5,5** | **4,5** | **3,0** |

| Giai đoạn | Thời gian | Ước tính | Khoảng |
|---|---|---|---|
| P1 | **3,25 tháng** | ~59.000 $ | **53–79k** |
| P2 | 1,75 tháng | ~27.000 $ | **22–34k** |
| P3 | 1,25 tháng | ~13.000 $ | **10–18k** |
| **Tổng** | **~6,25 tháng** | **~99.000 $** | **85–131k $** |

*P1 kéo dài 12–14 tuần (thay vì 10–12) và DevOps lên 1,5 FTE vì phải provisioning on-prem — Patroni, MinIO, HAProxy/keepalived thay cho Terraform + AWS. Xem `deployment-guide.md` §7.*

Nếu tính theo giá bán cho khách ngoài (hệ số 2–2,5×): **160–290k $**.

### Chi phí thêm một template (con số quan trọng nhất về mặt kinh doanh)

Sau P1, thêm một template = BA soát nhãn + dựng fixture + thêm vào corpus hồi quy, **không cần dev**:

| | |
|---|---|
| Công | 2–5 người-ngày |
| Chi phí | **200–600 $/template** |

Đây là con số quyết định mô hình kinh doanh có chạy được hay không. Nó rẻ được **chính vì** template là config có version và có corpus hồi quy tự động — nếu để template là dữ liệu trong DB không review được, con số này sẽ là 2–5 người-*tuần* vì mỗi lần thêm là một lần đánh cược lên toàn hệ thống.

## 4. Chi phí hạ tầng — on-premise, theo khối lượng thực tế

**Khối lượng đã xác nhận: 1.000 tài liệu/tháng giai đoạn nhập kho, 500/tháng ổn định.** Chi tiết cấu hình: `hardware-overview.md`.

| | Capex | Hằng tháng |
|---|---|---|
| Server ×2 (gộp app + worker + database + lưu trữ) | 180–260 tr | |
| Mạng, tủ rack, UPS, firewall | 60–120 tr | |
| Sao lưu (SSD mã hoá luân phiên) | 20–50 tr | |
| Colo 4–6U / 0,5 kW | | 5–12 tr |
| **Vận hành 0,2–0,4 FTE** | | **16–40 tr** |
| Khấu hao 20%/năm | | 4–7 tr |
| **Tổng** | **260–430 tr** | **25–59 tr/tháng** |
| *Node GPU — chỉ khi cần truy vấn tương tác* | *+395–545 tr* | |

**Năm 1: ~560 tr – 1,14 tỷ đ.**

*Giảm mạnh so với dự toán đầu (0,92–1,45 tỷ capex) sau hai lần hiệu chỉnh: **đo thật** tải xử lý (0,6 giây và ~100 MB RAM cho một chứng thư 5 trang), và **xác nhận khối lượng thật** (500–1.000 tài liệu/tháng thay vì 100.000). Ở khối lượng này, CPU cần **5 core-phút/tháng** và toàn bộ dữ liệu sau 5 năm **dưới 20 GB** — không cần tách máy theo vai trò, không cần thiết bị lưu trữ riêng, chưa cần GPU.*

Ba điều đáng chú ý:

- **Hai máy là để dự phòng, không để tăng năng lực.** Một máy đã dư hàng trăm lần. Nhưng `extract-worker` và database nằm trong đường tin cậy — một máy lỗi là dừng dịch vụ và không còn bản sao tại chỗ.
- **Chưa cần node GPU.** Ở 500 tài liệu/tháng, embedding và phân loại template chạy được trên CPU (25–80 phút/tháng). Chỉ tính năng truy vấn tương tác cần GPU. Hoãn được khoản 395–545 tr, và bổ sung sau không phải sửa gì — vì mô hình ngôn ngữ nằm ngoài đường tin cậy.
- **Khoản lớn nhất là nhân sự vận hành** (16–40 tr/tháng), và nó **không giảm theo khối lượng**: hai máy chủ cần vận hành như nhau dù xử lý 500 hay 50.000 tài liệu.

### Chi phí trên mỗi tài liệu — và kết luận về phạm vi

Ở 500 tài liệu/tháng, 5 năm là 30.000 tài liệu:

| | Tổng 5 năm | Mỗi tài liệu |
|---|---|---|
| Hạ tầng | 1,76 – 3,97 tỷ | 59 – 132 nghìn đ |
| **Phát triển** | **2,2 – 3,4 tỷ** | **73 – 113 nghìn đ** |
| **Tổng** | **3,96 – 7,37 tỷ** | **132 – 245 nghìn đ** |

**Chi phí phát triển giờ ngang bằng chi phí hạ tầng** — trong khi ở dự toán ban đầu (100.000 tài liệu/tháng) nhân công soát tài liệu chiếm phần lớn. Ở khối lượng thật, nhân công soát chỉ **1,7 giờ/tháng**, gần như bằng không.

→ **Kết luận đổi hướng: không tối ưu tỉ lệ tự động hoá, mà tối ưu phạm vi phát triển.**

Cụ thể, các hạng mục của P2 chỉ có giá trị ở quy mô lớn nên **nên cắt hoặc hoãn**:

| Hạng mục P2 | Ở 500 tài liệu/tháng | Đề xuất |
|---|---|---|
| Multi-tenant | Nếu chỉ một khách, on-premise | **Cắt** |
| Autoscale theo độ sâu queue | 2 worker tĩnh là đủ vĩnh viễn | **Cắt** |
| LLM triage đoán template | Người chọn template mất 5 giây; hoặc dùng đối chiếu embedding, miễn phí | **Cắt mô hình sinh văn bản**, giữ đối chiếu embedding |
| Dashboard `blocked_rate` theo template | 50 tài liệu cần soát mỗi tháng — xem danh sách là đủ | **Đơn giản hoá** |
| Tìm kiếm + truy vấn RAG | Là lý do duy nhất cần GPU | **Giữ nếu khách xác nhận cần** |

Cắt các hạng mục trên đưa P2 từ **22–34k $ về khoảng 8–15k $**, và bỏ được node GPU (−395–545 tr). Tổng chi phí phát triển xuống **71–112k $**.

Điều này không làm giảm cam kết chất lượng — toàn bộ cơ chế bảo đảm nằm ở P1 và P3, không ở P2.

### Giá trị của hệ thống ở khối lượng này

Cần nói rõ để không đặt kỳ vọng sai: **ở 500 tài liệu/tháng, hệ thống không hoàn vốn bằng tiết kiệm nhân công.** Nhập liệu thủ công cần ~100 giờ/tháng ≈ 0,6 nhân sự ≈ 1,5–3 tỷ trong 5 năm — thấp hơn tổng chi phí hệ thống.

Giá trị nằm ở bốn điểm khác:

| | Thủ công | Hệ thống |
|---|---|---|
| Độ chính xác số liệu | sai sót 1–3% là mức thông thường | **100%, có chứng minh từng giá trị** |
| Truy vết | không có | mỗi giá trị kèm trang và toạ độ trong file gốc |
| Tra cứu | theo tên file | tìm kiếm toàn bộ nội dung |
| Thời gian mỗi tài liệu | 10–15 phút | 0,6 giây |

Điểm đầu là điểm quyết định: nếu vấn đề cần giải là **sai sót trong số liệu tài chính**, thì nhập liệu thủ công không phải phương án thay thế — nó chính là nguyên nhân.

## 5. Rủi ro

| Rủi ro | Mức | Xử lý |
|---|---|---|
| DOCX thật của khách dùng Heading style / list của Word / bảng hai cột làm nhãn — khác mẫu hiện tại (sinh từ PDF) | **Cao** | Cần 1 file DOCX thật để kiểm. Rủi ro này chỉ giảm bằng file thật, không bằng code. |
| Số tiền bị ngắt dòng sau dấu `.` (`1.234.` + `567.000`) — quy tắc nối dòng hiện chỉ xử lý ngắt tại `-` | **Trung bình** | Cần 1 chứng thư có số tiền thật |
| Cấu trúc XLSX khó hơn dự kiến (header nhiều tầng, block rời) | Trung bình | Chốt 3 quyết định ở architecture §5 **trước** khi code; timebox P1 |
| Khách yêu cầu OCR cho file scan | Trung bình | Từ chối tường minh, hoặc báo là sản phẩm riêng có SLA riêng |
| Sức ép "cứ để AI tự bóc cho nhanh" | **Cao** | Đây là rủi ro chính trị, không phải kỹ thuật. Xem architecture §2.2 — mất cam kết là mất cả sản phẩm. |
| Tên công ty / địa danh thật đang nằm trong repo public | Cao | Anonymize pipeline (P3), hoặc chuyển repo về private ngay |

## Câu hỏi chưa chốt

1. **Quy mô thật**: bao nhiêu tài liệu/tháng, bao nhiêu loại template? Toàn bộ mục 4 dựng trên giả định 100k doc/tháng — nếu thực tế là 1.000/tháng thì P2 (multi-tenant, search) nên hoãn; nếu là 1 triệu thì phải xem lại queue và Postgres.
2. **Một khách hay nhiều khách?** Quyết định multi-tenant có nằm ở P1 thay vì P2.
3. **XLSX: `value`, `display`, hay cả hai là "nội dung của file"?** Và chính sách với sheet/dòng ẩn. Chặn việc code `xlsx_reader`.
4. **Review console có được sửa value bằng tay không?** Tôi đề xuất không (mất truy vết). Nếu nghiệp vụ buộc phải có, cần chốt sớm vì ảnh hưởng schema.
5. **Ai chịu trách nhiệm khi một giá trị sai lọt ra?** Câu này định hình SLA và mức đầu tư vào review — cần trả lời trước khi ký hợp đồng, không phải sau.
6. Repo `vanhaiit/ocr` đang public với dữ liệu chưa ẩn danh — giữ nguyên hay chuyển private?
