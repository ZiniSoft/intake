English | [Tiếng Việt](daily-report-format.vi.md)

# End-of-day report format (Daily Report)

Written for company members. Report emails are read automatically by Intake's rule set; write them in the right format and each task is linked to the right Issue, with the right hours, straight into the next day's day plan without anyone fixing it by hand.

## 1. Email subject

```
DAILY REPORT | 2026-10-09 | Nguyen Van A | ORBIT-WEB
```

Four parts separated by `|`: the words `DAILY REPORT`, the date `YYYY-MM-DD`, full name (as registered in Intake), project code in **uppercase** (several projects separated by commas: `ORBIT-WEB, ORBIT-API`).

## 2. Email body

```
ORBIT-WEB | Ember Web

[DONE] Lập danh sách sửa trang hướng dẫn index.html | Thời gian: 1.5 giờ | Tiến độ: 100%
GitLab #8
Bước tiếp theo: Chờ duyệt báo cáo, sau đó sửa README theo 12 đề xuất

[IN_PROGRESS] Chụp ảnh minh họa từng bước cho hướng dẫn cài | Thời gian: 2.5 giờ | Tiến độ: 60%
GitLab #14
Bước tiếp theo: Chụp nốt 4 bước còn lại trên Windows

[PLANNED] Chèn ảnh vào README.md và index.html, quay video hướng dẫn | Thời gian dự kiến: 4 giờ
GitLab #14

[BLOCKED] Đồng bộ CRM | Thời gian: 0.5 giờ | Tiến độ: 20%
GitLab #21
Vấn đề: Chờ API key của khách

Tổng thời gian: 4.5 giờ
```

Rules:
- Each project has one heading line `MÃ-DỰ-ÁN | Tên dự án` (project code | project name, code in uppercase), followed by that project's tasks.
- Each task starts with **one of six statuses** in square brackets: `PLANNED`, `IN_PROGRESS`, `PENDING_REVIEW`, `DONE`, `BLOCKED`, `CANCELLED`.
- On the same line, after the task title: `| Thời gian: X giờ | Tiến độ: N%` (time spent in hours, progress percent). `PLANNED` tasks write `Thời gian dự kiến: X giờ` (estimated time) instead of `Thời gian`. `DONE` means `Tiến độ: 100%`.
- **The Issue number goes on its own line, as `GitLab #8`** (projects on GitHub also write `GitLab #n`; Intake treats it as the project's Issue). Every development task must have one; without it Intake warns and the task cannot enter the plan.
- Optional, one line each: `Bước tiếp theo: …` (next step), `Vấn đề: …` (problem, required for `BLOCKED`), `Intake: KIN-26W41-007`, `Deadline/Milestone: …`, `Dependency: …`, evidence links (paste the full URL). The `Plane:` line in old reports is now only historical data and is not used by the parser for new work.
- End of email: `Tổng thời gian: X giờ` (total time), equal to the sum of hours of all tasks that are not `PLANNED`.
- Put the signature and greetings after a `--` line; anything after `--` is not read.

## 3. Right and wrong

| RIGHT | WRONG (Intake misreads or ignores it) |
|---|---|
| `DAILY REPORT \| 2026-10-09 \| Nguyen Van A \| ORBIT-WEB` | `Daily report 9/10` · missing date or project code · lowercase `orbit-web` in the body |
| `ORBIT-WEB \| Ember Web` on its own line before the tasks | No project line → `PROJECT_SECTION_MISSING` |
| `[DONE] Lập danh sách sửa trang hướng dẫn \| Thời gian: 1.5 giờ \| Tiến độ: 100%` | `Xong: Lập danh sách…` · `[Done]` without `|` separating the hours · `[DONE]` with `Tiến độ: 90%` |
| `GitLab #8` on its own line right below the task | `[#8 KIN-26W41-007] Lập danh sách…` · `Issue: https://gitlab…/work_items/17` · `Issue #8:` in the title (Intake **has learned** to read these three forms, but that is a fallback; writing nothing at all is plainly wrong) |
| `Thời gian: 1.5 giờ` (dot or comma both work) | `1h30`, `90 phút`, `1,5h` |
| `[PLANNED] … \| Thời gian dự kiến: 4 giờ` | `[PLANNED] … \| Thời gian: 4 giờ` (counted as hours worked) |
| `[BLOCKED] … ` + the line `Vấn đề: Chờ API key của khách` | `[BLOCKED]` without saying what is blocking |
| `Tổng thời gian: 4.5 giờ` equal to the sum of the tasks | Missing total line → warning; total off by more than 15 minutes → warning |
| One task = one status line + a few extra lines | Merging two jobs into one `[DONE]` · writing results as a long paragraph without `[STATUS]` |
| `Intake: KIN-26W41-007` when the task comes from an Intake request | Intake ID written in brackets in the title (readable, but confused with the Issue number) |

## 4. Resending on the same day

Sending a new email for **the same report date** **replaces** the old one: the old one becomes a previous version (still viewable, not used for planning), and the new one goes back to waiting for the CTO to confirm again, even if the old one was already confirmed. Only the same email sent again (same Message-ID) is ignored; a new email, even with identical content, becomes a new version. So: if you made a mistake, resend the whole email; do not send a "supplementary" email with only a few tasks, because it will replace the whole report.

## 5. Deadline

Send before the cutoff time (23:30 per configuration); after that the email is still read but marked late. On weekends a report is only needed when there is OT or real work.
