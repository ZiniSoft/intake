English | [Tiếng Việt](watch-flow.vi.md)

# Connecting an external scanning tool to Intake

Documentation for people building a scanning flow (for example with n8n or Make) to find posts matching the content pillars of the Private Space and of marketing projects. The design decisions are in ADR-0039 (Private Space) and ADR-0068 (multiple projects, hot topics).

Intake does not open any address by itself. Your flow does three things: fetch the list of sources and keywords, go scan, send the results back. A sample n8n flow is at `docs/stable/flows/watch-rss.n8n.json` (RSS, Google Trends, YouTube; Instagram, Threads and scraping service branches are in place, disabled).

## Multiple projects (since ADR-0068)

The same two endpoints below serve every project that is listening: the CTO's Private Space (two tracks `business`, `technical`) and each marketing project (one track `content`). Differences from the first version:

- `GET /api/v1/watch/config` also returns `projects[]`; each element has `project` (the project's Intake ID, for example `DMK`), `name`, `kind` (`PRIVATE` or `NON_CODE`), `networks` (social network channels the project enabled, among the channels the CTO opened in Settings > Scan sources ("Cài đặt > Nguồn quét")), `scan_every_hours`, `next_scan_at` (UTC time to scan again; `null` on the first read), and `tracks[]` in the same shape as the old `tracks` block. The `tracks` block at the root is still the Private Space, so old flows do not need changes.
- Each pillar also has `terms[]`: `{ text, kind: keyword | hashtag, priority: high | normal }`, high priority first. `keywords[]` (strings) is still there.
- Each item sent back may carry `project` (Intake ID) to indicate the project when there is no `source_id`; `via` (`api` by default, or `scrape` when obtained via a scraping service); `priority` (`high` when it matches a priority keyword). Order for determining the project: `source_id` → `project` → Private Space. Items with an unknown `project` are rejected with the reason `unknown project`.
- The flow should run every 30 minutes, read `config`, and scan only projects whose `next_scan_at` has passed (or is `null`). Scan frequency and AI run times are set by the Project Owner in Intake; the flow does not need a separate schedule per project.
- Scraping services (public Facebook pages, TikTok) are the flow's job; Intake only receives signals marked `via: "scrape"`, scores them one level lower than whitelisted sources, and does not keep that service's keys.

## Preparation on the Intake server

Set two variables in the server's `.env` and restart the API. Each value is a random string of 24 characters or more, different from the two keys of the publishing flow. Do not send these values over chat or email.

| Variable | Used for |
|---|---|
| `WATCH_API_KEY` | The flow reads sources and keywords |
| `WATCH_WEBHOOK_SECRET` | The flow signs the results it sends back |

If a variable is left empty, the corresponding endpoint returns `404`.

## 1. Fetch sources and keywords

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

Each track also has `demand`, which says how much to scan and by when:

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

| Field | Meaning |
|---|---|
| `wanted_per_week` | Number of signals the track needs per week. `0` means the track has no target |
| `deadline` | Next deadline by which data must exist, in UTC. `weekday` (1 is Monday) and `time` are the same deadline in Vietnam time |
| `window_start` | The previous deadline. Signals received after this point count toward the current week |
| `received`, `remaining` | Received and still missing in the current week |
| `accept_up_to` | Number of items Intake will still accept this week: one and a half times the target, minus what has been received. `null` when the track has no target |
| `lookback_days` | Only look for posts published within this many days |

- Each track has pillars, keywords for each pillar, and the active sources of that track. Sources declared for "both tracks" appear in both.
- `kind` is one of `WEB`, `FACEBOOK`, `X`, `YOUTUBE`, `LINKEDIN`, `OTHER`.
- A pillar without keywords returns an empty list: there is nothing to search for that pillar.
- Call it again before each scan run; the user may have changed sources or keywords.

### Deciding when to scan

The flow should run on a fixed schedule and let `demand` decide whether to do anything:

1. Call `config` at the start of each run.
2. Skip any track whose `remaining` is `0` until after `deadline`.
3. For tracks still short, scan the track's sources, only take posts within `lookback_days` days, and send back no more than `accept_up_to` items.
4. Run one extra pass about two hours before `deadline` to make up the shortfall.

Scanning blogs and YouTube once a day is enough; X and Facebook once or twice a day. Scanning more often than the source publishes yields no new posts.

## 2. Send results back

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

| Field | Required | Notes |
|---|---|---|
| `url` | yes | Starts with `http://` or `https://`, at most 1,000 characters |
| `title` | yes | The first 300 characters are kept |
| `source_id` or `track` | one of the two | `track` is `business`, `technical`, or `content` (marketing project). For a source belonging to "both tracks", `track` must be sent |
| `project` | no | The project's Intake ID (see `projects[].project` in config) when there is no `source_id`; if missing, it is the Private Space |
| `via` | no | `api` (default) or `scrape` |
| `priority` | no | `high` when it matches a priority keyword, default `normal` |
| `excerpt` | no | The first 1,000 characters are kept. Do not send the full post |
| `author`, `keyword` | no | The first 120 characters are kept |
| `pillar` | no | Must exactly match the name of one of the track's pillars, otherwise it is left empty |
| `published_at` | no | UTC time |

Limits: at most 50 items per call, request body at most 256 KB.

Response:

```json
{ "accepted": 1, "duplicates": 0, "rejected": [ { "index": 3, "reason": "url, title and a known track are required" } ] }
```

- The same `url` in the same track is stored only once; resending counts toward `duplicates`.
- Once a track has received one and a half times its weekly target, further items land in `rejected` with the reason `this week's quota for the track is reached`.
- Signals are deleted automatically after 30 days, unless the user has turned them into an idea. The store keeps at most 600 signals.

### How to sign

Same as the publish result callback: HMAC-SHA256, with `WATCH_WEBHOOK_SECRET` as the key, over the string `<dấu thời gian>.<nguyên thân yêu cầu>` (timestamp, then the raw request body), written as lowercase hex.

```js
const crypto = require('crypto')
const body = JSON.stringify({ items })        // gửi đúng chuỗi này, không định dạng lại
const timestamp = String(Math.floor(Date.now() / 1000))
const signature = crypto.createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex')
```

Timestamps more than 5 minutes off the server time are rejected.

| Code | Meaning |
|---|---|
| `200` | Processed; see `accepted`, `duplicates`, `rejected` |
| `401` | Missing or wrong signature, or expired timestamp |
| `404` | This endpoint is not enabled |
| `413` | Request body too large |
| `422` | Wrong format, or more than 200 items |

## How Intake checks your flow

At 07:30 and 19:30 Vietnam time, Intake checks each track with `wanted_per_week` greater than 0. If a track is still short (`remaining` greater than 0) and received no items in the previous 12 hours, the user sees a warning. Intake distinguishes two cases: the flow did not call `config` at all in 12 hours, and the flow called it but sent nothing.

To avoid unnecessary warnings: run at least twice a day while a track is still short, and always call `config` at the start of each run even when no posts are found.

## Things to know

- Scanning is the external flow's job, including complying with each platform's terms. Scanning Facebook or X with a personal account can get that account locked.
- Whoever has `WATCH_API_KEY` can see whom you follow and your content pillars. Whoever has `WATCH_WEBHOOK_SECRET` can put arbitrary titles into the signal list, and through it into what the AI reads when proposing the week.
- Intake's AI reads only the title, keyword and domain name of a signal, and treats them as untrusted text.
- Call only over HTTPS.

## Inbound gateway for services that do not sign with HMAC (FR-MKT-13)

Make, Zapier, Apify, Mention or any service that can push JSON to an address can connect without n8n:

1. The CTO goes to Settings > Scan sources, picks a project, and creates a gateway: name, service type (any JSON, n8n, Make, Apify, Mention), data path (API or scraping service), default pillar. Intake shows the push URL and the secret once; copy them into the service.
2. The service sends `POST <đường đẩy>` with header `X-Intake-Token: <bí mật>` (or `Authorization: Bearer`), JSON body, at most 512 KB and 50 items.
3. The mapping tells Intake where to read items: `items` is the dot path to the list (empty if the body is already a list or a single item), `fields` are the paths to each field (`url`, `title` required; `excerpt`, `author`, `published_at` ISO or epoch, `keyword`, `pillar`). Make example: `{"items": "", "fields": {"url": "link", "title": "title", "excerpt": "summary", "published_at": "date", "keyword": "query"}}`. Each type has a prefilled template.
4. Paste a sample payload into "Test mapping" ("Thử ánh xạ") to see how many items would be accepted and why any are rejected, without saving anything. The log keeps the 30 most recent calls.

The response is the same as `/watch/signals`, plus `problems[]` (places the mapping could not read). The gateway only writes signals: someone with the secret cannot read anything. A closed or nonexistent gateway returns `404`; a wrong secret `401`. Signals through the gateway follow the same path as the scanning flow: address dedupe, weekly quota, the 600 store, hot topics.
