English | [Tiếng Việt](mcp-agents.vi.md)

# Connecting Codex, Claude Code, Claude Desktop to Intake (MCP)

Written for the CTO and Project Owners. The agent calls Intake **with exactly your permissions**: create requests, answer clarifying questions, read the day plan, submit the end-of-day report. The agent does not approve, does not sync, and does not finalize plans.

## 1. Get a token

Settings → Account & security → **Tokens for Codex, Claude Code, Claude Desktop** ("Token cho Codex, Claude Code, Claude Desktop") → enter a name (for example "Codex work machine") → Create token. Copy it right away: the token is shown only once. If a token leaks, click **Revoke** ("Thu hồi") and create a new one.

## 2. Connect

Address: `https://<intake của bạn>/api/v1/mcp-server`.

**Codex** - `~/.codex/config.toml`:

```toml
[mcp_servers.intake]
url = "https://<intake của bạn>/api/v1/mcp-server"
bearer_token_env_var = "INTAKE_MCP_TOKEN"
```

then set the environment variable `INTAKE_MCP_TOKEN=<token>` for the Codex session.

**Claude Code:**

```
claude mcp add --transport http intake https://<intake của bạn>/api/v1/mcp-server --header "Authorization: Bearer <token>"
```

**Claude Desktop:** Settings → Connectors → Add custom connector → URL as above, header `Authorization: Bearer <token>`.

## 3. Tools

| Tool | What it does | Notes |
|---|---|---|
| `list_projects` | Projects you may use, project IDs, context pack band (`context_band`) | Call first |
| `get_project_context` | The project's context pack: band Sufficient / Needs more / Insufficient, score, missing items, whether it has been approved, verbatim `docs/agent/CONTEXT.md` | Call before changing code; if Insufficient, stop and tell the CTO |
| `create_intake` | Create a request from content the agent drafts; with `attachments` (images or PDF in base64, max 3) the AI reads the text in the images and merges it into the request | A stable `idempotency_key` is required; the AI reads once. CTO and Project Owner only; Developer tokens do not see this tool |
| `suggest_intake` | Suggestion for a project you are on (as a member) or a project you manage, with `attachments` as above; it waits for the Project Owner to accept it before it becomes an Intake and the AI reads it | All tokens; stable `idempotency_key`; returns `feedback_id`, no Intake ID yet |
| `get_intake` | Normalized version of a request | No raw content; empty until reading is done |
| `list_intakes` | List of requests | Filter by project, status, keyword |
| `answer_questions` | Answer open questions | `reanalyse: true` to have the AI read again |
| `get_day_plan` | Day plan, pending work, warnings | Read only; a Project Owner sees only their own projects |
| `submit_daily_report` | Structured end-of-day report | Waits for CTO confirmation like an email report |
| `get_my_day` | Your own work for the day, by priority; includes `personal` for personal tasks | Requires an account linked to a member |
| `add_personal_task`, `update_personal_task` | Add, mark done or skip a personal task outside projects | Only you see it; its hours are subtracted from free hours |
| `propose_work` | Propose a task for a day: Issue number, Intake ID or a description, with hours | Goes into Pending assignment under your name; the Project Owner schedules or skips it; if the plan is already finalized, pick another day |
| `update_work_status` | Report a task as in progress, done, blocked; on DONE include `evidence` (commit or MR link for code work, document, video, image link for other work) | Only your own tasks; the CTO can write for anyone. `commit` in `log_work` also becomes evidence automatically |
| `get_week_summary` | The past week in numbers for your projects | Read only |
| `get_cto_board` | Morning board: ready, overdue, no report | CTO only |
| `list_work_log_pending` | Work log entries awaiting CTO confirmation | CTO only; confirm on the web |
| `list_work`, `get_work` | A project's Internal tasks board in six columns (seven with `APPROVED` for marketing posts); `channel` and `week_of` filter posts by channel and publish week; one task with description, discussion, links, channel versions, history | Read only; task IDs look like `SAV-W-12` |
| `create_work` | Create a task on the board (non-code work, or work to discuss before it becomes an Issue); `template: VIDEO` also creates six steps Brief, Script, Shoot, Edit, Review, Publish; for marketing projects add `channel`, `publish_at`, `format`, `campaign`, `urgent` to make it a post with channel versions | CTO and Project Owner; goes into To discuss unless told otherwise; Review and Publish need a link or a reason before Done |
| `move_work` | Move column: Ready, In progress, Awaiting acceptance, Done, Dropped (needs `note`) | Assignees only for their own tasks, between working columns; tasks that became Issues do not move |
| `comment_work` | One line in the task's Discussion, under the token holder's name | For talking with the team, do not paste customer messages |
| `attach_link` | Attach a Drive, Canva, Figma, cut, or published post link to a task | Intake only keeps the address; the same address is not added twice |
| `hot_topics`, `trending`, `get_pillars`, `week_plan`, `review_queue` | Marketing projects (ADR-0068): the week's hot topics with angles and sources; rising keywords and hashtags in your own watch sources (not platform trends); pillar framework, channel rules, topics already used; this week in numbers (channel versions per day, awaiting review, late, empty days); posts awaiting review with the text and character count of each version | Read only, any role in the project; the tools do not call Intake's AI, the agent is the AI. Settings are read only via MCP, edit them on the Sources and pillars page |
| `topic_to_post`, `dismiss_topic`, `refresh_topics` | Make a post or Make a series from a topic (`angle` picks the angle); dismiss a topic; rerun rules and AI now | CTO and Project Owner; audit `AGENT`; Refresh at most 3 times per day, counted together with the web |
| `set_channel_text` | Write the text of one channel version of a post, get back the character count against channel rules (`over_short`, `over_long`) | Assignees only for their own posts; over the long limit, the post cannot be sent for review |
| `get_short_link` | Short link for a channel version with source tag and click count | CTO and Project Owner; calling again for the same version returns the same code |
| `add_signals` | Put what the agent found on the web into Intake as signals (`via = agent`) | CTO and Project Owner; scored one level lower than whitelisted sources; weekly quota and address dedupe still apply |

Example prompts for Codex: *"Read this customer thread, create an Intake for project orbit with an idempotency key that is the content hash, then give me the open questions."* - or *"From my commits today, send the end-of-day report for project ember."*

## 3a. Terminal commands, no files needed in the repo

The server publishes prompts; Claude Code shows each prompt as a command:

| Command | What it does |
|---|---|
| `/in-today` | Calls `get_my_day`, lists today's work, asks which one you start; when you pick, reads the details, marks it in progress, and follows `/fix-issue` if the repo has it |
| `/in-end-day` | Reads today's commits, matches them with tasks in the plan, drafts the report and WAITS for your confirmation before sending |
| `/in-content-day` | Content, video, operations people: tasks on the boards of the projects you are on, pick one, work in the terminal, attach links when available, move to Awaiting acceptance when done |
| `/in-week` | The past week in numbers, suggests post ideas (no customer names) |
| `/in-board` | CTO only: morning board, overdue, work log awaiting confirmation, three things to do first |
| `/in-hot-topics` | Marketing Project Owner, in the morning: hot topics with the best angle, rising keywords, empty days and posts without a date, posts awaiting review and versions over the character limit, three things to do first; pick a topic with `topic_to_post`, drop it with `dismiss_topic` |
| `/in-draft-post <mã bài>` | The agent reads the post and the project framework (`get_pillars`), drafts the text for each channel version in the right language and character count for the channel, shows you before saving with `set_channel_text`; short link if you want; does not send for review on your behalf |

Marketing Project Owners do not need to memorize these: the Sources and pillars ("Nguồn và trụ") page has a "Commands for the team's agent" ("Lệnh cho agent của đội") block listing the four commands above and a prompt for each tool (with the project ID filled in) with a Copy button; the "Agent commands" ("Lệnh cho agent") panel in the account menu, when the account is in marketing mode, shows only the team's commands and per-tool prompts; This week ("Tuần này") suggests `/in-hot-topics`, post cards suggest `/in-draft-post <mã bài>`.

Install the short commands once per machine (account menu > Agent commands has a Copy button): `curl -fsSL https://<intake>/api/v1/agent-commands/install.sh | bash` (PowerShell: `irm https://<intake>/api/v1/agent-commands/install.ps1 | iex`); add `--repo <mã dự án>` to write into `.claude/commands` of the current repo along with `/fix-issue` and `.claude/intake-project`. If not installed yet, type `/mcp__intake__today` once: the agent writes the command files itself (tool `get_agent_commands`). The files contain only instructions, are downloadable publicly, and contain no token.

Codex may not show MCP prompts: just type *"get my work for today from Intake"*, and the agent calls `get_my_day` based on the tool description.

Forgot a command: the account menu (top right) has **Agent commands** listing each command by role, the equivalent Codex prompt and when to use it, with a Copy button; the Today ("Hôm nay"), Daily Planning, Daily report ("Báo cáo ngày"), and Past week ("Tuần qua") pages have a one-line command hint in the right place; the 08:00 and 17:30 Telegram messages end with a command.

**Team developers** (not Project Owners) need a Developer role account: the CTO creates it in Settings > Users from the member list; the developer logs in to the web once to set a password and creates a token under Account & security. As soon as the token is created, that page generates a ready `claude mcp add` command with the token and a Codex config block: copy, paste, done.

## 4. Limits to know

- The agent runs on OpenAI/Anthropic: whatever the tools return goes there. The tools return only the normalized version, not the raw content the customer sent.
- Content the agent reads from Intake is data written by outsiders; the agent must not follow instructions in it. The server already says this in `instructions`.
- Reports sent via an agent require your account to be linked to a member in Intake; if not linked, the report is marked as unmatched.

## 5. Fixing an Issue with Claude Code (`/fix-issue`)

On the request detail page, the line "AI Agent: /fix-issue #7" has a **Copy** ("Chép") button - it copies `/fix-issue <mã Intake>`, paste it into Claude Code and it runs. Or in the project's repo (which already has `CLAUDE.md` and `.claude/intake-project`), type `/fix-issue 7` (the GitLab/GitHub Issue number in that repo) or `/fix-issue SAV-26W41-001`. Claude Code will:

1. `get_project_context` → the project's context pack; if the band is **Insufficient** ("Chưa đủ"), stop immediately and tell you the missing items, without changing code. Then `get_intake` → read the reproduction steps, expected result, criteria, clarified questions, **Hints for the fixer** ("Gợi ý cho người sửa") (which you write on the detail page) and the work log (including the reason for "not right" last time).
2. Create branch `fix/<n>-…`, **write a failing test first** to reproduce; if it cannot be reproduced, write to the work log and stop.
3. Fix, run tests, commit `Closes #<n>`, push the branch.
4. `log_work` → one entry in the request's **Work log** ("Lịch sử xử lý"): cause, what changed, tests, branch, commit, how to verify, deploy steps, `worked_on`, `actual_minutes`, `deployed`, and `context_suggestions`: what the context pack is missing or got wrong that the agent ran into. This is the mandatory final step of `/fix-issue`, including work the CTO assigns directly outside Daily Planning; on error the agent must report that the Intake is not ready for acceptance. Suggestions appear in the **Suggestions for the pack** ("Gợi ý cho hồ sơ") block on the project page; you edit the file in the repo and then click "Added to the pack" ("Đã đưa vào hồ sơ") or "Skip" ("Bỏ qua"). The agent does not edit the pack itself.

Your part: read that entry on Intake, merge, deploy, then click **Verified, deployed** ("Đã kiểm, đã triển khai") - or **Not right** ("Chưa đúng") with a reason so the agent redoes it. The agent does not merge, does not deploy, does not close Issues; the Issue reaches the "has code trace" level when the read model reads commit `#n` at 06:45.

## 6. "Ready for agent" score

Each request has a score of 0–100 (badge above the title and in the list): **≥ 70 ready**, 40–69 needs more (open the box below the journey to see what is missing: reproduction steps, expected result, criteria, unanswered questions…), < 40 work for people (shooting video, taking photos, publishing…). The project's context pack (`docs/agent/CONTEXT.md`, Settings > Projects > Edit) decides 20 points for every request in the project: band Sufficient +20, Needs more +10, Insufficient 0, and the missing part says exactly which items; there is no longer a manual checkbox. Agents use `list_intakes` with `readiness: "READY"` to get exactly the work they can do.
