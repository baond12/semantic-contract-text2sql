# Business Intent Ontology v01.1 | Báo cáo đóng băng taxonomy

**Ngày kiểm định:** 2026-10-14  |  **Database:** `omnichannel_retail` (SQLite v06)

## 1. Kết luận

**`INTENT_LABELS_FROZEN_V01_1 / REFERENTIAL_AUDIT_PASS / METHOD_ROUTING_NOT_READY`**.

Bộ dữ liệu đủ điều kiện dùng làm **nhãn tham chiếu v01.1 cho tập 162 câu hỏi đã gán nhãn**, bao gồm 138 ROUTE_INTENT và 24 policy actions. Điều này không chứng minh taxonomy phủ mọi câu hỏi tự nhiên hoặc classifier đã đạt accuracy. **Không sử dụng các method binding chưa được chuẩn hóa làm gold execution plan**.

| Hạng mục | Kết quả |
|---|---:|
| Business intents | 24 (23 atomic + 1 composite) |
| Thay đổi taxonomy | 15 giữ, 7 làm rõ, 2 đổi tên; không merge/tách |
| Scenarios | 162 |
| ROUTE_INTENT / CLARIFY / UNSUPPORTED / REFUSE | 138 / 10 / 8 / 6 |
| Boundary contrast pairs | 20 (tất cả hai nhãn khác nhau) |
| Base / Derived Classes | 20 / 25 |
| Properties vật lý | 157 |
| Methods tồn tại trong ontology | 117 |
| Foreign Keys / Relations | 31 / 31 |
| Ontology audit HIGH | 0 |
| Atomic core scenarios thiếu exact method đơn lẻ | **53** |
| Non-core chưa gán method gold | 44 (40 boundary examples + 4 composite) |
| Automated tests | **17/17 PASS** (16? kiểm 1 baseline + 16 mutation) |

## 2. Những thay đổi đã được duyệt

- Đổi tên `STORE_PERFORMANCE` thành `STORE_ANALYTICS`, `CHANNEL_PERFORMANCE` thành `CHANNEL_ANALYTICS` trong catalog, scenario, boundary, mapping và label policy.
- Làm rõ định nghĩa của **7 Intent**: `PRODUCT_DISCOVERY`, `PROMOTION_PROGRAM`, `SUPPLIER_NETWORK`, `ORDER_LIFECYCLE`, `PRODUCT_SALES`, `REVENUE_METRICS`, `REGIONAL_COVERAGE`.
- Sửa nhãn `BI-04-03` → `PRODUCT_DISCOVERY`, `BI-14-04` → `CHANNEL_ANALYTICS`.
- **BND-01-A** trước đây “GMV theo kênh...” đúng ra `CHANNEL_ANALYTICS`; **BND-19-A** trước đây “Số đơn theo kênh...” cũng đúng ra `CHANNEL_ANALYTICS`. Để duy trì test *hai nhãn khác nhau*, câu A của hai cặp đã được viết lại thành câu **cấp toàn hệ thống**. Câu gốc, nhãn sai, nhãn đúng được giữ trong sheet `Original Label Fixes`.
- 5 Method output mismatch đã duyệt được bỏ khỏi `gold_method_id`. 8 Method gap trước đó giữ nguyên, không tạo Method giả.

## 3. Các phát hiện bổ sung trong tối ưu

Đối chiếu các câu hỏi với **chữ ký Method thực tế của Object Ontology v01** cho thấy thêm **39 trường hợp** mà một Method không thể trả trực tiếp kết quả yêu cầu (thường là aggregate theo nhóm, TOP/RANK, LIST↔COUNT hoặc thiếu slot bắt buộc).

Ví dụ:

- `BI-04-03`: hỏi mọi SKU có promotion chính nhưng method cũ bắt buộc `promo_code`.
- `BI-15-01`: hỏi COUNT payment attempts nhưng method trả `List[Payment]`.
- `BI-16-02`: hỏi AVG thời gian giao nhưng method chỉ tính thời gian cho một shipment.
- `BI-17-03`: hỏi `return_qty` nhưng method tính `refund_amount`.
- `BI-19-02`: xếp hạng Store theo **GMV** nhưng method trả scalar theo một Store và chưa bảo đảm paid-order semantics.

Những trường hợp này đã được **bỏ binding gold, giữ nguyên Intent label**, đánh dấu `METHOD_SIGNATURE_REVIEW_REQUIRED`; toàn bộ bằng chứng ở `additional_method_signature_qa_v01_1.json` và sheet `Additional Signature QA`. Cộng với 14 trường hợp chính đã xác định, hiện có **53 atomic core scenarios thiếu exact single-method binding**. Điều này **không** có nghĩa dữ liệu hoặc task UNSUPPORTED: nhiều câu có thể giải bằng SQL composition ở phase Method Contracts v02.

## 4. Nguyên tắc độc lập và phân định Intent

- Câu hỏi hợp lệ trong 162 test cases nhận **đúng một** nhãn Intent chính; các policy actions không phải Intent.
- `GROUP BY Channel` → `CHANNEL_ANALYTICS`, `GROUP BY Store` → `STORE_ANALYTICS`, `GROUP BY Region` → `REGIONAL_COVERAGE`.
- Một Channel/Store/Region là **filter cố định** mà không thay output grain → giữ Intent theo metric hay đối tượng chính.
- `ORDER BY`, `TOP`, `RANK` không tự làm đổi Intent nếu đơn vị kết quả không đổi.
- `MULTI_OUTPUT_REPORT` là composite label (không phải Method); planner phải tách tác vụ trước khi execution.
- Intent có thể dùng chung Class/Property/Method. **Độc lập = nhãn loại trừ nhau theo annotation contract**, không có nghĩa các domain table disjoint hoặc tính độc lập thống kê.

## 5. Kiểm định và giới hạn

**PASS:** 20 bảng vật lý, 31 FK SQLite, 20 base class, 25 derived class có tối đa hai base, 157 physical properties, 117 method IDs, 31 ontology relations; Intent/Scenario/Boundary tham chiếu hợp lệ. Test mutate các trường: trùng ID, ID không tồn tại, sai policy gate, boundary lệch, method của class sai, Method đã loại bỏ được gắn lại, v.v.

**Chưa đánh giá:** mức độ bao phủ câu hỏi mới ngoài 162 câu, độ chính xác classifier thực tế, query-result equivalence, SQL semantic correctness, các quy tắc SQL templates và cross-class composition runtime. `REGIONAL_COVERAGE` vẫn cần chú ý JOIN đúng quan hệ theo từng cặp; không tạo class dẫn xuất >2 base.

**Quyết định cuối:** Đóng băng **Intent labels v01.1** và dùng cho bước chuẩn bị classifier; chuyển toàn bộ method gaps sang Method Contract Normalization, không để cản bước học classifier. Cần đánh giá trên tập unseen để đo chất lượng classifier trước khi đưa vào routing thực.
