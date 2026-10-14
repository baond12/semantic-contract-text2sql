-- Mẫu SQL trên Omnichannel Retail v06 FINAL, database DEMO.
-- 1. Nhân viên và cửa hàng đang phụ trách
SELECT a.agent_code, a.full_name, s.store_name
FROM agents a LEFT JOIN stores s ON s.store_id=a.store_id
ORDER BY a.agent_code;

-- 2. Top 10 thương hiệu theo số SKU
SELECT b.brand_name, COUNT(*) AS product_count
FROM products p JOIN brands b ON b.brand_id=p.brand_id
GROUP BY b.brand_id ORDER BY product_count DESC, b.brand_name LIMIT 10;

-- 3. Product + đường dẫn Category 3 cấp
SELECT p.sku,p.name, b.brand_name,
       root.category_name AS category_l1,
       mid.category_name AS category_l2,
       leaf.category_name AS category_l3
FROM products p
JOIN brands b ON b.brand_id=p.brand_id
JOIN categories leaf ON leaf.category_id=p.category_id
JOIN categories mid ON mid.category_id=leaf.parent_category_id
JOIN categories root ON root.category_id=mid.parent_category_id
LIMIT 10;

-- 4. Số chat theo kênh
SELECT c.channel_name, COUNT(*) AS messages, COUNT(DISTINCT ch.conversation_id) AS sessions
FROM chats ch JOIN channels c ON c.channel_id=ch.channel_id
GROUP BY c.channel_id ORDER BY messages DESC;

-- 5. Đơn hàng tạo từ chat (một chat_id = một message dẫn tới order)
SELECT o.order_code, ch.conversation_id, a.full_name, c.channel_name
FROM orders o JOIN chats ch ON ch.chat_id=o.chat_id
JOIN agents a ON a.agent_id=o.agent_id
JOIN channels c ON c.channel_id=o.channel_id
ORDER BY o.order_id LIMIT 12;

-- 6. Tổng GMV demo của đơn có thanh toán thành công (chống đếm đôi do retries)
SELECT COUNT(*) AS paid_orders,
       SUM(o.gross_amount - o.discount_amount + o.shipping_fee) AS paid_order_amount
FROM orders o
WHERE EXISTS (SELECT 1 FROM payments p WHERE p.order_id=o.order_id AND p.status='success');

-- 7. Tồn kho khả dụng từng SKU theo cửa hàng tại một snapshot
SELECT s.store_code,p.sku,inv.snapshot_date,
       inv.qty_on_hand - inv.qty_reserved AS available_quantity
FROM inventory_snapshots inv
JOIN stores s ON s.store_id=inv.store_id
JOIN products p ON p.product_id=inv.product_id
WHERE inv.snapshot_date='2026-10-13'
ORDER BY available_quantity DESC LIMIT 15;

-- 8. Hoàn trả theo trạng thái
SELECT status,COUNT(*) AS request_count,SUM(refund_amount) AS refund_amount
FROM returns GROUP BY status;

-- 9. Đơn hàng có snapshot địa chỉ giao hàng
SELECT o.order_code,s.ship_to_formatted_address,s.shipping_status
FROM shipments s JOIN orders o ON o.order_id=s.order_id
LIMIT 10;
