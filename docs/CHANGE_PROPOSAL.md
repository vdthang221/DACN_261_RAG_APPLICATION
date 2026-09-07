# Đề xuất tái cấu trúc tài liệu RE và SD

## 1. Mục tiêu thay đổi

Bộ tài liệu hiện tại mô tả một nền tảng luyện tập thích ứng sử dụng LLM và RAG, nhưng chưa phản ánh đầy đủ nhiệm vụ kế thừa luận văn **CodeLit-GV**. Đợt tái cấu trúc này nhằm:

1. Lấy pipeline `Generate → Verify → Decide → Regenerate → Question Pool` làm lõi hệ thống.
2. Giữ đúng đầu vào của luận văn: `Problem + Student Submission + Target Skill + Target Bloom Level`.
3. Hiện thực đầy đủ hai cơ chế kiểm chứng: Bloom verification và execution-based factual verification.
4. Hệ thống hóa prototype nghiên cứu thành domain model, API, lifecycle, audit trail, deployment và evaluation pipeline.
5. Phân tách rõ phạm vi đồ án chuyên ngành và phần mở rộng đồ án tốt nghiệp.
6. Đặt RAG và adaptive learning vào đúng vai trò mở rộng, không thay thế pipeline CodeLit-GV.

Các tài liệu đề xuất:

- [RE_PROPOSED.md](RE_PROPOSED.md): yêu cầu chức năng, phi chức năng, dữ liệu và tiêu chí nghiệm thu.
- [SD_PROPOSED.md](SD_PROPOSED.md): kiến trúc, component, mô hình dữ liệu, API và triển khai.
- [workflow_PROPOSED.md](workflow_PROPOSED.md): các luồng end-to-end và luồng lỗi.

## 2. Phân tầng phạm vi

### 2.1 Phạm vi lõi — đồ án chuyên ngành

| Nhóm | Nội dung bắt buộc |
|---|---|
| Input | Quản lý bài toán và mã nguồn bài nộp của sinh viên |
| Targeting | Sử dụng khung 9 kỹ năng và 6 mức Bloom; chỉ chọn cặp hợp lệ |
| Generate | Sinh MCQ có 4 lựa chọn, đúng 1 đáp án và phần giải thích |
| Verify Bloom | Phân loại Bloom, tính Bloom Harmony, trả `PASS/MAYBE/FAIL` |
| Verify factual | Thực thi sandbox cho kỹ năng 3 và 6; so sánh kết quả thực với đáp án MCQ |
| Decide | Quyết định accept/regenerate theo policy cấu hình được |
| Regenerate | Tạo structured feedback và sinh lại tối đa `N` lần |
| Question Pool | Lưu MCQ đạt cùng toàn bộ metadata, verification result và lịch sử |
| Evaluation | Chạy pipeline trên tập đánh giá cố định và xuất metric định lượng |
| Demo | Có giao diện hoặc API tối thiểu để chạy end-to-end |

### 2.2 Phần mở rộng tùy chọn của đồ án chuyên ngành

Chỉ triển khai sau khi vertical slice lõi chạy được:

- RAG cho bài nộp nhiều file, đề bài, tài liệu môn học hoặc metadata liên quan.
- Hỗ trợ nhiều LLM provider, chuyển provider ở runtime hoặc fallback local/cloud.
- Giao diện giảng viên duyệt question pool.
- Lựa chọn câu hỏi theo kỹ năng yếu bằng rule đơn giản.
- Adaptive regeneration dựa trên số lần thử hoặc độ khó câu hỏi.

### 2.3 Phần mở rộng đồ án tốt nghiệp

- First Test theo CAT và ước lượng confidence.
- Competency model và learning path đầy đủ.
- Partial correctness và edge-case generation.
- Hỗ trợ nhiều ngôn ngữ lập trình.
- Learning analytics cấp lớp.
- LMS/LTI production-grade.
- Đánh giá tác động học tập dài hạn.

## 3. Các thay đổi chính so với tài liệu hiện tại

| Hiện tại | Thay đổi đề xuất | Lý do |
|---|---|---|
| Hồ sơ dựa trên 6 kỹ năng chưa xác định | Dùng 9 kỹ năng đã được luận văn định nghĩa | Tránh nghiên cứu lại nền tảng đã có |
| RAG truy xuất code bất kỳ làm ngữ liệu sinh câu hỏi | Mã bài nộp là nguồn chính; RAG chỉ bổ sung context | Bảo toàn tính cá nhân hóa theo bài làm |
| Nhiều loại bài tập | MCQ là loại bắt buộc; loại khác là extension | Bám phạm vi đã được kiểm chứng |
| Quality Gate chỉ kiểm tra schema/trùng lặp | Tách Structural Validator, Bloom Verifier, Factual Verifier | Phản ánh đúng pha Verify |
| Retry chung khi lỗi | Decision Policy và structured regeneration feedback | Truy vết được nguyên nhân tái sinh |
| `Exercise.qc_status` | Question lifecycle và Generation Attempt | Lưu đầy đủ lịch sử Generate–Verify |
| RAG/Adaptive là component trung tâm | CodeLit-GV Orchestrator là trung tâm | Đúng nhiệm vụ kế thừa luận văn |
| Không có sandbox trong deployment | Sandbox Runner là trust boundary riêng | Thực thi mã không tin cậy an toàn |
| Metric thiên về retrieval/schema | Bổ sung Bloom, factual, regeneration, rubric và reliability metric | Đánh giá đúng đóng góp hệ thống |

## 4. Definition of Done cho vertical slice

Một vertical slice được coi là hoàn thành khi:

1. Nhận được một `Problem`, một `StudentSubmission` hợp lệ và một cặp `(Starget, Btarget)` hợp lệ.
2. Sinh được MCQ đúng schema.
3. Chạy Bloom verification và lưu phân phối xác suất, Harmony score, status.
4. Nếu thuộc kỹ năng 3 hoặc 6, chạy factual verification trong sandbox và lưu kết quả.
5. Decision Engine quyết định `ACCEPT` hoặc `REGENERATE` theo policy.
6. Khi regenerate, attempt sau nhận structured feedback từ attempt trước.
7. Khi accept, câu hỏi xuất hiện trong Question Pool cùng audit trail đầy đủ.
8. Khi hết số lần thử, job kết thúc ở trạng thái `FAILED` có lý do; không lặp vô hạn.
9. Có test tự động cho happy path, Bloom fail, factual fail, sandbox timeout và exhausted attempts.
10. Có báo cáo metric trên một evaluation dataset được version hóa.

## 5. Trình tự hiện thực đề xuất

1. Domain model và JSON schema của MCQ.
2. Generation Orchestrator với mock generator/verifier.
3. Question lifecycle, persistence và audit trail.
4. Tích hợp LLM Generator.
5. Tích hợp Bloom Verifier.
6. Tích hợp Sandbox Runner và Factual Verifier.
7. Decision/Regeneration policy.
8. Question Pool và API demo.
9. Evaluation pipeline.
10. RAG/adaptive extension nếu còn thời gian.
