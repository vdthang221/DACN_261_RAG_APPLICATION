# Mô tả chi tiết ERD — framework sinh và kiểm chứng MCQ

**Trạng thái nguồn:** mô hình logic dựa trên [RE.md](RE.md) v2.1 tại commit `e122a36`, đồng bộ với [SD_PROPOSED.md](SD_PROPOSED.md) v2 ngày 09/09/2026. Các quyết định còn mở được tập hợp tại SD_PROPOSED mục 13 để nhóm rà soát.

ERD là mô hình logic đề xuất, chưa phải schema SQL đã triển khai. Bản SD proposed lấy framework sinh–kiểm chứng MCQ của RE làm phạm vi chuẩn; tài liệu này giải thích các bảng và quan hệ dùng trong thiết kế đó.

## Cách đọc ký hiệu

- **PK:** khóa chính. Khi một bảng có nhiều cột PK, các cột tạo một khóa chính ghép, không phải mỗi cột đều duy nhất riêng.
- **FK:** khóa ngoại tham chiếu một bảng/cột khác. FK bắt buộc nghĩa là mỗi bản ghi con có đúng một bản ghi cha.
- **UK:** ràng buộc duy nhất. UK1 ở bảng version là duy nhất theo cặp định danh cha + số version; không phải số version duy nhất toàn hệ thống.
- **?:** cột có thể NULL. Với FK, phía cha là 0..1; thiếu dấu ? thì phía cha là 1.
- **1 / 0..1 / 0..N:** đúng một / không hoặc một / không hoặc nhiều. Quan hệ N–N được tách qua bảng nối.
- **↗:** tham chiếu tới bảng ở trang khác, không phải luồng điều khiển hay thao tác gọi API.

Bảng cha chưa nhất thiết có bản ghi con ngay khi được tạo. Ví dụ một job đang QUEUED có thể có 0 attempt; một attempt lỗi JSON có thể có 0 question_version.

## Bản đồ các trang

| Trang | Nội dung | Số bảng |
|---|---|---|
| 01 | Ngu lieu | 6 |
| 02 | Ma tran va cau hinh | 8 |
| 03 | Generate Verify Regenerate | 8 |
| 04 | Kho MCQ va danh gia | 7 |
| 05 | Dataset va nhan Bloom | 5 |

## 01 - Ngu lieu

FR-1; RE §5, §5.1 — Bài toán và bài nộp có version bất biến.

### `problem`

Định danh ổn định của bài toán lập trình. Tên/chủ đề giúp phân loại; đề bài chính xác nằm trong problem_version.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `title` | text | — |
| `topic` | text | — |
| `created_at` | timestamp | — |

### `problem_version`

Giữ nội dung đề bài tại một phiên bản cụ thể, cùng tham chiếu test chính thức và hash. Bài nộp dùng phiên bản nào phải truy lại đúng phiên bản đó.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `problem_id` | uuid FK | `problem.id` |
| `version_no` | int UK1 | — |
| `statement` | text | — |
| `official_tests_ref` | text ? | — |
| `content_hash` | text | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `problem_id` → `problem.id` (trang 01): mỗi `problem_version` liên kết 1 `problem`; mỗi `problem` có 0..N `problem_version`.

### `submission`

Định danh bài nộp của một sinh viên đã ẩn danh, thuộc một bài toán. Không chứa MSSV hoặc tên thật.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `problem_id` | uuid FK | `problem.id` |
| `anonymous_ref` | text | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `problem_id` → `problem.id` (trang 01): mỗi `submission` liên kết 1 `problem`; mỗi `problem` có 0..N `submission`.

### `submission_version`

Giữ mã đầy đủ để thực thi, mã rút gọn để đưa vào prompt, bằng chứng kiểm tra chức năng và version đề bài/runtime. Chỉ VALID mới tạo generation_job.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `submission_id` | uuid FK | `submission.id` |
| `problem_version_id` | uuid FK | `problem_version.id` |
| `language_profile_id` | uuid FK | `language_profile_version.id` |
| `version_no` | int UK1 | — |
| `full_source_ref` | text | — |
| `summarized_code` | text ? | — |
| `functional_status` | enum | — |
| `validation_evidence_ref` | text ? | — |
| `content_hash` | text | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `submission_id` → `submission.id` (trang 01): mỗi `submission_version` liên kết 1 `submission`; mỗi `submission` có 0..N `submission_version`.
- `problem_version_id` → `problem_version.id` (trang 01): mỗi `submission_version` liên kết 1 `problem_version`; mỗi `problem_version` có 0..N `submission_version`.
- `language_profile_id` → `language_profile_version.id` (trang 01): mỗi `submission_version` liên kết 1 `language_profile_version`; mỗi `language_profile_version` có 0..N `submission_version`.

### `language_profile_version`

Đóng băng cấu hình biên dịch, sandbox, trích đầu vào và so sánh đáp án cho một ngôn ngữ. C++ là profile đầu tiên.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `language` | text | — |
| `version_no` | int UK1 | — |
| `compiler_config` | json | — |
| `sandbox_limits` | json | — |
| `input_parser_config` | json | — |
| `answer_comparator_config` | json | — |
| `content_hash` | text | — |
| `retired_at` | timestamp ? | — |

### `import_event`

Ghi kết quả nạp hoặc loại đầu vào. FK có thể NULL khi dữ liệu bị loại trước khi tạo submission_version.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `submission_version_id` | uuid FK ? | `submission_version.id` |
| `status` | enum | — |
| `reason_code` | text ? | — |
| `sanitized_source_ref` | text ? | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `submission_version_id` → `submission_version.id` (trang 01): mỗi `import_event` liên kết 0..1 `submission_version`; mỗi `submission_version` có 0..N `import_event`.

**Ràng buộc của nhóm:**

- UK1 = UNIQUE(parent_id, version_no); language profile dùng (language, version_no).
- Chỉ functional_status = VALID được đưa vào pipeline; full_source_ref giữ mã để sandbox chạy.
- import_event là thiết kế bổ sung cho log bài bị loại (FR-1.2); không lưu MSSV/tên trong anonymous_ref hoặc log.
- FK sang trang khác được đánh dấu ↗; các bảng tham chiếu dùng cùng tên trên toàn bộ file.

## 02 - Ma tran va cau hinh

FR-2, FR-4, FR-10 — Cặp kỹ năng/Bloom hợp lệ và cấu hình tái lập.

### `skill`

Danh mục định danh chín kỹ năng hiểu mã. Mô tả đã dùng trong prompt nằm trong snapshot matrix_version.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | int PK | — |
| `code` | text UK | — |
| `name` | text | — |

### `matrix_version`

Snapshot khung kỹ năng/Bloom và ma trận. Mỗi version có 54 ô; thay đổi cấu hình tạo version mới.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `version_no` | int UK | — |
| `skill_definitions` | json | — |
| `bloom_definitions` | json | — |
| `content_hash` | text | — |
| `retired_at` | timestamp ? | — |

### `bloom_level`

Danh mục sáu mức Bloom và thứ tự nhận thức. ordinal phục vụ so sánh độ lệch giữa các mức.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | int PK | — |
| `code` | text UK | — |
| `ordinal` | int UK | — |

### `skill_bloom_cell`

Bảng liên kết kỹ năng, mức Bloom và version ma trận. applicable quyết định cặp mục tiêu có được đưa vào pipeline hay không.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `matrix_version_id` | uuid FK | `matrix_version.id` |
| `skill_id` | int FK | `skill.id` |
| `bloom_level_id` | int FK | `bloom_level.id` |
| `applicable` | bool | — |
| `task_description` | text ? | — |
| `assessment_criteria` | text ? | — |

**Quan hệ:**

- `matrix_version_id` → `matrix_version.id` (trang 02): mỗi `skill_bloom_cell` liên kết 1 `matrix_version`; mỗi `matrix_version` có 0..N `skill_bloom_cell`.
- `skill_id` → `skill.id` (trang 02): mỗi `skill_bloom_cell` liên kết 1 `skill`; mỗi `skill` có 0..N `skill_bloom_cell`.
- `bloom_level_id` → `bloom_level.id` (trang 02): mỗi `skill_bloom_cell` liên kết 1 `bloom_level`; mỗi `bloom_level` có 0..N `skill_bloom_cell`.

### `generation_config_version`

Gom các tham chiếu prompt, generator, classifier và policy cùng tham số suy luận để tái lập một cấu hình. Đây là lớp kỹ thuật hóa từ RE.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `version_no` | int UK | — |
| `prompt_version_id` | uuid FK | `prompt_template_version.id` |
| `llm_artifact_id` | uuid FK | `model_artifact.id` |
| `classifier_artifact_id` | uuid FK | `model_artifact.id` |
| `policy_version_id` | uuid FK | `accept_policy_version.id` |
| `inference_parameters` | json | — |
| `seed` | int ? | — |
| `content_hash` | text | — |
| `retired_at` | timestamp ? | — |

**Quan hệ:**

- `prompt_version_id` → `prompt_template_version.id` (trang 02): mỗi `generation_config_version` liên kết 1 `prompt_template_version`; mỗi `prompt_template_version` có 0..N `generation_config_version`.
- `llm_artifact_id` → `model_artifact.id` (trang 02): mỗi `generation_config_version` liên kết 1 `model_artifact`; mỗi `model_artifact` có 0..N `generation_config_version`.
- `classifier_artifact_id` → `model_artifact.id` (trang 02): mỗi `generation_config_version` liên kết 1 `model_artifact`; mỗi `model_artifact` có 0..N `generation_config_version`.
- `policy_version_id` → `accept_policy_version.id` (trang 02): mỗi `generation_config_version` liên kết 1 `accept_policy_version`; mỗi `accept_policy_version` có 0..N `generation_config_version`.

### `prompt_template_version`

Giữ nội dung template và biến thể V1–V5 tại một version. template_body là template; prompt thực tế của lần gọi được giữ qua input_snapshot_ref.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `template_code` | text | — |
| `version_no` | int | — |
| `variant` | text | — |
| `template_body` | text | — |
| `schema_version` | text | — |
| `content_hash` | text | — |
| `retired_at` | timestamp ? | — |

### `model_artifact`

Mô tả model theo vai GENERATOR/CLASSIFIER/JUDGE, provider, version và artifact liên quan. Không lưu API key. Các FK phải dùng đúng kind.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `kind` | enum GENERATOR/CLASSIFIER/JUDGE | — |
| `provider` | text | — |
| `model_name` | text | — |
| `model_version` | text | — |
| `artifact_ref` | text ? | — |
| `tokenizer_ref` | text ? | — |
| `label_mapping` | json ? | — |
| `training_metadata` | json ? | — |
| `content_hash` | text | — |
| `retired_at` | timestamp ? | — |

### `accept_policy_version`

Giữ ngưỡng Harmony, cách xử lý MAYBE, lỗi factual, soft-label và giới hạn sinh lại. Các giá trị cụ thể vẫn cần hiệu chỉnh theo RE.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `version_no` | int UK | — |
| `h_low` | decimal | — |
| `h_mid` | decimal | — |
| `h_high` | decimal | — |
| `max_regenerations` | int | — |
| `maybe_policy` | enum | — |
| `factual_error_policy` | json | — |
| `soft_label_parameters` | json | — |
| `retired_at` | timestamp ? | — |

**Ràng buộc của nhóm:**

- UNIQUE(matrix_version_id, skill_id, bloom_level_id); mỗi matrix có 54 ô, gồm cả N/A.
- skill_definitions/bloom_definitions đóng băng mô tả theo version; skill và bloom_level giữ mã định danh ổn định.
- CHECK 0 ≤ h_low < h_mid < h_high ≤ 1; cặp N/A bị từ chối trước khi tạo job.
- model_artifact gộp các artifact model theo kind; kiểm tra đúng kind của từng FK bằng ứng dụng/trigger.
- generation_config_version là bảng bổ sung gom cấu hình bất biến; prompt UNIQUE(template_code, version_no).

## 03 - Generate Verify Regenerate

FR-3 → FR-7; NFR-8, NFR-14 — Mọi lần thử và kết quả lỗi đều truy vết được.

### `generation_job`

Một yêu cầu sinh cho một submission_version, một cặp kỹ năng–Bloom và một cấu hình cố định. Có thể thuộc evaluation_run hoặc được chạy độc lập.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `submission_version_id` | uuid FK | `submission_version.id` |
| `skill_bloom_cell_id` | uuid FK | `skill_bloom_cell.id` |
| `config_version_id` | uuid FK | `generation_config_version.id` |
| `evaluation_run_id` | uuid FK ? | `evaluation_run.id` |
| `status` | enum | — |
| `created_at` | timestamp | — |
| `finished_at` | timestamp ? | — |

**Quan hệ:**

- `submission_version_id` → `submission_version.id` (trang 01): mỗi `generation_job` liên kết 1 `submission_version`; mỗi `submission_version` có 0..N `generation_job`.
- `skill_bloom_cell_id` → `skill_bloom_cell.id` (trang 02): mỗi `generation_job` liên kết 1 `skill_bloom_cell`; mỗi `skill_bloom_cell` có 0..N `generation_job`.
- `config_version_id` → `generation_config_version.id` (trang 02): mỗi `generation_job` liên kết 1 `generation_config_version`; mỗi `generation_config_version` có 0..N `generation_job`.
- `evaluation_run_id` → `evaluation_run.id` (trang 04): mỗi `generation_job` liên kết 0..1 `evaluation_run`; mỗi `evaluation_run` có 0..N `generation_job`.

### `generation_attempt`

Một lần sinh nội dung trong job. Lưu trạng thái, input snapshot và raw output để giải thích cả thành công lẫn thất bại.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `job_id` | uuid FK | `generation_job.id` |
| `attempt_no` | int | — |
| `raw_output_ref` | text ? | — |
| `input_snapshot_ref` | text | — |
| `status` | enum | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `job_id` → `generation_job.id` (trang 03): mỗi `generation_attempt` liên kết 1 `generation_job`; mỗi `generation_job` có 0..N `generation_attempt`.

### `question_version`

Nội dung MCQ bất biến: stem, bốn lựa chọn, đáp án và giải thích. origin_attempt_id giữ nguồn sinh; previous_version_id nối tới bản trước khi chỉnh sửa.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `question_id` | uuid FK | `question.id` |
| `origin_attempt_id` | uuid FK | `generation_attempt.id` |
| `previous_version_id` | uuid FK ? | `question_version.id` |
| `version_no` | int | — |
| `stem` | text | — |
| `options` | json A-D | — |
| `answer_key` | char A-D | — |
| `explanation` | text | — |
| `content_hash` | text | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `question_id` → `question.id` (trang 03): mỗi `question_version` liên kết 1 `question`; mỗi `question` có 0..N `question_version`.
- `origin_attempt_id` → `generation_attempt.id` (trang 03): mỗi `question_version` liên kết 1 `generation_attempt`; mỗi `generation_attempt` có 0..N `question_version`.
- `previous_version_id` → `question_version.id` (trang 03): mỗi `question_version` liên kết 0..1 `question_version`; mỗi `question_version` có 0..N `question_version`.

### `verification_result`

Một lượt kiểm tra cấu trúc/Bloom/factual trên attempt hoặc question_version. Các trường NULL phân biệt phần chưa chạy/không có kết quả với FAIL nội dung.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `attempt_id` | uuid FK ? | `generation_attempt.id` |
| `question_version_id` | uuid FK ? | `question_version.id` |
| `config_version_id` | uuid FK | `generation_config_version.id` |
| `structural_status` | enum | — |
| `structural_errors` | json ? | — |
| `bloom_probabilities` | json ? | — |
| `bloom_harmony` | decimal ? | — |
| `bloom_status` | enum ? | — |
| `factual_status` | enum ? | — |
| `factual_ok` | bool ? | — |
| `execution_log_ref` | text ? | — |
| `error_category` | enum ? | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `attempt_id` → `generation_attempt.id` (trang 03): mỗi `verification_result` liên kết 0..1 `generation_attempt`; mỗi `generation_attempt` có 0..N `verification_result`.
- `question_version_id` → `question_version.id` (trang 03): mỗi `verification_result` liên kết 0..1 `question_version`; mỗi `question_version` có 0..N `verification_result`.
- `config_version_id` → `generation_config_version.id` (trang 02): mỗi `verification_result` liên kết 1 `generation_config_version`; mỗi `generation_config_version` có 0..N `verification_result`.

### `decision`

Quyết định của pipeline dựa trên đúng một verification_result: ACCEPT, REGENERATE hoặc ABORT; kèm reason_codes có thể phân tích bằng máy.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `verification_result_id` | uuid FK UK | `verification_result.id` |
| `outcome` | enum ACCEPT/REGENERATE/ABORT | — |
| `reason_codes` | json | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `verification_result_id` → `verification_result.id` (trang 03): mỗi `decision` liên kết 1 `verification_result`; mỗi `verification_result` có 0..1 `decision`.

### `regenerate_feedback`

Nội dung G0 giải thích lỗi và chỉ dẫn điều chỉnh sau decision. Không phải câu trả lời của sinh viên.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `decision_id` | uuid FK UK | `decision.id` |
| `g0_content` | text | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `decision_id` → `decision.id` (trang 03): mỗi `regenerate_feedback` liên kết 1 `decision`; mỗi `decision` có 0..1 `regenerate_feedback`.

### `question`

Định danh logic chung cho nhiều version của một MCQ. Có bản ghi ở đây chưa đồng nghĩa câu hỏi đã được chấp nhận vào kho.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `created_at` | timestamp | — |

### `attempt_feedback`

Liên kết feedback đã thực sự dùng làm đầu vào của attempt kế tiếp. Attempt đầu không có liên kết này.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `attempt_id` | uuid PK FK | `generation_attempt.id` |
| `feedback_id` | uuid FK UK | `regenerate_feedback.id` |

**Quan hệ:**

- `attempt_id` → `generation_attempt.id` (trang 03): mỗi `attempt_feedback` liên kết 1 `generation_attempt`; mỗi `generation_attempt` có 0..1 `attempt_feedback`.
- `feedback_id` → `regenerate_feedback.id` (trang 03): mỗi `attempt_feedback` liên kết 1 `regenerate_feedback`; mỗi `regenerate_feedback` có 0..1 `attempt_feedback`.

**Ràng buộc của nhóm:**

- UNIQUE(job_id, attempt_no); UNIQUE(question_id, version_no). question là định danh MCQ, gồm cả bản nháp.
- Mã đề bài được suy ra từ submission_version.problem_version_id; cặp target và cấu hình truy qua job.
- MCQ chỉnh sửa giữ origin_attempt_id, tạo version mới và verification_result mới; không kế thừa ACCEPT cũ.
- verification_result phải có attempt_id hoặc question_version_id; nếu có cả hai phải cùng nguồn sinh.
- Attempt lỗi JSON có thể chưa tạo question_version; vẫn lưu verification_result và raw response.
- N_max = max_regenerations là số lần sinh lại tối đa; attempt_no bắt đầu 0, tổng số lần sinh tối đa N_max+1 theo quy ước SD mục 3.2. Giá trị N_max cụ thể chờ nhóm chốt.
- attempt_feedback là liên kết 0..1 feedback đầu vào/attempt; feedback phải đến từ lần thử trước cùng job.

## 04 - Kho MCQ va danh gia

FR-7.6–7.8; FR-9 — Duyệt thủ công tách khỏi quyết định tự động.

### `review_actor`

Định danh người duyệt/người chấm hoặc LLM judge. Model artifact chỉ dùng cho actor LLM; không phải tài khoản người học.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `actor_kind` | enum HUMAN/LLM | — |
| `display_label` | text | — |
| `model_artifact_id` | uuid FK ? | `model_artifact.id` |

**Quan hệ:**

- `model_artifact_id` → `model_artifact.id` (trang 02): mỗi `review_actor` liên kết 0..1 `model_artifact`; mỗi `model_artifact` có 0..N `review_actor`.

### `audit_event`

Lịch sử APPROVE/REJECT/NOTE của giảng viên đối với một question_version, có chủ thể và thời điểm. APPROVE thủ công không thay thế ACCEPT tự động.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `question_version_id` | uuid FK | `question_version.id` |
| `actor_id` | uuid FK | `review_actor.id` |
| `action` | enum APPROVE/REJECT/NOTE | — |
| `reason` | text ? | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `question_version_id` → `question_version.id` (trang 03): mỗi `audit_event` liên kết 1 `question_version`; mỗi `question_version` có 0..N `audit_event`.
- `actor_id` → `review_actor.id` (trang 04): mỗi `audit_event` liên kết 1 `review_actor`; mỗi `review_actor` có 0..N `audit_event`.

### `evaluation_run`

Một lần thực nghiệm cố định dataset, ma trận, cấu hình, seed và chế độ ablation. metrics chứa số liệu tổng hợp; dữ liệu gốc giữ ở các bảng liên quan.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `dataset_version_id` | uuid FK | `dataset_version.id` |
| `matrix_version_id` | uuid FK | `matrix_version.id` |
| `config_version_id` | uuid FK | `generation_config_version.id` |
| `mode` | enum GENERATE_ONLY/GENERATE_VERIFY | — |
| `seed` | int ? | — |
| `metrics` | json ? | — |
| `started_at` | timestamp | — |
| `finished_at` | timestamp ? | — |

**Quan hệ:**

- `dataset_version_id` → `dataset_version.id` (trang 05): mỗi `evaluation_run` liên kết 1 `dataset_version`; mỗi `dataset_version` có 0..N `evaluation_run`.
- `matrix_version_id` → `matrix_version.id` (trang 02): mỗi `evaluation_run` liên kết 1 `matrix_version`; mỗi `matrix_version` có 0..N `evaluation_run`.
- `config_version_id` → `generation_config_version.id` (trang 02): mỗi `evaluation_run` liên kết 1 `generation_config_version`; mỗi `generation_config_version` có 0..N `evaluation_run`.

### `evaluation_item`

Thành viên của tập câu hỏi được chấm trong một run. Liên kết đúng question_version để kết quả không đổi theo lần sửa câu hỏi sau đó.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `evaluation_run_id` | uuid FK | `evaluation_run.id` |
| `question_version_id` | uuid FK | `question_version.id` |

**Quan hệ:**

- `evaluation_run_id` → `evaluation_run.id` (trang 04): mỗi `evaluation_item` liên kết 1 `evaluation_run`; mỗi `evaluation_run` có 0..N `evaluation_item`.
- `question_version_id` → `question_version.id` (trang 03): mỗi `evaluation_item` liên kết 1 `question_version`; mỗi `question_version` có 0..N `evaluation_item`.

### `evaluation_record`

Một phiếu chấm của một actor cho một item ở một lượt độc lập. repetition_no giữ riêng các lần LLM-as-judge/self-consistency.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `evaluation_item_id` | uuid FK | `evaluation_item.id` |
| `actor_id` | uuid FK | `review_actor.id` |
| `repetition_no` | int | — |
| `judge_parameters` | json ? | — |
| `comment` | text ? | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `evaluation_item_id` → `evaluation_item.id` (trang 04): mỗi `evaluation_record` liên kết 1 `evaluation_item`; mỗi `evaluation_item` có 0..N `evaluation_record`.
- `actor_id` → `review_actor.id` (trang 04): mỗi `evaluation_record` liên kết 1 `review_actor`; mỗi `review_actor` có 0..N `evaluation_record`.

### `rubric_criterion`

Định nghĩa một tiêu chí trong một rubric version và điểm tối đa. Rubric của RE có tám tiêu chí, tổng tối đa 30.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `rubric_version` | text | — |
| `code` | text | — |
| `name` | text | — |
| `max_score` | int | — |

### `rubric_score`

Điểm của một tiêu chí trong một phiếu chấm. Hai FK tạo khóa chính ghép; một phiếu chỉ có một điểm cho mỗi tiêu chí.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `evaluation_record_id` | uuid PK FK | `evaluation_record.id` |
| `criterion_id` | uuid PK FK | `rubric_criterion.id` |
| `score` | decimal | — |

**Quan hệ:**

- `evaluation_record_id` → `evaluation_record.id` (trang 04): mỗi `rubric_score` liên kết 1 `evaluation_record`; mỗi `evaluation_record` có 0..N `rubric_score`.
- `criterion_id` → `rubric_criterion.id` (trang 04): mỗi `rubric_score` liên kết 1 `rubric_criterion`; mỗi `rubric_criterion` có 0..N `rubric_score`.

**Ràng buộc của nhóm:**

- UNIQUE(evaluation_run_id, question_version_id); UNIQUE(evaluation_item_id, actor_id, repetition_no).
- UNIQUE(rubric_version, code); điểm nằm trong [0, max_score], mỗi record hoàn tất đủ 8 tiêu chí cùng rubric version.
- Kho mặc định là VIEW: version có quyết định ACCEPT, chưa bị REJECT ở trạng thái duyệt hiện tại.
- Trạng thái duyệt lấy thao tác APPROVE/REJECT mới nhất (NOTE không thay đổi trạng thái); audit chỉ thêm mới.
- metrics lưu alpha theo tiêu chí/tổng, trung bình, Pearson và chỉ số pipeline; tính từ các record, không lưu alpha mỗi điểm.
- Run cố định dataset/matrix/config; job trong run phải dùng đúng config và matrix. GENERATE_ONLY không tự vào kho.

## 05 - Dataset va nhan Bloom

FR-8, FR-9.8 — Dữ liệu huấn luyện, thẩm định nhãn và snapshot thực nghiệm.

### `dataset_version`

Snapshot có định danh/version/hash của tập dữ liệu, có mục đích sinh, huấn luyện hoặc đánh giá. Đã dùng thì không sửa thành viên tại chỗ.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `dataset_name` | text | — |
| `version_no` | int | — |
| `purpose` | enum GENERATION/TRAINING/EVALUATION | — |
| `content_hash` | text | — |
| `created_at` | timestamp | — |

### `dataset_submission`

Thành viên bài nộp của dataset. Hai FK tạo khóa chính ghép, hiện thực quan hệ N–N giữa dataset version và submission version.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `dataset_version_id` | uuid PK FK | `dataset_version.id` |
| `submission_version_id` | uuid PK FK | `submission_version.id` |

**Quan hệ:**

- `dataset_version_id` → `dataset_version.id` (trang 05): mỗi `dataset_submission` liên kết 1 `dataset_version`; mỗi `dataset_version` có 0..N `dataset_submission`.
- `submission_version_id` → `submission_version.id` (trang 01): mỗi `dataset_submission` liên kết 1 `submission_version`; mỗi `submission_version` có 0..N `dataset_submission`.

### `dataset_question`

Thành viên MCQ của dataset cùng nhãn tham chiếu, split và kết luận lọc. Không dùng kết luận lọc như nhãn dự đoán của classifier.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `dataset_version_id` | uuid FK | `dataset_version.id` |
| `question_version_id` | uuid FK | `question_version.id` |
| `reference_bloom_id` | int FK | `bloom_level.id` |
| `split` | enum TRAIN/VALIDATION/TEST | — |
| `filter_outcome` | enum EXACT/ADJUDICATED/EXCLUDED | — |
| `filter_reason` | text ? | — |

**Quan hệ:**

- `dataset_version_id` → `dataset_version.id` (trang 05): mỗi `dataset_question` liên kết 1 `dataset_version`; mỗi `dataset_version` có 0..N `dataset_question`.
- `question_version_id` → `question_version.id` (trang 03): mỗi `dataset_question` liên kết 1 `question_version`; mỗi `question_version` có 0..N `dataset_question`.
- `reference_bloom_id` → `bloom_level.id` (trang 02): mỗi `dataset_question` liên kết 1 `bloom_level`; mỗi `bloom_level` có 0..N `dataset_question`.

### `bloom_label`

Mỗi phiếu gán nhãn của judge hoặc giảng viên thẩm định, có actor và repetition. Giữ từng phiếu để chứng minh quá trình lọc.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `dataset_question_id` | uuid FK | `dataset_question.id` |
| `actor_id` | uuid FK | `review_actor.id` |
| `bloom_level_id` | int FK | `bloom_level.id` |
| `label_role` | enum JUDGE/ADJUDICATION | — |
| `repetition_no` | int | — |
| `created_at` | timestamp | — |

**Quan hệ:**

- `dataset_question_id` → `dataset_question.id` (trang 05): mỗi `bloom_label` liên kết 1 `dataset_question`; mỗi `dataset_question` có 0..N `bloom_label`.
- `actor_id` → `review_actor.id` (trang 04): mỗi `bloom_label` liên kết 1 `review_actor`; mỗi `review_actor` có 0..N `bloom_label`.
- `bloom_level_id` → `bloom_level.id` (trang 02): mỗi `bloom_label` liên kết 1 `bloom_level`; mỗi `bloom_level` có 0..N `bloom_label`.

### `training_run`

Một lần huấn luyện trên dataset cố định, có model nền, siêu tham số, seed và metrics. output_artifact_id có thể NULL khi chưa hoàn tất hoặc thất bại.

| Thuộc tính | Kiểu và khóa | Bảng/cột được tham chiếu |
|---|---|---|
| `id` | uuid PK | — |
| `dataset_version_id` | uuid FK | `dataset_version.id` |
| `output_artifact_id` | uuid FK UK ? | `model_artifact.id` |
| `base_model_ref` | text | — |
| `hyperparameters` | json | — |
| `seed` | int ? | — |
| `metrics` | json ? | — |
| `status` | enum | — |
| `started_at` | timestamp | — |
| `finished_at` | timestamp ? | — |

**Quan hệ:**

- `dataset_version_id` → `dataset_version.id` (trang 05): mỗi `training_run` liên kết 1 `dataset_version`; mỗi `dataset_version` có 0..N `training_run`.
- `output_artifact_id` → `model_artifact.id` (trang 02): mỗi `training_run` liên kết 0..1 `model_artifact`; mỗi `model_artifact` có 0..1 `training_run`.

**Ràng buộc của nhóm:**

- UNIQUE(dataset_name, version_no); UNIQUE(dataset_version_id, question_version_id).
- UNIQUE(dataset_question_id, actor_id, label_role, repetition_no); review_actor lưu từng giảng viên/LLM judge.
- Chỉ giữ exact-match hoặc off-by-one được ít nhất 2/3 giảng viên thẩm định; khử gần trùng trước khi split.
- reference_bloom_id là nhãn tham chiếu đã chốt; bloom_label giữ từng phiếu, không gộp mất bằng chứng thẩm định.
- Dataset đã dùng phải bất biến; FK RESTRICT với mọi version/artifact đã được tham chiếu.
- training_run, bảng nối dataset và các cột chi tiết là thiết kế bổ sung từ RE, chưa phải schema đã triển khai.

## Ví dụ truy vết một câu hỏi

1. Từ `question_version.origin_attempt_id`, lấy lần sinh trong `generation_attempt`.
2. Theo `generation_attempt.job_id` tới `generation_job`. Job xác định bài nộp, cặp kỹ năng–Bloom và cấu hình đã dùng.
3. Theo `submission_version_id` tới mã đầy đủ/rút gọn; theo `submission_version.problem_version_id` tới đề bài chính xác.
4. Theo `skill_bloom_cell_id` tới kỹ năng, Bloom và version ma trận; theo `config_version_id` tới prompt, generator, classifier và policy.
5. Lấy các `verification_result` của đúng question_version, cùng `decision` tương ứng. Không dùng ACCEPT của version trước để xuất version đã sửa.
6. Xem APPROVE/REJECT mới nhất trong audit; NOTE không đổi trạng thái duyệt. Chỉ version có ACCEPT hợp lệ và không bị giảng viên REJECT mới thuộc tập xuất mặc định.
7. Nếu đánh giá chất lượng, theo `evaluation_item → evaluation_record → rubric_score` để xem điểm từng người chấm thay vì chỉ xem điểm trung bình.

## Những luật không được bảo đảm chỉ bằng đường nối

- Cùng bài toán giữa submission và problem_version; cùng job giữa feedback và attempt kế tiếp.
- Chỉ ô applicable được tạo job; chỉ bài nộp VALID được sinh MCQ.
- Options có đúng A–D, không rỗng/trùng sau chuẩn hóa và answer_key hợp lệ.
- Một verification_result phải có attempt hoặc question_version; nếu cả hai thì cùng nguồn sinh. ACCEPT yêu cầu nội dung đã được kiểm chứng.
- Lỗi hạ tầng không bị tính thành FAIL nội dung; factual chỉ bắt buộc kỹ năng 3/6.
- Version đã dùng bất biến và cấm xóa cứng. Sửa nội dung tạo version mới, kiểm chứng mới.
- Một phiếu rubric đủ tám tiêu chí cùng version, mỗi điểm trong giới hạn; dataset huấn luyện được lọc và chia tập đúng quy tắc.

Các luật này cần constraint SQL, trigger hoặc kiểm tra backend phù hợp. Nhóm cần rà các điểm mở tại SD_PROPOSED mục 13 trước khi tạo migration.
