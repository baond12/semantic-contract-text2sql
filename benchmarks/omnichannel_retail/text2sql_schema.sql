-- Text2SQL demonstration schema. All monetary fields are in VND.
PRAGMA foreign_keys = ON;
CREATE TABLE regions (
  region_id INTEGER PRIMARY KEY, region_code TEXT NOT NULL UNIQUE,
  region_name TEXT NOT NULL
);
CREATE TABLE stores (
  store_id INTEGER PRIMARY KEY, store_code TEXT NOT NULL UNIQUE,
  store_name TEXT NOT NULL, region_id INTEGER NOT NULL REFERENCES regions(region_id),
  city TEXT NOT NULL, opened_on TEXT NOT NULL
);
CREATE TABLE channels (
  channel_id INTEGER PRIMARY KEY, channel_code TEXT NOT NULL UNIQUE,
  channel_name TEXT NOT NULL, channel_type TEXT NOT NULL CHECK(channel_type IN ('marketplace','web','offline'))
);
CREATE TABLE brands (
  brand_id INTEGER PRIMARY KEY, brand_name TEXT NOT NULL UNIQUE
);
CREATE TABLE categories (
  category_id INTEGER PRIMARY KEY, category_name TEXT NOT NULL,
  parent_category_id INTEGER REFERENCES categories(category_id)
);
CREATE TABLE products (
  product_id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, product_name TEXT NOT NULL,
  brand_id INTEGER NOT NULL REFERENCES brands(brand_id),
  category_id INTEGER NOT NULL REFERENCES categories(category_id),
  list_price INTEGER NOT NULL CHECK(list_price >= 0),
  is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
);
CREATE TABLE suppliers (
  supplier_id INTEGER PRIMARY KEY, supplier_name TEXT NOT NULL UNIQUE, region_id INTEGER NOT NULL REFERENCES regions(region_id)
);
CREATE TABLE product_suppliers (
  product_id INTEGER NOT NULL REFERENCES products(product_id),
  supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
  is_primary INTEGER NOT NULL CHECK(is_primary IN (0,1)),
  PRIMARY KEY (product_id,supplier_id)
);
CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY, customer_code TEXT NOT NULL UNIQUE,
  region_id INTEGER NOT NULL REFERENCES regions(region_id),
  customer_segment TEXT NOT NULL CHECK(customer_segment IN ('Retail','VIP','Wholesale')),
  joined_at TEXT NOT NULL
);
CREATE TABLE promotions (
  promotion_id INTEGER PRIMARY KEY, promo_code TEXT NOT NULL UNIQUE, promo_name TEXT NOT NULL,
  start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  discount_pct INTEGER NOT NULL CHECK(discount_pct BETWEEN 0 AND 100)
);
CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY, order_code TEXT NOT NULL UNIQUE,
  customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
  channel_id INTEGER NOT NULL REFERENCES channels(channel_id),
  store_id INTEGER NOT NULL REFERENCES stores(store_id),
  ordered_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('placed','paid','shipped','delivered','cancelled')),
  gross_amount INTEGER NOT NULL CHECK(gross_amount>=0),
  discount_amount INTEGER NOT NULL CHECK(discount_amount>=0),
  shipping_fee INTEGER NOT NULL CHECK(shipping_fee>=0)
);
CREATE TABLE order_items (
  order_item_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(order_id),
  product_id INTEGER NOT NULL REFERENCES products(product_id),
  quantity INTEGER NOT NULL CHECK(quantity>0),
  unit_price INTEGER NOT NULL CHECK(unit_price>=0),
  line_discount INTEGER NOT NULL CHECK(line_discount>=0),
  promotion_id INTEGER REFERENCES promotions(promotion_id)
);
CREATE TABLE payments (
  payment_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(order_id),
  payment_method TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','failed','success')),
  amount INTEGER NOT NULL CHECK(amount>=0), paid_at TEXT
);
CREATE TABLE shipments (
  shipment_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL UNIQUE REFERENCES orders(order_id),
  carrier TEXT NOT NULL, shipped_at TEXT NOT NULL, delivered_at TEXT,
  shipping_status TEXT NOT NULL CHECK(shipping_status IN ('in_transit','delivered'))
);
CREATE TABLE returns (
  return_id INTEGER PRIMARY KEY, order_item_id INTEGER NOT NULL REFERENCES order_items(order_item_id),
  return_qty INTEGER NOT NULL CHECK(return_qty>0),
  refund_amount INTEGER NOT NULL CHECK(refund_amount>=0),
  status TEXT NOT NULL CHECK(status IN ('requested','approved','rejected')),
  requested_at TEXT NOT NULL, decided_at TEXT
);
CREATE TABLE inventory_snapshots (
  snapshot_id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(store_id),
  product_id INTEGER NOT NULL REFERENCES products(product_id),
  snapshot_date TEXT NOT NULL, qty_on_hand INTEGER NOT NULL CHECK(qty_on_hand>=0),
  qty_reserved INTEGER NOT NULL CHECK(qty_reserved>=0 AND qty_reserved<=qty_on_hand),
  UNIQUE(store_id,product_id,snapshot_date)
);
CREATE TABLE support_tickets (
  ticket_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id),
  customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
  issue_type TEXT NOT NULL, priority TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('open','in_progress','resolved')),
  created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE INDEX idx_orders_time_status ON orders(ordered_at,status);
CREATE INDEX idx_orders_channel ON orders(channel_id);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
CREATE INDEX idx_payments_order_status ON payments(order_id,status);
CREATE INDEX idx_returns_item_status ON returns(order_item_id,status);
CREATE INDEX idx_inventory_asof ON inventory_snapshots(store_id,product_id,snapshot_date);
CREATE INDEX idx_tickets_created ON support_tickets(created_at);
