"""Build a step-by-step page (Russian) from a recorded run: every graph node in order, what it does, which
code and prompt template run, every model and search call with its full prompt and reply, and what the
node produced.

    ALLOW_PAID=1 python -m hyparena.showcase --paste input.txt --writer openai --trace runs/trace.json --out runs/r.json
    python scripts/trace_page.py runs/trace.json page.html

The page has no <!doctype>/<html>/<body> of its own (it is published as an artifact, which adds them)."""
from __future__ import annotations

import html
import json
import sys
from collections import Counter

NODES = {
    "parse_goal": ("Разбор цели", "hyparena/agents/parse_goal.py · make_parse_goal", "parse_goal/v1",
                   "Одна модель переводит цель исследования в предпочтения и ограничения для судей. Критерии и их "
                   "порядок важности берутся не от модели, а из configs/criteria.yaml."),
    "supervisor": ("Решение супервизора", "hyparena/agents/supervisor.py · make_supervisor", "без вызова модели",
                   "Решает, запускать ли ещё цикл: останавливает по числу циклов, по бюджету токенов или когда "
                   "топ перестал меняться."),
    "normalize": ("Карточки гипотез", "hyparena/agents/normalize.py · make_normalize (схема configs/card.yaml)", "normalize/v2",
                  "Из свободного текста извлекается карточка: утверждение, механизм, вмешательство, решающий "
                  "эксперимент, что опровергнет и так далее. Ничего не додумывается: незаявленные обязательные "
                  "поля попадают в «пробелы». Модель заодно предлагает поисковые запросы. Если ответ не проходит "
                  "проверку схемы, модель переспрашивают с причиной (refine loop)."),
    "retrieve": ("Поиск литературы", "hyparena/agents/retrieve.py · make_retrieve → hyparena/tools/europepmc.py",
                 "без вызова модели",
                 "По запросам из карточки ищутся публикации в Europe PMC (до 5 на запрос, до 10 на гипотезу). "
                 "Каждая запись получает эпистемический тип (первичная работа, обзор и т. п.), отозванные статьи "
                 "помечаются по Retraction Watch и судьям не показываются."),
    "review": ("Рецензии", "hyparena/agents/review.py · make_review", "review_initial/v1 → review_full/v4 → review_deep/v1",
               "Три рецензии на гипотезу, каждая от семейства, отличного от автора: первичная (без литературы), "
               "полная (с найденной литературой, новизна только относительно неё) и глубокая проверка "
               "допущений. Рецензии совещательные: ничего не отсеивают (кроме проблем безопасности), а их "
               "замечания потом видят судьи."),
    "proximity": ("Поиск дубликатов", "hyparena/agents/proximity.py · make_proximity", "без вызова модели",
                  "Эмбеддинги текстов, слияние почти одинаковых гипотез (порог сходства 0.97 в демо) и кластеры "
                  "для выбора пар."),
    "tournament": ("Турнир", "hyparena/agents/tournament.py · make_tournament; судьи: hyparena/llm/judges.py · pick_judges; "
                   "рейтинг: hyparena/rating.py · fit_bt", "compare/v4 или debate/v4",
                   "Выбор пар, затем судьи из семейств, не совпадающих с автором ни одной из двух гипотез. "
                   "Порядок A/B случайный. Судья выносит отдельный вердикт по каждому критерию. Маленький пул "
                   "(до 8) сначала играет все пары; пары внутри текущего топ-5 разбираются дебатами одного "
                   "судьи, остальные — двумя судьями, при разногласии добавляется третий. После матчей по "
                   "каждому критерию заново подгоняется Bradley–Terry."),
    "meta_review": ("Мета-обзор раунда", "hyparena/agents/meta_review.py · make_meta_review", "meta_review/v1",
                    "Повторяющиеся замечания рецензентов и судей сводятся в советы на следующий цикл: что "
                    "учитывать судьям и рецензентам."),
    "report": ("Итог: агрегация и обзор", "hyparena/agents/report.py · make_report → hyparena/aggregate.py · mrsp",
               "research_overview/v3",
               "Итоговый порядок без числовых весов. По каждому критерию считается ожидаемая доля побед против "
               "остальных гипотез пула, веса сэмплируются равномерно из всех векторов, согласованных с порядком "
               "важности (на основе МРСП), рейтинги — в пределах своей погрешности. Затем одна модель пишет "
               "обзор на русском."),
}
CRIT = {"value": "Ценность", "evidence_support": "Опора на данные", "testability": "Проверяемость", "novelty": "Новизна"}
ROLE = {"parse_goal": "разбор цели", "normalize": "карточка", "review_initial": "первичная рецензия",
        "review_full": "полная рецензия", "review_deep": "глубокая проверка", "compare": "сравнение",
        "debate": "дебаты", "meta_review": "мета-обзор", "research_overview": "обзор"}
EVT = {"primary_text": "первичная работа", "review_text": "обзор", "curated_record": "курируемая база",
       "plans": "реестр", "machine_derived": "машинная подсказка", "measurement": "измерение"}


def e(x) -> str:
    return html.escape(str("" if x is None else x))


def cut(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


def title_of(text: str) -> str:
    return text.strip().split("\n", 1)[0][:90]


class Page:
    def __init__(self, trace: dict):
        self.t = trace
        self.r = trace["result"]
        self.titles = {it["id"]: it["title"] for it in self.r["items"]}
        self.calls = [c for s in trace["steps"] for c in s["calls"] if c["kind"] == "llm"]
        self.call_no = 0

    def short(self, hid: str) -> str:
        return f'<span class="hid">{e(hid)}</span> {e(cut(self.titles.get(hid, ""), 60))}'

    # --- calls ---
    def call_table(self, calls: list[dict]) -> str:
        llm = [c for c in calls if c["kind"] == "llm"]
        if not llm:
            return ""
        rows = []
        for c in llm:
            self.call_no += 1
            c["_no"] = self.call_no
            fb = (f' <span class="warn">(просили {e(c["asked_family"])})</span>' if c["asked_family"] != c["family"] else "")
            err = f'<div class="warn">{e(cut(c["error"], 160))}</div>' if c["error"] else ""
            rows.append(f'<tr><td class="num">{c["_no"]}</td><td>{e(ROLE.get(c["role"], c["role"]))}</td>'
                        f'<td>{e(c["family"])}{fb}<div class="sub">{e(c["model"])}</div>{err}</td>'
                        f'<td class="num">{c["seconds"]}</td><td class="num">{c["tokens_in"]} / {c["tokens_out"]}</td>'
                        f'<td>{e(", ".join(c["avoid"])) or "—"}</td></tr>')
        return ('<div class="scroll"><table class="calls"><thead><tr><th>#</th><th>Роль</th><th>Кто ответил</th>'
                '<th>Секунд</th><th>Токены вход / выход</th><th>Запрещённые семейства</th></tr></thead><tbody>'
                + "".join(rows) + "</tbody></table></div>")

    def call_details(self, calls: list[dict]) -> str:
        out = []
        for c in calls:
            if c["kind"] != "llm":
                continue
            out.append(f'<details class="call"><summary>Вызов {c["_no"]}: {e(ROLE.get(c["role"], c["role"]))} · '
                       f'{e(c["family"])} · промпт {len(c["prompt"])} символов, ответ {len(c["reply"])}</summary>'
                       f'<div class="pair"><div><h5>Промпт</h5><pre>{e(c["prompt"])}</pre></div>'
                       f'<div><h5>Ответ модели</h5><pre>{e(c["reply"]) or "(пусто)"}</pre></div></div></details>')
        return "".join(out)

    def excerpt(self, calls: list[dict], role: str | None = None) -> str:
        c = next((c for c in calls if c["kind"] == "llm" and (role is None or c["role"] == role) and c["reply"]), None)
        if not c:
            return ""
        return (f'<div class="excerpt"><div><h5>Промпт (начало), вызов {c["_no"]}</h5><pre>{e(cut(c["prompt"], 700))}</pre></div>'
                f'<div><h5>Ответ (начало)</h5><pre>{e(cut(c["reply"], 700))}</pre></div></div>')

    # --- outputs per node ---
    def out_parse_goal(self, o):
        p = o["plan"]
        crit = "".join(f'<li><b>{e(CRIT.get(c["name"], c["name"]))}</b> <span class="mono">{e(c["name"])}</span>, '
                       f'ожидаемый вес {c["weight"]:.3f}: {e(c["description"])}</li>' for c in p["criteria"])
        order = " ≥ ".join(CRIT.get(c, c) for c in (p.get("importance") or []))
        return (f'<p><b>Предпочтения:</b> {e(p["preferences"])}</p>'
                f'<p><b>Атрибуты:</b> {e(", ".join(p["attributes"])) or "—"}. <b>Ограничения:</b> {e(", ".join(p["constraints"])) or "—"}</p>'
                f'<p><b>Порядок важности</b> (из конфига): {e(order)}. Ожидаемые веса при этом порядке — центроидные; '
                f'они нужны только для выбора пар.</p><ul class="crit">{crit}</ul>')

    def out_supervisor(self, o):
        return f'<p>Решение: <b>{"ещё цикл" if o.get("next") == "continue" else "остановиться и перейти к итогу"}</b>' + (
            f', начинается цикл {o["cycle"]}.' if o.get("cycle") else ".") + "</p>"

    def out_normalize(self, o):
        if not o or not o.get("hypotheses"):
            return '<p class="sub">Новых гипотез нет, шаг пропущен.</p>'
        blocks = []
        for hid, h in o["hypotheses"].items():
            card = (h.get("card") or {})
            f = card.get("fields", {})
            rows = "".join(f'<tr><th>{e(k)}</th><td>{e(v if isinstance(v, str) else "; ".join(map(str, v)))}</td></tr>'
                           for k, v in f.items() if v not in ("", [], None))
            gaps = ", ".join(card.get("gaps", [])) or "нет"
            q = "".join(f"<li>{e(x)}</li>" for x in card.get("search_queries", []))
            blocks.append(f'<details><summary>{self.short(hid)}</summary><div class="scroll"><table class="kv">{rows}</table></div>'
                          f'<p><b>Пробелы:</b> {e(gaps)}</p><p><b>Поисковые запросы:</b></p><ul>{q}</ul></details>')
        return "".join(blocks)

    def out_retrieve(self, o, calls):
        if not o or not o.get("hypotheses"):
            return '<p class="sub">Новых гипотез нет, шаг пропущен.</p>'
        searches = [c for c in calls if c["kind"] == "search"]
        srows = "".join(f'<tr><td>{e(c["query"])}</td><td class="num">{len(c["records"])}</td><td>{e(c["as_of"] or "без ограничения")}</td></tr>'
                        for c in searches)
        blocks = []
        for hid, h in o["hypotheses"].items():
            ev = h.get("evidence", [])
            kinds = Counter(EVT.get(x.get("epistemic_type"), x.get("epistemic_type") or "?") for x in ev)
            items = "".join(f'<li><a href="{e(x.get("url"))}" target="_blank" rel="noopener">{e(x["record_id"])}</a> '
                            f'<span class="sub">({e(x.get("publication_date"))}, {e(EVT.get(x.get("epistemic_type"), x.get("epistemic_type")))})</span> '
                            f'{e(cut(x.get("title"), 120))}{" <span class=warn>отозвана</span>" if "retracted" in x.get("flags", []) else ""}</li>'
                            for x in ev)
            blocks.append(f'<details><summary>{self.short(hid)}: {len(ev)} записей ({e(", ".join(f"{k} {v}" for k, v in kinds.items()))})</summary><ul>{items}</ul></details>')
        return (f'<p>Поисковых запросов к Europe PMC: {len(searches)}.</p><div class="scroll"><table class="calls"><thead><tr><th>Запрос</th>'
                f'<th>Найдено</th><th>Дата отсечения</th></tr></thead><tbody>{srows}</tbody></table></div>' + "".join(blocks))

    def out_review(self, o):
        if not o or not o.get("hypotheses"):
            return '<p class="sub">Новых гипотез нет, шаг пропущен.</p>'
        rows = []
        for hid, h in o["hypotheses"].items():
            cells = []
            for kind in ("initial", "full", "deep"):
                r = next((r for r in h.get("reviews", []) if r["kind"] == kind), None)
                if not r:
                    cells.append("<td>—</td>")
                    continue
                sc = " · ".join(f'{ {"correctness": "прав.", "novelty": "нов.", "quality": "кач."}.get(k, k)} {v:g}' for k, v in r["scores"].items())
                cells.append(f'<td><span class="sub">{e(r["provenance"]["family"])}</span> {e(sc) or ("изъян" if not r["passed"] else "без фатального изъяна")}'
                             f'<div class="note">{e(cut("; ".join(r["notes"]), 260))}</div></td>')
            rows.append(f'<tr><td>{self.short(hid)}<div class="sub">статус: {e(h["status"])}</div></td>{"".join(cells)}</tr>')
        return ('<div class="scroll"><table class="calls rev"><thead><tr><th>Гипотеза</th><th>Первичная</th><th>С литературой</th>'
                '<th>Глубокая</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
                '<p class="sub">Оценки 0–10: правильность, новизна, качество. Судьи числа не видят, только замечания.</p>')

    def out_proximity(self, o):
        if not o or not o.get("hypotheses"):
            return '<p class="sub">Изменений нет.</p>'
        merged = [h for h in o["hypotheses"].values() if h.get("status") == "merged"]
        cl = Counter(h.get("cluster") for h in o["hypotheses"].values())
        return (f'<p>Слито дубликатов: {len(merged)}. Кластеров: {len(cl)} '
                f'({e(", ".join(f"кластер {k}: {v}" for k, v in cl.items()))}).</p>')

    def out_tournament(self, o):
        ms = o.get("matches", [])
        rows = []
        for m in ms:
            v = next((v for v in m["judges"] if v["parse_ok"]), None)
            win = " ".join(f'<span class="pill {"a" if w == m["a"] else "b" if w == m["b"] else ""}">{e(CRIT.get(c, c))}: {e(w or "ничья")}</span>'
                           for c, w in m["winners"].items())
            rows.append(f'<tr><td>{self.short(m["a"])}<br>против {self.short(m["b"])}</td>'
                        f'<td>{"дебаты" if m["mode"] == "debate" else "сравнение"}<div class="sub">{e(", ".join(j["provenance"]["family"] for j in m["judges"]))}</div></td>'
                        f'<td>{win}<div class="note">{e(cut(v["rationale"] if v else "", 300))}</div></td></tr>')
        rt = o.get("ratings", {})
        ids = list(next(iter(rt.values()), {}).keys())
        rrows = "".join(f'<tr><td>{self.short(h)}</td>' + "".join(
            f'<td class="num">{rt[c][h]["score"]:+.2f} <span class="sub">± {rt[c][h]["se"]:.2f}, игр {rt[c][h]["games"]}</span></td>' for c in rt) + "</tr>"
            for h in ids)
        heads = "".join(f"<th>{e(CRIT.get(c, c))}</th>" for c in rt)
        return (f'<p>Матчей в этом цикле: {len(ms)}.</p><div class="scroll"><table class="calls"><thead><tr><th>Пара</th><th>Режим и судьи</th>'
                f'<th>Победитель по критериям и довод судьи</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
                f'<h4>Рейтинги Bradley–Terry после цикла (логарифм силы, погрешность, число игр)</h4>'
                f'<div class="scroll"><table class="calls"><thead><tr><th>Гипотеза</th>{heads}</tr></thead><tbody>{rrows}</tbody></table></div>')

    def out_meta_review(self, o):
        fb = o.get("feedback", {})
        return "<ul>" + "".join(f'<li><b>{e(k)}</b>: {e(v)}</li>' for k, v in fb.items()) + "</ul>"

    def out_report(self, o):
        rep = o["report"]
        agg = rep["aggregate"]
        crit_order = [c for c in (agg.get("importance") or [])]
        rows = []
        for rank, hid in enumerate(agg["order"], start=1):
            a = agg["by_id"][hid]
            shares = "".join(f'<td class="num">{a["criteria"][c]["share"] * 100:.0f}% <span class="sub">'
                             f'[{a["criteria"][c]["lo"] * 100:.0f}–{a["criteria"][c]["hi"] * 100:.0f}]</span></td>' for c in crit_order)
            rows.append(f'<tr><td class="num big">{rank}</td><td>{self.short(hid)}</td><td class="num">{a["mean"] * 100:.0f} '
                        f'<span class="sub">± {a["sd"] * 100:.0f}</span></td><td class="num">{a["rank_lo"]}–{a["rank_hi"]}</td>{shares}</tr>')
        heads = "".join(f"<th>{e(CRIT.get(c, c))}</th>" for c in crit_order)
        dom = agg.get("dominance", {})
        ids = agg["order"]
        drows = "".join(f'<tr><th>{e(a)}</th>' + "".join("<td>·</td>" if a == b else f'<td class="num">{dom[a][b] * 100:.0f}%</td>' for b in ids) + "</tr>" for a in ids)
        return (f'<p>Выборок Монте-Карло: {agg["samples"]}. Индикатор: доля побед против пула.</p>'
                f'<div class="scroll"><table class="calls"><thead><tr><th>Место</th><th>Гипотеза</th><th>Балл</th><th>Интервал места</th>{heads}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>'
                f'<h4>Вероятность, что гипотеза в строке выше гипотезы в столбце</h4><div class="scroll"><table class="calls dom"><thead><tr><th></th>'
                + "".join(f"<th>{e(h)}</th>" for h in ids) + f'</tr></thead><tbody>{drows}</tbody></table></div>'
                f'<h4>Обзор (начало)</h4><pre class="prose">{e(cut(rep.get("overview", ""), 1800))}</pre>')

    # --- page ---
    def steps(self) -> str:
        out, n = [], 0
        for s in self.t["steps"]:
            node, o, calls = s["node"], s["output"] or {}, s["calls"]
            if node in ("generate", "evolve"):
                continue            # pasted hypotheses, evolution off in the demo: these nodes do nothing
            if node in ("normalize", "retrieve", "review", "proximity") and not (o.get("hypotheses") if o else None):
                continue            # second cycle: nothing new to process
            n += 1
            name, code, tmpl, what = NODES[node]
            body = (self.out_retrieve(o, calls) if node == "retrieve" else getattr(self, f"out_{node}")(o))
            llm = [c for c in calls if c["kind"] == "llm"]
            table = self.call_table(calls)
            out.append(
                f'<section class="step" id="s{n}"><div class="stephead"><span class="no">{n}</span><div><h3>{e(name)}</h3>'
                f'<div class="meta"><span class="mono">{e(node)}</span> · цикл {s["cycle"]} · {s["seconds"]} с · вызовов модели: {len(llm)}</div></div></div>'
                f'<p>{e(what)}</p><p class="code"><span>Код:</span> <span class="mono">{e(code)}</span><br><span>Промпт:</span> <span class="mono">{e(tmpl)}</span></p>'
                + (f"<h4>Вызовы</h4>{table}{self.excerpt(calls)}" if table else "")
                + f"<h4>Результат</h4>{body}" + (f'<h4>Все вызовы целиком</h4>{self.call_details(calls)}' if llm else "")
                + "</section>")
        return "".join(out)

    def render(self) -> str:
        t, r, meta = self.t, self.r, self.r["meta"]
        steps_html = self.steps()
        modes = Counter(m["mode"] for it in r["items"] for m in it["matches"])
        fallbacks = sum(c["asked_family"] != c["family"] for c in self.calls)
        errors = sum(bool(c["error"]) for c in self.calls)
        tok_in, tok_out = sum(c["tokens_in"] for c in self.calls), sum(c["tokens_out"] for c in self.calls)
        by_role = Counter(ROLE.get(c["role"], c["role"]) for c in self.calls)
        hyps = "".join(f'<details><summary>{e(it["id"])} · {e(it["title"])} <span class="sub">автор: {e(it["writer"])}</span></summary>'
                       f'<pre class="prose">{e(it["text"])}</pre></details>' for it in sorted(r["items"], key=lambda x: x["id"]))
        cfg = t["config"]
        return f"""<title>Прогон Арены гипотез по шагам</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Serif:wght@600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header><p class="eyebrow">Арена гипотез · запись настоящего прогона {e(meta["created"][:10])}</p>
<h1>Один прогон по шагам</h1>
<p class="lede">Три гипотезы о старении из ChatGPT-диалога вставлены в систему и проранжированы нашим методом (L4) на дешёвых
моделях. Ниже каждый узел графа в том порядке, в каком он выполнялся: что он делает, какой код и шаблон промпта работают,
какие модели вызывались, с каким промптом и что ответили, и что узел передал дальше. Все тексты и числа взяты из записи
прогона, ничего не дописано руками.</p>
<div class="facts">
<div><b>{len(r["items"])}</b><span>гипотезы, автор openai</span></div>
<div><b>{len(self.calls)}</b><span>вызовов моделей</span></div>
<div><b>{meta["matches"]}</b><span>парных сравнений</span></div>
<div><b>{meta["seconds"] // 60} мин {meta["seconds"] % 60} с</b><span>на весь прогон</span></div>
<div><b>{(tok_in + tok_out) // 1000}k</b><span>токенов (оценка)</span></div>
</div></header>

<section class="block"><h2>Что подано на вход</h2>
<p>Команда (её же выполняет кнопка «Ранжировать» в демо):</p>
<pre class="cmd">ALLOW_PAID=1 python -m hyparena.showcase --paste input.txt --writer openai \\
    --config configs/paid-test.yaml --trace runs/trace_real.json --out runs/trace_result.json</pre>
<p><span class="mono">hyparena/showcase.py · run</span> разбивает текст на гипотезы (по нумерации), каждой даёт id и
происхождение <span class="mono">family=openai</span> (это важно для правила независимости судей), собирает контекст
(<span class="mono">hyparena/live.py · _context</span>: клиент моделей, поиск, критерии, схема карточки) и запускает граф
LangGraph (<span class="mono">hyparena/graph.py · build_graph</span>).</p>
{hyps}
<div class="scroll"><table class="calls"><tbody>
<tr><th>Модели (одно семейство — одна модель)</th><td>{e(", ".join(f"{f}: {m}" for f, m in zip(t["families"], t["models"])))}</td></tr>
<tr><th>Кто может судить эти гипотезы</th><td>все, кроме openai (автор): zhipu и google</td></tr>
<tr><th>Критерии и порядок важности</th><td>{e(" ≥ ".join(CRIT.get(c, c) for c in t["importance"]))}</td></tr>
<tr><th>Циклы, матчей на гипотезу</th><td>{cfg["max_cycles"]}, {cfg["matches_per_item"]}</td></tr>
<tr><th>Судей на матч, доп. судья при разногласии, дебаты в топ-N</th><td>{cfg["judges_per_match"]}, {cfg["extra_judges"]}, {cfg["debate_top"]}</td></tr>
<tr><th>Полный круг для пулов до</th><td>{cfg["round_robin_max"]} гипотез</td></tr>
<tr><th>Рецензии</th><td>{e(cfg["review_gate"])} (совещательные: не отсеивают)</td></tr>
<tr><th>Рейтинг, выбор пар, независимость</th><td>{e(cfg["rating"])}, {e(cfg["pairing"])}, {e(cfg["lineage_mode"])}</td></tr>
</tbody></table></div>
</section>

<section class="block"><h2>Порядок узлов</h2>
<pre class="mermaid">flowchart LR
  A[parse_goal] --> S{{supervisor}}
  S -- цикл --> N[normalize] --> R[retrieve] --> V[review] --> P[proximity] --> T[tournament] --> M[meta_review] --> S
  S -- стоп --> F[report]</pre>
<p class="sub">Узлы generate и evolve тоже стоят в цикле, но в этом прогоне ничего не делают: гипотезы вставлены, эволюция
выключена. Во втором цикле карточки, поиск и рецензии не повторяются — новых гипотез нет; работают только турнир и
мета-обзор.</p>
</section>

{steps_html}

<section class="block"><h2>Что видно из этого прогона</h2>
<ul>
<li>Вызовы по ролям: {e(", ".join(f"{k} {v}" for k, v in by_role.most_common()))}.</li>
<li>Режимы сравнений: {e(", ".join(f"{'дебаты' if k == 'debate' else 'сравнение'} {v // 2}" for k, v in modes.items()))}.
При трёх гипотезах все пары попадают в топ-5, поэтому каждая разбирается дебатами одного судьи, а ансамбль из двух судей
не включается. На пулах крупнее топ-5 обычные пары судят двое.</li>
<li>Независимость: ни один рецензент и ни один судья не был из семейства openai (автор). Запасной путь к другому семейству
сработал {fallbacks} раз, ошибок вызовов: {errors}.</li>
<li>Внутренние промпты на английском, поэтому рецензии и доводы судей частично по-английски; итоговый обзор — на русском
(задано в конфиге).</li>
<li>Баллы и вероятности относятся к этому пулу из трёх гипотез и этим судьям; сравнивать их можно только внутри прогона.</li>
</ul></section>
<footer>Страница собрана из записи прогона скриптом <span class="mono">scripts/trace_page.py</span>.</footer>
</div>"""


CSS = """
/* Layout: one reading column with numbered step sections; wide tables scroll inside their own box. */
:root{--bg:#f5f7f9;--surface:#ffffff;--ink:#18212c;--muted:#5a6675;--line:#dbe1e8;--accent:#1f5f7d;--accent-soft:#e2eef4;
--call:#8a5a00;--call-soft:#f6ecd8;--b:#6b4c9a;--b-soft:#ece6f4;--warn:#a2461f;
--sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
--display:"IBM Plex Serif",Georgia,serif}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#12171d;--surface:#1a2129;--ink:#e3e8ee;--muted:#9aa6b4;
--line:#2c3540;--accent:#7cbcdc;--accent-soft:#1d3240;--call:#e2b25a;--call-soft:#33291a;--b:#b9a2e0;--b-soft:#2b2438;--warn:#ec9a72;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#12171d;--surface:#1a2129;--ink:#e3e8ee;--muted:#9aa6b4;--line:#2c3540;--accent:#7cbcdc;--accent-soft:#1d3240;
--call:#e2b25a;--call-soft:#33291a;--b:#b9a2e0;--b-soft:#2b2438;--warn:#ec9a72;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.55}
.wrap{max-width:1040px;margin:0 auto;padding-block:28px 48px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:22px}
h1{font-family:var(--display);font-size:2rem;line-height:1.15;margin:0;text-wrap:balance}
h2{font-size:1.25rem;margin:0 0 8px;text-wrap:balance}h3{font-size:1.1rem;margin:0}h4{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:16px 0 6px}
h5{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 4px}
p{margin:6px 0;max-width:72ch}.lede{font-size:1.02rem;max-width:75ch}
.eyebrow{font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin:0 0 6px}
.facts{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}.facts div{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:8px 12px;display:flex;flex-direction:column;min-width:120px}
.facts b{font-size:1.15rem;font-variant-numeric:tabular-nums}.facts span{font-size:.8rem;color:var(--muted)}
.block,.step{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:16px 18px;min-width:0}
.stephead{display:flex;gap:12px;align-items:center;margin-bottom:6px}.no{flex:none;width:2rem;height:2rem;border-radius:50%;background:var(--accent);color:var(--surface);display:grid;place-items:center;font-weight:700}
.meta,.sub{color:var(--muted);font-size:.82rem}.mono,.hid{font-family:var(--mono);font-size:.85em}.hid{color:var(--accent);font-weight:500}
.code{font-size:.85rem;color:var(--muted);border-left:3px solid var(--call);padding-left:10px}.code span:first-child{color:var(--call)}
.scroll{overflow-x:auto;max-width:100%}table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}thead th{font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
tbody th{font-weight:600;color:var(--muted);width:32%}td.num{font-variant-numeric:tabular-nums;white-space:nowrap}td.big{font-size:1.2rem;font-weight:700;color:var(--accent)}
table.kv th{width:24%;font-family:var(--mono);font-weight:400;font-size:.8rem}
table.dom td,table.dom th{text-align:center}
.note{color:var(--muted);font-size:.82rem;margin-top:3px}.warn{color:var(--warn)}
.pill{display:inline-block;border-radius:10px;padding:0 7px;font-size:.75rem;margin:1px 3px 1px 0;background:var(--line)}
.pill.a{background:var(--accent-soft);color:var(--ink)}.pill.b{background:var(--b-soft);color:var(--ink)}
pre{font-family:var(--mono);font-size:.78rem;line-height:1.45;white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:4px 0;max-height:420px;overflow:auto}
pre.prose{font-family:var(--sans);font-size:.88rem;max-height:none}pre.cmd{background:var(--call-soft);border-color:transparent}
.excerpt,.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}.excerpt>div,.pair>div{min-width:0}
details{border:1px solid var(--line);border-radius:6px;padding:6px 10px;margin:6px 0;background:var(--surface)}
details>summary{cursor:pointer;font-weight:500}details.call>summary{font-size:.85rem;color:var(--call)}
summary:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
a{color:var(--accent)}ul{margin:6px 0;padding-left:20px}ul.crit li{margin:3px 0}
pre.mermaid{background:var(--surface);border:none;max-height:none;text-align:center}
footer{color:var(--muted);font-size:.8rem}
@media (max-width:720px){.excerpt,.pair{grid-template-columns:1fr}h1{font-size:1.6rem}tbody th{width:40%}}
"""


def main() -> None:
    trace = json.loads(open(sys.argv[1], encoding="utf-8").read())
    open(sys.argv[2], "w", encoding="utf-8").write(Page(trace).render())
    print(sys.argv[2])


if __name__ == "__main__":
    main()
