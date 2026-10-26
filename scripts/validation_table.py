"""Render specs/validation-criteria.yaml into docs/validation-criteria.md (one table per level and the criteria below).

    python -m scripts.validation_table            # write the file
    python -m scripts.validation_table --check    # exit 1 if the file is out of date"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

SRC, OUT = Path("specs/validation-criteria.yaml"), Path("docs/validation-criteria.md")
STATUS = ("pass", "fail", "inconclusive", "not_run", "blocked", "not_applied")
STATUS_RU = {"pass": "пройдено", "fail": "не пройдено", "inconclusive": "не доказано", "not_run": "не проводилось",
             "blocked": "заблокировано", "not_applied": "механизм есть, не применён"}
DECLARED = ("before_run", "after_result", "pending")
DECLARED_RU = {"before_run": "до прогона", "after_result": "после результата", "pending": "ждёт одобрения"}


def load(path: Path = SRC) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def render(spec: dict) -> str:
    tests = spec["tests"]
    count = Counter(t["status"] for t in tests)
    out = ["# Критерии «пройдено» для проверок системы",
           "",
           f"Источник: `specs/validation-criteria.yaml` (версия {spec['version']}, записан {spec['declared_on']}). Этот файл генерируется "
           "(`python -m scripts.validation_table`), руками не правится.",
           "",
           "**Как читать.** Статус «пройдено» означает: критерий из колонки «критерий» выполнен. Критерии для проведённых тестов записаны "
           "**после** результата (колонка «записан»): такой статус информативен, но не подтверждает. Для непроведённых критерии "
           "ждут одобрения; после коммита они становятся заданными до прогона. «Не доказано»: измерено, критерий не выполнен, но и не опровергнут "
           "(интервал включает порог или выборка мала).",
           "",
           "Итог: " + ", ".join(f"{STATUS_RU[s]} — {count[s]}" for s in STATUS if count[s]) + ".",
           ""]
    for level, title in spec["levels"].items():
        rows = [t for t in tests if t["level"] == level]
        out += [f"## Уровень {level}. {title}", "", "| № | Проверка | Класс | Статус | Критерий записан |", "|---|---|---|---|---|"]
        out += [f"| {t['id']} | {t['name']} | {t['cls']} | **{STATUS_RU[t['status']]}** | {DECLARED_RU[t['declared']]} |" for t in rows]
        out.append("")
        for t in rows:
            out += [f"**{t['id']}. {t['name']}** ({STATUS_RU[t['status']]})", f"- Критерий: {t['criterion']}"]
            if t.get("evidence"):
                out.append(f"- Где: {t['evidence']}")
            if t.get("blocker"):
                out.append(f"- Препятствие: {t['blocker']}")
            if t.get("note"):
                out.append(f"- Примечание: {t['note']}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = render(load())
    if a.check:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("up to date" if ok else f"{OUT} is out of date: run python -m scripts.validation_table")
        return 0 if ok else 1
    OUT.write_text(text, encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
