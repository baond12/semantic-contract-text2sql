# 00 Sources Acceptance Review

## Status

`ACCEPTED_FOR_00_SOURCES`

Package này đủ điều kiện làm `00_sources` cho pipeline Omnichannel Retail tiếp theo.

## Acceptance Checks

| Check | Result |
| --- | --- |
| 20 business tables | PASS |
| All tables have data | PASS |
| SQLite `integrity_check` | ok |
| SQLite `foreign_key_check` | 0 violations |
| Schema can be rebuilt from `schema.sql` + `seed_data.sql` | PASS |
| Rebuilt database matches original rows/FKs/schema | PASS |
| ERD relationships match physical schema | PASS |
| Product source records preserved | 300 products |
| Product source trace available | `product_source_trace.jsonl` |

## Notes

- This is a demo-ready source package, not a production migration package.
- Product source fields such as original brand/category/promotion details are preserved in `product_source_trace.jsonl`.
- `orders.chat_id` points to the message that led to order creation. There is no separate `conversations` table by design.
- `products.promotion_id` represents primary promotion and may be `NULL`.
- `categories` uses parent-child hierarchy to represent product taxonomy.

## Minor Non-blocking Notes

- Some orders have `chat_id` and `agent_id` as `NULL`, representing orders not created from manual chat.
- If production later requires strict session-level attribution, add `conversations` in a future schema version.
- If product can have multiple active promotions, add a bridge table in a future schema version.

## Done Definition

`DONE = 20 tables + sample data + valid relationships + ERD matches SQLite + team can open/review.`

