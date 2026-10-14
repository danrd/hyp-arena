"""Build the search tool from source names, so that runs can choose connectors by configuration."""
from __future__ import annotations

from hyparena.tools.search import MultiSearch, NullSearch, SearchTool

SOURCES = ("europepmc", "pubtator", "opengenes", "clinicaltrials")


def build_search(names: list[str]) -> SearchTool:
    tools = []
    for name in names:
        if name == "europepmc":
            from hyparena.tools.europepmc import EuropePMCSearch
            tools.append(EuropePMCSearch())
        elif name == "pubtator":
            from hyparena.tools.pubtator import PubTatorSearch
            tools.append(PubTatorSearch())
        elif name == "opengenes":
            from hyparena.tools.opengenes import OpenGenesSearch
            tools.append(OpenGenesSearch())
        elif name == "clinicaltrials":
            from hyparena.tools.clinicaltrials import ClinicalTrialsSearch
            tools.append(ClinicalTrialsSearch())
        elif name != "none":
            raise ValueError(f"unknown source {name!r}; known: {', '.join(SOURCES)}")
    return MultiSearch(*tools) if tools else NullSearch()
