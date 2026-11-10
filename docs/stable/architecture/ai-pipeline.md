English | [Tiếng Việt](ai-pipeline.vi.md)

# AI ingestion pipeline architecture

_Target + runtime pipeline 1.2 | Updated 2026-10-04_

## 1. Provider policy

Primary endpoint: `https://api-sg.umodelverse.ai/v1`.

| Purpose | UModelVerse model |
|---|---|
| Text normalization | `deepseek-v4.1-flash` |
| Reprocess/advanced analysis | `deepseek-v4-pro-0813` |
| Image/vision | `deepseek-v4-flash-vision-exp` (not used in the pilot, ADR-0015) |

The controlled pilot only calls UModelVerse per ADR-0011; the pilot environment does not configure an OpenRouter key. After the pilot, if fallback is re-enabled by a new ADR, OpenRouter must enable ZDR, deny data collection, and disable internal fallback. Model IDs must be in a server-side allowlist.

## 2. Stage contract

| Stage | Input | Output | Terminal/error behavior |
|---|---|---|---|
| `INGEST` | API transaction | source/object/outbox | rollback if persistence fails |
| `SCAN` | quarantine object ID | clean/rejected | check the file per ADR-0015 (magic bytes, size, page count, encrypted PDF/embedded files), no malware scan; stop the file if it fails |
| `EXTRACT_TEXT` | source/PDF | canonical text + evidence | OCR runs on a separate machine on the same LAN in an isolated container, with a timeout and resource limits; partial per page |
| `VISION` | clean image/page | description + evidence | Does not run in the pilot: images/PDFs are only OCR'd internally and only the OCR'd text is sent to UModelVerse (ADR-0015) |
| `EVIDENCE` | branch results | complete/partial bundle | never drop errors silently |
| `NORMALIZE` | text/evidence refs | strict JSON extraction | provider chain |
| `VALIDATE` | extraction | accepted/warnings/errors | deterministic, fail closed |
| `MATERIALIZE` | accepted result | update intake review fields | optimistic version |

## 3. Failure matrix in the pilot

| Primary outcome | Action |
|---|---|
| Success + valid schema | Persist UModelVerse result |
| Timeout/transport/429/5xx | Retry up to `AI_TASK_MAX_RETRIES`; when exhausted, move to `FAILED`. No fallback in the pilot |
| 2xx but invalid JSON/schema | Retry within the same budget; when exhausted, move to `FAILED` |
| 400/401/403 | Fail permanent |
| Model outside the allowlist | Fail permanent before any network call |

## 4. Retry and terminal state

- The outbox only claims `NEW`, `RETRY`, or `PUBLISHING` whose lease has expired.
- Broker failures use exponential backoff with at most `OUTBOX_MAX_ATTEMPTS` (default 8); when the budget is exhausted, move to `DEAD`.
- Processing runs use `AI_TASK_MAX_RETRIES` (default 3). A lease that expires below the limit moves to `RETRY`; at the limit it moves to `FAILED` and the Intake moves to `PROCESSING_FAILED`.
- An event payload that is not a JSON object moves to `DEAD/INVALID_EVENT_PAYLOAD`; no silent success and no infinite retry.
- Each normalization job has a unique `job_key`; completing a run that is already `SUCCEEDED` is idempotent.

## 5. Required output schema

This is the full target schema. Runtime 1.2 currently requires only five fields: `item_type`, `suggested_priority`, `proposed_route`, `normalized_title`, `normalized_summary`; the rest stays `PARTIAL` in readiness and must not be described as materialized.

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

The AI must not add facts that have no evidence. A deterministic validator checks enums, length, priority rules, BUG evidence, and route prerequisites.

## 6. Data minimization

- Decrypt raw data only in the memory of the worker that needs it.
- Do not write raw prompts, raw chat, or base64 files to logs/outbox/Redis.
- Remove unnecessary metadata before a cloud call.
- Original files (images/PDFs) never leave the internal network; cloud calls contain only source text and OCR'd text.
- Each call records a provider/model/policy/prompt/schema trace, never secrets.
- Retention purge must delete both the source ciphertext and the corresponding SeaweedFS object.

## 6.1 Intake normalization: input and prompt (from 2026-10-05)

- **The input is always the original content** of the Intake, decrypted, even when "Reanalyze" ("Phân tích lại") is clicked. Previously a reanalysis read the summary the AI wrote in the previous run, so details were gradually lost. The summary is used only when the original content has been purged by retention; `run_metadata.input_origin` records `RAW` or `SUMMARY`.
- **The message sent to the model** contains a few context lines (project name and type, channel, available routes) followed by the original content inside `<source>...</source>`; any closing-tag string appearing in the content is neutralized.
- **Prompt `intake-worker-v4`** (v3 the same day, v4 after the first measurement) defines each type, each priority level (per the table in functional-spec section 6), and each route (per the diagram in flows section 2), requires using only facts present in the source, writes the title and summary in the source's language, and includes three examples. The prompt version is stored in `ai_extractions.prompt_version`.
- **Routes per project.** The model may only choose among the routes the project has linked; `WORK` is always available, while GitLab/GitHub are available only when the project has a delivery target. An unavailable route is adjusted in a controlled way and recorded in `run_metadata.route_adjusted`.
- Text in attached images and PDFs still does not reach the model because OCR has not been deployed (ADR-0015).

See section 6.2 for measurement results. The model does not give identical results across runs even with `temperature = 0`, so every comparison must be run repeatedly.

## 6.2 Measuring Intake normalization prompt quality

The command `python -m app.tools.evaluate_intake_prompt`, run in the `ai-worker` container (the only place with the provider key), writes nothing to the database:

- **Synthetic cases:** 26 requests (the original 20 plus 6 `hold-*` cases written after tuning v4, not used for tuning) in `app/tools/intake_eval_cases.json`, containing no customer data. The expected answers were written by the prompt author; the CTO needs to review them before trusting the scores.
- **Real cases (`--real N`):** Intakes the CTO has approved. The expected answer is the priority and route the CTO chose (request type is not scored because the CTO does not decide it). Content is read from the database at run time and sent to the provider as in normal processing; nothing is written to a file, and the report prints only Intake IDs. This set grows as more Intakes are approved.
- `--repeat K` asks each case K times to measure stability; `--prompt-file` scores a different prompt for comparison.

Measurement on 2026-10-05, model `deepseek-v4.1-flash`, 21 cases (20 synthetic, 1 real), 3 runs per case:

| Criterion | Old prompt | `intake-worker-v3` |
|---|---|---|
| Correct type | 51/60 | 55/60 |
| Correct priority | 45/63 | 58/63 |
| Correct route | 50/63 | 60/63 |
| Title in source language | 59/63 | 60/63 |
| Cases stable across 3 runs | 11/21 | 18/21 |

After that measurement the prompt was tuned into `intake-worker-v4`: a normal feature request is P2 (matching the CTO's decision on the only real Intake), data loss is always P0, customers receiving wrong information is P1, slow behavior is still a bug, an idea proposing new work is a feature. Re-measured on 27 cases, 3 runs each: correct type 78/78, priority 79/81, route 80/81, title in correct language 78/81, stable 25/27. The 6 held-out cases alone (18 answers) were off by only 1 answer on route. The expected answer of one synthetic case (`syn-03`) was changed from P3 to P2 per the CTO's real decision, so the two measurements are not directly comparable on that case.

Limits of the measurement: v4 was tuned on the same original 20 cases, so scores there are optimistic; the synthetic answers were written by the prompt author; there is only one approved real Intake; the old prompt was scored with the new message format (with context lines and the route list), so its route score is higher than it actually was before.

At the end of 2026-10-07 the prompt is `intake-worker-v8`: adds a rule that questions must converge after the team has answered one round (measured: type 77/77, priority 73/77, route 76/77, stable 24/26, one provider error run). Just before that was `intake-worker-v7` (ADR-0032; v6 added rules for subtasks, split suggestions, and how to read a split request; v7 added how to use the team's answers to the questions the AI raised; v7 measured: type 78/78, priority 74/78, route 78/78, stable 25/26). The v5 version just before that (ADR-0032): the message adds the project description, glossary, and open Issues; the result adds a details section (where, steps, expected result, subtasks, acceptance criteria, clarifying questions, possibly duplicate Issues). Measured on 26 synthetic cases, 3 runs each: correct type 77/78, priority 76/78, route 76/78, title in correct language 75/78, stable 23/26. The details section does not yet have a scored case set.

## 6A. AI calls outside Intake normalization

| Call | Input | Output | Notes |
|---|---|---|---|
| Re-reading a malformed Daily Report | Email subject and report body, with the signature after the `--` line removed (ADR-0019) | Task list per schema, allowlisted statuses | At most 5 emails per scan (minute 10 and 40), timeout `AI_REPORT_TIMEOUT_SECONDS`; the result is not used for Planning until the CTO confirms |
| Meeting note | Transcript by speaker, names of active projects, the meeting's project | Summary, decisions, request/bug/scope change items, action items, questions, risks | At most 3 attempts; audio never goes to UModelVerse; a project guessed by the AI is ignored when the meeting has a project |

Speech-to-text from audio is not an AI call of this pipeline: it is done by `meeting-gateway` calling ElevenLabs (ADR-0018).

## 7. Current implementation gap - baseline 1.2

Text normalization, provider chain, outbox/Celery, and JSONB persistence have been `VERIFIED` by a synthetic runtime smoke on two test projects. Gate C verified that a Redis outage and worker lease recovery do not lose data or create duplicates. OpenRouter fallback has a deterministic contract test, stays `CODE_COMPLETE`, and is outside the pilot scope per ADR-0011. The Scan/OCR/vision/evidence pipeline is not fully implemented and continues to be recorded as `NOT_STARTED` or `PARTIAL` in the readiness matrix.
