# CodeLit — MVP Sprint 2 (30/9)

Ứng dụng luyện C++17 theo luồng:

**Chủ đề → bài toán (kỹ năng + mức Bloom) → nộp code → pass toàn bộ testcase mẫu → 3 MCQ → nộp đáp án → Gemini giải thích và feedback.**

Không có pha verify/Bloom classifier/factual verifier hay vòng tái sinh nội dung. Chỉ kiểm tra cấu trúc JSON, số phương án và metadata để UI đọc được dữ liệu an toàn. Mức độ/kỹ năng do bài toán quyết định, sinh viên không tự chọn.

## Chạy trên máy

Yêu cầu: Python 3.11+. Railway/backend dùng thêm thư viện Google Auth chính thức để xác minh chữ ký đăng nhập; frontend không cần npm install. Chấm C++ được gửi tới judge gateway trên GCP, không cần Docker daemon trong backend.

Từ thư mục `mvp`, chạy PowerShell:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py
```

Chỉ copy `.env` lần đầu; giữ file đã cấu hình. Mở **http://127.0.0.1:8000**.

Trong `.env`:

```dotenv
GEMINI_API_KEY=điền_key_của_project_tại_đây
GEMINI_MODEL=gemini-3.6-flash
LLM_MODE=gemini
ADMIN_TOKEN=đặt_một_mã_quản_trị_dài_ngẫu_nhiên
GOOGLE_CLIENT_ID=client_id_của_OAuth_web_app
GOOGLE_CLIENT_SECRET=client_secret_của_OAuth_web_app
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback
GCP_JUDGE_URL=http://dia_chi_gateway_da_bao_ve:8000
GCP_JUDGE_TOKEN=token_trung_voi_GCP
GCP_JUDGE_TIMEOUT=65
```

Không gửi API key qua chat, không đưa vào frontend hoặc commit. Khởi động lại server sau khi đổi cấu hình. Thiếu key sẽ hiện lỗi có thể retry sau khi cấu hình; hệ thống không giả làm LLM.

Muốn diễn tập không gọi API: đặt `LLM_MODE=demo`. **Demo vẫn chấm C++ thật qua GCP Docker judge**, nhưng MCQ/feedback là fixture được gắn nhãn DEMO; không dùng để đánh giá chất lượng sinh câu hỏi. Chế độ được lưu theo lần nộp; đổi chế độ chỉ áp dụng cho lần nộp mới, không trộn demo/Gemini trong một bài.

### Đăng nhập Google dành cho sinh viên HCMUT

1. Trong Google Cloud/Google Auth Platform của bạn, tạo OAuth client loại **Web application** và cấu hình consent screen.
2. Thêm chính xác Authorized redirect URI: `http://127.0.0.1:8000/auth/google/callback`. `localhost` và `127.0.0.1` không thay thế nhau. Nếu chạy cổng 8001, đăng ký URI cổng 8001 và sửa `GOOGLE_REDIRECT_URI` của instance tương ứng.
3. Điền `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` trong `.env` rồi khởi động lại. Đây là OAuth credentials, **khác** Gemini API key và key của delegate Astra. Không gửi secret qua chat hoặc commit.
4. Nếu OAuth app đang ở chế độ Testing, thêm các tài khoản trường dùng thử vào danh sách Test users của Google. Khi muốn mở cho toàn bộ sinh viên, cấu hình audience/publishing phù hợp trong Google Cloud; ứng dụng không tự xuất bản consent screen.
5. Nhấn **Đăng nhập bằng Google**, chọn tài khoản có email chính xác đuôi `@hcmut.edu.vn`.

Server xác minh chữ ký Google, issuer, audience, expiry, nonce, `email_verified=true`, `hd=hcmut.edu.vn` và domain email chính xác. State một lần trong 10 phút gắn với cookie trình duyệt, kèm PKCE. Không chấp nhận Gmail cá nhân, subdomain hoặc chuỗi giả dạng `hcmut.edu.vn.evil`. Định danh ổn định `google:sub`; tên/email chỉ để hiển thị.

**Tất cả sinh viên đăng nhập hợp lệ được xem và làm mọi bài mẫu**, không có enrollment hay khóa theo tiến độ. Đề, code khởi đầu và testcase hiển thị đầy đủ; lời giải chuẩn vẫn thuộc ngân hàng giảng viên. Lịch sử mỗi tài khoản tách riêng. Các mã `sv01-demo`…`sv03-demo` và endpoint đăng nhập cũ đã bỏ; cookie demo bị vô hiệu, bài nộp cũ được giữ và không tự gán sang tài khoản Google.

`LLM_MODE=demo` chỉ mô phỏng LLM, **không** bỏ qua Google login. Thiếu cấu hình OAuth sẽ hiện thông báo chưa sẵn sàng, không có đường đăng nhập thay thế.

Mặc định server chỉ lắng nghe localhost. Google callback cho máy khác cần HTTPS và tên miền được đăng ký; HTTP chỉ chấp nhận loopback local. HTTPS callback tự bật Secure cookie. Judge gateway ban đầu cũng chỉ lắng nghe localhost trên GCP; phải có private route hoặc HTTPS và firewall hạn chế trước khi Railway kết nối. Bản MVP chưa phải dịch vụ judge multi-tenant đã được kiểm toán.

Tham khảo: [Google OpenID Connect server flow](https://developers.google.com/identity/openid-connect/openid-connect), [xác minh Google ID token](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

## Những gì đã có

- 4 bài gốc, 4 chủ đề: tổng mảng, palindrome, tìm vị trí đầu tiên bằng binary search, ngoặc hợp lệ.
- 18 testcase công khai; từng bài có starter C++ và lời giải chuẩn dành cho giảng viên.
- Editor hai cột, lọc/tìm bài, lưu bản nháp, báo compile/runtime/timeout/output sai.
- Chỉ toàn bộ testcase pass mới tạo job MCQ. So sánh output theo các token phân cách bởi khoảng trắng; không có hidden tests.
- MCQ sinh từ **đề + code sinh viên + testcase + skills + Bloom**. Lời giải chuẩn không đưa tới sinh viên hoặc prompt.
- Đáp án đúng và giải thích không được trả qua API trước khi nộp đủ 3 câu. Server tính điểm theo answer key; Gemini nhận câu hỏi, đáp án sinh viên, điểm và code để giải thích. LLM không tùy ý sửa điểm.
- Lịch sử, snapshot đề/code/testcase, câu hỏi, đáp án và feedback được lưu. Import cập nhật đề không thay đổi bài đã nộp.
- Chống gọi trùng theo request ID; nộp đáp án lặp lại giữ nguyên kết quả; không được sửa đáp án sau khi nộp.
- Khôi phục job khi server restart; retry judge/LLM không làm mất đáp án.
- XML bài lập trình và Moodle XML nhập/xuất qua màn hình **Ngân hàng XML**, có mã quản trị.

## Gemini 3.6 Flash và 3 người đồng thời

Model ID đã đối chiếu: [`gemini-3.6-flash`](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash). Dùng REST `generateContent`, JSON schema, temperature 0.2, tối đa 4096 output tokens/lần; không fine-tune model.

Google áp quota **theo project**, gồm RPM, input TPM, RPD; thêm key không tăng quota. Xem quota thực tế tại [Google AI Studio / tài liệu rate limits](https://ai.google.dev/gemini-api/docs/rate-limits). Không thể cam kết tuyệt đối không có 429 hoặc hết quota.

| Cấu hình | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `LLM_RPM` | 4 | Tối đa 4 request/phút, giãn ít nhất 15 giây |
| `LLM_INPUT_TPM` | 20000 | Giới hạn input theo ước lượng bảo thủ bằng byte UTF-8 |
| `LLM_RPD` | 100 | Giới hạn trên cửa sổ 24 giờ trượt, bảo thủ hơn lịch reset Google |
| `LLM_MAX_OUTPUT_TOKENS` | 4096 | Giới hạn output |
| `LLM_TIMEOUT_SECONDS` | 60 | Timeout một request |

**Đây là ngân sách local khởi điểm, không phải quota được Google bảo đảm.** Đặt thấp hơn quota thật (gợi ý 70–80%) và trừ lưu lượng ứng dụng khác dùng cùng project. Nếu quota thấp hơn mặc định, phải giảm cấu hình. Một lượt hoàn thành cần 2 request: sinh MCQ + feedback. 3 người cần 6 request thành công; ở 4 RPM, thời điểm bắt đầu request thứ 6 cách request đầu ít nhất 75 giây, chưa tính thời gian làm MCQ, inference và retry. 100 RPD tương đương tối đa 50 lượt/ngày nếu không có retry/lỗi.

- Railway dispatch tuần tự và gateway GCP mặc định chỉ chạy **1 judge container tại một thời điểm** trên `e2-medium`. **Một worker LLM** xử lý hàng đợi SQLite chung, không khóa HTTP/UI.
- Mỗi sinh viên tối đa một job đang xử lý; tối đa 5 lần nộp mới/phút.
- Quota reservation lưu bền, tính cả request lỗi; chờ quota thì job tự tiếp tục và UI hiện thời gian dự kiến.
- HTTP 429/5xx/network lỗi: exponential backoff + jitter, tối đa 3 lần tự gọi mỗi giai đoạn; cooldown chung. Hết lượt tự retry thì hiển thị lỗi và nút thử lại; không quay API key, không tự nâng billing.
- Giới hạn code 12 KB, XML 500 KB, số testcase/MCQ và output. Schema lỗi thì dừng, không có semantic verification ngầm.
- Chạy **một instance server trên một database**. Chưa hỗ trợ nhiều replica/worker process.

## Ngân hàng XML

- `examples/problems.xml`: đủ 4 bài, lời giải C++ và 18 testcase; có thể nhập hoặc tải export tương đương trong UI.
- `examples/moodle.xml`: MCQ mẫu một đáp án đúng. Có tag `problem:sum-array`, `skill:S3`, `bloom:APPLY`.
- Import bài toán: root `<problem-bank version="1">`, các trường theo file mẫu. ID trùng được cập nhật nguyên tử; validate toàn bộ trước khi ghi.
- Moodle: chỉ `multichoice`, `single=true`, 4 phương án, đúng một `fraction=100`, ba `fraction=0`, có `generalfeedback`. Bỏ qua category, từ chối loại khác; không hỗ trợ media/plugin Moodle. HTML được hiển thị như văn bản, không thực thi.
- Moodle MCQ vào ngân hàng và xuất lại; MCQ do Gemini sinh cũng được lưu vào ngân hàng. Nội dung ngân hàng không thay thế bước sinh mới theo code sinh viên.
- DTD/entity bị từ chối; ID bài, skill và Bloom phải hợp lệ. Import trùng MCQ được bỏ qua theo hash.
- XML export bài toán chứa lời giải chuẩn nên cần `ADMIN_TOKEN`.

## Kiểm tra

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_mvp test_google_login
.\.venv\Scripts\python.exe -m unittest -v test_judge_client
.\.venv\Scripts\python.exe -m py_compile server.py google_login.py bank.py llm.py judge_client.py
node --check static/app.js
```

`test_mvp` và `test_google_login` không tiêu thụ Gemini quota hoặc gọi tài khoản Google thật. Bao phủ nghiệp vụ cũ, quyền xem toàn bộ bài, bỏ đăng nhập demo, session isolation/logout, OIDC callback HTTP, state/nonce/replay/domain và chữ ký RSA thật với certificate transport mô phỏng. Judge/Gemini được stub trong suite API; không dùng suite này để khẳng định provider thật hoạt động.

Kiểm tra Docker executor thật trên máy có Docker sau khi build image `codelit-judge:local`:

```powershell
python test_judge.py
```

Kiểm tra UI tùy chọn (cần Playwright có sẵn và Edge): `node test_browser.cjs`. Chạy server trước, `BASE_URL` mặc định `http://127.0.0.1:8000`. Mặc định kiểm tra màn hình Google login, lỗi domain và chặn truy cập ẩn danh. Để kiểm tra các trang sau đăng nhập, truyền `BROWSER_STORAGE_STATE` là file Playwright storage state từ một phiên Google hợp lệ; giữ file này trong `data/`, không commit/chia sẻ vì có session cookie. `RUN_FULL_FLOW=1` nộp bài thật; 3 phiên chỉ chạy nếu có thêm `BROWSER_STORAGE_STATE_2` và `BROWSER_STORAGE_STATE_3`. Không cài Playwright thành dependency ứng dụng.

## Kiến trúc và phạm vi Sprint 2

```text
HTML/CSS/JS → HTTP API (Python stdlib) → SQLite
                       ├─ JudgeClient → GCP gateway → Docker → g++ / C++17
                       └─ 1 LLM worker → quota queue → Gemini → JSON
```

**ARCHITECTURE:** Railway giữ API/auth/SQLite/Gemini/attempt state; GCP giữ gateway và Docker execution. Mỗi submission dùng một judge container; DB và trạng thái không được sao chép sang GCP. Xem `docs/gcp-judge.md`.

**ROUTING:** Codex tích hợp/kiểm tra. Router chọn Astra cho đánh giá kiến trúc và Antigravity cho seed. Astra không thực hiện được do cấu hình API không hợp lệ. Antigravity có model khả dụng, nhưng tại bước routing chưa có worktree/project mapping được xác minh; Local LLM cung cấp bản nháp seed. Codex sửa format testcase, đồng bộ stdin, bổ sung constraints và tự xác minh. Git ở workspace ngoài chưa có commit; repository dự án lồng bên trong có lịch sử riêng. Không auto-commit hoặc sửa hệ thống orchestration toàn cục.

**PONYTAIL:** stdlib + SQLite và Google Auth cho xác minh bảo mật; không Redis/Celery/RAG/Bloom classifier, không pipeline review nhiều tầng. **ASTRA:** đề xuất mã qua API read-only; Codex áp dụng và kiểm tra. **ANTIGRAVITY:** worker bounded khi có worktree phù hợp. **MANUS:** integration ở host, không gọi cho thay đổi đăng nhập nhỏ này. **EMIL/UI RULES:** giao diện làm việc, một màu nhấn, trạng thái rõ, responsive, focus, reduced motion; không thêm animation trang trí hoặc thư viện UI khi chưa cần.

**FILES CREATED/MODIFIED:** toàn bộ mã mới nằm trong `mvp/`; README dự án thêm liên kết. Các tài liệu/diagram hiện có không bị viết lại.

**REMOVED / AVOIDED COMPLEXITY:** không Docker-in-Docker trên Railway, không mount Docker socket vào gateway container, không Redis/broker/distributed queue, không sandbox tự chế chạy code sinh viên trực tiếp trên host.

**RISKS / OPEN QUESTIONS:** gateway user thuộc nhóm `docker`, là trust boundary có quyền cao trên VM; chỉ mở kết nối Railway sau khi có private route hoặc HTTPS/firewall. Docker resource isolation phục vụ demo có kiểm soát, chưa là multi-tenant judge được kiểm toán cho Internet. SQLite chứa code và kết quả sinh viên; bảo vệ/sao lưu thư mục `data/`.

**NEXT RECOMMENDED STEP:** cấu hình key/quota project rồi cho 3 sinh viên chạy đồng thời một lượt thật, ghi thời gian chờ/429/chất lượng MCQ để chốt thông số trước 30/9.

### Kết quả kiểm tra trên máy này — 15/9/2026

- 13/13 kiểm thử API/state/XML/quota đạt.
- Docker image đã build; 4 lời giải chuẩn pass 18/18 testcase, chạy tối đa 3 container song song.
- Judge từ chối code không biên dịch, output sai, vòng lặp vô hạn và output vượt giới hạn; kiểm tra non-root, root filesystem read-only và không có mạng ngoài đều đạt.
- Playwright + Edge: 3 phiên SV01–SV03 đồng thời hoàn tất **C++ thật → MCQ demo → feedback demo → reload**; nhập Moodle XML và tải XML bài toán đạt. Desktop/mobile không có lỗi JavaScript hoặc tràn trang ngang ở kích thước đã kiểm tra.
- **Chưa gọi Gemini thật:** chưa có API key/quota project cho ứng dụng. Kiểm thử 429 là mô phỏng, không phải đo tải Google thật.

### Thay đổi đăng nhập — 16/9/2026

- **ARCHITECTURE:** thêm OIDC Google + bảng students/google_logins, giữ API/SQLite/judge/LLM hiện tại. Mọi tài khoản trường hợp lệ thấy toàn bộ bài mẫu.
- **ROUTING / ASTRA:** theo yêu cầu ưu tiên khoảng 90% giao việc cho delegate Astra chỉ trong yêu cầu này. Lần gọi lớn bị HTTP 524; chia nhỏ thành module auth, tích hợp và test. Astra trả bản nháp; Codex sửa những điểm không khớp contract, bổ sung giới hạn, áp dụng và kiểm thử. Không khẳng định tỷ lệ công việc thực tế đo được là 90%, không đổi routing toàn cục.
- **ANTIGRAVITY / MANUS:** không gọi trong thay đổi này; không có redesign đáng kể cần UI judge.
- **FILES:** thêm `google_login.py`, `requirements.txt`, `test_google_login.py`; sửa `server.py`, `static/app.js`, `static/style.css`, `.env.example`, `.gitignore`, `test_mvp.py`, `test_browser.cjs`, README này.
- **AVOIDED COMPLEXITY:** không thêm role/enrollment framework, không tự làm mật mã JWT, không auth demo bypass, không tự liên kết dữ liệu SV01–SV03 với tài khoản thật.
- **RISKS / NEXT STEP:** cần OAuth Web Client ID/Secret và consent screen của project để thử đăng nhập thật; điền `.env`, khởi động lại rồi dùng một email `@hcmut.edu.vn` kiểm tra callback.
- **VALIDATION:** 27/27 kiểm thử nghiệp vụ/xác thực đạt; có kiểm tra chữ ký RSA thật và callback HTTP với provider mô phỏng. `pip check` và kiểm tra cú pháp JS đạt. Playwright/Edge kiểm tra trang Google login, chặn truy cập ẩn danh, thông báo lỗi domain và bố cục mobile đạt. Chưa thử tài khoản Google thật vì chưa có OAuth credentials.
