"""Is this request ready to be handed to an agent? (FR-MCP-04)

A score from what the request already holds — what kind of work it is, whether it says how to reproduce and what
"done" looks like, whether questions are still open, how complete the project's context pack is — and the
reasons, so the CTO sees what is missing rather than a bare number. No AI call: the rules are plain and the same
every time, which is what a gate into a queue needs.
"""
from __future__ import annotations

READY = "READY"
NEEDS_WORK = "NEEDS_WORK"
HUMAN = "HUMAN"

TYPE_POINTS = {"BUG": 25, "TASK": 15, "SCOPE_CHANGE": 5, "UNCLEAR": 0}
# Work that is done with hands, a camera or a console, not in a repo.
NON_CODE_HINTS = (
    "quay video", "chụp ảnh", "ảnh minh họa", "publish", "phát hành lên", "app store", "play store", "thu hồi", "api key",
    "test tay", "kiểm tra app", "họp với", "viết bài", "cài đặt server", "deploy lên", "mua ", "thanh toán cho", "gửi mail cho",
)


def agent_readiness(
    *, item_type: str | None, title: str | None, summary: str | None, details: dict | None, fix_hints: str | None,
    project_context: dict | None = None,
) -> dict[str, object]:
    """`project_context` is the project's pack as scored (FR-CTX-02): `band` FULL, PARTIAL or MISSING and `missing` sections."""
    details = details if isinstance(details, dict) else {}
    reasons: list[str] = []
    missing: list[str] = []
    score = 0

    kind = str(item_type or "UNCLEAR").upper()
    points = TYPE_POINTS.get(kind, 0)
    score += points
    if kind == "UNCLEAR":
        missing.append("loại việc chưa rõ")
    else:
        reasons.append(f"loại việc {kind.lower()} (+{points})")

    if details.get("steps"):
        score += 20
        reasons.append("có bước tái hiện (+20)")
    else:
        missing.append("bước tái hiện")
    if (details.get("expected") or "").strip():
        score += 15
        reasons.append("có kết quả mong đợi (+15)")
    else:
        missing.append("kết quả mong đợi")
    if details.get("acceptance"):
        score += 15
        reasons.append("có tiêu chí nghiệm thu (+15)")
    else:
        missing.append("tiêu chí nghiệm thu")
    if (details.get("where") or "").strip():
        score += 5
        reasons.append("biết ở đâu trong sản phẩm (+5)")

    settled = {
        str(row.get("question") or "").strip()
        for row in details.get("clarifications") or [] if isinstance(row, dict) and (row.get("answer") or row.get("skipped"))
    }
    open_questions = [q for q in details.get("open_questions") or [] if str(q).strip() and str(q).strip() not in settled]
    if open_questions:
        penalty = min(30, 10 * len(open_questions))
        score -= penalty
        missing.append(f"{len(open_questions)} câu hỏi chưa trả lời (−{penalty})")

    if (fix_hints or "").strip():
        score += 5
        reasons.append("có gợi ý cho người sửa (+5)")
    pack = project_context if isinstance(project_context, dict) else {}
    band = str(pack.get("band") or "MISSING").upper()
    if band == "FULL":
        score += 20
        reasons.append("hồ sơ ngữ cảnh dự án đủ (+20)")
    elif band == "PARTIAL":
        score += 10
        reasons.append("hồ sơ ngữ cảnh dự án cần bổ sung (+10)")
    else:
        gaps = [str(row) for row in pack.get("missing") or [] if str(row).strip()]
        missing.append("hồ sơ ngữ cảnh dự án chưa đủ" + (f" (thiếu {', '.join(gaps)})" if gaps else " (chưa có docs/agent/CONTEXT.md)"))

    text = f"{title or ''} {summary or ''}".lower()
    hint = next((word for word in NON_CODE_HINTS if word in text), None)
    if hint:
        score = min(score, 30)
        missing.append(f"có vẻ là việc không làm bằng code (\"{hint.strip()}\")")

    score = max(0, min(100, score))
    band = READY if score >= 70 else NEEDS_WORK if score >= 40 else HUMAN
    return {"score": score, "band": band, "reasons": reasons, "missing": missing}
