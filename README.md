# DACN_261_RAG_APPLICATION
Hệ thống luyện tập kỹ năng đọc hiểu mã nguồn thích ứng sử dụng LLM

## MVP Sprint 2

[Chạy CodeLit MVP](mvp/README.md): đăng nhập Google `@hcmut.edu.vn`, C++17 → testcase → MCQ Gemini 3.6 Flash → feedback, kèm ngân hàng XML và hàng đợi cho demo 3 người đồng thời.

Chạy toàn bộ môi trường dev từ thư mục gốc:

```powershell
.\dev.ps1
```

Nhấn `Ctrl+C` sẽ tự gọi `stop.ps1` để ngưng server. Script chỉ dọn judge container local còn sót từ kiểm thử Docker, nếu có.

## Tài liệu

- [Tài liệu Yêu cầu (RE)](docs/RE.md)
- [Workflow hệ thống](docs/workflow.md)
- [Thiết kế Hệ thống (SD)](docs/SD.md)
- [Triển khai GCP Judge Gateway](docs/gcp-judge.md)
