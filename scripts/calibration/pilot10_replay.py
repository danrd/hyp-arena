"""Replay frozen calibration cases without network access.

The manifest embeds the selected source cases and archived scores. Optional
compound and target snapshots are maps keyed by normalized compound name and
ChEMBL target ID respectively. A null compound entry means a recorded negative
lookup. Missing entries are reported and make affected scoring conditional.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pilot10_mutations import _load_card_and_verifications, run_mutations_on_case

from hyparena.scoring import rules_v32, v3_extra
from hyparena.tools import compounds


class NetworkAttempt(BaseException):
    """Escape scoring fallbacks that intentionally catch lookup exceptions."""


class FrozenLookups:
    def __init__(self, snapshot: dict):
        self.compounds = snapshot["compounds"]
        self.targets = snapshot["target_names"]
        self.missing = set()

    def lookup(self, name: str, *, raise_on_error: bool = False):
        key = compounds.key(compounds.resolve_alias(name))
        if not key:
            return None
        if key not in self.compounds:
            self.missing.add(f"compound:{key}")
            return None
        value = self.compounds[key]
        return compounds.Compound(**value) if value is not None else None

    def target_names(self, target_id: str) -> list[str]:
        if target_id not in self.targets:
            self.missing.add(f"target:{target_id}")
            return []
        return list(self.targets[target_id])


def sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def comparison(saved, computed, *, conditional=False) -> dict:
    if computed is None:
        status = "snapshot_missing"
    elif computed != saved:
        status = "different"
    else:
        status = "matches"
    return {"saved": saved, "replay": computed, "status": status, "conditional": conditional}


def replay_case(entry: dict, lookups: FrozenLookups, *, strict_candidate: bool = False) -> dict:
    source = entry["case"]
    saved = entry["saved"]
    for field in ("case", "saved"):
        if sha256(entry[field]) != entry[f"{field}_sha256"]:
            raise ValueError(f"{entry['id']}: {field} checksum mismatch")
    if source["id"] != entry["original_id"]:
        raise ValueError(f"{entry['id']}: source case ID mismatch")
    card, verifications, alternatives = _load_card_and_verifications(source)
    lookups.missing.clear()
    # Same options as calculate.py in the released evaluation kit.
    observed = rules_v32.evaluate(card, verifications, alternatives, v36=True).as_dict()
    original_missing = sorted(lookups.missing)
    frozen = next(
        (part for part in (saved.get("feasibility_breakdown") or {}).get("parts", [])
         if part["key"] == "readiness"),
        None,
    )
    readiness = None
    if frozen is not None:
        readiness = frozen["score"] if frozen["known"] else None
        with patch.object(v3_extra, "readiness_assessment", return_value=(readiness, frozen["value"])):
            feasibility = v3_extra.feasibility(card)
    else:
        feasibility = None
    # The legacy mutation harness uses its own operational feasibility proxy.
    lookups.missing.clear()
    mutations = run_mutations_on_case(source, strict_candidate=strict_candidate)
    mutation_missing = sorted(lookups.missing)
    return {
        "id": entry["id"],
        "pool": entry["pool"],
        "original_id": entry["original_id"],
        "source_method": entry["source_method"],
        "cutoff": entry["cutoff"],
        "case_sha256": entry["case_sha256"],
        "saved_sha256": entry["saved_sha256"],
        "comparison": {
            metric: comparison(saved["evaluation"][metric], observed[metric], conditional=bool(original_missing))
            for metric in ("P", "I", "chain_state")
        } | {"feasibility": comparison(saved["feasibility"], feasibility)},
        "readiness_snapshot": (
            {"score": readiness, "status": frozen["value"], "origin": "archived_feasibility_breakdown"}
            if frozen is not None else None
        ),
        "missing_original_lookups": original_missing,
        "missing_mutation_lookups": mutation_missing,
        "diagnostic_mutations": mutations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--ids", nargs="+", help="Pilot IDs, e.g. C03")
    parser.add_argument("--strict-candidate", action="store_true", help="Run strict candidate checks on M1, M2, and M4.")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["version"] != 1:
        parser.error("unsupported manifest version")
    entries = manifest["cases"]
    by_id = {entry["id"]: entry for entry in entries}
    if len(by_id) != len(entries):
        parser.error("duplicate case ID")
    unknown = set(args.ids or ()) - by_id.keys()
    if unknown:
        parser.error("unknown pilot IDs: " + ", ".join(sorted(unknown)))

    current = "initialization"

    def forbid_network(event, event_args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.gethostbyname"}:
            raise NetworkAttempt(f"{current}: blocked network call {event}: {event_args!r}")

    # Install only in this CLI process. The hook also covers any future HTTP client.
    sys.addaudithook(forbid_network)
    lookups = FrozenLookups(manifest["lookup_snapshot"])
    out = []
    try:
        with patch.object(compounds, "lookup", lookups.lookup), patch.object(compounds, "target_names", lookups.target_names):
            for entry in entries:
                if args.ids and entry["id"] not in args.ids:
                    continue
                current = f"{entry['id']} ({entry['original_id']})"
                out.append(replay_case(entry, lookups, strict_candidate=args.strict_candidate))
    except NetworkAttempt as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps({
        "manifest_sha256": sha256(manifest),
        "network": "blocked",
        "source_pools": manifest["source_pools"],
        "separate_checks": manifest["separate_checks"],
        "cases": out,
    }, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
