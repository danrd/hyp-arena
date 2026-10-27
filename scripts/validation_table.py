"""Render specs/validation-criteria.yaml into docs/validation-criteria.md (summary, one table per level, the criteria below).

    python -m scripts.validation_table            # write the file
    python -m scripts.validation_table --check    # exit 1 if the file is out of date"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

SRC, OUT = Path("specs/validation-criteria.yaml"), Path("docs/validation-criteria.md")
STATUS = ("pass", "formal", "fail", "inconclusive", "uninformative", "not_run", "blocked", "not_applied")
STATUS_RU = {"pass": "пройдено", "formal": "выполнено формально", "fail": "не пройдено", "inconclusive": "не доказано",
             "uninformative": "неинформативно", "not_run": "не проводилось", "blocked": "заблокировано",
             "not_applied": "механизм есть, не применён"}
DECLARED = ("before_run", "after_result", "pending")
DECLARED_RU = {"before_run": "до прогона", "after_result": "после результата", "pending": "ждёт подтверждения"}
KINDS = ("code", "claim")
KIND_RU = {"code": "Проверки кода и метода", "claim": "Проверки утверждения об отборе"}


def current_set() -> str:
    """Prefix of the hash of the current indicator set and profiles (what a recorded result is compared with)."""
    from hyparena.aspid import load_profiles
    from hyparena.card import indicators as ind
    return ind.set_hash(ind.INDICATORS, load_profiles())[:8]


def freshness(t: dict, current: str) -> str:
    """Whether a measured result still describes the current indicator set (measured_on.indicators)."""
    m = (t.get("measured_on") or {}).get("indicators")
    if m is None or t["status"] in ("not_run", "blocked", "not_applied"):
        return ""
    if m == "frozen":
        return "эталон: заморожен намеренно, набор показателей с тех пор изменился"
    if m == current:
        return f"актуально: измерено на текущем наборе показателей ({m})"
    return "УСТАРЕЛО: измерено на прежнем наборе показателей, повторить на текущем коде"


def load(path: Path = SRC) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _counts(tests: list[dict]) -> str:
    c = Counter(t["status"] for t in tests)
    return ", ".join(f"{STATUS_RU[s]} — {c[s]}" for s in STATUS if c[s]) or "нет"


def summary(tests: list[dict]) -> list[str]:
    """Three separate tallies: checks of the code, checks of the claim about selection, and how many passes had the criterion before the result."""
    out = ["## Итог (три раздельных счёта)", ""]
    for kind in KINDS:
        rows = [t for t in tests if t["kind"] == kind]
        out.append(f"- **{KIND_RU[kind]}** ({len(rows)}): {_counts(rows)}.")
    claim = [t for t in tests if t["kind"] == "claim"]
    passed = [t for t in claim if t["status"] == "pass"]
    before = [t for t in passed if t["declared"] == "before_run"]
    formal = [t for t in claim if t["status"] == "formal"]
    out.append(f"- **Из пройденных проверок утверждения с критерием, зафиксированным до результата:** {len(before)} из {len(passed)}"
               + (f" ({', '.join(t['id'] for t in before)})" if before else "")
               + f". Выполнено формально (почти не могло провалиться): {len(formal)}"
               + (f" ({', '.join(t['id'] for t in formal)})" if formal else "") + ".")
    out += ["", "Проверки кода проходят, но говорят только о том, что код делает задуманное. Ни одно утверждение об отборе пока не подтверждено "
            "проверкой с критерием, зафиксированным до результата и способным провалиться." if not before else "", ""]
    return out


def render(spec: dict) -> str:
    tests = spec["tests"]
    cur = current_set()
    out = ["# Критерии «пройдено» для проверок системы",
           "",
           f"Источник: `specs/validation-criteria.yaml` (версия {spec['version']}, {spec['declared_on']}). Этот файл генерируется "
           "(`python -m scripts.validation_table`), руками не правится.",
           "",
           "**Как читать.** «Пройдено» значит: критерий выполнен. Критерии для проведённых тестов записаны **после** результата (колонка «критерий записан»): "
           "такой статус информативен, но не подтверждает. Критерии непроведённых проверок зафиксированы коммитом до любого прогона. "
           "«Не доказано» — измерено, критерий не выполнен, но и не опровергнут. «Выполнено формально» — критерий почти не мог провалиться. "
           "«Неинформативно» — единиц меньше минимума (`min_units`), значение ничего не говорит. Для каждой проверки указано, может ли она провалиться и при каком исходе.",
           ""]
    out += summary(tests)
    for level, title in spec["levels"].items():
        rows = [t for t in tests if t["level"] == level]
        out += [f"## Уровень {level}. {title}", "", "| № | Проверка | Вид | Класс | Статус | Критерий записан |", "|---|---|---|---|---|---|"]
        out += [f"| {t['id']} | {t['name']} | {'код' if t['kind'] == 'code' else 'утверждение'} | {t['cls']} | **{STATUS_RU[t['status']]}** | {DECLARED_RU[t['declared']]} |" for t in rows]
        out.append("")
        for t in rows:
            out += [f"**{t['id']}. {t['name']}** ({STATUS_RU[t['status']]})", f"- Критерий: {t['criterion']}", f"- Может ли провалиться: {t['can_fail']}"]
            if t.get("min_units"):
                mu = t["min_units"]
                out.append(f"- Минимум единиц: оцениваемых не менее {mu['scored']}, положительных не менее {mu['positives']}"
                           + (f"; при таком объёме обнаружим AUC от {mu['mde_auc']}" if mu.get("mde_auc") else "") + "; меньше — «неинформативно».")
            if t.get("thresholds"):
                out.append("- Пороги (зафиксированы заранее): " + ", ".join(f"{k} = {v}" for k, v in t["thresholds"].items() if not isinstance(v, dict))
                           + "; мини-выборка: " + ", ".join(f"{k} = {v}" for k, v in t["thresholds"].get("mini_sample", {}).items()) + ".")
            if t.get("procedure"):
                out.append(f"- Порядок: {t['procedure']}")
            if t.get("multiplicity"):
                out.append(f"- Множественность: {t['multiplicity']}.")
            if freshness(t, cur):
                out.append(f"- Свежесть: {freshness(t, cur)}")
            if t.get("result"):
                out.append(f"- Результат: {t['result']}")
            if t.get("evidence"):
                out.append(f"- Где: {t['evidence']}")
            if t.get("blocker"):
                out.append(f"- Препятствие: {t['blocker']}")
            if t.get("note"):
                out.append(f"- Примечание: {t['note']}")
            out.append("")
    pw, mp, cp = spec["power"], spec["multiplicity"], spec["clean_policy"]
    out += ["## Мощность и минимальный объём", "", pw["note"] + ".", "",
            "| Положительных | Отрицательных | Обнаружимый AUC (мощность 80%) | Мощность при AUC 0.70 |", "|---|---|---|---|"]
    out += [f"| {d['positives']} | {d['negatives']} | {d['mde_auc']} | {d['power_at_auc_0_70']} |" for d in pw["designs"]]
    out += ["", pw["rule"], "", "## Множественность", "",
            f"Вторичные проверки {', '.join(mp['family'])}: {mp['method']}. {mp['primary']}.", "",
            "## Политика чистоты" + ("" if cp["confirmed"] else " (ждёт подтверждения)"), "",
            f"- Основной тест: {cp['main_test']}.", f"- Отдельно: {cp['separate']}.", f"- Фоном: {cp['background']}.", "",
            f"Реализуемость варианта А (проверено {cp['feasibility_of_A']['checked_on']}):", ""]
    out += [f"- {c['model']}: заявленная отсечка {c['stated_cutoff']} ([страница провайдера]({c['source']})); {c['note']}" for c in cp["feasibility_of_A"]["candidates"]]
    out += ["", "Нужно до прогона:"] + [f"- {x}" for x in cp["feasibility_of_A"]["needs_before_a_run"]]
    out += ["", "Риски:"] + [f"- {x}" for x in cp["feasibility_of_A"]["risks"]]
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
