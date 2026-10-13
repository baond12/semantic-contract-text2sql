# Text2SQL Omnichannel Retail Benchmark v01

Ngày thiết kế: 2026-10-12. Ngôn ngữ: Vietnamese. SQL dialect: SQLite 3.
Dữ liệu HOÀN TOÀN TỔNG HỢP, không chứa thông tin cá nhân thật.

## Nguồn thiết kế
Dựa trên cấu trúc của hai file người dùng cung cấp:
- "Danh sách kịch bản.xlsx": nhóm nghiệp vụ, tình huống, khả năng xử lý, mức ưu tiên.
- "Testcase_AI_ChatHub.xlsx": ground truth, PASS/FAIL, chấm điểm, dashboard, ví dụ.
Không sao chép lỗi chấm điểm/logic từ các file nguồn.

## File trong gói
1. Text2SQL_Danh_sach_kich_ban.xlsx : 85 tình huống/nhóm Intent; coverage; 21 method contracts; tổng quan DB.
2. Text2SQL_Testcase_Benchmark.xlsx  : 85 testcase; gold SQL + expected result + SHA256;
   14 ví dụ PASS, 16 ví dụ FAIL; rubric 10 điểm; dashboard tự cập nhật theo chấm thực tế.
3. text2sql_omnichannel_retail.sqlite : SQLite database có dữ liệu tổng hợp.
4. text2sql_schema.sql : DDL tạo bảng, FK và indexes.
5. text2sql_gold_queries.sql : Các SQL chuẩn để tham khảo/copy/chạy trong SQLite.
6. text2sql_benchmark_spec.json : Machine-readable testcase, gồm SQL, method ID và expected results.
7. text2sql_negative_examples.json : SQL sai có chủ đích, failure types và diagnostic outputs.
8. generate_text2sql_demo_db.py : Seed dữ liệu lặp lại bằng random seed=20261012.
9. build_text2sql_specs.py : Dựng lại JSON golden benchmark sau khi seed DB.
10. build_negative_examples.py : Dựng lại negative SQL examples.
11. create_text2sql_workbooks.py : Dựng lại 2 Excel bằng artifact_tool.

## Quy mô
- 17 bảng; 8 cửa hàng; 4 kênh bán (Shopee, TikTok Shop, Website, Offline).
- 72 SKU; 850 khách hàng anonymous; 4200 đơn hàng; các bảng payment, shipment, returns,
  inventory snapshots, promotions, tickets, supplier mapping.
- 85 use cases: 70 SQL gold (đã EXECUTE và ghi expected result),
  6 CLARIFY, 5 UNSUPPORTED, 4 REFUSE.
- Các độ khó L1..L5; tình huống multi-turn, SQL window, CTE, nhiều bảng, guardrails.

## Các quy tắc semantic bắt buộc
1. GMV (merchandise GMV) = SUM(orders.gross_amount - orders.discount_amount)
   trên các orders status IN ('paid','shipped','delivered') VÀ EXISTS payment success.
   Không cộng phí vận chuyển, chưa trừ hoàn trả; thời kỳ theo orders.ordered_at.
2. Net sales = GMV - tổng refund_amount của returns.status='approved'
   trên cohort cùng orders.ordered_at; không trừ requested/rejected returns.
3. Inventory available = qty_on_hand-qty_reserved của snapshot mới nhất
   theo (store_id,product_id) với snapshot_date <= as_of_date; as-of 2026-10-11.
4. Số đơn = COUNT theo grain orders, không JOIN one-to-many rồi COUNT(*) bị fanout.
5. Discount = orders.discount_amount ở cấp order; doanh thu theo sản phẩm
   SUM(order_items.quantity*unit_price - order_items.line_discount).
6. Dùng khoảng thời gian nửa kín [start,end): >= '2026-09-01' AND < '2026-10-01'.
7. Nếu câu NL thiếu metric/period/grain quan trọng => CLARIFY, không đoán nghĩa.
8. Dữ liệu không có traffic_sessions, giá vốn, live attribution, khách hàng PII.
   Yêu cầu dựa vào các trường đó => UNSUPPORTED.
9. Không chạy UPDATE, DELETE, INSERT, DROP, GRANT hoặc truy vấn credential.

## Chạy DB trực tiếp (Python standard library)
```python
import sqlite3
conn = sqlite3.connect('file:text2sql_omnichannel_retail.sqlite?mode=ro', uri=True)
cur = conn.execute('SELECT COUNT(*) AS orders_count FROM orders')
print(cur.fetchall())
conn.close()
```
Ví dụ chắc chắn hợp lệ: test T2SQL-017, T2SQL-023, T2SQL-041.
Ví dụ có expected 0-row: T2SQL-008, T2SQL-067. Đây là test no-result thật, không phải lỗi SQL.

## Cách đánh giá hệ thống Text2SQL
A. Với EXECUTE_SQL: đối chiếu action, syntax/permission, expected columns, result set
   và semantics từ method contract. KHÔNG chỉ so sánh text SQL với gold.
B. Với CLARIFY/REFUSE/UNSUPPORTED: chấm action và nội dung lý giải, KHÔNG cố execute SQL.
C. Điền cột R-Y ở sheet Test_Cases, điền actual SQL/response, điểm và trace. Dashboard
   lấy trạng thái từ công thức Z-AA. Ví dụ PASS/FAIL chỉ là demo minh họa không tính KPI.
D. Gold SHA256 dùng để regression so sánh raw ordered result. Hai query tương đương
   nhưng ORDER BY khác cần canonicalize trước khi dùng hash làm điều kiện PASS.

## Giới hạn và hướng nghiên cứu
Database synthetic chỉ phù hợp kiểm tra contract consistency, regression, grounding,
semantic errors và demo pipeline. KHÔNG thể dùng tự nó để tuyên bố SOTA Text2SQL.
Benchmark học thuật nên đánh giá tiếp trên bộ public real-world như BIRD/Spider
với cách map ontology/method/template và tiêu chí execution accuracy.

## Chạy lại toàn bộ
Cài Python 3.10+ và artifact_tool (chỉ cần để tạo Excel). Để các file .py
cùng thư mục gốc. Chạy theo thứ tự:
  python generate_text2sql_demo_db.py
  python build_text2sql_specs.py
  python build_negative_examples.py
  python create_text2sql_workbooks.py

Dataset built as a standalone synthetic demo, no external API required.
