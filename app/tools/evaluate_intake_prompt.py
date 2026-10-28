"""Measure the Intake normalization prompt against labelled cases.

Run it in the AI worker container, the only place that holds the provider key:

    docker compose run --rm --no-deps ai-worker python -m app.tools.evaluate_intake_prompt

Two kinds of case:
- synthetic ones from intake_eval_cases.json, which contain no customer data;
- real Intakes the CTO has approved (--real N). Their label is the CTO's own priority and route. Their text
  is read from the database at run time and sent to the provider, exactly as normal processing does;
  it is never written to a file and the report only shows their public IDs.

Nothing is written to the database.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.services.ai_processor import (
    INTAKE_PROMPT_VERSION,
    SYSTEM_PROMPT,
    AIExtraction,
    AIProviderError,
    _parse_model,
    available_routes,
    build_intake_message,
    fit_route,
    umodelverse_adapter,
)

CASES_FILE = Path(__file__).with_name("intake_eval_cases.json")
FIELDS = ("item_type", "priority", "route")


@dataclass
class Case:
    id: str
    message: str
    routes: list[str]
    expected: dict[str, str]
    source_is_vietnamese: bool = True
    results: list[dict[str, str] | None] = field(default_factory=list)


def load_synthetic(path: Path = CASES_FILE) -> list[Case]:
    cases = []
    for row in json.loads(path.read_text(encoding="utf-8"))["cases"]:
        routes = available_routes(has_delivery=bool(row["has_delivery"]))
        if row["expected"]["route"] not in routes:
            raise ValueError(f"{row['id']}: expected route is not available for that project")
        cases.append(Case(
            id=row["id"], routes=routes, expected=dict(row["expected"]), source_is_vietnamese=_is_vietnamese(row["text"]),
            message=build_intake_message(row["text"], project_name="Dự án mẫu", project_kind=row["project_kind"], channel=row.get("channel", "ZALO"), routes=routes),
        ))
    return cases


def load_real(limit: int) -> list[Case]:
    """Intakes the CTO approved, newest first. The label is the CTO's decision; item type is not one of them."""
    from app.db import get_session
    from app.models import ApprovalSnapshot, IntakeItem
    from app.services.intake_service import intake_store

    cases: list[Case] = []
    with get_session() as session:
        rows = session.execute(
            select(ApprovalSnapshot, IntakeItem).join(IntakeItem, IntakeItem.id == ApprovalSnapshot.intake_id)
            .where(ApprovalSnapshot.invalidated_at.is_(None)).order_by(ApprovalSnapshot.created_at.desc())
        ).all()
    seen: set[str] = set()
    for snapshot, item in rows:
        if str(item.id) in seen or len(cases) >= limit:
            continue
        seen.add(str(item.id))
        source = intake_store.normalization_source(str(item.id))
        payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
        priority = str(payload.get("approved_priority") or "")
        if source is None or source["origin"] != "RAW" or not priority:
            continue
        routes = available_routes(has_delivery=bool(source["has_delivery"]))
        # GitLab and GitHub are the same choice for the model: "the delivery tracker".
        route = "GITLAB" if snapshot.approved_route in ("GITLAB", "GITHUB") else str(snapshot.approved_route)
        cases.append(Case(
            id=item.public_id, routes=routes, expected={"priority": priority, "route": route},
            source_is_vietnamese=_is_vietnamese(str(source["text"])),
            message=build_intake_message(str(source["text"]), project_name=source["project_name"], project_kind=source["project_kind"], channel=source["channel"], routes=routes),
        ))
    return cases


def _is_vietnamese(text: str) -> bool:
    return any(char in text.lower() for char in "ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ")


async def _ask(prompt: str, case: Case) -> dict[str, str] | None:
    try:
        response = await umodelverse_adapter._complete(case.message, prompt)
        result = _parse_model(response, "UMODELVERSE", AIExtraction)
    except AIProviderError:
        return None
    return {
        "item_type": result.item_type, "priority": result.suggested_priority,
        "route": fit_route(result.proposed_route, case.routes), "title": result.normalized_title,
    }


def score(cases: list[Case]) -> dict[str, object]:
    """Accuracy per field over every answer, how often repeated runs agree, and language of the title."""
    correct = {name: 0 for name in FIELDS}
    asked = {name: 0 for name in FIELDS}
    failures = answers = stable = repeated = language_ok = language_checked = 0
    for case in cases:
        got = [result for result in case.results if result is not None]
        failures += len(case.results) - len(got)
        answers += len(got)
        for result in got:
            for name in FIELDS:
                if name in case.expected:
                    asked[name] += 1
                    correct[name] += result[name] == case.expected[name]
            language_checked += 1
            language_ok += _is_vietnamese(result["title"]) == case.source_is_vietnamese
        if len(got) > 1:
            repeated += 1
            stable += len({tuple(result[name] for name in FIELDS) for result in got}) == 1
    return {
        "cases": len(cases), "answers": answers, "provider_failures": failures,
        **{f"{name}_correct": f"{correct[name]}/{asked[name]}" for name in FIELDS},
        "title_in_source_language": f"{language_ok}/{language_checked}",
        "stable_cases": f"{stable}/{repeated}" if repeated else "not measured (use --repeat)",
    }


async def run(cases: list[Case], prompt: str, repeat: int, concurrency: int = 4) -> None:
    limit = asyncio.Semaphore(concurrency)

    async def ask(case: Case) -> dict[str, str] | None:
        async with limit:
            return await _ask(prompt, case)

    answers = await asyncio.gather(*(ask(case) for case in cases for _ in range(repeat)))
    for index, case in enumerate(cases):
        case.results = list(answers[index * repeat:(index + 1) * repeat])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--real", type=int, default=0, metavar="N", help="also evaluate up to N approved real Intakes (their text is sent to the provider)")
    parser.add_argument("--no-synthetic", action="store_true", help="skip the synthetic cases")
    parser.add_argument("--repeat", type=int, default=1, help="ask each case this many times to measure stability")
    parser.add_argument("--prompt-file", type=Path, help="evaluate the prompt in this file instead of the built-in one")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cases = ([] if args.no_synthetic else load_synthetic()) + (load_real(args.real) if args.real > 0 else [])
    if not cases:
        print("No cases to evaluate.")
        return 1
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else SYSTEM_PROMPT
    asyncio.run(run(cases, prompt, max(args.repeat, 1)))

    for case in cases:
        for result in case.results:
            if result is None:
                print(f"{case.id}: provider failure")
                continue
            wrong = [f"{name} {result[name]} (expected {case.expected[name]})" for name in FIELDS if name in case.expected and result[name] != case.expected[name]]
            if wrong:
                print(f"{case.id}: " + "; ".join(wrong))
    summary = {
        "prompt": str(args.prompt_file) if args.prompt_file else INTAKE_PROMPT_VERSION,
        "model": umodelverse_adapter.describe("normalize")[1], **score(cases),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
