# Tài liệu Yêu cầu Hệ thống

## Hệ thống sinh và kiểm chứng câu hỏi đọc hiểu mã nguồn sử dụng LLM

**Phiên bản:** Proposed v2  
**Cơ sở:** Hệ thống hóa và mở rộng phương pháp CodeLit-GV

---

## 1. Giới thiệu

### 1.1 Mục đích

Tài liệu đặc tả yêu cầu cho hệ thống sinh, kiểm chứng, tái sinh và quản lý câu hỏi trắc nghiệm đọc hiểu mã nguồn. Hệ thống kế thừa pipeline Generate–Verify của CodeLit-GV và chuyển phương pháp nghiên cứu thành một ứng dụng có thể triển khai, kiểm thử, truy vết và đánh giá end-to-end.

### 1.2 Bài toán

Tính đúng chức năng của một bài nộp lập trình không chứng minh rằng sinh viên hiểu mã nguồn đã nộp. Hệ thống cần sinh câu hỏi cá nhân hóa từ chính đề bài và mã nguồn của sinh viên, đồng thời kiểm chứng:

- Câu hỏi có phù hợp với kỹ năng đọc hiểu mã nguồn và mức Bloom mục tiêu hay không.
- Đáp án của câu hỏi liên quan đến hành vi chương trình có khớp với kết quả thực thi hay không.

### 1.3 Mục tiêu hệ thống

1. Sinh MCQ theo một cặp kỹ năng–Bloom hợp lệ từ đề bài và mã nguồn sinh viên.
2. Kiểm chứng mức Bloom bằng mô hình phân loại ordinal soft-label.
3. Kiểm chứng factual bằng thực thi sandbox cho các kỹ năng execution-oriented.
4. Tái sinh câu hỏi không đạt bằng phản hồi có cấu trúc.
5. Lưu question pool cùng metadata và audit trail đầy đủ.
6. Cung cấp evaluation pipeline tái lập được.
7. Cho phép mở rộng RAG, adaptive learning và LMS mà không làm thay đổi core contract.

### 1.4 Đối tượng sử dụng

| Vai trò | Nhu cầu chính |
|---|---|
| Giảng viên | Nạp bài toán/bài nộp, sinh và duyệt câu hỏi, xem bằng chứng kiểm chứng |
| Sinh viên | Trả lời câu hỏi được chọn từ question pool và nhận phản hồi |
| Nhà nghiên cứu/nhóm phát triển | Chạy evaluation, thay model/prompt/policy và so sánh kết quả |
| Quản trị viên | Quản lý cấu hình, model artifact, sandbox và dữ liệu hệ thống |

### 1.5 Thuật ngữ

| Thuật ngữ | Diễn giải |
|---|---|
| `Starget` | Kỹ năng đọc hiểu mã nguồn mục tiêu |
| `Btarget` | Mức nhận thức Bloom mục tiêu |
| MCQ | Câu hỏi trắc nghiệm nhiều lựa chọn |
| Bloom Harmony | Điểm thể hiện mức độ hòa hợp giữa phân phối Bloom dự đoán và phân phối mục tiêu |
| Factual verification | Kiểm tra đáp án bằng hành vi thực thi thực tế |
| Generation Attempt | Một lần sinh hoặc tái sinh MCQ trong cùng một job |
| Question Pool | Kho câu hỏi đã được chấp nhận cùng metadata kiểm chứng |

---

## 2. Phạm vi

### 2.1 Phạm vi lõi

- Quản lý bài toán lập trình và bài nộp mã nguồn.
- Khung 9 kỹ năng đọc hiểu mã nguồn và 6 mức Bloom.
- Ma trận cặp kỹ năng–Bloom hợp lệ.
- Sinh MCQ từ `Problem + StudentSubmission + Starget + Btarget`.
- Structural validation.
- Bloom verification.
- Execution-based factual verification cho kỹ năng 3 và 6.
- Decision và regeneration có giới hạn.
- Question Pool và audit trail.
- Evaluation pipeline.
- API và giao diện demo tối thiểu.

### 2.2 Ngoài phạm vi lõi

- Chấm bài lập trình tổng quát như Online Judge.
- Sinh giáo trình lập trình từ đầu.
- Native mobile application.
- CAT, learning path và learner modeling đầy đủ.
- Partial correctness tổng quát.
- LMS/LTI production-grade.
- Hỗ trợ nhiều ngôn ngữ ngay từ phiên bản đầu.

Việc biên dịch và chạy mã trong factual verification là một cơ chế nội bộ, bị giới hạn trong sandbox; không phải dịch vụ Online Judge.

### 2.3 Ngôn ngữ mục tiêu ban đầu

Hệ thống phải chốt **một ngôn ngữ lập trình** cho vertical slice đầu tiên. Mọi parser, compiler/runtime, input extractor và output comparator phải dùng cùng language profile. Ngôn ngữ khác được xem là extension.

---

## 3. Khung kỹ năng và Bloom

### 3.1 Chín kỹ năng đọc hiểu mã nguồn

| Mã | Kỹ năng |
|---|---|
| S1 | Basic Code Structure Understanding |
| S2 | Function and Variable Roles and Behaviors |
| S3 | Code Tracing / Step-by-Step Execution |
| S4 | Understanding Abstractions and Design Patterns |
| S5 | Implicit Logic and Side Effects Detection |
| S6 | Anticipating Code Output or Behavior |
| S7 | Code Summarization and Intent Explanation |
| S8 | Mental Simulation / Visual Representation |
| S9 | Understanding Syntax and Semantics of Keywords |

Tên tiếng Anh được giữ làm canonical key để tương thích với artifact và dữ liệu của luận văn; giao diện có thể hiển thị bản dịch tiếng Việt.

### 3.2 Sáu mức Bloom

`REMEMBER`, `UNDERSTAND`, `APPLY`, `ANALYZE`, `EVALUATE`, `CREATE`.

### 3.3 Ma trận hợp lệ

- Hệ thống phải seed ma trận kỹ năng–Bloom từ luận văn.
- Cặp được đánh dấu `N/A` không được dùng làm generation target.
- Mỗi version của ma trận phải có định danh và thời điểm hiệu lực.
- Mọi Question phải tham chiếu version ma trận đã sử dụng.

---

## 4. Yêu cầu chức năng

### FR-01 — Quản lý bài toán

- **FR-01.1:** Giảng viên tạo hoặc nhập `Problem` gồm tiêu đề, mô tả, định dạng input/output, ràng buộc và ví dụ.
- **FR-01.2:** Hệ thống lưu version nội dung bài toán; generation job phải tham chiếu version cụ thể.
- **FR-01.3:** Hệ thống cho phép đánh dấu bài toán hoạt động hoặc ngừng sử dụng mà không xóa lịch sử.

### FR-02 — Quản lý bài nộp mã nguồn

- **FR-02.1:** Hệ thống nhận mã nguồn gắn với `Problem`, người học ẩn danh/pseudonymous và language profile.
- **FR-02.2:** Hệ thống tính content hash để nhận diện đúng version bài nộp.
- **FR-02.3:** Chỉ bài nộp đạt điều kiện đầu vào của generation policy mới được dùng sinh câu hỏi.
- **FR-02.4:** Hệ thống lưu trạng thái validation của bài nộp và lý do từ chối.

### FR-03 — Chọn mục tiêu kỹ năng–Bloom

- **FR-03.1:** Người dùng hoặc strategy module chọn `Starget` và `Btarget`.
- **FR-03.2:** Hệ thống kiểm tra cặp mục tiêu có hợp lệ theo matrix version hay không.
- **FR-03.3:** Cặp `N/A` phải bị từ chối trước khi gọi LLM.
- **FR-03.4:** Mỗi generation job chỉ có một cặp mục tiêu canonical.

### FR-04 — Sinh MCQ

- **FR-04.1:** Generator nhận tối thiểu `ProblemVersion`, `SubmissionVersion`, `Starget`, `Btarget`, skill/Bloom definitions và output schema.
- **FR-04.2:** Đầu ra phải gồm một stem, đúng bốn lựa chọn A–D, đúng một đáp án, phần giải thích và dữ liệu cần thiết cho factual verification nếu áp dụng.
- **FR-04.3:** Generator phải trả dữ liệu có cấu trúc theo schema version xác định.
- **FR-04.4:** Mỗi attempt phải lưu model provider, model name/version, prompt template version, generation parameters, thời gian và raw response hoặc reference an toàn tới raw response.
- **FR-04.5:** Attempt tái sinh phải nhận structured feedback từ Decision Engine.

### FR-05 — Kiểm tra cấu trúc

- **FR-05.1:** Structural Validator kiểm tra đủ field, đúng kiểu dữ liệu, bốn lựa chọn khác rỗng và đúng một đáp án.
- **FR-05.2:** Validator kiểm tra đáp án được giải thích và không tham chiếu lựa chọn không tồn tại.
- **FR-05.3:** Validator phát hiện lựa chọn trùng lặp sau normalize.
- **FR-05.4:** Lỗi cấu trúc phải tạo verification result và không được chuyển trực tiếp vào Question Pool.

### FR-06 — Kiểm chứng Bloom

- **FR-06.1:** Bloom Verifier nhận toàn bộ MCQ theo input format của model artifact.
- **FR-06.2:** Verifier trả phân phối xác suất trên sáu mức Bloom.
- **FR-06.3:** Hệ thống tính Bloom Harmony với phân phối mục tiêu tạo từ `Btarget`.
- **FR-06.4:** Hệ thống ánh xạ kết quả thành `PASS`, `MAYBE` hoặc `FAIL` bằng policy version xác định.
- **FR-06.5:** Hệ thống lưu classifier artifact version, threshold/policy version, probability distribution, Harmony score và status.
- **FR-06.6:** Lỗi tải model hoặc inference phải được phân biệt với kết quả `FAIL` về mặt sư phạm.

### FR-07 — Kiểm chứng factual

- **FR-07.1:** Factual verification bắt buộc với `S3` và `S6`; kỹ năng khác trả `NOT_APPLICABLE`.
- **FR-07.2:** Input Extractor trích dữ liệu thực thi từ MCQ hoặc nhận execution specification có cấu trúc từ Generator.
- **FR-07.3:** Sandbox Runner biên dịch/chạy đúng submission version với input đã trích.
- **FR-07.4:** Output Comparator so sánh kết quả thực thi với đáp án đã decode.
- **FR-07.5:** Kết quả phải phân biệt tối thiểu: `PASS`, `ANSWER_MISMATCH`, `INPUT_PARSE_FAILED`, `COMPILE_ERROR`, `RUNTIME_ERROR`, `TIMEOUT`, `OUTPUT_LIMIT`, `INFRASTRUCTURE_ERROR`.
- **FR-07.6:** Hệ thống lưu execution evidence cần thiết nhưng không lưu bí mật hoặc dữ liệu nhạy cảm trong log.

### FR-08 — Ra quyết định và tái sinh

- **FR-08.1:** Decision Engine nhận Structural, Bloom và Factual verification results.
- **FR-08.2:** Structural fail, Bloom fail hoặc factual mismatch phải dẫn tới `REGENERATE` nếu còn attempt.
- **FR-08.3:** Cách xử lý Bloom `MAYBE` phải được cấu hình trong policy, không hard-code.
- **FR-08.4:** Hệ thống tạo structured feedback nêu nguyên nhân không đạt mà không làm lộ đáp án ngoài phạm vi nội bộ.
- **FR-08.5:** Số attempt tối đa phải cấu hình được; mặc định đề xuất là 3.
- **FR-08.6:** Hết attempt nhưng chưa đạt phải kết thúc `FAILED_EXHAUSTED`, không lặp vô hạn.
- **FR-08.7:** Mỗi decision phải lưu policy version, input result, output decision và reason codes.

### FR-09 — Question Pool

- **FR-09.1:** Chỉ Question đạt decision `ACCEPT` mới được đưa vào pool mặc định.
- **FR-09.2:** Question phải giữ liên kết tới Problem, Submission, target, accepted attempt và toàn bộ verification history.
- **FR-09.3:** Giảng viên có thể lọc theo problem, skill, Bloom, status, model và thời gian.
- **FR-09.4:** Giảng viên có thể duyệt, từ chối hoặc ghi chú câu hỏi; thao tác phải được audit.
- **FR-09.5:** Không được sửa đè nội dung accepted question; chỉnh sửa tạo version mới.

### FR-10 — Làm bài và phản hồi tối thiểu

- **FR-10.1:** Sinh viên nhận một accepted question mà không thấy answer key.
- **FR-10.2:** Hệ thống chấm MCQ bằng answer key đã lưu.
- **FR-10.3:** Sau khi nộp, hệ thống trả đúng/sai và phần giải thích được cho phép hiển thị.
- **FR-10.4:** Hệ thống lưu response, score, thời điểm và question version.

### FR-11 — Evaluation Pipeline

- **FR-11.1:** Cho phép chạy batch generation trên evaluation dataset được version hóa.
- **FR-11.2:** Mỗi evaluation run phải cố định dataset version, matrix version, prompt version, model version và policy version.
- **FR-11.3:** Xuất tối thiểu các metric: structural pass rate, Bloom exact/within-1, phân bố Harmony, factual pass rate, accept rate theo attempt và exhausted rate.
- **FR-11.4:** Cho phép xuất dữ liệu phục vụ đánh giá rubric của giảng viên hoặc LLM-as-judge.
- **FR-11.5:** Kết quả run phải tái truy vết về từng Question và Generation Attempt.

### FR-12 — Cấu hình và quản trị artifact

- **FR-12.1:** Quản trị viên cấu hình provider/model, threshold, max attempts, timeout và resource limit.
- **FR-12.2:** Mọi thay đổi cấu hình ảnh hưởng kết quả phải tạo version mới.
- **FR-12.3:** Không cho xóa cứng artifact/config version đang được lịch sử tham chiếu.

---

## 5. Yêu cầu mở rộng

### EXT-RAG — Bổ sung ngữ cảnh bằng RAG

- **EXT-RAG-01:** Truy xuất context từ repository nhiều file, đặc tả bài toán hoặc tài liệu môn học.
- **EXT-RAG-02:** Context phải giữ source reference và không thay thế submission code làm nguồn chính.
- **EXT-RAG-03:** Có ablation evaluation so sánh cùng pipeline khi bật và tắt RAG.
- **EXT-RAG-04:** Retrieval failure không được làm mất input bắt buộc của core pipeline.

### EXT-ADAPT — Adaptive question selection/regeneration

- **EXT-ADAPT-01:** Chọn target dựa trên lịch sử trả lời theo skill/Bloom.
- **EXT-ADAPT-02:** Điều chỉnh regeneration policy dựa trên attempt history hoặc difficulty.
- **EXT-ADAPT-03:** Mọi adaptive decision phải lưu feature đầu vào, policy version và reason.

### EXT-GRAD — Đồ án tốt nghiệp

- **EXT-GRAD-01:** Partial correctness và edge-case generation.
- **EXT-GRAD-02:** First Test/CAT và competency confidence.
- **EXT-GRAD-03:** Learning path/re-planning.
- **EXT-GRAD-04:** Learning analytics cấp lớp.
- **EXT-GRAD-05:** LMS/LTI.
- **EXT-GRAD-06:** Đa ngôn ngữ và evaluation dài hạn.

---

## 6. Yêu cầu phi chức năng

| Mã | Thuộc tính | Yêu cầu và tiêu chí nghiệm thu |
|---|---|---|
| NFR-01 | Tính đúng Bloom | Trên evaluation dataset đã chốt: `Acc_exact ≥ 65%`, `Acc_within-1 ≥ 90%`, hoặc không thấp hơn baseline artifact được GVHD cung cấp |
| NFR-02 | Độ tin cậy đánh giá | Rubric/human evaluation báo cáo inter-rater reliability; mục tiêu `Krippendorff's α ≥ 0.90` khi quy mô đánh giá cho phép |
| NFR-03 | An toàn sandbox | Mỗi run không có network, có CPU/memory/process/time/output limit và workspace tạm bị hủy sau run |
| NFR-04 | Tính kết thúc | Mọi generation job kết thúc ở trạng thái terminal trong tối đa `N` attempts; không có vòng lặp vô hạn |
| NFR-05 | Truy vết | 100% accepted question truy ra được input version, attempt, model, prompt, verifier artifact, policy và evidence |
| NFR-06 | Khả năng tái lập | Evaluation run lưu đủ version/config để chạy lại; seed được lưu khi provider hỗ trợ deterministic seed |
| NFR-07 | Hiệu năng | Với môi trường demo đã công bố, báo cáo p50/p95 cho generation, Bloom verify và factual verify; target p95 end-to-end được chốt sau baseline đo thực tế |
| NFR-08 | Bảo mật | Secret chỉ qua biến môi trường/secret store; password hash; answer key không gửi trước khi nộp |
| NFR-09 | Khả năng bảo trì | Generator, Bloom Verifier, Sandbox Runner và policy phụ thuộc interface, có fake adapter cho test |
| NFR-10 | Khả năng kiểm thử | Unit test cho domain/policy và integration test cho vertical slice; các nhánh Bloom fail, factual mismatch, timeout và exhausted attempts bắt buộc có test |
| NFR-11 | Khả năng triển khai | Core services chạy bằng Docker Compose hoặc quy trình triển khai tương đương được tài liệu hóa |
| NFR-12 | Quan sát hệ thống | Log có correlation ID/job ID/attempt ID; metric lỗi phân biệt lỗi nội dung và lỗi hạ tầng |
| NFR-13 | Riêng tư dữ liệu | Dataset xuất đánh giá phải pseudonymize student identity và không công khai bài nộp ngoài quyền được cấp |
| NFR-14 | Khả năng mở rộng ngôn ngữ | Language profile đóng gói parser/compiler/input extractor/comparator; thêm ngôn ngữ không đổi core orchestration contract |

---

## 7. Yêu cầu dữ liệu

Các thực thể bắt buộc:

- `Problem`, `ProblemVersion`.
- `Student`, `StudentSubmission`, `SubmissionVersion`.
- `Skill`, `BloomLevel`, `SkillBloomMatrixVersion`.
- `GenerationJob`, `GenerationAttempt`.
- `Question`, `QuestionVersion`, `QuestionOption`.
- `StructuralVerificationResult`.
- `BloomVerificationResult`.
- `FactualVerificationResult`, `SandboxExecution`.
- `RegenerationDecision`, `AuditEvent`.
- `QuestionResponse`.
- `EvaluationDataset`, `EvaluationRun`, `EvaluationMetric`.
- `ModelArtifact`, `PromptTemplateVersion`, `PolicyVersion`, `LanguageProfileVersion`.

### 7.1 Quy tắc dữ liệu

1. Version đã được lịch sử sử dụng là immutable.
2. Question không được tách khỏi submission và problem version đã dùng để sinh.
3. Raw model output và sandbox output phải có retention policy.
4. Dữ liệu định danh sinh viên phải tách khỏi dữ liệu evaluation khi có thể.
5. Answer key không xuất hiện trong API lấy câu hỏi trước khi sinh viên nộp.

---

## 8. Quy tắc nghiệp vụ cốt lõi

1. Chỉ cặp skill–Bloom hợp lệ mới được tạo job.
2. Structural validation luôn chạy trước Bloom/factual verification.
3. Factual verification chỉ bắt buộc cho S3/S6.
4. Lỗi hạ tầng không được tự động quy thành nội dung `FAIL`.
5. Chỉ decision `ACCEPT` mới đưa câu hỏi vào question pool mặc định.
6. Regeneration không vượt quá `max_attempts`.
7. Mọi decision phải giải thích được bằng reason codes.

---

## 9. Tiêu chí nghiệm thu end-to-end

| Mã | Kịch bản | Kết quả mong đợi |
|---|---|---|
| AC-01 | Cặp skill–Bloom là `N/A` | API từ chối trước khi gọi LLM |
| AC-02 | LLM trả sai schema | Attempt structural fail và regenerate nếu còn lượt |
| AC-03 | Bloom status `FAIL` | Structured Bloom feedback được chuyển sang attempt kế |
| AC-04 | S3/S6 có đáp án sai hành vi | Factual mismatch và regenerate |
| AC-05 | Sandbox timeout | Ghi `TIMEOUT`, áp policy lỗi hạ tầng/nội dung đã chốt, không treo job |
| AC-06 | Câu hỏi đạt mọi verification bắt buộc | `ACCEPT`, lưu Question Pool và audit trail |
| AC-07 | Hết lượt | `FAILED_EXHAUSTED`, lưu đủ attempts và reason |
| AC-08 | Lấy câu hỏi để làm | Payload không chứa answer key |
| AC-09 | Evaluation run | Metric truy được tới từng sample và configuration version |

---

## 10. Các quyết định cần GVHD chốt trước khi implement

1. Ngôn ngữ lập trình đầu tiên.
2. Artifact Bloom classifier, tokenizer và label mapping được bàn giao.
3. Dataset nào được phép sử dụng và phạm vi quyền truy cập.
4. Công thức/threshold chính thức cho `PASS/MAYBE/FAIL`.
5. Policy xử lý Bloom `MAYBE`.
6. Input specification cho factual questions: ưu tiên structured field hay regex fallback.
7. `max_attempts` và policy khi lỗi hạ tầng.
8. Phạm vi UI tối thiểu cần trình diễn.
9. RAG có bắt buộc trong đồ án chuyên ngành hay là extension sau core.

