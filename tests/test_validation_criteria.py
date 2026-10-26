"""The validation criteria file is well formed, its evidence exists, and the rendered table is up to date."""
import re
from pathlib import Path

from scripts import validation_table as vt


def test_every_test_has_the_required_fields_and_valid_values():
    spec = vt.load()
    ids = [t["id"] for t in spec["tests"]]
    assert len(ids) == len(set(ids))
    for t in spec["tests"]:
        assert t["level"] in spec["levels"] and t["status"] in vt.STATUS and t["declared"] in vt.DECLARED, t["id"]
        assert t["criterion"].strip() and t["name"].strip() and t["cls"].strip(), t["id"]
        assert t["id"].startswith(f"L{t['level']}."), t["id"]
        if t["status"] == "blocked":
            assert t.get("blocker"), t["id"]
        if t["status"] in ("pass", "fail", "inconclusive", "not_applied"):
            assert t.get("evidence"), f"{t['id']}: a measured status needs a source"


def test_a_criterion_written_after_the_result_is_never_a_pending_one():
    for t in vt.load()["tests"]:
        if t["status"] == "not_run":
            assert t["declared"] == "pending", t["id"]            # nothing was run, so nothing can be post hoc


def test_evidence_paths_exist():
    for t in vt.load()["tests"]:
        for part in (t.get("evidence") or "").split(";"):
            path = re.split(r" \(", part.strip())[0].strip()
            if path.startswith(("docs/", "tests/", "hyparena/", "scripts/", "specs/")):
                assert Path(path).exists(), f"{t['id']}: {path}"


def test_the_rendered_table_is_up_to_date():
    assert vt.OUT.read_text(encoding="utf-8") == vt.render(vt.load())
