# Nối một luồng đăng bài bên ngoài với Intake

Tài liệu cho người dựng luồng tự động (ví dụ bằng n8n hoặc Make) để đăng các bài đã duyệt trong khu riêng. Quyết định thiết kế nằm ở ADR-0038.

Intake không đăng bài. Luồng của bạn làm ba việc: lấy bài đã duyệt, đăng lên nền tảng, báo lại kết quả.

## Chuẩn bị trên máy chủ Intake

Đặt hai biến trong `.env` của máy chủ rồi khởi động lại API. Mỗi giá trị là một chuỗi ngẫu nhiên từ 24 ký tự trở lên. Không gửi hai giá trị này qua chat hay email.

| Biến | Dùng để |
|---|---|
| `PUBLISH_API_KEY` | Luồng đọc hàng chờ |
| `PUBLISH_WEBHOOK_SECRET` | Luồng ký lời gọi báo kết quả |

Để trống một biến thì đường tương ứng trả `404`.

## 1. Lấy bài đã duyệt

```
GET /api/v1/publish/queue
Authorization: Bearer <PUBLISH_API_KEY>
```

Thêm `?channel=LINKEDIN` để chỉ lấy một kênh. Kết quả nằm trong `data`, bài có giờ dự định sớm nhất đứng trước:

```json
{
  "success": true,
  "data": [
    {
      "draft_id": "5d0c…",
      "track": "business",
      "channel": "LINKEDIN",
      "group_context": null,
      "pillar": "AI trong vận hành",
      "title": "Tiêu đề của ý",
      "text": "Nội dung bài, đúng như lúc được duyệt.",
      "scheduled_for": "2026-10-08T01:00:00Z",
      "approved_at": "2026-10-07T15:02:11Z"
    }
  ],
  "request_id": "…"
}
```

- `channel` là một trong `FACEBOOK`, `LINKEDIN`, `THREADS`, `FACEBOOK_GROUP`, `BLOG`, `VIDEO_SCRIPT`.
- `scheduled_for` là giờ UTC; có thể là `null` khi bài được duyệt mà không gắn ô nào của tuần.
- Một bài ở lại hàng chờ cho tới khi có ghi nhận đã đăng. Luồng của bạn phải tự nhớ bài nào nó đang xử lý để không đăng hai lần.
- Bài bị bỏ duyệt sẽ biến khỏi hàng chờ. Nên lấy lại hàng chờ ngay trước giờ đăng.

Facebook cá nhân và hội nhóm Facebook không có đường đăng tự động chính thức. Với hai kênh này, hãy đăng tay rồi bấm "Đánh dấu đã đăng" trong Intake.

## 2. Báo kết quả

```
POST /api/v1/publish/events
Content-Type: application/json
X-Intake-Timestamp: <giây Unix hiện tại>
X-Intake-Signature: <chữ ký, dạng hex>
```

Thân yêu cầu:

```json
{
  "draft_id": "5d0c…",
  "status": "POSTED",
  "posted_at": "2026-10-08T01:03:20Z",
  "url": "https://www.linkedin.com/posts/…",
  "platform": "linkedin"
}
```

Khi đăng không được, gửi `"status": "FAILED"` kèm `"error": "mô tả ngắn"`. Bài vẫn ở trạng thái đã duyệt và ở lại hàng chờ; lỗi hiện trên thẻ nháp.

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `draft_id` | có | Lấy từ hàng chờ |
| `status` | có | `POSTED` hoặc `FAILED` |
| `posted_at` | không | Giờ bài lên; bỏ trống thì lấy giờ Intake nhận được lời gọi |
| `url` | không | Phải bắt đầu bằng `http://` hoặc `https://`, tối đa 500 ký tự |
| `platform` | không | Tối đa 40 ký tự, chỉ để ghi lại |
| `error` | không | Tối đa 200 ký tự |

### Cách ký

Chữ ký là HMAC-SHA256, khóa là `PUBLISH_WEBHOOK_SECRET`, trên chuỗi `<dấu thời gian>.<nguyên thân yêu cầu>`, viết dạng hex chữ thường.

```js
const crypto = require('crypto')
const body = JSON.stringify(event)            // gửi đúng chuỗi này, không định dạng lại
const timestamp = String(Math.floor(Date.now() / 1000))
const signature = crypto.createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex')
```

Thân yêu cầu gửi đi phải đúng từng byte với chuỗi đã ký. Dấu thời gian lệch quá 5 phút so với giờ máy chủ bị từ chối.

### Trả lời

| Mã | Nghĩa |
|---|---|
| `200` | Đã ghi. Gọi lặp cho một bài đã có ghi nhận đăng vẫn trả `200` và giữ ghi nhận đầu tiên |
| `401` | Thiếu hoặc sai chữ ký, hoặc dấu thời gian quá hạn |
| `404` | Không có nháp với mã đó, hoặc đường này chưa được bật |
| `409` | Nháp chưa được duyệt |
| `422` | Thân yêu cầu sai định dạng |

## Điều cần biết

- Ai có `PUBLISH_API_KEY` đọc được mọi bài đã duyệt chưa đăng. Ai có `PUBLISH_WEBHOOK_SECRET` đánh dấu được một bài đã duyệt là đã đăng. Giữ hai giá trị ở nơi lưu bí mật của công cụ tự động, không để trong nội dung luồng.
- Trễ vài phút giữa lúc bài lên và lúc Intake biết là bình thường; giờ hiển thị là `posted_at` bạn gửi.
- Chỉ gọi qua HTTPS.

## Bài của đội marketing (FR-MKT-14, ADR-0068)

Cùng hai đường trên phục vụ thêm bài của dự án marketing khi CTO bật "Tự đăng" cho kênh ở Cài đặt > Kênh đăng:

- `GET /api/v1/publish/queue` trả thêm các mục `"kind": "post_version"`: `draft_id` dạng `work_channel:<id>`, `channel` (mã kênh của Intake, ví dụ `FACEBOOK_PAGE`, `LINKEDIN`), `title`, `text` (chữ của bản kênh, hoặc mô tả bài nếu chưa có chữ), `scheduled_for`, `project` (mã Intake), `work` (mã bài), `language`, `short_link` (link rút gọn nếu đã cấp; dán vào bài thay link gốc). Chỉ bản Sẵn sàng của bài Đã duyệt trên kênh bật tự đăng, tới giờ trong 15 phút tới và chưa quá 48 giờ. Khi CTO bấm "Dừng khẩn", hàng chờ trống.
- `POST /api/v1/publish/events` với `draft_id` đó, ký như cũ: `POSTED` kèm `url` làm bản sang Đã đăng và bài tự Đã đăng khi mọi bản đã đăng; `FAILED` kèm `error` ghi lại và bản vẫn ở hàng chờ để luồng thử lại hoặc người làm đăng tay. Nói hai lần thì lần đầu đứng.
