"""Prompt rendering from `prompts/<name>/<version>.j2` (same layout as llm_kit.PromptBuilder blocks)."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), undefined=StrictUndefined,
                   trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=False)


def render(name: str, version: str, **variables) -> str:
    return _env.get_template(f"{name}/{version}.j2").render(**variables).strip()
