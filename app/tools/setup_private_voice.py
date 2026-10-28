"""Load the private space's voice from a setup bundle: master document, directions, references, notebook, rhythm.

The bundle is a JSON file kept outside the repository, next to the documents it points at:

    {
      "master_dna_file": "DNA-Ca-Nhan.md",
      "tracks": {
        "business": {
          "name": "Kinh doanh", "direction_note": "...", "positioning": "...", "audience": "...",
          "pillars": ["..."], "tone": "...", "avoid": "...", "default_channel": "FACEBOOK",
          "references": [{"title": "DNA Acme 2.2", "file": "DNA-Acme.md"}],
          "notes": [{"kind": "FACT", "text": "..."}],
          "samples": [{"channel": "FACEBOOK", "file": "bai-mau/kinh-doanh-1.md"}],
          "rhythm": [{"weekday": 2, "time": "08:00", "channel": "FACEBOOK", "pillar": null}]
        },
        "technical": {...}
      }
    }

File paths are relative to the bundle. Samples are replaced only when the track gives "samples" (at most 8, each 20 to
4000 characters); without it, what the owner pasted stays. Notes already in the notebook are not added twice, so the
bundle can be loaded again after an edit.

Run inside the API container, with the bundle's folder mounted read-only:

    docker compose run --rm -T -v "<folder>:/bundle:ro" api python -m app.tools.setup_private_voice /bundle/intake-voice-setup.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.db import get_session
from app.modules.content_plan.service import content_plan_service
from app.modules.private_space.service import MASTER_DNA_LIMIT, NOTE_KINDS, TRACKS, PrivateSpaceService, private_space_service, voices_of

ACTOR = "setup-tool"
VOICE_FIELDS = ("name", "direction_note", "positioning", "audience", "pillars", "tone", "avoid", "default_channel")
# Samples are social posts; the long channels have no sample form.
SAMPLE_CHANNELS = ("FACEBOOK", "LINKEDIN", "THREADS")


def _read(base: Path, name: str, limit: int) -> str:
    path = (base / name).resolve()
    if base.resolve() not in path.parents and path != base.resolve():
        raise SystemExit(f"{name}: a document must sit next to the bundle")
    text = path.read_text(encoding="utf-8")
    if len(text) > limit:
        raise SystemExit(f"{name}: {len(text)} characters, more than the {limit} the field holds")
    return text


def load_bundle(path: Path, actor: str = ACTOR) -> dict[str, object]:
    base = path.parent
    bundle = json.loads(path.read_text(encoding="utf-8"))
    report: dict[str, object] = {}
    space = private_space_service.create(actor)
    report["project"] = space["project"]["code"]

    if bundle.get("master_dna_file"):
        text = _read(base, str(bundle["master_dna_file"]), MASTER_DNA_LIMIT)
        private_space_service.save_master_dna(text, actor)
        report["master_dna_chars"] = len(text)

    for track, given in (bundle.get("tracks") or {}).items():
        if track not in TRACKS:
            raise SystemExit(f"{track}: unknown track; use one of {', '.join(TRACKS)}")
        with get_session() as session:
            project = private_space_service._project(session)
            current = voices_of(project.project_settings)[track]
            held = {(note["kind"], note["text"]) for note in PrivateSpaceService.notes_for(session, project.id, track)}
        voice = {**current, **{key: given[key] for key in VOICE_FIELDS if key in given}}
        if "references" in given:
            voice["references"] = [
                {"title": str(item.get("title") or ""), "text": _read(base, str(item["file"]), 20000) if item.get("file") else str(item.get("text") or "")}
                for item in given["references"]
            ]
        if "samples" in given:
            voice["samples"] = []
            for item in given["samples"]:
                channel = str(item.get("channel") or "FACEBOOK")
                if channel not in SAMPLE_CHANNELS:
                    raise SystemExit(f"{track}: sample channel {channel!r} is not one of {', '.join(SAMPLE_CHANNELS)}")
                text = (_read(base, str(item["file"]), 4000) if item.get("file") else str(item.get("text") or "")).strip()
                if len(text) < 20:
                    raise SystemExit(f"{track}: a sample needs at least 20 characters")
                voice["samples"].append({"channel": channel, "text": text})
            if len(voice["samples"]) > 8:
                raise SystemExit(f"{track}: at most 8 samples")
        private_space_service.save_voice(voice, actor, track)
        added = 0
        for note in given.get("notes") or []:
            kind, text = str(note.get("kind") or ""), " ".join(str(note.get("text") or "").split())
            if kind not in NOTE_KINDS:
                raise SystemExit(f"{track}: note kind {kind!r} is not one of {', '.join(NOTE_KINDS)}")
            if (kind, text) in held:
                continue
            private_space_service.add_note(track, kind, text, actor)
            added += 1
        if "rhythm" in given:
            content_plan_service.save_rhythm(track, list(given["rhythm"]), actor)
        report[track] = {
            "pillars": len(voice.get("pillars") or []), "references": len(voice.get("references") or []),
            "samples": len(voice.get("samples") or []), "samples_replaced": "samples" in given, "notes_added": added, "rhythm": len(given.get("rhythm") or []) if "rhythm" in given else None,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle", help="path to the setup bundle (JSON)")
    args = parser.parse_args()
    report = load_bundle(Path(args.bundle))
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
