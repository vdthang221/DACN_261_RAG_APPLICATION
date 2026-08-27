# Tài liệu Yêu cầu (Requirements Engineering)
## Hệ thống luyện tập kỹ năng đọc hiểu mã nguồn thích ứng sử dụng LLM + RAG

---

## 1. Giới thiệu

### 1.1 Mục đích tài liệu
Tài liệu này đặc tả các yêu cầu chức năng và phi chức năng của hệ thống luyện tập kỹ năng đọc hiểu mã nguồn (code reading comprehension) thích ứng, làm cơ sở cho các bước thiết kế hệ thống (System Design), thiết kế kiến trúc (Architectural Design) và thiết kế phần mềm (Software Design) tiếp theo.

### 1.2 Phạm vi hệ thống
Hệ thống là một **web application** cho phép người học:
- Làm bài kiểm tra đầu vào (First Test) để đánh giá năng lực đọc hiểu mã nguồn theo 6 kỹ năng.
- Nhận lộ trình học cá nhân hóa dựa trên kết quả đánh giá.
- Luyện tập qua các dạng bài tập đa dạng (đọc hiểu code, trắc nghiệm, điền khuyết, tìm lỗi, dự đoán output...) được sinh tự động bằng LLM, có sử dụng RAG để đảm bảo nội dung bám sát mã nguồn thật và cá nhân hóa theo hồ sơ năng lực.
- Nhận phản hồi (feedback) tự động sau mỗi bài làm.
- Theo dõi tiến trình học tập qua thời gian.

Hệ thống **không** bao gồm (out of scope):
- Biên soạn giáo trình lập trình từ đầu (chỉ tận dụng mã nguồn có sẵn làm ngữ liệu).
- Chấm bài lập trình dạng chạy test case tự động như OJ (Online Judge) chuyên biệt — trọng tâm là đọc hiểu, không phải viết code chạy được.
- Ứng dụng di động (mobile app) — xem mục 1.4.

### 1.3 Đối tượng người dùng (Stakeholders)
| Vai trò | Mô tả | Nhu cầu chính |
|---|---|---|
| Người học (sinh viên CNTT) | Người dùng chính, luyện đọc hiểu code | Bài tập phù hợp trình độ, phản hồi rõ ràng, thấy được tiến bộ |
| Giảng viên hướng dẫn / Hội đồng | Đánh giá đề tài | Tính đúng đắn học thuật, khả năng giải thích được kiến trúc RAG/adaptive |
| Quản trị viên hệ thống (nếu có) | Vận hành, nạp ngữ liệu mới | Dễ bổ sung nguồn code mới, theo dõi chất lượng sinh bài tập |

### 1.4 Ràng buộc & giả định (Constraints & Assumptions)
- **Nền tảng:** Web app (responsive), có thể nâng cấp PWA sau này. Không phát triển native mobile app trong phạm vi đồ án.
- **Ngôn ngữ lập trình mục tiêu ban đầu:** cần xác định rõ (ví dụ: Python, Java, C++) — ảnh hưởng trực tiếp đến ngữ liệu RAG và bộ parser (tree-sitter).
- **Tài nguyên tính toán:** giới hạn ở máy cá nhân/server nhỏ — cần cân nhắc giữa LLM local (Ollama) và API cloud khi thiết kế độ trễ.
- **Thời gian:** giới hạn theo lịch trình đồ án/khóa luận — ưu tiên phần lõi (RAG, adaptive engine, 6 kỹ năng) hơn các tính năng phụ (gamification, thông báo...).
- **Giả định:** người học có kiến thức lập trình cơ bản trở lên; hệ thống không dạy lập trình từ số 0.

---

## 2. Yêu cầu chức năng (Functional Requirements)

Ký hiệu: **FR-x.y** — nhóm x, yêu cầu y.

### FR-1: Quản lý người dùng & hồ sơ năng lực
- **FR-1.1** Hệ thống cho phép người dùng đăng ký/đăng nhập.
- **FR-1.2** Hệ thống khởi tạo **hồ sơ năng lực (competency profile)** gồm điểm số/mức độ thành thạo cho từng kỹ năng trong 6 kỹ năng đọc hiểu mã nguồn.
- **FR-1.3** Hồ sơ năng lực được cập nhật tự động sau mỗi lần người dùng hoàn thành bài tập (adaptive loop).
- **FR-1.4** Người dùng xem được lịch sử làm bài và biểu đồ tiến bộ theo từng kỹ năng.

### FR-2: First Test (Đánh giá năng lực đầu vào)
- **FR-2.1** Hệ thống cung cấp bộ đề kiểm tra đầu vào bao phủ đều 6 kỹ năng.
- **FR-2.2** *(Cần quyết định)* First Test có thể chạy ở 1 trong 2 chế độ:
  - (a) **Đề cố định**: số lượng câu hỏi cố định, tính điểm theo từng kỹ năng sau khi hoàn thành toàn bộ.
  - (b) **Adaptive (CAT — Computerized Adaptive Testing)**: câu hỏi tiếp theo phụ thuộc kết quả câu trước, dừng sớm khi đã ước lượng đủ tin cậy năng lực người học.
- **FR-2.3** Sau khi hoàn thành First Test, hệ thống sinh **hồ sơ năng lực ban đầu** và **lộ trình học** tương ứng.

### FR-3: Sinh lộ trình học (Learning Path Generation)
- **FR-3.1** Hệ thống sinh lộ trình học cá nhân hóa dựa trên hồ sơ năng lực, ưu tiên các kỹ năng yếu.
- **FR-3.2** Lộ trình tuân theo mô hình sư phạm đã chọn (ví dụ: scaffolding — tăng độ khó dần; hoặc Bloom's Taxonomy — đi từ remember/understand đến apply/analyze).
- **FR-3.3** Lộ trình được **cập nhật lại (re-plan)** khi hồ sơ năng lực thay đổi đáng kể (ví dụ: người học cải thiện nhanh một kỹ năng, hoặc liên tục sai một kỹ năng khác).

### FR-4: Sinh bài tập (Exercise Generation qua LLM + RAG)
- **FR-4.1** Hệ thống truy xuất (retrieve) đoạn mã nguồn/tài liệu liên quan từ vector DB dựa trên: kỹ năng mục tiêu, ngôn ngữ lập trình, mức độ khó.
- **FR-4.2** Hệ thống dùng LLM sinh bài tập dựa trên ngữ liệu đã truy xuất, ở nhiều định dạng:
  - Câu hỏi đọc hiểu tự luận ngắn (giải thích chức năng đoạn code)
  - Trắc nghiệm (multiple choice)
  - Điền khuyết (fill-in-the-blank)
  - Dự đoán output
  - Tìm lỗi / debug
- **FR-4.3** Mỗi bài tập sinh ra phải gắn nhãn: kỹ năng liên quan, mức độ khó, ngôn ngữ lập trình, nguồn ngữ liệu tham chiếu (để truy vết/kiểm chứng).
- **FR-4.4** Hệ thống có cơ chế kiểm tra chất lượng tối thiểu của bài tập sinh ra (ví dụ: câu hỏi có đáp án hợp lệ, không rỗng, không trùng lặp gần đây) trước khi hiển thị cho người dùng.

### FR-5: Chấm điểm & phản hồi (Grading & Feedback)
- **FR-5.1** Hệ thống chấm tự động câu trả lời của người dùng (đối chiếu đáp án chuẩn với trắc nghiệm/điền khuyết; dùng LLM đánh giá với câu tự luận).
- **FR-5.2** Hệ thống sinh phản hồi có giải thích (không chỉ đúng/sai), tham chiếu lại đoạn code liên quan.
- **FR-5.3** Với câu trả lời sai, hệ thống gợi ý điểm kiến thức cần ôn lại.

### FR-6: Theo dõi tiến trình (Progress Tracking)
- **FR-6.1** Dashboard hiển thị mức độ thành thạo theo từng kỹ năng (dạng biểu đồ radar/bar).
- **FR-6.2** Lịch sử các bài đã làm, thời gian, kết quả.
- **FR-6.3** *(Tùy chọn)* Nhắc ôn tập theo nguyên lý spaced repetition cho các kỹ năng có dấu hiệu quên.

### FR-7: Quản trị ngữ liệu (Content/Corpus Management)
- **FR-7.1** Cho phép nạp thêm mã nguồn/tài liệu mới vào kho ngữ liệu RAG (ví dụ qua thư mục nạp hoặc GitHub repo).
- **FR-7.2** Hệ thống tự động parse (tree-sitter) và tạo embedding cho mã nguồn mới, lưu vào vector DB kèm metadata (ngôn ngữ, chủ đề, độ phức tạp ước lượng).

---

## 3. Yêu cầu phi chức năng (Non-Functional Requirements)

| Mã | Loại | Mô tả | Tiêu chí đo |
|---|---|---|---|
| NFR-1 | Hiệu năng | Thời gian sinh 1 bài tập (RAG + LLM) | < 5–10s trong môi trường demo |
| NFR-2 | Khả năng triển khai | Toàn bộ hệ thống (backend, vector DB, DB quan hệ, LLM nếu local) chạy được bằng 1 lệnh Docker Compose | `docker compose up` chạy thành công |
| NFR-3 | Khả năng mở rộng | Thêm ngôn ngữ lập trình/ngữ liệu mới không cần sửa code lõi | Chỉ cần thao tác qua FR-7 |
| NFR-4 | Độ chính xác RAG | Retrieval trả về ngữ liệu liên quan đến truy vấn | Đo bằng recall@k / precision@k trên tập test tự tạo |
| NFR-5 | Độ tin cậy sinh bài tập | Tỉ lệ bài tập sinh ra hợp lệ (không lỗi định dạng, có đáp án) | ≥ ngưỡng đặt ra, đo qua FR-4.4 |
| NFR-6 | Bảo mật | Không lộ API key, dữ liệu người dùng được lưu an toàn | `.env` không commit, mật khẩu hash |
| NFR-7 | Khả năng bảo trì | Tách rõ lớp LLM provider (Ollama/API cloud) qua interface chung | Đổi provider không sửa business logic |
| NFR-8 | Khả năng kiểm thử | Có test riêng cho pipeline RAG và adaptive engine | Test coverage cho 2 module này bằng pytest |
| NFR-9 | Khả năng giải thích (Explainability) | Hội đồng/người dùng hiểu được vì sao hệ thống chọn bài tập/độ khó đó | Log lại lý do chọn (kỹ năng yếu, độ khó theo hồ sơ) |

---

## 4. Yêu cầu dữ liệu (Data Requirements) — sơ bộ

Các thực thể dữ liệu chính cần có trong thiết kế CSDL (sẽ chi tiết hóa ở System/Software Design):
- **User** (thông tin tài khoản)
- **CompetencyProfile** (điểm từng kỹ năng theo thời gian, gắn với User)
- **Skill** (định nghĩa 6 kỹ năng — *cần chốt danh sách cụ thể*)
- **Exercise** (bài tập đã sinh: nội dung, loại, kỹ năng, độ khó, nguồn tham chiếu)
- **Submission** (câu trả lời của người dùng, kết quả chấm, thời điểm)
- **LearningPath** (lộ trình đã sinh cho từng người dùng, trạng thái hoàn thành)
- **CorpusDocument** (mã nguồn/tài liệu gốc trong kho ngữ liệu, metadata, liên kết tới vector embedding)

---

## 5. Vấn đề còn mở (Open Issues — cần chốt trước khi sang System Design)
1. Danh sách cụ thể **6 kỹ năng đọc hiểu mã nguồn** là gì.
2. Mô hình **sư phạm** áp dụng cụ thể (Bloom's Taxonomy / scaffolding / spaced repetition / kết hợp).
3. First Test chạy theo chế độ **cố định** hay **adaptive (CAT)**.
4. Ngôn ngữ lập trình mục tiêu ban đầu (chỉ 1 ngôn ngữ để làm sâu, hay hỗ trợ nhiều ngôn ngữ ngay từ đầu).
5. Ngưỡng đo lường cụ thể cho NFR-4 và NFR-5 (cần có tập dữ liệu đánh giá).

---

*Tài liệu này là bản v1 — nên rà soát lại cùng giảng viên hướng dẫn trước khi chuyển sang giai đoạn System Design.*
