"""Export completed Codex benchmark archives for longevity-kg tools.skeleton.backfill."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.whole_system.codex_benchmark import write_json


def export(run: Path, destination: Path) -> dict:
    state = json.loads((run / "predictions.json").read_text(encoding="utf-8"))
    rows, missing = [], []
    for trial, prediction in state["predictions"]["system"].items():
        if not prediction.get("archive"):
            missing.append(trial)
            continue
        archive = run / prediction["archive"]
        raw = archive.read_bytes()
        saved = json.loads(raw)
        result = saved["pipeline"]
        if saved["schema_version"] != 1 or result["meta"].get("failures"):
            raise ValueError(f"unsupported or incomplete archive: {archive}")
        for item in result["items"]:
            item["card"] = item.get("card") or {}
            alternatives = {alt["id"]: alt for alt in item["card"].get("proposed_alternatives", [])}
            verification = item.get("verification")
            if verification:
                for key, alternative in item.get("v3_alternatives", {}).items():
                    claim = alternative.get("claim") or alternatives.get(key) or {"id": key}
                    verification["claims"].append({**alternative, "claim": claim})
        output = destination / f"{trial}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        write_json(output, {trial: result})
        rows.append({"unit": trial, "file": output.name, "archive": str(prediction["archive"]),
                     "archive_sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"schema_version": 1, "benchmark": state["manifest"], "files": rows,
                "without_archive": missing, "pending_system": sorted(set(state["manifest"]["ids"])
                                                                   - state["predictions"]["system"].keys())}
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    manifest = export(args.run, args.run / "kg-export")
    for field in ("files", "without_archive", "pending_system"):
        print(field, len(manifest[field]))


if __name__ == "__main__":
    main()
