import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_units_match_spec():
    spec = yaml.safe_load((ROOT / "specs/benchmark-v1.yaml").read_text())
    data = (ROOT / spec["units"]["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == spec["units"]["sha256"]
    u = json.loads(data)["units"]
    c = spec["units"]["counts"]
    assert len(u) == c["all"] and sum(x["label"] for x in u) == c["positive"]
    assert sum(x["b2_clean"] for x in u) == c["b2_clean"] and len({x["id"] for x in u}) == len(u)
