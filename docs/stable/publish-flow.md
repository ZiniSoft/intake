English | [Tiếng Việt](publish-flow.vi.md)

# Connecting an external publishing flow to Intake

Documentation for people building an automated flow (for example with n8n or Make) to publish approved posts in the Private Space. The design decision is in ADR-0038.

Intake does not publish posts. Your flow does three things: fetch approved posts, publish them on the platform, report the result back.

## Preparation on the Intake server

Set two variables in the server's `.env` and restart the API. Each value is a random string of 24 characters or more. Do not send these two values over chat or email.

| Variable | Used for |
|---|---|
| `PUBLISH_API_KEY` | The flow reads the queue |
| `PUBLISH_WEBHOOK_SECRET` | The flow signs its result callbacks |

If a variable is left empty, the corresponding endpoint returns `404`.

## 1. Fetch approved posts

```
GET /api/v1/publish/queue
Authorization: Bearer <PUBLISH_API_KEY>
```

Add `?channel=LINKEDIN` to fetch only one channel. Results are in `data`, with the earliest scheduled post first:

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

- `channel` is one of `FACEBOOK`, `LINKEDIN`, `THREADS`, `FACEBOOK_GROUP`, `BLOG`, `VIDEO_SCRIPT`.
- `scheduled_for` is UTC time; it can be `null` when the post was approved without being assigned to a slot in the week.
- A post stays in the queue until a published record exists. Your flow must remember which posts it is handling so it does not publish twice.
- A post whose approval is withdrawn disappears from the queue. Fetch the queue again right before publishing time.

Personal Facebook and Facebook groups have no official automated publishing path. For these two channels, publish manually and then click "Mark as published" ("Đánh dấu đã đăng") in Intake.

## 2. Report the result

```
POST /api/v1/publish/events
Content-Type: application/json
X-Intake-Timestamp: <giây Unix hiện tại>
X-Intake-Signature: <chữ ký, dạng hex>
```

Request body:

```json
{
  "draft_id": "5d0c…",
  "status": "POSTED",
  "posted_at": "2026-10-08T01:03:20Z",
  "url": "https://www.linkedin.com/posts/…",
  "platform": "linkedin"
}
```

When publishing fails, send `"status": "FAILED"` with `"error": "mô tả ngắn"` (a short description). The post stays approved and remains in the queue; the error shows on the draft card.

| Field | Required | Notes |
|---|---|---|
| `draft_id` | yes | Taken from the queue |
| `status` | yes | `POSTED` or `FAILED` |
| `posted_at` | no | Time the post went live; if empty, the time Intake received the call is used |
| `url` | no | Must start with `http://` or `https://`, at most 500 characters |
| `platform` | no | At most 40 characters, for record only |
| `error` | no | At most 200 characters |

### How to sign

The signature is HMAC-SHA256, with `PUBLISH_WEBHOOK_SECRET` as the key, over the string `<dấu thời gian>.<nguyên thân yêu cầu>` (timestamp, then the raw request body), written as lowercase hex.

```js
const crypto = require('crypto')
const body = JSON.stringify(event)            // gửi đúng chuỗi này, không định dạng lại
const timestamp = String(Math.floor(Date.now() / 1000))
const signature = crypto.createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex')
```

The request body sent must match the signed string byte for byte. Timestamps more than 5 minutes off the server time are rejected.

### Response

| Code | Meaning |
|---|---|
| `200` | Recorded. Repeated calls for a post that already has a published record still return `200` and keep the first record |
| `401` | Missing or wrong signature, or expired timestamp |
| `404` | No draft with that ID, or this endpoint is not enabled |
| `409` | Draft not approved yet |
| `422` | Request body in the wrong format |

## Things to know

- Whoever has `PUBLISH_API_KEY` can read every approved, unpublished post. Whoever has `PUBLISH_WEBHOOK_SECRET` can mark an approved post as published. Keep both values in the automation tool's secret store, not in the flow content.
- A delay of a few minutes between when a post goes live and when Intake knows is normal; the displayed time is the `posted_at` you send.
- Call only over HTTPS.

## Marketing team posts (FR-MKT-14, ADR-0068)

The same two endpoints above also serve marketing project posts when the CTO turns on "Auto publish" ("Tự đăng") for a channel in Settings > Publishing channels ("Cài đặt > Kênh đăng"):

- `GET /api/v1/publish/queue` also returns items with `"kind": "post_version"`: `draft_id` in the form `work_channel:<id>`, `channel` (Intake's channel code, for example `FACEBOOK_PAGE`, `LINKEDIN`), `title`, `text` (the channel version's text, or the post description if there is no text yet), `scheduled_for`, `project` (Intake ID), `work` (post ID), `language`, `short_link` (the short link if one has been issued; paste it into the post instead of the original link). Only Ready versions of Approved posts on channels with auto publish on, due within the next 15 minutes and not more than 48 hours overdue. When the CTO clicks "Emergency stop" ("Dừng khẩn"), the queue is empty.
- `POST /api/v1/publish/events` with that `draft_id`, signed as before: `POSTED` with `url` moves the version to Published and the post becomes Published automatically once all versions are published; `FAILED` with `error` is recorded and the version stays in the queue for the flow to retry or for the assignee to publish manually. If reported twice, the first one stands.
