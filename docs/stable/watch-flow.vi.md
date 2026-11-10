[English](watch-flow.md) | Tiếng Việt

# Nối một công cụ quét bên ngoài với Intake

Tài liệu cho người dựng luồng quét (ví dụ bằng n8n hoặc Make) để tìm bài viết theo các trụ nội dung của khu riêng và của các dự án marketing. Quyết định thiết kế nằm ở ADR-0039 (khu riêng) và ADR-0068 (nhiều dự án, chủ đề nóng).

Intake không tự mở địa chỉ nào. Luồng của bạn làm ba việc: lấy danh sách nguồn và từ khóa, đi quét, gửi kết quả về. Một mẫu luồng n8n nằm ở `docs/stable/flows/watch-rss.n8n.json` (RSS, Google Trends, YouTube; nhánh Instagram, Threads và dịch vụ cào để sẵn, tắt).

## Nhiều dự án (từ ADR-0068)

Cùng hai đường dưới đây phục vụ mọi dự án đang nghe: khu riêng của CTO (hai mạch `business`, `technical`) và mỗi dự án marketing (một mạch `content`). Khác biệt so với bản đầu:

- `GET /api/v1/watch/config` trả thêm `projects[]`; mỗi phần tử có `project` (mã Intake của dự án, ví dụ `DMK`), `name`, `kind` (`PRIVATE` hoặc `NON_CODE`), `networks` (kênh mạng xã hội dự án bật, trong số kênh CTO đã mở ở Cài đặt > Nguồn quét), `scan_every_hours`, `next_scan_at` (giờ UTC nên quét lại; `null` ở lần đọc đầu), và `tracks[]` cùng dạng với khối `tracks` cũ. Khối `tracks` ở gốc vẫn là khu riêng, để luồng cũ không phải sửa.
- Mỗi trụ có thêm `terms[]`: `{ text, kind: keyword | hashtag, priority: high | normal }`, ưu tiên cao đứng trước. `keywords[]` (chuỗi) vẫn còn.
- Mỗi mục gửi về có thể mang `project` (mã Intake) để chỉ dự án khi không có `source_id`; `via` (`api` mặc định, hoặc `scrape` khi lấy qua dịch vụ cào); `priority` (`high` khi khớp từ khóa ưu tiên). Thứ tự xác định dự án: `source_id` → `project` → khu riêng. Mục có `project` không ai biết bị từ chối với lý do `unknown project`.
- Luồng nên chạy mỗi 30 phút, đọc `config`, và chỉ quét dự án có `next_scan_at` đã qua (hoặc `null`). Nhịp quét và giờ AI chạy do Project Owner đặt trong Intake; luồng không cần lịch riêng cho từng dự án.
- Dịch vụ cào (Facebook trang công khai, TikTok) là việc của luồng; Intake chỉ nhận tín hiệu đánh dấu `via: "scrape"`, chấm điểm thấp hơn nguồn trắng một bậc, và không giữ khóa của dịch vụ đó.

## Chuẩn bị trên máy chủ Intake

Đặt hai biến trong `.env` của máy chủ rồi khởi động lại API. Mỗi giá trị là một chuỗi ngẫu nhiên từ 24 ký tự trở lên, khác với hai khóa của luồng đăng bài. Không gửi các giá trị này qua chat hay email.

| Biến | Dùng để |
|---|---|
| `WATCH_API_KEY` | Luồng đọc nguồn và từ khóa |
| `WATCH_WEBHOOK_SECRET` | Luồng ký kết quả gửi về |

Để trống một biến thì đường tương ứng trả `404`.

## 1. Lấy nguồn và từ khóa

```
GET /api/v1/watch/config
Authorization: Bearer <WATCH_API_KEY>
```

```json
{
  "success": true,
  "data": {
    "tracks": [
      {
        "track": "business",
        "name": "Nova Labs",
        "pillars": [
          { "pillar": "AI trong vận hành", "keywords": ["chatbot trả lời khách", "tự động hóa đơn hàng"] }
        ],
        "sources": [
          { "id": "9b1e…", "kind": "WEB", "url": "https://blog.example.com/feed", "label": "Blog thử" }
        ]
      }
    ]
  },
  "request_id": "…"
}
```

Mỗi mạch còn có `demand`, cho biết cần quét bao nhiêu và trước lúc nào:

```json
"demand": {
  "wanted_per_week": 10,
  "weekday": 7,
  "time": "20:00",
  "timezone": "Asia/Ho_Chi_Minh",
  "lookback_days": 7,
  "window_start": "2026-10-04T13:00:00Z",
  "deadline": "2026-10-11T13:00:00Z",
  "received": 4,
  "remaining": 6,
  "accept_up_to": 11
}
```

| Trường | Nghĩa |
|---|---|
| `wanted_per_week` | Số tín hiệu mạch cần mỗi tuần. `0` là mạch không đặt mục tiêu |
| `deadline` | Hạn kế tiếp phải có dữ liệu, giờ UTC. `weekday` (1 là thứ Hai) và `time` là cùng hạn đó theo giờ Việt Nam |
| `window_start` | Hạn liền trước. Tín hiệu nhận sau mốc này được tính cho tuần hiện tại |
| `received`, `remaining` | Đã nhận và còn thiếu trong tuần hiện tại |
| `accept_up_to` | Số mục Intake còn nhận trong tuần này: gấp rưỡi số cần, trừ số đã nhận. `null` khi mạch không đặt mục tiêu |
| `lookback_days` | Chỉ tìm bài đăng trong số ngày này |

- Mỗi mạch có trụ, từ khóa của từng trụ, và các nguồn đang bật của mạch đó. Nguồn khai cho "cả hai mạch" xuất hiện ở cả hai.
- `kind` là một trong `WEB`, `FACEBOOK`, `X`, `YOUTUBE`, `LINKEDIN`, `OTHER`.
- Trụ chưa có từ khóa trả danh sách rỗng: không có gì để tìm cho trụ đó.
- Gọi lại trước mỗi lượt quét; người dùng có thể đã đổi nguồn hoặc từ khóa.

### Tự quyết lúc nào quét

Luồng nên chạy theo lịch cố định và để `demand` quyết có làm gì hay không:

1. Gọi `config` đầu mỗi lượt.
2. Mạch nào có `remaining` bằng `0` thì bỏ qua cho tới sau `deadline`.
3. Mạch còn thiếu thì quét các nguồn của mạch, chỉ lấy bài trong `lookback_days` ngày, và gửi về không quá `accept_up_to` mục.
4. Chạy thêm một lượt khoảng hai giờ trước `deadline` để bù phần còn thiếu.

Quét blog và YouTube một lần mỗi ngày là đủ; X và Facebook một đến hai lần mỗi ngày. Quét dày hơn nhịp đăng của nguồn không cho thêm bài mới.

## 2. Gửi kết quả về

```
POST /api/v1/watch/signals
Content-Type: application/json
X-Intake-Timestamp: <giây Unix hiện tại>
X-Intake-Signature: <chữ ký, dạng hex>
```

```json
{
  "items": [
    {
      "url": "https://blog.example.com/bai-viet",
      "title": "Tiêu đề bài tìm thấy",
      "excerpt": "Vài câu đầu của bài.",
      "author": "Tên tác giả",
      "source_id": "9b1e…",
      "pillar": "AI trong vận hành",
      "keyword": "chatbot trả lời khách",
      "published_at": "2026-10-06T03:00:00Z"
    }
  ]
}
```

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `url` | có | Bắt đầu bằng `http://` hoặc `https://`, tối đa 1.000 ký tự |
| `title` | có | Giữ lại 300 ký tự đầu |
| `source_id` hoặc `track` | một trong hai | `track` là `business`, `technical`, hoặc `content` (dự án marketing). Nguồn thuộc "cả hai mạch" thì phải gửi `track` |
| `project` | không | Mã Intake của dự án (xem `projects[].project` trong config) khi không có `source_id`; thiếu thì là khu riêng |
| `via` | không | `api` (mặc định) hoặc `scrape` |
| `priority` | không | `high` khi khớp từ khóa ưu tiên, mặc định `normal` |
| `excerpt` | không | Giữ lại 1.000 ký tự đầu. Không gửi nguyên bài |
| `author`, `keyword` | không | Giữ lại 120 ký tự đầu |
| `pillar` | không | Phải đúng tên một trụ của mạch, nếu không sẽ bị bỏ trống |
| `published_at` | không | Giờ UTC |

Giới hạn: tối đa 50 mục mỗi lần gọi, thân yêu cầu tối đa 256 KB.

Trả lời:

```json
{ "accepted": 1, "duplicates": 0, "rejected": [ { "index": 3, "reason": "url, title and a known track are required" } ] }
```

- Cùng một `url` trong cùng một mạch chỉ được lưu một lần; gửi lại được tính vào `duplicates`.
- Khi mạch đã nhận đủ gấp rưỡi số cần trong tuần, các mục gửi thêm nằm trong `rejected` với lý do `this week's quota for the track is reached`.
- Tín hiệu tự bị xóa sau 30 ngày, trừ khi người dùng đã chuyển nó thành ý. Kho giữ tối đa 600 tín hiệu.

### Cách ký

Giống lời gọi báo kết quả đăng bài: HMAC-SHA256, khóa là `WATCH_WEBHOOK_SECRET`, trên chuỗi `<dấu thời gian>.<nguyên thân yêu cầu>`, viết dạng hex chữ thường.

```js
const crypto = require('crypto')
const body = JSON.stringify({ items })        // gửi đúng chuỗi này, không định dạng lại
const timestamp = String(Math.floor(Date.now() / 1000))
const signature = crypto.createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex')
```

Dấu thời gian lệch quá 5 phút so với giờ máy chủ bị từ chối.

| Mã | Nghĩa |
|---|---|
| `200` | Đã xử lý; xem `accepted`, `duplicates`, `rejected` |
| `401` | Thiếu hoặc sai chữ ký, hoặc dấu thời gian quá hạn |
| `404` | Đường này chưa được bật |
| `413` | Thân yêu cầu quá lớn |
| `422` | Sai định dạng, hoặc hơn 200 mục |

## Intake kiểm luồng của bạn thế nào

Lúc 07:30 và 19:30 giờ Việt Nam, Intake xét từng mạch có `wanted_per_week` lớn hơn 0. Mạch còn thiếu (`remaining` lớn hơn 0) mà 12 giờ trước đó không nhận được mục nào thì người dùng thấy cảnh báo. Intake phân biệt hai trường hợp: luồng không gọi `config` lần nào trong 12 giờ, và luồng có gọi nhưng không gửi gì.

Để không sinh cảnh báo thừa: chạy ít nhất hai lần mỗi ngày khi mạch còn thiếu, và luôn gọi `config` đầu mỗi lượt kể cả khi không tìm thấy bài nào.

## Điều cần biết

- Việc quét là của luồng bên ngoài, kể cả việc tuân theo điều khoản của từng nền tảng. Quét Facebook hoặc X bằng tài khoản cá nhân có thể làm tài khoản đó bị khóa.
- Ai có `WATCH_API_KEY` thấy được bạn theo dõi ai và trụ nội dung của bạn. Ai có `WATCH_WEBHOOK_SECRET` đưa được tiêu đề tùy ý vào danh sách tín hiệu, và qua đó vào thứ AI đọc khi đề xuất tuần.
- AI của Intake chỉ đọc tiêu đề, từ khóa và tên miền của tín hiệu, và coi đó là văn bản không tin cậy.
- Chỉ gọi qua HTTPS.

## Cổng nhận cho dịch vụ không ký HMAC (FR-MKT-13)

Make, Zapier, Apify, Mention hay bất kỳ dịch vụ nào đẩy được JSON tới một địa chỉ đều nối được mà không cần n8n:

1. CTO vào Cài đặt > Nguồn quét, chọn dự án, tạo một cổng: tên, loại dịch vụ (JSON tùy ý, n8n, Make, Apify, Mention), đường lấy dữ liệu (API hay dịch vụ cào), trụ mặc định. Intake hiện đường đẩy và bí mật một lần; chép sang dịch vụ.
2. Dịch vụ gửi `POST <đường đẩy>` với header `X-Intake-Token: <bí mật>` (hoặc `Authorization: Bearer`), thân là JSON, tối đa 512 KB và 50 mục.
3. Ánh xạ nói Intake đọc mục ở đâu: `items` là đường dẫn chấm tới danh sách (rỗng nếu thân gọi đã là danh sách hoặc một mục), `fields` là đường dẫn tới từng trường (`url`, `title` bắt buộc; `excerpt`, `author`, `published_at` ISO hoặc epoch, `keyword`, `pillar`). Ví dụ Make: `{"items": "", "fields": {"url": "link", "title": "title", "excerpt": "summary", "published_at": "date", "keyword": "query"}}`. Mỗi loại có mẫu điền sẵn.
4. Dán một payload mẫu vào "Thử ánh xạ" để thấy sẽ nhận mấy mục và vì sao từ chối, không lưu gì. Nhật ký giữ 30 lần gọi gần nhất.

Trả lời giống `/watch/signals`, thêm `problems[]` (chỗ ánh xạ không đọc được). Cổng chỉ ghi tín hiệu: ai có bí mật không đọc được gì. Cổng đã đóng hoặc không tồn tại trả `404`; sai bí mật `401`. Tín hiệu qua cổng đi cùng đường với luồng quét: trùng địa chỉ, hạn mức tuần, kho 600, chủ đề nóng.
