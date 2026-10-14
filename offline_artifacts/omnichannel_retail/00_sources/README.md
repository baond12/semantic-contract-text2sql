# Omnichannel Retail v06 FINAL | Demo ERD + SQLite

**Trạng thái: DONE cho mục đích review và demo nhóm.** Tổng **20 bảng nghiệp vụ** theo schema v05, không thêm bảng `conversations` hoặc `product_promotions`.

## File trong gói

| File | Mục đích |
|---|---|
| `omnichannel_retail.sqlite3` | SQLite đầy đủ dữ liệu, mở trực tiếp bằng DB Browser for SQLite hoặc DBeaver. |
| `schema.sql` | Canonical DDL v06, tạo đủ 20 bảng và indexes. |
| `seed_data.sql` | Toàn bộ INSERT, tự chứa cả 300 sản phẩm và dữ liệu demo. |
| `ERD.png`, `ERD.svg` | ERD chi tiết đủ bảng/cột, PK/FK, tạo **trực tiếp từ `PRAGMA`** của SQLite. |
| `ERD_overview.png`, `ERD_overview.svg` | Sơ đồ tổng quan 20 bảng, ưu tiên nhìn quan hệ. |
| `ERD.mmd` | Mermaid ERD có thể chỉnh sửa. |
| `product_source_trace.jsonl` | 300 dòng đối chiếu brand, category L1/L2/L3 và `promotions` JSON từ nguồn. |
| `sample_queries.sql` | Truy vấn ví dụ giúp nhóm demo. |
| `validation.json` | Kết quả kiểm thử trên database vật lý và việc dựng lại từ SQL. |
| `rebuild_from_sql.py` | Tạo lại SQLite chỉ từ `schema.sql` + `seed_data.sql`, **không cần file nguồn**. |

## Phạm vi

- 17 bảng retail cũ, **thay nội dung/cấu trúc** bảng `products` bằng bản chuẩn hóa từ `knowledge_base.sqlite3 → dim_products`.
- 3 bảng mới `agents`, `chats`, `addresses`.
- Tổng 20 bảng, ERD và DDL dùng **tên bảng `products`**.
- Không tạo các bảng FTS của knowledge base vì đây là database demo Omnichannel Retail, không phải bản sao engine tìm kiếm.

## Số dòng

| Bảng | Dòng | Nguồn/loại dữ liệu |
|---|---:|---|
| `products` | 300 | Product từ `knowledge_base.sqlite3/dim_products` (normalize FK). |
| `brands` | 72 | Các brand phân biệt từ Product nguồn. |
| `categories` | 229 | Node phân cấp sinh từ category L1/L2/L3 của Product nguồn; tên lặp ở các nhánh được giữ tách biệt. |
| `promotions` | 4 | 3 chương trình map từ nhãn % nguồn rõ ràng + 1 chương trình demo cho đơn hàng. |
| `regions` | 5 | MOCK. |
| `stores` | 5 | MOCK. |
| `channels` | 6 | MOCK: Shopee, TikTok Shop, Zalo, website, offline, Facebook. |
| `suppliers` | 12 | MOCK. |
| `product_suppliers` | 393 | Quan hệ MOCK tham chiếu 300 Product nguồn. |
| `customers` | 30 | MOCK. |
| `agents` | 10 | MOCK. |
| `addresses` | 30 | MOCK. |
| `chats` | 100 | MOCK, 25 hội thoại × 4 tin nhắn. |
| `orders` | 50 | MOCK, 25 đơn có Chat liên kết và 25 đơn không qua Chat. |
| `order_items` | 103 | MOCK, có sản phẩm và giá từ catalog. |
| `payments` | 55 | MOCK, có cả failed/pending/success phục vụ demo truy vấn. |
| `shipments` | 22 | MOCK, liên kết Order + Address và lưu snapshot giao hàng. |
| `returns` | 4 | MOCK, hoàn trả một phần theo Order Item. |
| `inventory_snapshots` | 895 | MOCK, tổng `qty_on_hand` theo Product tại ngày snapshot bằng `stock_quantity` từ nguồn. |
| `support_tickets` | 20 | MOCK. |

## Quy ước mô hình v05 được giữ

- `agents.store_id → stores.store_id`.
- `chats.channel_id → channels.channel_id`, mỗi dòng `chats` là **một tin nhắn**, `conversation_id` chỉ dùng để nhóm tin nhắn (không có bảng Conversation riêng).
- `orders.chat_id → chats.chat_id`: tin nhắn agent dẫn trực tiếp tới lúc tạo đơn, có thể NULL.
- `orders.agent_id → agents.agent_id`: agent tạo/chốt đơn, có thể NULL với đơn tự động.
- `products.brand_id → brands.brand_id`.
- `products.category_id → categories.category_id`, trỏ đến node **category cấp 3**. `categories.parent_category_id` lưu đường dẫn 3 cấp.
- `products.promotion_id → promotions.promotion_id`, **một khuyến mãi chính**, có thể NULL.
- Các trường `brand`, `category_l1/l2/l3`, `promotions` của nguồn **không còn là cột vật lý trong products** vì thiết kế v05 đã chuẩn hóa; bản gốc không thay đổi, đường dẫn và nội dung gốc của 300 sản phẩm được lưu trong `product_source_trace.jsonl`.
- 300 Product giữ nguyên ID, SKU, tên, giá, thông tin tồn, mô tả, thông số, ảnh, JSON khác và BLOB embedding từ nguồn.
- `TEXT`/`VARCHAR PRIMARY KEY` của 4 bảng `products`, `agents`, `chats`, `addresses` được bổ sung `NOT NULL` để đúng hành vi khóa chính trên SQLite.

### Lưu ý về khuyến mãi

`promotions` JSON nguồn có **33 nhãn ưu đãi phân biệt**, bao gồm quà tặng, trả góp và giao hàng, không nhất thiết là các đợt giảm giá phần trăm. Bản v06 chỉ ánh xạ nhãn phần trăm xác định chính xác `Sinh viên giảm 5%/10%/20%` sang khuyến mãi chính của Product (**13 Product có `promotion_id`**). Các ưu đãi khác **không được ngụy tạo thành discount_pct**, vẫn đọc được trong `product_source_trace.jsonl` hoặc database nguồn gốc. `DEMO_BASKET10` là khuyến mãi phát sinh ở dữ liệu *order* giả lập, không đại diện cho một ưu đãi nguồn.

### Lưu ý về địa chỉ

`addresses` và snapshot `ship_to_*` trong `shipments` đều là MOCK. Chỉ dùng tọa độ xấp xỉ cho mục đích giả lập; **không gọi Google API**, không tạo `google_place_id` giả và không coi là địa chỉ giao hàng đã xác minh.

## Cách dùng

**Mở để review ngay:** dùng DB Browser for SQLite hoặc DBeaver, chọn file `omnichannel_retail.sqlite3`. Xem `ERD_overview.svg` để duyệt quan hệ, `ERD.svg` để xem toàn bộ cột.

**Tạo lại DB từ SQL, không cần file Product gốc:**

```bash
python rebuild_from_sql.py --output ./omnichannel_retail_rebuilt.sqlite3
```

Hoặc chạy `schema.sql`, sau đó `seed_data.sql` trong công cụ SQLite hỗ trợ chạy script (bật `PRAGMA foreign_keys = ON`).

**Kiểm tra nhanh bằng Python:**

```python
import sqlite3
con = sqlite3.connect("omnichannel_retail.sqlite3")
print(con.execute("PRAGMA integrity_check").fetchone())
print(con.execute("PRAGMA foreign_key_check").fetchall())
print(con.execute("SELECT COUNT(*) FROM products").fetchone())
```

**Demo nghiệp vụ:** chạy `sample_queries.sql` để xem Brand/Category, chat qua Channel, Order từ Chat/Agent, doanh thu có payment, tồn kho, giao hàng và hoàn trả.

## Điều kiện nghiệm thu đã kiểm tra

```text
Business tables                 20/20 PASS
All tables populated            20/20 PASS
Products from source               300 PASS
SQLite integrity_check               ok
SQLite foreign_key_check     0 violations
Physical FK mappings                  31
ERD FK coverage                  31/31 PASS
schema.sql + seed_data.sql     exact replay PASS
Primary key / FK negative tests      5/5 PASS
```

**Ranh giới:** Dữ liệu doanh thu, giao hàng, nhân viên và khách hàng là giả lập, phù hợp review/demo, không được xem là số liệu vận hành có thật. SQLite demo này không phải migration dữ liệu nghiệp vụ cũ; không có yêu cầu chạy audit Ontology/Text2SQL trong phạm vi hiện tại.
