"""Literature search interface. The skeleton ships a no-op; Europe PMC / OpenAlex come later."""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class Passage(BaseModel):
    source: str      # identifier or URL a claim can cite
    title: str = ""
    text: str = ""


class SearchTool(Protocol):
    def search(self, query: str, limit: int = 5) -> list[Passage]: ...


class NullSearch:
    def search(self, query: str, limit: int = 5) -> list[Passage]:
        return []
