# Giải thích luồng và lý do thiết kế ERD

Tài liệu đọc nhanh cho ERD framework sinh–kiểm chứng MCQ, đồng bộ với RE.md, SD_PROPOSED.md v2 và trang tổng quan draw.io đã chia scope 01–05. Mô tả cột và khóa ngoại nằm trong [ERD_DETAILS.md](ERD_DETAILS.md).

## 1. Bức tranh chung

**01–05 là năm nhóm dữ liệu, không phải năm bước chạy nối tiếp.** Luồng chính đi từ **01 + 02 → 03 → 04**. Nhóm **05** chuẩn bị dữ liệu cho huấn luyện và thực nghiệm.

```text
01. Đề bài + code đúng ───────┐
                             ├──→ 03. Sinh MCQ → Kiểm chứng
02. Target + cấu hình ───────┘          ↑              │
                                       └── Sinh lại ──┤ chưa đạt, còn lượt
                                                      │ đạt
                                                      ↓
                                          04. Kho MCQ, duyệt, đánh giá

05. Dataset → Huấn luyện bộ phân loại Bloom → dùng để kiểm chứng ở 03
            → Cung cấp dữ liệu thực nghiệm → đánh giá ở 04
```

Ví dụ xuyên suốt: từ một bài code C++ tính tổng đã chạy đúng, sinh một câu MCQ thuộc kỹ năng 3 và mức Bloom được chọn trong ô áp dụng hợp lệ.

Hệ thống cần trả lời được: **Câu này sinh từ đâu, bằng cấu hình nào, đã thử bao nhiêu lần và dựa vào đâu để chấp nhận?** Phần lớn thiết kế bảng phục vụ truy vết và tái lập thực nghiệm.

> Đường nối trên ERD biểu diễn quan hệ dữ liệu, không biểu diễn thứ tự thực thi. Trang tổng quan chỉ hiện 18 bảng trung tâm; năm trang chi tiết có đủ 34 bảng.

## 2. Scope 01 — Ngữ liệu

**Câu hỏi chính: Lấy gì để sinh câu hỏi?**

### Luồng

1. Nhập đề bài và bài nộp.
2. Lọc bài không hợp lệ, ẩn danh thông tin người nộp.
3. Giữ code đã được xác nhận chạy đúng.
4. Tạo phiên bản ngữ liệu để đưa vào pipeline.

| Bảng | Vai trò |
|---|---|
| problem | Định danh bài toán |
| problem_version | Nội dung đề bài tại một phiên bản cụ thể |
| submission | Định danh bài nộp |
| submission_version | Code và kết quả xác nhận của một phiên bản bài nộp |
| language_profile_version | Cấu hình compiler, sandbox, parser và so sánh đáp án |
| import_event | Ghi nhận quá trình nhập, kể cả bài bị loại |

Trong ví dụ, hệ thống giữ đúng phiên bản đề tính tổng và đúng code đã kiểm tra. Bản tóm tắt code dùng cho prompt; bản đầy đủ dùng khi chạy sandbox. Chỉ submission_version có functional_status = VALID được đưa vào pipeline.

### Tại sao thiết kế như vậy?

Đề hoặc code có thể được sửa sau này. Nếu ghi đè, câu hỏi cũ sẽ trỏ tới nội dung mới, khiến việc tái kiểm tra không còn chính xác. Tách định danh và phiên bản giúp giữ nguyên đầu vào của từng lần sinh.

Cấu hình ngôn ngữ cũng có version vì kết quả chạy phụ thuộc compiler, giới hạn sandbox và cách diễn giải input/output. Log nhập giữ bằng chứng bài bị loại mà không cần đưa bài đó vào pipeline.

## 3. Scope 02 — Ma trận và cấu hình

**Câu hỏi chính: Sinh loại câu nào, bằng cách nào?**

### Luồng

1. Chọn phiên bản ma trận kỹ năng–Bloom.
2. Chọn một ô được phép áp dụng.
3. Chọn cấu hình gồm prompt, model sinh, bộ phân loại Bloom và policy kiểm chứng.
4. Gắn các lựa chọn này vào job.

```text
matrix_version + skill + bloom_level
                ↓
         skill_bloom_cell

prompt_template_version ────┐
model_artifact ─────────────┼──→ generation_config_version
accept_policy_version ──────┘
```

Ma trận có 9 kỹ năng × 6 mức Bloom = 54 ô, kể cả ô không áp dụng. Nếu chọn ô N/A, hệ thống từ chối trước khi sinh. Prompt theo phạm vi hiện tại là zero-shot, không dùng RAG/few-shot.

### Tại sao thiết kế như vậy?

Một lần sinh phụ thuộc nhiều lựa chọn. generation_config_version gom các tham chiếu thành một cấu hình bất biến, tránh chạy lại nhưng vô tình dùng prompt mới hoặc ngưỡng khác.

Tách prompt, model và policy cho phép so sánh các cấu hình trong thực nghiệm mà vẫn truy ra chính xác thành phần nào được sử dụng. Định nghĩa kỹ năng và Bloom được snapshot theo phiên bản ma trận để thay đổi mô tả không làm đổi ngữ nghĩa của lịch sử.

## 4. Scope 03 — Sinh, kiểm chứng, sinh lại

**Câu hỏi chính: Câu vừa sinh có dùng được không?** Đây là phần trung tâm.

### Luồng

1. Tạo generation_job: gắn ngữ liệu từ 01 và target/cấu hình từ 02.
2. Tạo generation_attempt: gọi model và giữ phản hồi thô.
3. Kiểm tra cấu trúc: đủ stem, bốn lựa chọn A–D, một đáp án đúng và giải thích. Nội dung hợp lệ được biểu diễn bằng question_version.
4. Kiểm chứng Bloom: bộ phân loại đánh giá câu hỏi, tính độ phù hợp với mức Bloom mục tiêu.
5. Kiểm chứng thực thi: với kỹ năng 3/6, trích input từ stem bằng regex rồi chạy code đầy đủ trong sandbox để đối chiếu đáp án. Kỹ năng khác dùng NOT_APPLICABLE với factual_ok = true theo phạm vi hiện tại.
6. Lưu verification_result và đưa ra decision.

| Quyết định | Điều xảy ra |
|---|---|
| ACCEPT | Câu đạt điều kiện kiểm chứng |
| REGENERATE | Tạo feedback chỉ ra lỗi, sinh lần tiếp theo |
| ABORT | Dừng vì hết lượt hoặc có nguyên nhân cần dừng |

Điều kiện ACCEPT yêu cầu structural PASS, factual_ok = true và Bloom PASS, hoặc Bloom MAYBE với điểm harmony đạt h_mid theo policy chuẩn. Các ngưỡng và budget cụ thể phải được chốt trong cấu hình.

Ví dụ: model sinh câu có đáp án 10, nhưng chạy code với input trong câu cho kết quả 12. Hệ thống lưu lỗi, tạo regenerate_feedback và yêu cầu sửa ở attempt tiếp theo.

Attempt đầu là 0. Nếu cho phép tối đa N lần sinh lại, tổng số lần sinh tối đa là N + 1. attempt_feedback nối feedback với lần thử sử dụng feedback đó.

### Tại sao thiết kế như vậy?

| Tách bảng | Lý do |
|---|---|
| job / attempt | Một yêu cầu có thể cần nhiều lần thử; cần giữ lịch sử từng lần |
| question / question_version | Định danh câu hỏi khác với nội dung tại một thời điểm |
| verification_result / decision | Bằng chứng kiểm tra khác với kết luận áp dụng policy |
| regenerate_feedback / attempt_feedback | Truy được hướng dẫn sửa nào đã được đưa vào lần thử nào |

Một attempt lỗi JSON có thể chưa có question_version nhưng vẫn có kết quả kiểm tra cấu trúc. Lỗi gọi model có thể chưa tạo verification_result hoặc decision; lỗi được ghi nhận ở job/log vận hành.

Câu bị giảng viên sửa phải tạo version mới và kiểm chứng lại, không thừa hưởng ACCEPT cũ. previous_version phải cùng question, tăng version_no và không tạo chu trình.

Lỗi hạ tầng được ghi riêng: factual_ok = NULL, dừng job; không coi đó là bằng chứng câu hỏi sai hoặc tự chuyển thành PASS. Kiểm chứng lại tạo lượt kết quả mới, không ghi mất lỗi cũ.

## 5. Scope 04 — Kho MCQ và đánh giá

**Câu hỏi chính: Câu nào được giữ lại và chất lượng ra sao?** Nhóm này có hai luồng.

### Luồng quản lý kho

```text
Version có ACCEPT hợp lệ
        ↓
Giảng viên xem, nhận xét, duyệt hoặc từ chối
        ↓
Lọc và khử trùng → xuất các version đủ điều kiện
```

audit_event lưu ai đã APPROVE/REJECT/NOTE, vào lúc nào và vì sao. Kho mặc định lấy các version có ACCEPT hợp lệ và không bị từ chối ở trạng thái duyệt hiện tại.

Trạng thái duyệt lấy APPROVE/REJECT mới nhất theo thứ tự (created_at, id); NOTE chỉ thêm nhận xét. Khi xuất, giữ manifest các question_version_id đã xuất và thông tin khử trùng.

### Luồng thực nghiệm

```text
evaluation_run
    → evaluation_item: câu nào được đánh giá
        → evaluation_record: ai chấm, lượt nào
            → rubric_score: điểm từng tiêu chí
```

rubric_criterion định nghĩa tiêu chí và điểm tối đa. Thiết kế đánh giá dùng 8 tiêu chí với tổng tối đa 30 điểm; có 5 người chấm và LLM judge 5 lượt theo RE/SD. Các điểm được tổng hợp để phân tích chất lượng, độ đồng thuận và tương quan. Chỉ số tổng hợp không phải thuộc tính của từng điểm riêng lẻ.

Run cố định dataset, ma trận, cấu hình và seed được dùng. GENERATE_ONLY là nhánh thực nghiệm, không tự đưa câu vào kho mặc định.

### Tại sao thiết kế như vậy?

Kiểm chứng tự động, duyệt sử dụng và chấm chất lượng trả lời những câu hỏi khác nhau. Câu vượt qua máy kiểm tra vẫn có thể bị giảng viên từ chối vì diễn đạt chưa tốt.

Một câu có thể được nhiều người chấm, hoặc được LLM judge chấm nhiều lượt. Tách item, record và score biểu diễn được các chiều này mà không nhân bản nội dung MCQ.

**APPROVE của giảng viên không thay thế ACCEPT của bộ kiểm chứng.** review_actor là người duyệt/người chấm hoặc LLM judge; không phải hồ sơ người học. Log lifecycle/job được giữ riêng với audit duyệt câu hỏi.

## 6. Scope 05 — Dataset và nhãn Bloom

**Câu hỏi chính: Lấy dữ liệu đâu để huấn luyện và đo hiệu quả?**

### Luồng chuẩn bị dữ liệu

1. Tạo dataset_version.
2. Gắn các phiên bản bài nộp qua dataset_submission hoặc câu hỏi qua dataset_question.
3. Với dữ liệu huấn luyện Bloom, thu thập nhãn judge và phiếu thẩm định trong bloom_label.
4. Lọc theo quy tắc: giữ exact-match; trường hợp lệch một mức cần ít nhất 2/3 giảng viên thẩm định.
5. Khử gần trùng trước khi chia train/validation/test.
6. Đóng băng membership, nhãn và bằng chứng thẩm định trước khi huấn luyện hoặc thực nghiệm.

Sau đó:

- training_run dùng dataset để huấn luyện và tạo model_artifact; ghi cấu hình, seed, metrics và artifact đầu ra.
- Model phân loại Bloom được tham chiếu từ cấu hình nhóm 02 để sử dụng ở nhóm 03.
- Dataset thực nghiệm được dùng trong evaluation_run của nhóm 04.

Baseline CodeBERT giữ cố định 6 tầng dưới, tinh chỉnh 6 tầng trên và head theo SD. Đây là thiết kế, không phải khẳng định hệ thống đã được triển khai hoặc huấn luyện xong.

### Tại sao thiết kế như vậy?

Chỉ lưu nhãn cuối sẽ mất bằng chứng về việc nhãn đó được chốt thế nào. bloom_label giữ từng phiếu; dataset_question giữ nhãn tham chiếu và kết luận lọc. Judge phải chấm độc lập, không nhận Bloom mục tiêu hoặc nhãn tham chiếu.

Nếu dữ liệu hoặc nhãn thay đổi giữa hai lần chạy, việc so sánh model sẽ không còn công bằng. Vì vậy dataset còn biên soạn có thể sửa, nhưng phải đóng băng trước khi dùng. Khử gần trùng trước khi split giúp hạn chế rò rỉ nội dung giữa tập huấn luyện và tập kiểm tra.

## 7. Cách nhớ và tự kiểm tra trong 30 phút

| Nhóm | Câu hỏi cần nhớ |
|---|---|
| 01 | Đầu vào là đề và code nào? |
| 02 | Sinh theo target và cấu hình nào? |
| 03 | Đã sinh, kiểm tra và sửa như thế nào? |
| 04 | Câu nào được giữ, ai duyệt và chất lượng ra sao? |
| 05 | Dữ liệu nào dùng để huấn luyện và thực nghiệm? |

| Thời gian | Nội dung |
|---|---|
| 0–5 phút | Đọc luồng chung và ví dụ |
| 5–12 phút | Theo dõi job → attempt → question_version → verification_result → decision |
| 12–17 phút | Xem đầu vào và cấu hình ở 01/02 |
| 17–22 phút | Phân biệt ACCEPT, duyệt thủ công và chấm chất lượng ở 04 |
| 22–26 phút | Xem dataset, gán nhãn và huấn luyện ở 05 |
| 26–30 phút | Tự kể lại một câu MCQ đi qua hệ thống mà không nhìn tài liệu |

Bài tự kiểm tra: **Câu này được sinh từ code nào, bằng cấu hình nào, đã thử mấy lần, vì sao được nhận và ai đã duyệt?** Lần theo được các bảng để trả lời là đã nắm phần cốt lõi.

34 bảng chủ yếu xuất hiện vì hệ thống phải giữ phiên bản, nhiều lần thử, nhiều người chấm và bằng chứng thực nghiệm. Đây là mô hình logic đề xuất; các quyết định còn mở xem [SD_PROPOSED.md](SD_PROPOSED.md), mục 13.
