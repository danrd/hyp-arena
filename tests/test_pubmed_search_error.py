import pytest

from hyparena.tools import pubmed


class _R:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def test_an_error_in_a_200_body_is_not_an_empty_result(monkeypatch):
    monkeypatch.setattr(pubmed.time, "sleep", lambda s: None)
    calls = []
    bad = {"esearchresult": {"ERROR": "Search Backend failed: Cannot connect to SOLR"}}
    monkeypatch.setattr(pubmed, "_get", lambda path, params: calls.append(1) or _R(bad))
    with pytest.raises(RuntimeError, match="SOLR"):
        pubmed.search("x")
    assert len(calls) == 5
    seq = iter([_R(bad), _R({"esearchresult": {"idlist": ["1", "2"]}})])
    monkeypatch.setattr(pubmed, "_get", lambda path, params: next(seq))
    assert pubmed.search("x") == ["1", "2"]
