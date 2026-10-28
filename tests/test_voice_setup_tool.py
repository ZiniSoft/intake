"""The setup tool loads a voice bundle into the private space; samples change only when the bundle gives them (ADR-0042)."""
import json

from app.tools.setup_private_voice import load_bundle
from tests.test_private_space import VOICE, _space, cto

WATCH = "/api/v1/private-space"


def test_a_bundle_fills_the_voice_keeps_samples_and_loads_again_cleanly(tmp_path) -> None:
    _space()
    cto.put(f"{WATCH}/voice?track=business", json=VOICE)  # one sample the owner pasted
    (tmp_path / "master.md").write_text("MASTER-GOI-THU: lõi và hai hướng.", encoding="utf-8")
    (tmp_path / "company.md").write_text("THAM-CHIEU-GOI-THU: dữ kiện công ty.", encoding="utf-8")
    (tmp_path / "bai-mau").mkdir()
    (tmp_path / "bai-mau" / "ky-thuat-1.md").write_text("BAI-MAU-GOI-THU: mình kể một việc nhỏ, đủ hai mươi ký tự.", encoding="utf-8")
    bundle = tmp_path / "setup.json"
    bundle.write_text(json.dumps({
        "master_dna_file": "master.md",
        "tracks": {
            "business": {
                "name": "Kinh doanh", "direction_note": "Hướng Kinh doanh (Lớp 2)", "positioning": "DINH-VI-GOI", "pillars": ["Trụ gói một", "Trụ gói hai"],
                "default_channel": "FACEBOOK", "references": [{"title": "Công ty", "file": "company.md"}],
                "notes": [{"kind": "FACT", "text": "  DU-KIEN-GOI   mười lăm năm. "}, {"kind": "DECISION", "text": "QUYET-DINH-GOI"}],
                "rhythm": [{"weekday": 2, "time": "08:00", "channel": "FACEBOOK", "pillar": None}],
            },
            "technical": {"name": "Kỹ thuật", "default_channel": "BLOG", "pillars": ["Trụ kỹ thuật"], "notes": [], "samples": [{"channel": "THREADS", "file": "bai-mau/ky-thuat-1.md"}], "rhythm": [{"weekday": 4, "channel": "BLOG"}, {"weekday": 6, "time": "09:00", "channel": "VIDEO_SCRIPT"}]},
        },
    }, ensure_ascii=False), encoding="utf-8")
    try:
        report = load_bundle(bundle)
        assert report["master_dna_chars"] > 0 and report["business"]["notes_added"] == 2 and report["business"]["samples"] == 1 and not report["business"]["samples_replaced"] and report["technical"]["samples_replaced"] and report["technical"]["rhythm"] == 2

        data = cto.get(WATCH).json()["data"]
        assert data["master_dna"] == "MASTER-GOI-THU: lõi và hai hướng."
        business = data["voices"]["business"]
        assert business["positioning"] == "DINH-VI-GOI" and business["pillars"] == ["Trụ gói một", "Trụ gói hai"] and business["direction_note"] == "Hướng Kinh doanh (Lớp 2)"
        assert len(business["samples"]) == 1, "what the owner pasted stays when the bundle says nothing about samples"
        assert data["voices"]["technical"]["samples"] == [{"channel": "THREADS", "text": "BAI-MAU-GOI-THU: mình kể một việc nhỏ, đủ hai mươi ký tự."}], "samples given by the bundle replace what was there"
        assert business["references"] == [{"title": "Công ty", "text": "THAM-CHIEU-GOI-THU: dữ kiện công ty."}]
        assert business["tone"] == VOICE["tone"], "a field the bundle leaves out keeps its value"
        assert data["voices"]["technical"]["default_channel"] == "BLOG"
        notes = cto.get(f"{WATCH}/notes?track=business").json()["data"]
        assert [(note["kind"], note["text"]) for note in notes if "GOI" in note["text"]] == [("FACT", "DU-KIEN-GOI mười lăm năm."), ("DECISION", "QUYET-DINH-GOI")]
        rhythm = cto.get(f"{WATCH}/plan").json()["data"]["rhythm"]
        assert len(rhythm["business"]) == 1 and [slot["channel"] for slot in rhythm["technical"]] == ["BLOG", "VIDEO_SCRIPT"]

        # Loaded again: nothing doubled.
        again = load_bundle(bundle)
        assert again["business"]["notes_added"] == 0
        assert len([note for note in cto.get(f"{WATCH}/notes?track=business").json()["data"] if "GOI" in note["text"]]) == 2

        # A document outside the bundle's folder is refused.
        (tmp_path / "bad.json").write_text(json.dumps({"master_dna_file": "../outside.md"}), encoding="utf-8")
        try:
            load_bundle(tmp_path / "bad.json")
        except SystemExit as stopped:
            assert "next to the bundle" in str(stopped)
        else:
            raise AssertionError("a path outside the bundle folder must be refused")
    finally:
        for note in cto.get(f"{WATCH}/notes?track=business").json()["data"]:
            if "GOI" in note["text"]:
                cto.delete(f"{WATCH}/notes/{note['id']}")
        for track in ("business", "technical"):
            cto.put(f"{WATCH}/plan/rhythm?track={track}", json={"slots": []})
        cto.put(f"{WATCH}/master-dna", json={"text": ""})
        cto.put(f"{WATCH}/voice?track=business", json=VOICE)
        cto.put(f"{WATCH}/voice?track=technical", json={**VOICE, "samples": [], "pillars": []})
