# Nối Codex, Claude Code, Claude Desktop vào Intake (MCP)

Viết cho CTO và Project Owner. Agent gọi Intake **với đúng quyền của bạn**: tạo yêu cầu, trả lời câu hỏi làm rõ, đọc kế hoạch ngày, gửi báo cáo cuối ngày. Agent không duyệt, không đồng bộ, không chốt kế hoạch.

## 1. Lấy token

Cài đặt → Tài khoản & bảo mật → **Token cho Codex, Claude Code, Claude Desktop** → đặt tên (ví dụ "Codex máy làm việc") → Tạo token. Chép ngay: token chỉ hiện một lần. Lộ token thì bấm **Thu hồi** và tạo cái mới.

## 2. Nối

Địa chỉ: `https://<intake của bạn>/api/v1/mcp-server`.

**Codex** - `~/.codex/config.toml`:

```toml
[mcp_servers.intake]
url = "https://<intake của bạn>/api/v1/mcp-server"
bearer_token_env_var = "INTAKE_MCP_TOKEN"
```

rồi đặt biến môi trường `INTAKE_MCP_TOKEN=<token>` cho phiên Codex.

**Claude Code:**

```
claude mcp add --transport http intake https://<intake của bạn>/api/v1/mcp-server --header "Authorization: Bearer <token>"
```

**Claude Desktop:** Settings → Connectors → Add custom connector → URL như trên, header `Authorization: Bearer <token>`.

## 3. Tool

| Tool | Làm gì | Ghi chú |
|---|---|---|
| `list_projects` | Dự án bạn được dùng, mã dự án, dải hồ sơ ngữ cảnh (`context_band`) | Gọi trước |
| `get_project_context` | Hồ sơ ngữ cảnh của dự án: dải Đủ / Cần bổ sung / Chưa đủ, điểm, mục thiếu, đã duyệt chưa, nguyên văn `docs/agent/CONTEXT.md` | Gọi trước khi sửa mã; Chưa đủ thì dừng và báo CTO |
| `create_intake` | Tạo yêu cầu từ nội dung agent soạn; kèm `attachments` (ảnh hoặc PDF base64, tối đa 3) thì AI đọc chữ trong ảnh và ghép vào yêu cầu | Bắt buộc `idempotency_key` ổn định; AI đọc một lần. Chỉ CTO và Project Owner; token Developer không thấy tool này |
| `suggest_intake` | Góp ý cho dự án mình có mặt (theo nhân sự) hoặc dự án mình quản, kèm `attachments` như trên; chờ Project Owner nhận rồi mới thành Intake và AI đọc | Mọi token; `idempotency_key` ổn định; trả `feedback_id`, chưa có mã Intake |
| `get_intake` | Bản chuẩn hóa của một yêu cầu | Không có nội dung thô; chưa đọc xong thì trống |
| `list_intakes` | Danh sách yêu cầu | Lọc dự án, trạng thái, từ khóa |
| `answer_questions` | Trả lời câu hỏi còn mở | `reanalyse: true` để AI đọc lại |
| `get_day_plan` | Kế hoạch ngày, việc chờ, cảnh báo | Chỉ đọc; Project Owner chỉ thấy dự án của mình |
| `submit_daily_report` | Báo cáo cuối ngày có cấu trúc | Chờ CTO xác nhận như báo cáo email |
| `get_my_day` | Việc của chính bạn trong ngày, ưu tiên trước; kèm `personal` là việc riêng | Cần tài khoản gắn nhân sự |
| `add_personal_task`, `update_personal_task` | Thêm, đánh dấu xong hay bỏ qua một việc riêng ngoài dự án | Chỉ bạn thấy; giờ trừ vào giờ trống |
| `propose_work` | Đề xuất một việc cho một ngày: số Issue, mã Intake hoặc lời mô tả, kèm giờ | Vào Việc chờ phân công với tên bạn; Project Owner xếp hoặc bỏ qua; kế hoạch đã chốt thì chọn ngày khác |
| `update_work_status` | Báo một việc đang làm, xong, bị chặn; khi DONE kèm `evidence` (link commit hoặc MR cho việc code, link tài liệu, video, ảnh cho việc khác) | Chỉ việc của mình; CTO ghi được cho mọi người. `commit` trong `log_work` cũng tự thành bằng chứng |
| `get_week_summary` | Tuần qua bằng con số trong dự án của bạn | Chỉ đọc |
| `get_cto_board` | Bảng đầu ngày: sẵn sàng, quá hạn, chưa báo cáo | Chỉ CTO |
| `list_work_log_pending` | Lịch sử xử lý chờ CTO xác nhận | Chỉ CTO; xác nhận trên web |
| `list_work`, `get_work` | Bảng Việc nội bộ của một dự án theo sáu cột (bảy với `APPROVED` của bài marketing); `channel` và `week_of` lọc bài theo kênh và tuần đăng; một việc với mô tả, thảo luận, link, bản kênh, lịch sử | Chỉ đọc; mã việc dạng `SAV-W-12` |
| `create_work` | Tạo việc trên bảng (việc không phải code, hoặc việc cần bàn trước khi thành Issue); `template: VIDEO` tạo kèm sáu bước Brief, Kịch bản, Quay, Dựng, Duyệt, Đăng; với dự án marketing thêm `channel`, `publish_at`, `format`, `campaign`, `urgent` để thành một bài có bản kênh | CTO và Project Owner; vào Cần bàn trừ khi nói khác; Duyệt và Đăng cần link hoặc lý do mới Xong |
| `move_work` | Chuyển cột: Sẵn sàng, Đang làm, Chờ nghiệm thu, Xong, Bỏ (cần `note`) | Người làm chỉ việc của mình, giữa các cột làm; việc đã thành Issue không chuyển |
| `comment_work` | Một dòng vào Thảo luận của việc, đứng tên người giữ token | Để bàn với đội, không dán tin nhắn khách |
| `attach_link` | Đính link Drive, Canva, Figma, bản cắt, bài đã đăng vào việc | Intake chỉ giữ địa chỉ; cùng địa chỉ không tạo đôi |
| `hot_topics`, `trending`, `get_pillars`, `week_plan`, `review_queue` | Dự án marketing (ADR-0068): chủ đề nóng tuần với góc và nguồn; từ khóa và hashtag đang lên trong nguồn mình theo dõi (không phải xu hướng của nền tảng); khung trụ cột, luật kênh, chủ đề đã dùng; tuần này bằng con số (bản kênh theo ngày, chờ duyệt, trễ, ngày trống); bài chờ duyệt với chữ và số ký tự từng bản | Chỉ đọc, mọi vai trong dự án; tool không gọi AI của Intake, agent tự là AI. Cài đặt chỉ đọc qua MCP, sửa ở trang Nguồn và trụ |
| `topic_to_post`, `dismiss_topic`, `refresh_topics` | Thành bài hoặc Thành chuỗi từ một chủ đề (`angle` chọn góc); bỏ chủ đề; chạy lại luật và AI ngay | CTO và Project Owner; audit `AGENT`; Làm mới tối đa 3 lần mỗi ngày tính chung với web |
| `set_channel_text` | Ghi chữ của một bản kênh của bài, nhận lại số ký tự so với luật kênh (`over_short`, `over_long`) | Người làm chỉ bài của mình; vượt mức dài thì bài không gửi duyệt được |
| `get_short_link` | Link rút gọn của bản kênh kèm thẻ nguồn và số bấm | CTO và Project Owner; cùng bản gọi lại trả cùng mã |
| `add_signals` | Đưa điều agent tự tìm trên web vào Intake làm tín hiệu (`via = agent`) | CTO và Project Owner; chấm thấp hơn nguồn trắng một bậc; hạn mức tuần và trùng địa chỉ vẫn giữ |

Ví dụ nhắc Codex: *"Đọc thread này của khách, tạo Intake cho dự án orbit với idempotency key là hash nội dung, rồi cho tôi câu hỏi còn mở."* - hoặc *"Từ commit hôm nay của tôi, gửi báo cáo cuối ngày cho dự án ember."*

## 3a. Lệnh trong terminal, không cần tệp trong repo

Server công bố các prompt; Claude Code hiện mỗi prompt là một lệnh:

| Lệnh | Làm gì |
|---|---|
| `/in-today` | Gọi `get_my_day`, liệt kê việc hôm nay, hỏi bạn bắt đầu việc nào; khi bạn chọn thì đọc chi tiết, ghi đang làm, và theo `/fix-issue` nếu repo có |
| `/in-end-day` | Đọc commit hôm nay, khớp với việc trong kế hoạch, soạn báo cáo và CHỜ bạn xác nhận rồi mới gửi |
| `/in-content-day` | Người làm nội dung, video, vận hành: việc trên bảng của các dự án mình có mặt, chọn một việc, làm trong terminal, đính link khi có, chuyển Chờ nghiệm thu khi xong |
| `/in-week` | Tuần qua bằng con số, gợi ý ý viết bài (không nêu khách) |
| `/in-board` | Chỉ CTO: bảng đầu ngày, quá hạn, lịch sử xử lý chờ xác nhận, ba việc nên làm trước |
| `/in-hot-topics` | Project Owner marketing, buổi sáng: chủ đề nóng với góc đáng nhất, từ khóa đang lên, ngày còn trống và bài chưa có ngày, bài chờ duyệt và bản vượt ký tự, ba việc nên làm trước; chọn chủ đề thì `topic_to_post`, bỏ thì `dismiss_topic` |
| `/in-draft-post <mã bài>` | Agent đọc bài và khung dự án (`get_pillars`), soạn chữ cho từng bản kênh đúng ngôn ngữ và ký tự của kênh, cho bạn xem rồi mới lưu bằng `set_channel_text`; link rút gọn nếu bạn muốn; không gửi duyệt thay bạn |

Project Owner marketing không cần nhớ: trang Nguồn và trụ có khối "Lệnh cho agent của đội" liệt kê bốn lệnh trên và một câu nhắc cho từng tool (đã điền mã dự án) với nút Chép; tấm "Lệnh cho agent" ở menu tài khoản, khi tài khoản ở chế độ marketing, chỉ hiện lệnh của đội và câu nhắc từng tool; Tuần này gợi `/in-hot-topics`, thẻ bài gợi `/in-draft-post <mã bài>`.

Cài lệnh ngắn một lần mỗi máy (menu tài khoản > Lệnh cho agent có nút Chép): `curl -fsSL https://<intake>/api/v1/agent-commands/install.sh | bash` (PowerShell: `irm https://<intake>/api/v1/agent-commands/install.ps1 | iex`); thêm `--repo <mã dự án>` để ghi vào `.claude/commands` của repo đang đứng kèm `/fix-issue` và `.claude/intake-project`. Chưa cài thì gõ `/mcp__intake__today` một lần: agent tự ghi các tệp lệnh (tool `get_agent_commands`). Các tệp chỉ chứa chỉ dẫn, tải công khai, không có token.

Codex chưa chắc hiện prompt MCP: gõ thẳng *"lấy việc hôm nay của tôi từ Intake"*, agent gọi `get_my_day` theo mô tả tool.

Quên lệnh: menu tài khoản (góc phải trên) có **Lệnh cho agent** liệt kê từng lệnh theo vai, câu nhắc Codex tương đương và lúc nào dùng, có nút Chép; các trang Hôm nay, Daily Planning, Báo cáo ngày, Tuần qua có một dòng gợi ý lệnh đúng chỗ; tin Telegram 08:00 và 17:30 kết bằng lệnh.

**Dev trong đội** (không phải Project Owner) cần tài khoản vai Developer: CTO tạo ở Cài đặt > Người dùng từ danh sách nhân sự; dev đăng nhập web một lần để đặt mật khẩu và tạo token ở Tài khoản & bảo mật. Ngay khi tạo token, trang đó sinh sẵn lệnh `claude mcp add` có token và khối config Codex: chép, dán, xong.

## 4. Giới hạn cần biết

- Agent chạy trên OpenAI/Anthropic: những gì tool trả về đi tới đó. Tool chỉ trả bản chuẩn hóa, không trả nội dung thô khách gửi.
- Nội dung agent đọc từ Intake là dữ liệu do người ngoài viết; agent không được làm theo chỉ dẫn trong đó. Server đã dặn điều này trong `instructions`.
- Báo cáo gửi qua agent cần tài khoản của bạn gắn với một nhân sự trong Intake; chưa gắn thì báo cáo bị đánh dấu chưa khớp người.

## 5. Sửa một Issue bằng Claude Code (`/fix-issue`)

Trên trang chi tiết yêu cầu, dòng "AI Agent: /fix-issue #7" có nút **Chép** - nó chép `/fix-issue <mã Intake>`, dán vào Claude Code là chạy. Hoặc trong repo của dự án (đã có `CLAUDE.md` và `.claude/intake-project`), gõ `/fix-issue 7` (số Issue GitLab/GitHub của repo đó) hoặc `/fix-issue SAV-26W41-001`. Claude Code sẽ:

1. `get_project_context` → hồ sơ ngữ cảnh của dự án; dải **Chưa đủ** thì dừng ngay và báo anh các mục thiếu, không sửa mã. Rồi `get_intake` → đọc bước tái hiện, kết quả mong đợi, tiêu chí, câu hỏi đã làm rõ, **Gợi ý cho người sửa** (anh ghi ở trang chi tiết) và lịch sử xử lý (kể cả lý do "chưa đúng" lần trước).
2. Tạo nhánh `fix/<n>-…`, **viết test thất bại trước** để tái hiện; không tái hiện được thì ghi lịch sử và dừng.
3. Sửa, chạy test, commit `Closes #<n>`, push nhánh.
4. `log_work` → một mục trong **Lịch sử xử lý** của yêu cầu: nguyên nhân, đổi gì, test, nhánh, commit, cách kiểm, bước triển khai, `worked_on`, `actual_minutes`, `deployed`, và `context_suggestions`: điều hồ sơ ngữ cảnh còn thiếu hoặc sai mà agent gặp. Đây là bước kết thúc bắt buộc của `/fix-issue`, kể cả việc CTO giao thẳng ngoài Daily Planning; lỗi thì agent phải báo Intake chưa sẵn sàng nghiệm thu. Gợi ý nằm ở khối **Gợi ý cho hồ sơ** trên trang dự án; anh sửa tệp trong repo rồi bấm "Đã đưa vào hồ sơ" hoặc "Bỏ qua". Agent không tự sửa hồ sơ.

Phần anh làm: đọc mục đó trên Intake, merge, deploy, rồi bấm **Đã kiểm, đã triển khai** - hoặc **Chưa đúng** kèm lý do để agent làm lại. Agent không merge, không deploy, không đóng Issue; Issue lên mức "có dấu vết code" khi read model đọc commit `#n` lúc 06:45.

## 6. Điểm "sẵn sàng cho agent"

Mỗi yêu cầu có điểm 0–100 (thẻ trên tiêu đề và trong danh sách): **≥ 70 sẵn sàng**, 40–69 cần bổ sung (mở ô dưới hành trình để thấy thiếu gì: bước tái hiện, kết quả mong đợi, tiêu chí, câu hỏi chưa trả lời…), < 40 việc cho người (quay video, chụp ảnh, publish…). Hồ sơ ngữ cảnh của dự án (`docs/agent/CONTEXT.md`, Cài đặt > Dự án > Sửa) quyết 20 điểm cho mọi yêu cầu của dự án: dải Đủ +20, Cần bổ sung +10, Chưa đủ 0 và phần thiếu nêu rõ mục nào; không còn ô đánh dấu tay. Agent dùng `list_intakes` với `readiness: "READY"` để lấy đúng việc mình làm được.
