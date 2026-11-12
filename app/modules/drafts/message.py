"""The message the AI reads for one draft, as blocks (ADR-0041).

The worker joins the blocks into one text. The prompt preview shows the same blocks one by one, with who each comes
from and what was cut, so what the owner sees is what the model gets.
"""
from __future__ import annotations

GROUP_NAMES = {
    "FNB": "F&B (quán ăn, cà phê, chuỗi): giờ cao điểm, đơn hàng, POS, phản hồi khách",
    "EDUCATION": "Tuyển sinh và đào tạo: mùa tuyển sinh, xử lý lead, tư vấn ngoài giờ",
    "RETAIL": "Bán lẻ: khuyến mãi, dữ liệu đơn hàng, tồn kho, khách quay lại",
    "SERVICE": "Doanh nghiệp dịch vụ: tiếp nhận yêu cầu, phân công, theo dõi trạng thái",
    "AGENCY": "Agency marketing: khoảng trống giữa tạo lead và xử lý lead",
    "CONSULTING": "Tư vấn doanh nghiệp: khoảng cách giữa quy trình trên tài liệu và hệ thống vận hành",
}

# What is kept of each part, so the idea always fits.
DNA_LIMIT = 40000
REFERENCE_LIMIT = 20000
CONTEXT_NAMES = {
    "REAL": "REAL (something the author did or saw)",
    "EXAMPLE": "EXAMPLE (made up to show a point; must be called an example)",
    "SOURCE": "SOURCE (taken from another source; cite it, never tell it as the author's experience)",
}
COMMERCIAL_NAMES = {"SPONSORED": "SPONSORED (paid by the maker of what is discussed)", "AFFILIATE": "AFFILIATE (the author earns from links)"}
NOTEBOOK_LIMIT = 8000
SAMPLE_LIMIT = 3000
SAMPLE_COUNT = 8
NOTE_LIMIT = 6000


def _cut(what: str, kept: int, total: int) -> dict[str, object]:
    return {"what": what, "kept": kept, "total": total}


def draft_blocks(source: dict[str, object]) -> list[dict[str, object]]:
    """Each block: a key, whose words they are, its lines, and what was left out of it.

    `trust` is CHOICE for what the person picked on the screen, AUTHOR for text the author wrote as their standard,
    DATA for what the system knows, and UNTRUSTED for text the model must never take instructions from.
    """
    voice = source["voice"]
    blocks: list[dict[str, object]] = []

    def add(key: str, trust: str, lines: list[str], cuts: list[dict[str, object]] | None = None) -> None:
        blocks.append({"key": key, "trust": trust, "lines": lines, "cuts": cuts or []})

    lines = [f"Channel: {source['channel']}"]
    if source.get("kind") == "OUTLINE":
        lines.append("Kind: OUTLINE")
    if source.get("group_context"):
        lines.append(f"Group: {GROUP_NAMES.get(str(source['group_context']), source['group_context'])}")
    if source.get("direction"):
        lines.append(f"Direction: {source['direction']}{' — ' + str(source['direction_note']) if source.get('direction_note') else ''}")
    for label, key in (("Goal", "goal"), ("Audience", "audience"), ("Pillar", "pillar")):
        if source.get(key):
            lines.append(f"{label}: {source[key]}")
    if source.get("context"):
        lines.append(f"Context: {CONTEXT_NAMES.get(str(source['context']), source['context'])}")
    if source.get("commercial"):
        lines.append(f"Commercial: {COMMERCIAL_NAMES.get(str(source['commercial']), source['commercial'])}")
    if source.get("trial"):
        lines.append("Trial: 80 to 120 words, to hear the voice only")
    add("choices", "CHOICE", lines)

    lines = ["Author"]
    for label, key in (("Positioning", "positioning"), ("Writes for", "audience"), ("Tone", "tone"), ("Avoid", "avoid")):
        if voice.get(key):
            lines.append(f"- {label}: {voice[key]}")
    if voice.get("pillars"):
        lines.append(f"- Content pillars: {'; '.join(voice['pillars'])}")
    add("author", "AUTHOR", lines)

    dna = str(source.get("master_dna") or voice.get("dna") or "").strip()
    if dna:
        add(
            "dna", "AUTHOR",
            ["Master brand document (written by the author; a shared core and its directions)", "--- master brand document ---", dna[:DNA_LIMIT], "--- end of master brand document ---"],
            [_cut("characters", DNA_LIMIT, len(dna))] if len(dna) > DNA_LIMIT else [],
        )

    references = [item for item in (source.get("references") or []) if isinstance(item, dict) and str(item.get("text") or "").strip()]
    if references:
        lines = ["Reference documents (written by the author; facts to check against, not the voice to write in)"]
        cuts = []
        for index, item in enumerate(references, start=1):
            text = str(item["text"]).strip()
            lines += [f"--- reference {index}: {str(item.get('title') or '')[:120]} ---", text[:REFERENCE_LIMIT], f"--- end of reference {index} ---"]
            if len(text) > REFERENCE_LIMIT:
                cuts.append(_cut(f"reference {index} characters", REFERENCE_LIMIT, len(text)))
        add("references", "AUTHOR", lines, cuts)

    notes = [note for note in (source.get("notes") or []) if note.get("text")]
    if notes:
        lines = ["Author's notebook (written by the author)", "--- notebook ---"]
        used, kept = 0, 0
        for note in notes:
            # What is true and what may be shown come first; the rest is dropped when the notebook is very long.
            used += len(note["text"])
            if used > NOTEBOOK_LIMIT:
                break
            lines.append(f"{note['kind']}: {note['text']}")
            kept += 1
        lines.append("--- end of notebook ---")
        add("notebook", "AUTHOR", lines, [_cut("notes", kept, len(notes))] if kept < len(notes) else [])

    if source.get("posted_titles"):
        add("published", "DATA", ["Already published"] + [f"- {title}" for title in source["posted_titles"]])

    samples = [sample for sample in (voice.get("samples") or []) if isinstance(sample, dict) and sample.get("text")]
    if samples:
        lines = ["Sample posts (style reference only)"]
        cuts = [_cut("samples", SAMPLE_COUNT, len(samples))] if len(samples) > SAMPLE_COUNT else []
        for index, sample in enumerate(samples[:SAMPLE_COUNT], start=1):
            text = str(sample["text"])
            lines += [f"--- sample {index} ({sample.get('channel', 'FACEBOOK')}) ---", text[:SAMPLE_LIMIT]]
            if len(text) > SAMPLE_LIMIT:
                cuts.append(_cut(f"sample {index} characters", SAMPLE_LIMIT, len(text)))
        lines.append("--- end of samples ---")
        add("samples", "UNTRUSTED", lines, cuts)

    if source.get("previous_text") and source.get("previous_kind") == "OUTLINE":
        add("outline", "AUTHOR", ["Outline to follow (read and kept by the author)", str(source["previous_text"])])
    elif source.get("previous_text") and source.get("previous_track"):
        add("previous", "DATA", [f"Draft to adapt (written for the other direction: {source['previous_track']}, channel {source.get('previous_channel') or '?'})", str(source["previous_text"])])
    elif source.get("previous_text"):
        add("previous", "DATA", [f"Draft to adapt (written for {source.get('previous_channel') or 'another channel'})", str(source["previous_text"])])

    if source.get("angle"):
        add("angle", "CHOICE", [f"Central question or angle to stress: {source['angle']}"])

    add("about", "DATA", ["What it is about", f"{source.get('title') or ''}".strip(), f"{source.get('summary') or ''}".strip()])

    if source.get("note"):
        note = str(source["note"])
        add("note", "UNTRUSTED", ["Idea note", note[:NOTE_LIMIT]], [_cut("characters", NOTE_LIMIT, len(note))] if len(note) > NOTE_LIMIT else [])
    return blocks


def build_draft_message(source: dict[str, object]) -> str:
    """One text for the model: what the post is for, who writes and how, then the idea."""
    return "\n\n".join("\n".join(block["lines"]).strip() for block in draft_blocks(source)).strip()
