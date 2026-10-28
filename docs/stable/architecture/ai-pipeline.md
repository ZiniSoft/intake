# Kiến trúc AI ingestion pipeline

_Target + runtime pipeline 1.2 | Cập nhật 2026-10-04_

## 1. Provider policy

Primary endpoint: `https://api-sg.umodelverse.ai/v1`.

| Mục đích | Model UModelVerse |
|---|---|
| Text normalization | `deepseek-v4.1-flash` |
| Reprocess/phân tích nâng cao | `deepseek-v4-pro-0813` |
| Image/vision | `deepseek-v4-flash-vision-exp` (không dùng trong pilot, ADR-0015) |

Controlled pilot chỉ gọi UModelVerse theo ADR-0011; môi trường pilot không cấu hình OpenRouter key. Sau pilot, nếu fallback được bật lại bằng ADR mới, OpenRouter phải bật ZDR, deny data collection và tắt fallback nội bộ. Model ID phải nằm trong server-side allowlist.

## 2. Stage contract

| Stage | Input | Output | Terminal/error behavior |
|---|---|---|---|
| `INGEST` | API transaction | source/object/outbox | rollback nếu persistence lỗi |
| `SCAN` | quarantine object ID | clean/rejected | kiểm tra file theo ADR-0015 (magic bytes, kích thước, số trang, PDF mã hóa/file nhúng), không dùng malware scan; không đạt thì dừng file |
| `EXTRACT_TEXT` | source/PDF | canonical text + evidence | OCR chạy trên máy riêng cùng LAN trong container cô lập, có timeout và giới hạn tài nguyên; partial theo trang |
| `VISION` | clean image/page | description + evidence | Không chạy trong pilot: ảnh/PDF chỉ OCR nội bộ và chỉ phần chữ đã OCR được gửi lên UModelVerse (ADR-0015) |
| `EVIDENCE` | branch results | complete/partial bundle | không bỏ lỗi âm thầm |
| `NORMALIZE` | text/evidence refs | strict JSON extraction | provider chain |
| `VALIDATE` | extraction | accepted/warnings/errors | deterministic, fail closed |
| `MATERIALIZE` | accepted result | update intake review fields | optimistic version |

## 3. Failure matrix trong pilot

| Primary outcome | Hành động |
|---|---|
| Success + valid schema | Persist UModelVerse result |
| Timeout/transport/429/5xx | Retry theo `AI_TASK_MAX_RETRIES`; hết lượt chuyển `FAILED`. Không fallback trong pilot |
| 2xx nhưng JSON/schema invalid | Retry trong cùng ngân sách; hết lượt chuyển `FAILED` |
| 400/401/403 | Fail permanent |
| Model ngoài allowlist | Fail permanent trước khi gọi mạng |

## 4. Retry và terminal state

- Outbox chỉ claim `NEW`, `RETRY` hoặc `PUBLISHING` đã hết lease.
- Broker failure dùng exponential backoff và tối đa `OUTBOX_MAX_ATTEMPTS` (mặc định 8); hết ngân sách chuyển `DEAD`.
- Processing run dùng `AI_TASK_MAX_RETRIES` (mặc định 3). Lease hết hạn dưới giới hạn chuyển `RETRY`; tại giới hạn chuyển `FAILED` và Intake chuyển `PROCESSING_FAILED`.
- Payload event không phải JSON object chuyển `DEAD/INVALID_EVENT_PAYLOAD`; không silent success và không retry vô hạn.
- Mỗi normalization job có `job_key` duy nhất; completion của run đã `SUCCEEDED` là idempotent.

## 5. Output schema bắt buộc

Đây là target schema đầy đủ. Runtime 1.2 hiện chỉ yêu cầu năm field `item_type`, `suggested_priority`, `proposed_route`, `normalized_title`, `normalized_summary`; phần còn lại giữ trạng thái `PARTIAL` trong readiness và không được mô tả là đã materialize.

```json
{
  "schema_version": "intake.normalization.v1",
  "item_type": "BUG|TASK|FEATURE|SCOPE_CHANGE|FEEDBACK|QUESTION|UNCLEAR",
  "title": "string",
  "summary": "string",
  "suggested_priority": "P0|P1|P2|P3",
  "proposed_route": "RESPONSE|WORK|GITLAB|GITHUB|NEEDS_INFO",
  "acceptance_criteria": ["string"],
  "missing_information": ["string"],
  "risks": ["string"],
  "evidence_refs": ["source-or-fragment-id"],
  "confidence": 0.0
}
```

AI không được tự thêm fact không có evidence. Deterministic validator kiểm enum, length, priority rule, BUG evidence và route prerequisites.

## 6. Data minimization

- Chỉ decrypt raw data trong memory của worker cần dùng.
- Không ghi raw prompt, raw chat hoặc base64 file vào log/outbox/Redis.
- Loại metadata không cần thiết trước cloud call.
- File gốc (ảnh/PDF) không rời mạng nội bộ; cloud call chỉ chứa text nguồn và phần chữ đã OCR.
- Mỗi call ghi provider/model/policy/prompt/schema trace, không ghi secret.
- Retention purge phải xóa cả source ciphertext và SeaweedFS object tương ứng.

## 6.1 Intake normalization: đầu vào và prompt (từ 2026-10-05)

- **Đầu vào luôn là nội dung gốc** đã giải mã của Intake, kể cả khi bấm "Phân tích lại". Trước đó lượt phân tích lại đọc bản tóm tắt do AI viết ở lượt trước nên mất dần chi tiết. Bản tóm tắt chỉ được dùng khi nội dung gốc đã bị purge theo retention; `run_metadata.input_origin` ghi `RAW` hoặc `SUMMARY`.
- **Tin nhắn gửi model** gồm vài dòng ngữ cảnh (tên và loại dự án, kênh, các tuyến khả dụng) rồi nội dung gốc đặt trong `<source>...</source>`; chuỗi đóng thẻ xuất hiện trong nội dung bị vô hiệu hóa.
- **Prompt `intake-worker-v4`** (v3 cùng ngày, v4 sau lần đo đầu) định nghĩa từng loại, từng mức ưu tiên (theo bảng ở functional-spec mục 6) và từng tuyến (theo sơ đồ ở flows mục 2), yêu cầu chỉ dùng dữ kiện có trong nguồn, viết tiêu đề và tóm tắt theo ngôn ngữ của nguồn, và kèm ba ví dụ. Phiên bản prompt được lưu ở `ai_extractions.prompt_version`.
- **Tuyến theo dự án.** Model chỉ được chọn trong các tuyến dự án có liên kết; `WORK` luôn khả dụng, còn GitLab/GitHub chỉ khả dụng khi dự án có nơi giao việc. Tuyến không khả dụng được điều chỉnh có kiểm soát và ghi `run_metadata.route_adjusted`.
- Chữ trong ảnh và PDF đính kèm vẫn chưa tới model vì OCR chưa được triển khai (ADR-0015).

Kết quả đo xem mục 6.2. Model không cho kết quả giống hệt nhau giữa các lượt dù `temperature = 0`, nên mọi so sánh phải chạy lặp.

## 6.2 Đo chất lượng prompt chuẩn hóa Intake

Lệnh `python -m app.tools.evaluate_intake_prompt`, chạy trong container `ai-worker` (nơi duy nhất có key của nhà cung cấp), không ghi gì vào database:

- **Trường hợp tổng hợp:** 26 yêu cầu (20 ban đầu và 6 trường hợp `hold-*` viết sau khi chỉnh v4, không dùng để chỉnh) trong `app/tools/intake_eval_cases.json`, không chứa dữ liệu khách hàng. Đáp án do người viết prompt soạn; CTO cần rà lại trước khi tin vào điểm số.
- **Trường hợp thật (`--real N`):** các Intake CTO đã duyệt. Đáp án là độ ưu tiên và tuyến CTO đã chọn (loại yêu cầu không được chấm vì CTO không quyết định nó). Nội dung được đọc từ database lúc chạy và gửi tới nhà cung cấp như xử lý bình thường; không ghi ra file, báo cáo chỉ in mã Intake. Bộ này tự lớn dần theo số Intake được duyệt.
- `--repeat K` hỏi mỗi trường hợp K lần để đo độ ổn định; `--prompt-file` chấm một prompt khác để so sánh.

Lần đo ngày 2026-10-05, model `deepseek-v4.1-flash`, 21 trường hợp (20 tổng hợp, 1 thật), mỗi trường hợp 3 lần:

| Tiêu chí | Prompt cũ | `intake-worker-v3` |
|---|---|---|
| Đúng loại | 51/60 | 55/60 |
| Đúng độ ưu tiên | 45/63 | 58/63 |
| Đúng tuyến | 50/63 | 60/63 |
| Tiêu đề đúng ngôn ngữ nguồn | 59/63 | 60/63 |
| Trường hợp ổn định qua 3 lần | 11/21 | 18/21 |

Sau lần đo đó prompt được chỉnh thành `intake-worker-v4`: yêu cầu tính năng thông thường là P2 (khớp quyết định của CTO trên Intake thật duy nhất), mất dữ liệu luôn là P0, khách hàng nhận thông tin sai là P1, hành vi chậm vẫn là bug, ý tưởng đề xuất việc mới là tính năng. Đo lại trên 27 trường hợp, mỗi trường hợp 3 lần: đúng loại 78/78, ưu tiên 79/81, tuyến 80/81, tiêu đề đúng ngôn ngữ 78/81, ổn định 25/27. Riêng 6 trường hợp giữ lại (18 câu trả lời) chỉ lệch 1 câu về tuyến. Đáp án của một trường hợp tổng hợp (`syn-03`) được sửa từ P3 sang P2 theo quyết định thật của CTO, nên hai lần đo không so sánh trực tiếp được ở trường hợp đó.

Giới hạn của phép đo: v4 được chỉnh trên chính 20 trường hợp ban đầu nên điểm ở đó lạc quan; đáp án tổng hợp do chính người viết prompt soạn; chỉ có một Intake thật đã duyệt; prompt cũ được chấm với định dạng tin nhắn mới (có dòng ngữ cảnh và danh sách tuyến) nên điểm tuyến của nó cao hơn thực tế trước đây.

Cuối ngày 2026-10-07 prompt là `intake-worker-v8`: thêm quy tắc câu hỏi phải hội tụ sau khi team đã trả lời một lượt (đo được: loại 77/77, ưu tiên 73/77, tuyến 76/77, ổn định 24/26, một lượt nhà cung cấp lỗi). Ngay trước đó là `intake-worker-v7` (ADR-0032; v6 thêm quy tắc việc con, gợi ý tách và cách đọc yêu cầu đã tách; v7 thêm cách dùng câu trả lời của team cho các câu hỏi AI nêu; v7 đo được: loại 78/78, ưu tiên 74/78, tuyến 78/78, ổn định 25/26). Bản v5 ngay trước đó (ADR-0032): tin nhắn có thêm mô tả dự án, thuật ngữ và Issue đang mở; kết quả có thêm phần chi tiết (ở đâu, các bước, kết quả mong đợi, việc con, tiêu chí nghiệm thu, câu hỏi cần làm rõ, Issue có thể trùng). Đo trên 26 ca tổng hợp, mỗi ca 3 lần: đúng loại 77/78, ưu tiên 76/78, tuyến 76/78, tiêu đề đúng ngôn ngữ 75/78, ổn định 23/26. Phần chi tiết chưa có bộ ca chấm điểm.

## 6A. Các lượt gọi AI ngoài Intake normalization

| Lượt gọi | Đầu vào | Đầu ra | Ghi chú |
|---|---|---|---|
| Đọc lại Daily Report sai mẫu | Subject và phần báo cáo của thư, đã bỏ chữ ký sau dòng `--` (ADR-0019) | Danh sách task theo schema, trạng thái allowlist | Tối đa 5 thư mỗi lượt quét (phút 10 và 40), timeout `AI_REPORT_TIMEOUT_SECONDS`; kết quả không dùng cho Planning tới khi CTO xác nhận |
| Meeting note | Bản chữ theo người nói, tên các dự án đang hoạt động, dự án của cuộc họp | Tóm tắt, quyết định, mục yêu cầu/bug/thay đổi phạm vi, việc cần làm, câu hỏi, rủi ro | Tối đa 3 lần thử; audio không bao giờ tới UModelVerse; dự án do AI đoán bị bỏ qua khi cuộc họp có dự án |

Chuyển chữ từ audio không phải lượt gọi AI của pipeline này: do `meeting-gateway` gọi ElevenLabs (ADR-0018).

## 7. Current implementation gap - baseline 1.2

Text normalization, provider chain, outbox/Celery và JSONB persistence đã được `VERIFIED` bằng synthetic runtime smoke trên hai dự án thử. Gate C đã xác minh Redis outage và worker lease recovery không làm mất dữ liệu hoặc tạo duplicate. OpenRouter fallback có deterministic contract test, giữ `CODE_COMPLETE` và nằm ngoài phạm vi pilot theo ADR-0011. Scan/OCR/vision/evidence pipeline chưa triển khai đầy đủ và tiếp tục được ghi `NOT_STARTED` hoặc `PARTIAL` trong readiness matrix.
