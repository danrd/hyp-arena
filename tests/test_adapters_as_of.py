"""Tests for as_of date filtering in adapters."""

import pytest
import httpx

from hyparena.tools import europepmc, clinicaltrials, opengenes, pubtator, pubmed, search
from hyparena.state import Evidence
from hyparena.tools.http import Http


class StubResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
        self.content = b""

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError("error")


class StubClient:
    def __init__(self):
        self.calls = []
        self.responses = []

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, params))
        if self.responses:
            return self.responses.pop(0)
        return StubResponse({})


def test_europepmc_as_of():
    client = StubClient()
    adapter = europepmc.EuropePMCSearch(client=client)

    # With as_of
    adapter.search("test query", as_of="2010-12-31")
    assert len(client.calls) == 1
    params = client.calls[0][1]
    assert "FIRST_PDATE:[1800-01-01 TO 2010-12-31]" in params["query"]

    # Without as_of
    client.calls.clear()
    adapter.search("test query")
    assert len(client.calls) == 1
    params = client.calls[0][1]
    assert "FIRST_PDATE" not in params["query"]


def test_clinicaltrials_as_of():
    client = StubClient()
    adapter = clinicaltrials.ClinicalTrialsSearch(http=Http(client=client))

    # With as_of
    adapter.search("test query", as_of="2010-12-31")
    assert len(client.calls) == 1
    params = client.calls[0][1]
    assert params["filter.advanced"] == "AREA[StudyFirstSubmitDate]RANGE[MIN,2010-12-31]"

    # Without as_of
    client.calls.clear()
    adapter.search("test query")
    assert len(client.calls) == 1
    params = client.calls[0][1]
    assert "filter.advanced" not in params


def test_pubmed_search_as_of(monkeypatch):
    calls = []

    def mock_get(path, params):
        calls.append(params)
        return StubResponse({"esearchresult": {"idlist": []}})

    monkeypatch.setattr(pubmed, "_get", mock_get)

    # With as_of
    pubmed.search("test query", as_of="2010-12-31")
    assert len(calls) == 1
    params = calls[0]
    assert params["datetype"] == "pdat"
    assert params["maxdate"] == "2010/12/31"

    # Without as_of
    calls.clear()
    pubmed.search("test query")
    assert len(calls) == 1
    params = calls[0]
    assert "datetype" not in params
    assert "maxdate" not in params


def test_opengenes_as_of():
    client = StubClient()
    adapter = opengenes.OpenGenesSearch(http=Http(client=client))

    # With as_of
    results = adapter.search("FOXO3", as_of="2010-12-31")
    assert results == []
    assert len(client.calls) == 0

    # Without as_of
    client.responses = [StubResponse({"symbol": "FOXO3", "name": "FOXO3"})]
    results = adapter.search("FOXO3")
    assert len(client.calls) == 1
    assert len(results) == 1
    assert results[0].source == "opengenes"


def test_pubtator_as_of():
    client = StubClient()
    adapter = pubtator.PubTatorSearch(http=Http(client=client))

    # With as_of
    results = adapter.search("test query", as_of="2010-12-31")
    assert results == []
    assert len(client.calls) == 0

    # Without as_of
    client.responses = [StubResponse({
        "results": [{"pmid": "1", "title": "t", "text_hl": "hl"}]
    })]
    results = adapter.search("test query")
    assert len(client.calls) == 1
    assert len(results) == 1
    assert results[0].source == "pubtator"


class DummySearchTool:
    def search(self, query: str, limit: int = 5, as_of: str | None = None) -> list[Evidence]:
        return [
            Evidence(source="dummy", record_id="1", publication_date="2009-05-10"),
            Evidence(source="dummy", record_id="2", publication_date="2012-08-20"),
            Evidence(source="dummy", record_id="3", publication_date=None),
        ]

def test_multisearch_as_of_drops_late_records():
    searcher = search.MultiSearch(DummySearchTool())

    # With as_of, it should drop the 2012 record and the one without a date
    results = searcher.search("query", as_of="2010-12-31")
    assert len(results) == 1
    assert results[0].record_id == "1"

    # Without as_of, it should return all three records
    results = searcher.search("query")
    assert len(results) == 3
    assert {r.record_id for r in results} == {"1", "2", "3"}

def test_multisearch_as_of_formats():
    class DummySearchToolVariousDates:
        def search(self, query: str, limit: int = 5, as_of: str | None = None) -> list[Evidence]:
            return [
                Evidence(source="dummy", record_id="1", publication_date="2010"),
                Evidence(source="dummy", record_id="2", publication_date="2010-12"),
                Evidence(source="dummy", record_id="3", publication_date="2011"),
                Evidence(source="dummy", record_id="4", publication_date="2011-01"),
            ]

    searcher = search.MultiSearch(DummySearchToolVariousDates())
    results = searcher.search("query", as_of="2010-12-31")
    assert len(results) == 2
    assert {r.record_id for r in results} == {"1", "2"}
