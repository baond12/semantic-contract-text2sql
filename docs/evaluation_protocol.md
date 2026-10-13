# Evaluation Protocol

## Không chỉ dùng Execution Accuracy

Execution Accuracy quan trọng, nhưng chưa đủ.

Cần đánh giá thêm:

- intent accuracy,
- method selection accuracy,
- parameter preservation rate,
- semantic contract violation detection,
- unsupported/refuse correctness,
- result correctness.

## Action types

Hệ thống cần phân biệt:

- `EXECUTE_SQL`: đủ dữ liệu và đủ contract để chạy SQL.
- `CLARIFY`: thiếu metric/period/grain quan trọng.
- `UNSUPPORTED`: database không có dữ liệu/quan hệ cần thiết.
- `REFUSE`: yêu cầu thay đổi database hoặc truy cập nhạy cảm.

## Static vs Behavioral Tests

Static contract checking:

- không cần database,
- kiểm tra artifact/schema/template.

Behavioral contract testing:

- cần fixture database,
- kiểm tra SQL thực tế có đúng semantic không.

Ví dụ:

```text
Tỉnh nào có ít phường nhất?
```

Cần fixture có tỉnh count = 0 để kiểm tra SQL có giữ zero-count entity không.

