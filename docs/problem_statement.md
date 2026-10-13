# Problem Statement

## Bài toán

Text2SQL thường được đánh giá bằng việc SQL có chạy được hay không, hoặc kết quả có giống gold SQL hay không.

Tuy nhiên trong hệ thống thực tế, một SQL có thể hợp lệ về cú pháp nhưng vẫn sai ngữ nghĩa:

- sai metric,
- sai filter,
- sai join,
- sai aggregation,
- sai output column,
- trả lời câu hỏi ngoài phạm vi dữ liệu.

Ví dụ:

```text
User: Liệt kê tên ngắn các phường
SQL:  SELECT full_name FROM wards ...
```

SQL chạy được, nhưng sai `projection`.

## Giả thuyết kỹ thuật

Nếu biểu diễn domain bằng ontology và kiểm tra semantic contract trước execution, hệ thống Text2SQL có thể:

- dễ debug hơn,
- ít hallucination hơn,
- phát hiện lỗi semantic sớm hơn,
- giải thích được vì sao query hợp lệ hoặc không hợp lệ.

## Hướng nghiên cứu

```text
Ontology-based Semantic Contract Audit for Text2SQL
```

Mục tiêu chưa phải là chứng minh SOTA, mà là xây nền tảng kiểm soát semantic có thể kiểm chứng.

