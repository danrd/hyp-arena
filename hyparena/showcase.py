"""Demonstration run: a handful of pasted or generated hypotheses -> ranking, as one JSON-serializable
result and a self-contained HTML page (Russian interface). Used by the Gradio app (hyparena/app.py).

    python -m hyparena.showcase --paste data/demo/example_input.txt --config configs/paid-test.yaml --out runs/demo.json
    python -m hyparena.showcase --goal "..." --generate 5 --fake --out runs/demo.json
    python -m hyparena.showcase --render runs/demo.json --html runs/demo.html

Paid models need ALLOW_PAID=1, as everywhere else."""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

from hyparena.aggregate import to_logit
from hyparena.graph import build_graph
from hyparena.live import _context
from hyparena.llm.providers import CallCapExceeded
from hyparena.schema import CONFIGS
from hyparena.state import Hypothesis, Provenance, initial_state

DEFAULT_GOAL = "Identify the most promising and feasible hypotheses on the biology of ageing."

STAGES = {
    "parse_goal": "Разбор цели", "supervisor": "Планирование цикла", "generate": "Генерация гипотез",
    "normalize": "Разбор гипотез в карточки", "retrieve": "Поиск литературы", "review": "Рецензии",
    "proximity": "Поиск дубликатов", "tournament": "Турнир: парные сравнения судьями", "evolve": "Эволюция",
    "meta_review": "Мета-обзор раунда", "report": "Итоговая агрегация и обзор",
}
CRITERIA_RU = {"value": "Ценность", "evidence_support": "Опора на данные", "testability": "Проверяемость",
               "novelty": "Новизна", "overall": "Общая оценка", "promise": "Перспективность",
               "feasibility": "Реализуемость"}
CARD_RU = {"claim": "Утверждение", "mechanism": "Механизм", "intervention": "Вмешательство", "hallmarks": "Признаки старения",
           "outcome_claimed": "Заявленный исход", "known": "Что заявлено как известное", "assumptions": "Допущения",
           "decisive_experiment": "Решающий эксперимент", "falsifiable_implications": "Что опровергнет",
           "unknowns": "Открытые вопросы"}
EVIDENCE_RU = {"primary_text": "первичная работа", "review_text": "обзор: фон, а не результат",
               "curated_record": "курируемая база: сигнал, не доказательство", "measurement": "измерение",
               "machine_derived": "машинная подсказка, не доказательство", "quality_metadata": "метаданные качества",
               "plans": "реестр: планы и статус, не результаты"}
REVIEW_RU = {"initial": "Первичная", "full": "С литературой", "deep": "Глубокая проверка"}


def split_hypotheses(text: str) -> list[str]:
    """Pasted text -> hypotheses: numbered items ("1." / "1)") if there are at least two, else blocks
    separated by blank lines."""
    text = text.strip()
    if not text:
        return []
    marks = list(re.finditer(r"(?m)^\s*\d{1,2}[.)]\s+", text))
    if len(marks) >= 2:
        parts = [text[m.end():(marks[i + 1].start() if i + 1 < len(marks) else len(text))] for i, m in enumerate(marks)]
    else:
        parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def cycle_of(state) -> int:
    return (state or {}).get("cycle", 0)


def _args(config: str, fake: bool, search: str, max_calls: int, seed: int) -> SimpleNamespace:
    return SimpleNamespace(ladder="L4", mode="full", fake=fake, config=config, max_calls=max_calls, seed=seed,
                           criteria=str(CONFIGS / "criteria.yaml"), criteria_given=False,
                           card=str(CONFIGS / "card.yaml"), max_tokens=None, as_of=None, search=search)


def run(texts: Optional[list[str]] = None, goal: str = "", generate: int = 0, writer: str = "unknown",
        config: str = "configs/paid-test.yaml", fake: bool = False, search: str = "europepmc",
        cycles: int = 2, matches: float = 2.0, max_calls: int = 400, seed: int = 0,
        on_stage: Callable[[str, str], None] = lambda node, text: None) -> dict:
    """One demonstration run with our full method (L4). `texts`: pasted hypotheses; or `generate` > 0 to
    have the model families write that many for `goal`. `on_stage(node, message)` reports progress."""
    texts = texts or []
    if not texts and generate <= 0:
        raise ValueError("nothing to rank: paste hypotheses or ask to generate some")
    started = time.time()
    ctx, client = _context(_args(config, fake, search, max_calls, seed), max_cycles=cycles,
                           gen_per_cycle=0 if texts else generate, gen_cycles=1, evolve_per_cycle=0,
                           matches_per_item=matches, report_language="Russian", dedup_threshold=0.97)
    prov = Provenance(family=writer or "unknown", model_version="pasted", role="imported", strategy="pasted")
    imported = [Hypothesis(id=f"imp{i:03d}", text=t, provenance=prov) for i, t in enumerate(texts, start=1)]
    graph = build_graph(ctx)
    state, done = None, set()
    try:
        for mode, chunk in graph.stream(initial_state(goal or DEFAULT_GOAL, imported), {"recursion_limit": 200},
                                        stream_mode=["updates", "values"]):
            if mode == "values":
                state = chunk
                continue
            for node in chunk:
                if node in ("supervisor", "evolve") or (node == "generate" and (texts or cycle_of(state) > 1)):
                    continue
                cycle = (state or {}).get("cycle", 0)
                on_stage(node, f"{STAGES.get(node, node)}" + (f" (цикл {cycle})" if node in ("tournament", "review") else "")
                         + f" — готово; вызовов моделей: {client.calls}")
                done.add(node)
    except CallCapExceeded as e:
        raise RuntimeError(f"остановлено: исчерпан лимит вызовов ({e})") from e
    return collect(state, ctx, client, goal or DEFAULT_GOAL, seconds=time.time() - started,
                   mode="paste" if texts else "generate", fake=fake)


def collect(final: dict, ctx, client, goal: str, seconds: float, mode: str, fake: bool) -> dict:
    """Final graph state -> the demonstration result (everything the page shows, nothing else)."""
    plan, ratings, hyps = final["plan"], final.get("ratings", {}), final["hypotheses"]
    agg = (final.get("report") or {}).get("aggregate") or {}
    names = plan.names
    order = list(agg.get("order", []))
    rest = [h for h in hyps if h not in order and hyps[h].status != "merged"]
    items = []
    for rank, hid in enumerate(order + rest, start=1):
        h = hyps[hid]
        ranked = hid in order
        scores = {}
        for c in names:
            r = ratings.get(c, {}).get(hid)
            if r is not None:
                theta, se = to_logit(r, ctx.cfg.rating)
                scores[c] = {"p": 1 / (1 + math.exp(-theta)), "games": r.games,
                             "lo": 1 / (1 + math.exp(-(theta - 1.64 * se))), "hi": 1 / (1 + math.exp(-(theta + 1.64 * se)))}
        played = []
        for m in final.get("matches", []):
            if hid not in (m.a, m.b):
                continue
            other = m.b if m.a == hid else m.a
            verdict = next((v for v in m.judges if v.parse_ok and v.rationale), None)
            played.append({"opponent": other, "mode": m.mode,
                           "won": {c: (w == hid) if w else None for c, w in m.winners.items()},
                           "judges": [v.provenance.family for v in m.judges],
                           "rationale": verdict.rationale if verdict else ""})
        items.append({
            "id": hid, "rank": rank if ranked else None, "status": h.status,
            "title": h.text.strip().split("\n", 1)[0][:160], "text": h.text,
            "writer": h.provenance.family, "writer_model": h.provenance.model_version,
            "aggregate": agg.get("by_id", {}).get(hid), "scores": scores,
            "card": h.card.filled() if h.card else {}, "gaps": h.card.gaps if h.card else [],
            "evidence": [{"id": e.record_id, "title": e.title, "url": e.url, "date": e.publication_date,
                          "type": e.epistemic_type} for e in h.evidence if e.usable][:8],
            "reviews": [{"kind": r.kind, "family": r.provenance.family, "scores": r.scores, "notes": r.notes[:4]}
                        for r in h.reviews],
            "matches": played})
    return {"meta": {"goal": goal, "mode": mode, "created": datetime.now().isoformat(timespec="seconds"),
                     "seconds": round(seconds), "calls": client.calls, "failures": client.failures,
                     "tokens_estimated": ctx.tokens_used(), "families": [j.family for j in ctx.judge_pool],
                     "models": [j.model_version for j in ctx.judge_pool], "fake": fake,
                     "criteria": [{"name": c, "label": CRITERIA_RU.get(c, c)} for c in names],
                     "importance": plan.importance, "matches": len(final.get("matches", [])),
                     "step": ctx.cfg.step},
            "items": items, "dominance": agg.get("dominance", {}),
            "overview": (final.get("report") or {}).get("overview", "")}


# ---- rendering ----

CSS = """
:root{--bg:#fbfaf7;--card:#ffffff;--ink:#1f2328;--muted:#5d6670;--line:#e3e0d8;--accent:#2f6f5e;--accent-soft:#e3efe9;
--bar:#2f6f5e;--bar-bg:#ece9e1;--warn:#9a5b13}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#16181b;--card:#1e2125;--ink:#e8e6e1;--muted:#a3a9b0;
--line:#33373c;--accent:#7cc2ad;--accent-soft:#23332e;--bar:#7cc2ad;--bar-bg:#2b2f34;--warn:#e0a35a}}
:root[data-theme="dark"]{--bg:#16181b;--card:#1e2125;--ink:#e8e6e1;--muted:#a3a9b0;--line:#33373c;--accent:#7cc2ad;
--accent-soft:#23332e;--bar:#7cc2ad;--bar-bg:#2b2f34;--warn:#e0a35a}
.hx{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg);line-height:1.45;
padding:16px;border-radius:10px}
.hx h2{font-size:1.25rem;margin:0 0 4px}.hx .sub{color:var(--muted);font-size:.9rem;margin-bottom:14px}
.hx table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.hx th,.hx td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;font-size:.92rem}
.hx th{font-weight:600;color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.03em}
.hx .rank{font-size:1.3rem;font-weight:700;color:var(--accent);width:2.5rem}
.hx .interval{color:var(--muted);font-size:.8rem}
.hx .bar{display:flex;align-items:center;gap:6px;margin:2px 0;font-size:.8rem}
.hx .bar span.l{width:7.5rem;color:var(--muted)}.hx .bar .t{flex:1;height:8px;background:var(--bar-bg);border-radius:4px;position:relative;min-width:60px}
.hx .bar .f{position:absolute;left:0;top:0;bottom:0;background:var(--bar);border-radius:4px}
.hx .bar .ci{position:absolute;top:-2px;bottom:-2px;border-left:1px solid var(--muted);border-right:1px solid var(--muted);opacity:.6}
.hx details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:8px 0;padding:8px 12px}
.hx summary{cursor:pointer;font-weight:600}.hx .pill{display:inline-block;background:var(--accent-soft);color:var(--ink);
border-radius:10px;padding:1px 8px;font-size:.75rem;margin-right:4px}
.hx .muted{color:var(--muted)}.hx .warn{color:var(--warn)}.hx pre{white-space:pre-wrap;font-family:inherit;margin:4px 0}
.hx .dom td{text-align:center}.hx .dom th{text-transform:none;letter-spacing:0}.hx .overview{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin-top:14px}
.hx a{color:var(--accent)}
@media (max-width:640px){.hx .bar span.l{width:5.5rem}.hx th:nth-child(4),.hx td:nth-child(4){display:none}}
"""


def _e(x) -> str:
    return html.escape(str(x or ""))


def _bars(item: dict, criteria: list[dict]) -> str:
    out = []
    for c in criteria:
        s = item["scores"].get(c["name"])
        if not s:
            continue
        out.append(f'<div class="bar"><span class="l">{_e(c["label"])}</span><span class="t">'
                   f'<span class="ci" style="left:{s["lo"] * 100:.0f}%;width:{max(1, (s["hi"] - s["lo"]) * 100):.0f}%"></span>'
                   f'<span class="f" style="width:{s["p"] * 100:.0f}%"></span></span><span>{s["p"] * 100:.0f}%</span></div>')
    return "".join(out)


def _md(text: str) -> str:
    """Minimal markdown for the overview: headings, bullets, bold, paragraphs."""
    lines, out = text.splitlines(), []
    for line in lines:
        t = _e(line.strip())
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        if not t:
            continue
        if t.startswith("#"):
            out.append(f"<h3>{t.lstrip('#').strip()}</h3>")
        elif t[:2] in ("- ", "* "):
            out.append(f"<div>• {t[2:]}</div>")
        else:
            out.append(f"<p>{t}</p>")
    return "".join(out)


def render(result: dict, standalone: bool = False) -> str:
    """The result as HTML: ranking table, pairwise dominance, details per hypothesis, overview."""
    meta, items, crit = result["meta"], result["items"], result["meta"]["criteria"]
    rank_of = {c: i for i, g in enumerate(meta.get("importance") or []) for c in ([g] if isinstance(g, str) else g)}
    crit = sorted(crit, key=lambda c: rank_of.get(c["name"], len(rank_of)))     # most important first
    order_ru = " ≥ ".join(CRITERIA_RU.get(c, c) if isinstance(c, str) else " = ".join(CRITERIA_RU.get(x, x) for x in c)
                          for c in (meta.get("importance") or []))
    sub = (f'{len(items)} гипотез · {"вставлены" if meta["mode"] == "paste" else "сгенерированы"} · судьи: '
           f'{", ".join(meta["models"])} · {meta["matches"]} парных сравнений · {meta["calls"]} вызовов моделей · '
           f'{meta["seconds"] // 60} мин {meta["seconds"] % 60} с' + (" · <span class='warn'>фейковая LLM: оценки случайны</span>" if meta.get("fake") else ""))
    rows = []
    for it in items:
        a = it.get("aggregate")
        rank = f'{it["rank"]}' if it["rank"] else "—"
        interval = (f'<div class="interval">место {a["rank_lo"]}–{a["rank_hi"]} (90%)</div>' if a else
                    f'<div class="interval">{"отклонена" if it["status"] == "rejected" else "без оценки"}</div>')
        score = f'{a["mean"] * 100:.0f}<div class="interval">± {a["sd"] * 100:.0f}</div>' if a else "—"
        rows.append(f'<tr><td class="rank">{rank}{interval}</td><td><b>{_e(it["title"])}</b>'
                    f'<div class="muted">{_e(it["id"])} · автор: {_e(it["writer"])}</div></td>'
                    f'<td>{score}</td><td>{_bars(it, crit)}</td></tr>')
    table = ('<table><tr><th>Место</th><th>Гипотеза</th><th>Балл</th><th>По критериям (вероятность выиграть '
             'у средней гипотезы, 90% интервал)</th></tr>' + "".join(rows) + "</table>")
    dom = result.get("dominance") or {}
    head = [it["id"] for it in items if it["id"] in dom][:6]
    dom_html = ""
    if len(head) >= 2:
        cells = "".join(f"<th>{_e(h)}</th>" for h in head)
        body = "".join(f"<tr><th>{_e(a)}</th>" + "".join(
            "<td class='muted'>·</td>" if a == b else f"<td>{dom[a].get(b, 0) * 100:.0f}%</td>" for b in head) + "</tr>"
            for a in head)
        dom_html = (f'<h3>Насколько уверен порядок</h3><div class="sub">Вероятность, что гипотеза в строке выше гипотезы в '
                    f'столбце, по всем весам, согласованным с порядком важности, и с учётом неточности оценок.</div>'
                    f'<table class="dom"><tr><th></th>{cells}</tr>{body}</table>')
    details = []
    for it in items:
        ev = "".join(f'<div>• <a href="{_e(e["url"])}" target="_blank">{_e(e["id"])}</a> ({_e(e["date"] or "дата неизвестна")}'
                     f'{", " + _e(EVIDENCE_RU.get(e["type"], e["type"])) if e["type"] else ""}) {_e(e["title"])}</div>' for e in it["evidence"]) \
            or '<div class="muted">ничего не найдено</div>'
        rv = "".join(f'<div><span class="pill">{_e(REVIEW_RU.get(r["kind"], r["kind"]))}</span><span class="muted">{_e(r["family"])}</span> '
                     f'{_e("; ".join(r["notes"]))}</div>' for r in it["reviews"]) or '<div class="muted">нет</div>'
        title_of = {x["id"]: x["title"][:60] for x in items}
        mt = "".join(
            f'<div><span class="pill">{"дебаты" if m["mode"] == "debate" else "сравнение"}</span> против <b>{_e(m["opponent"])}</b> '
            f'<span class="muted">({_e(title_of.get(m["opponent"], ""))})</span>: '
            + ", ".join(f'{_e(CRITERIA_RU.get(c, c))} {"✓" if w else ("✗" if w is False else "=")}' for c, w in m["won"].items())
            + (f'<div class="muted">{_e(m["rationale"][:400])}</div>' if m["rationale"] else "") + "</div>"
            for m in it["matches"]) or '<div class="muted">не сравнивалась</div>'
        card = "".join(f'<div><span class="muted">{_e(CARD_RU.get(k, k))}:</span> {_e(v if isinstance(v, str) else "; ".join(map(str, v)))}</div>'
                       for k, v in it["card"].items() if k != "search_queries")
        details.append(f'<details><summary>{it["rank"] or "—"}. {_e(it["title"])}</summary>'
                       f'<pre>{_e(it["text"])}</pre>'
                       + (f'<h4>Карточка (из текста, не проверена)</h4>{card}' if card else "")
                       + (f'<div class="warn">Не указано: {_e(", ".join(CARD_RU.get(g, g) for g in it["gaps"]))}</div>' if it["gaps"] else "")
                       + f'<h4>Литература</h4>{ev}<h4>Рецензии</h4>{rv}<h4>Сравнения</h4>{mt}</details>')
    overview = f'<div class="overview"><h3>Обзор</h3>{_md(result.get("overview", ""))}</div>' if result.get("overview") else ""
    body = (f'<div class="hx"><h2>Ранжирование гипотез</h2><div class="sub">{sub}</div>'
            f'<div class="sub">Цель: {_e(meta["goal"])}<br>Порядок важности критериев: {_e(order_ru) or "заданные веса"}. '
            f'Итоговый балл — ожидаемое значение по всем весам, согласованным с этим порядком (на основе МРСП).</div>'
            f'{table}{dom_html}<h3>Подробно</h3>{"".join(details)}{overview}</div>')
    style = f"<style>{CSS}</style>"
    if not standalone:
        return style + body
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>Ранжирование гипотез</title>{style}'
            f'<style>body{{margin:0;background:var(--bg)}}</style></head><body>{body}</body></html>')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paste", default=None, help="text file with hypotheses (numbered or separated by blank lines)")
    ap.add_argument("--goal", default="")
    ap.add_argument("--generate", type=int, default=0)
    ap.add_argument("--writer", default="unknown", help="family that wrote the pasted hypotheses, if known")
    ap.add_argument("--config", default="configs/paid-test.yaml")
    ap.add_argument("--search", default="europepmc")
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--max-calls", type=int, default=400)
    ap.add_argument("--out", default=None, help="result JSON")
    ap.add_argument("--render", default=None, help="render an existing result JSON instead of running")
    ap.add_argument("--html", default=None, help="write the result as a standalone HTML page")
    args = ap.parse_args()
    if args.render:
        result = json.loads(Path(args.render).read_text())
    else:
        texts = split_hypotheses(Path(args.paste).read_text(encoding="utf-8")) if args.paste else []
        result = run(texts, args.goal, args.generate, args.writer, args.config, args.fake, args.search,
                     max_calls=args.max_calls, on_stage=lambda node, msg: print(msg, flush=True))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"result: {args.out}")
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(render(result, standalone=True), encoding="utf-8")
        print(f"page: {args.html}")


if __name__ == "__main__":
    main()
