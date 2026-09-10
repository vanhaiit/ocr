# Hạ tầng phần cứng

Khối lượng: **1.000 tài liệu/tháng** (giai đoạn nhập kho) → **500 tài liệu/tháng** (ổn định).
Giá tham khảo thị trường Việt Nam, đã gồm VAT 10%.

| | Hạng mục | Cấu hình | SL | Giá VN |
|---|---|---|---|---|
| **A** | **PHẦN CỨNG PHỤC VỤ SERVICE** | | | |
| A1 | Server (gộp API, worker, database, lưu trữ) | 8–16 core · 64GB ECC · 4× 2TB NVMe RAID10 · 2 nguồn · bảo hành 3 năm onsite | 2 | 180 – 260 tr |
| A2 | Mạng & phụ trợ | 2× switch 10GbE managed · firewall · tủ rack · UPS online 3kVA · PDU | 1 bộ | 60 – 120 tr |
| A3 | Sao lưu | SSD enterprise mã hoá, luân phiên lưu giữ ngoài site | 2 bộ | 20 – 50 tr |
| | **Cộng A** | 4–6U · 300–500 W · không cần nhánh điện riêng | | **260 – 430 tr** |
| **B** | **PHẦN CỨNG PHỤC VỤ LLM** | *chưa cần ở giai đoạn đầu* | | |
| B1 | Card GPU | RTX PRO 6000 Blackwell **96GB** GDDR7 ECC | 1 | 275 – 350 tr |
| B2 | Máy chứa card | 24 core · 128GB DDR5 ECC · 2× 2TB NVMe · PSU 1.200W Titanium · 4U | 1 | 120 – 195 tr |
| | **Cộng B** | +4U · +750 W · cần nhánh điện riêng và điều hoà 24/7 | | **395 – 545 tr** |
| | **TỔNG (A + B)** | | | **655 – 975 tr** |
| | **TỔNG giai đoạn đầu (chỉ A)** | | | **260 – 430 tr** |

**Vận hành: 25 – 59 tr/tháng** — colo 4–6U (5–12 tr) + nhân sự 0,2–0,4 người (16–40 tr) + khấu hao (4–7 tr).

### Ba ghi chú

1. **Phần B hoãn được.** Ở 500–1.000 tài liệu/tháng, embedding và phân loại template chạy trên CPU (25–80 phút/tháng). Chỉ **tính năng truy vấn tương tác** cần GPU. Bổ sung sau không phải sửa gì trong hệ thống đang chạy.
2. **Hai server ở A1 là để dự phòng, không để tăng năng lực.** Khối lượng thật cần 5 core-phút/tháng; một máy đã dư hàng trăm lần. Nhưng worker và database nằm trong đường tin cậy — một máy lỗi là dừng dịch vụ và không còn bản sao tại chỗ.
3. **Cấu hình A chịu được tới ~5.000 tài liệu/tháng** mà không phải thay đổi gì. Toàn bộ dữ liệu sau 5 năm dưới 20 GB.
