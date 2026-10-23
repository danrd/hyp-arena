"""A4: a spec fixed before the run, its hash in the run's meta, checked against git (no model calls, no network)."""
import inspect
from pathlib import Path
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from hyparena import backtest, prespec, site
from hyparena.card import evolve, pipeline, verifier
from hyparena.tools import pubmed

CONFIG = str(Path(__file__).parents[1] / "configs" / "v2.yaml")
SPEC = "# a comment\nid: t\nk: 3\nrule: top k\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    (tmp_path / "spec.yaml").write_text(SPEC)
    git("add", "spec.yaml")
    git("commit", "-qm", "spec")
    return tmp_path, git


def test_the_hash_is_over_the_content_not_the_text():
    assert prespec.digest(SPEC) == prespec.digest("rule: top k\nk: 3\nid: t   # other order, other comment\n")
    assert prespec.digest(SPEC) != prespec.digest(SPEC.replace("k: 3", "k: 4"))


def test_a_spec_must_be_committed_and_unchanged(repo):
    path, git = repo
    (path / "new.yaml").write_text(SPEC)
    with pytest.raises(prespec.SpecNotCommitted, match="not tracked"):
        prespec.stamp("new.yaml")
    (path / "spec.yaml").write_text(SPEC.replace("k: 3", "k: 4"))
    with pytest.raises(prespec.SpecNotCommitted, match="uncommitted"):
        prespec.stamp("spec.yaml")
    git("checkout", "spec.yaml")
    assert prespec.stamp("spec.yaml")["sha256"] == prespec.digest(SPEC)


def test_a_run_after_the_commit_verifies(repo):
    entry = prespec.stamp("spec.yaml")
    assert prespec.verify(entry) == []


def test_a_run_that_started_before_the_commit_fails(repo):
    entry = prespec.stamp("spec.yaml")
    early = datetime.fromisoformat(entry["committed_at"]) - timedelta(hours=1)
    problems = prespec.verify({**entry, "stamped_at": early.astimezone(timezone.utc).isoformat(timespec="seconds")})
    assert any("after the run started" in p for p in problems)


def test_a_hash_that_does_not_match_the_commit_fails(repo):
    entry = prespec.stamp("spec.yaml")
    assert any("does not match" in p for p in prespec.verify({**entry, "sha256": "0" * 64}))
    assert any("does not hold" in p for p in prespec.verify({**entry, "commit": "1" * 40}))


def test_a_run_that_differs_from_the_spec_does_not_start(repo):
    with pytest.raises(ValueError, match="k: run 5, spec 3"):
        prespec.begin("spec.yaml", {"k": 5, "other": 1})
    assert prespec.begin("spec.yaml", {"k": 3, "other": 1})["file"] == "spec.yaml"


def test_the_pipeline_writes_the_stamp_into_the_meta(repo, monkeypatch):
    path, _ = repo
    (path / "run.yaml").write_text("id: r\nK: 2000\nk_top: 3\n")
    subprocess.run(["git", "add", "run.yaml"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "run spec"], cwd=path, check=True)
    abstract = {"pmid": "1", "title": "A fake compound extends lifespan in mice.", "year": "2020", "pubtypes": ["Journal Article"],
                "abstract": "We show that the fake compound extends median lifespan of mice by 12%.", "first_author": "X", "journal": "J"}
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: ["1"])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": abstract})
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None, cid=None: ([], []))
    res = pipeline.run(["The fake compound extends the lifespan of mice."], fake=True, config=CONFIG, K=2000, spec="run.yaml")
    assert res["meta"]["spec"]["file"] == "run.yaml" and prespec.verify(res["meta"]["spec"]) == []
    with pytest.raises(ValueError, match="K: run 500"):
        pipeline.run(["The fake compound extends the lifespan of mice."], fake=True, config=CONFIG, K=500, spec="run.yaml")


def test_spec_files_say_what_the_code_does():
    itp = prespec.load("specs/itp-backtest-2010.yaml")
    assert itp["dropped_indicators"] == backtest.PRIMARY_DROP == site.ITP_DROP
    assert itp["k_top"] == 3 and itp["K"] == 10000 and itp["profile"] == evolve.PROFILE
    evo = prespec.load("specs/evolution-1.yaml")
    sig = inspect.signature(evolve.evolve).parameters
    assert {k: sig[k].default for k in ("rounds", "parents", "children", "max_calls", "writer")} == \
        {k: evo[k] for k in ("rounds", "parents", "children", "max_calls", "writer")}
    assert evo["profile"] == evolve.PROFILE and evo["k"] == inspect.signature(evolve.criterion).parameters["k"].default
