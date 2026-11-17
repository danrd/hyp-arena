"""The form of a report written outside the code (method manual, section 10a: "an outside report is read against this table
and list before its content is compared with the code report"), checked by code. The report is rendered in a headless
browser (reports build their tabs with JavaScript), every tab is opened, and the page is searched only for OUR words: the
tab and help names of the manual, the codes of the names table, the scheme's labels. The output is found / not found per
word of our list and counts; no text of the report is ever printed, so the hypotheses in it stay unread by whoever runs it.

    python -m scripts.argon.report_check REPORT.html [--out check.json]

Run it on a code report first as the control: the code report must pass every item.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

TABS = ["Рейтинг", "Карточки гипотез", "Оценка", "Схема работы", "Справка"]
HELP = {   # the second level of the help (manual, section 10, tab 5): name -> pattern of its summary
    "weight": r"вес\w* записи",
    "strength": r"сил\w* звена|баланс доказательств",
    "reading": r"правил\w* (чтения|прочтения)",
    "novelty": r"новизн",
    "experiment": r"эксперимент.*(размах|реализуем)|реализуем",
    "profiles": r"профил|аспид|aspid",
    "versions": r"верси|улучшени|поднимет",
    "provenance": r"происхожд",
    "glossary": r"словар|глоссари",
}
FIRST_LEVEL = {"how_to_read_card": r"карточк", "not_a_forecast": r"не\s+(является\s+)?прогноз|это не прогноз",
               "prospective": r"проспективн"}
CARD_FIELDS = {"intervention": r"^\s*вмешательств", "population": r"^\s*популяци", "comparator": r"^\s*(сравнени|компаратор|контрол)",
               "outcome": r"^\s*исход"}
# codes that must not be shown bare (manual, section 10a); single letters (P, I, W, N) are left out: they are shown with names
CODES = ["chain_state", "support_share", "against_share", "I_headroom", "best_design_outcome", "independent_outcome",
         "endpoint_clinical", "trend_pubmed", "ai_role", "feasibility", "delivery", "engagement", "pathway", "new_context",
         "translation", "new_mechanism", "new_combination", "new_link", "meta_analysis", "non_randomised", "observational",
         "eliminated", "weakened", "unchanged", "build_mechanism", "name_supported_alternatives", "improve_experiment",
         "threats_open", "find_primary_report", "contested_link", "retracted_source_dropped", "established_by_approval",
         "evidence", "funding", "frontier", "outcome"]
IDS = r"(?<![\w(])(c\d{1,2}|alt\d{1,2})(?![\w)])"   # link and alternative ids; p\d+ is left out (p53, p16 are genes)
FORMULA = r"=|\bexp\b|\bln\b|Σ|∑|\^|√"   # not "·": a common separator


RENDER_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const [url, tabs] = [process.argv[1], JSON.parse(process.argv[2])];
  const b = await chromium.launch(); const page = await b.newPage();
  await page.goto(url, { waitUntil: 'load', timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const visible = {};
  for (const name of tabs) {
    const loc = page.locator('button, a, [role=tab], li', { hasText: new RegExp('^\\s*(\\d+[.)]\\s*)?' + name, 'i') });
    if (await loc.count()) {
      await loc.first().click({ timeout: 3000 }).catch(() => {}); await page.waitForTimeout(500);
      visible[name] = await page.evaluate(() => document.body.innerText);
    }
  }
  await page.evaluate(() => document.querySelectorAll('details').forEach(d => d.open = true));
  process.stdout.write(JSON.stringify({ html: await page.content(), visible })); await b.close();
})();
"""


def render(path: Path) -> dict:
    """{html: the page after every tab was opened, visible: {tab: the visible text after a click on it}}; tabs are found by
    our names only; through the Node Playwright of the environment."""
    import subprocess
    r = subprocess.run(["node", "-e", RENDER_JS, path.resolve().as_uri(), json.dumps(TABS)], capture_output=True, text=True,
                       timeout=180, cwd="/tmp")
    if r.returncode or not r.stdout:
        raise SystemExit(f"render failed: {r.stderr[-300:]}")
    return json.loads(r.stdout)


def _txt(el) -> str:
    return " ".join(el.get_text(" ").split())


def check_html(html: str, visible: dict | None = None) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for s in soup(["script", "style", "template"]):
        s.decompose()
    text = _txt(soup)
    out: dict = {}

    # 1. tabs: a clickable element named by each tab, in the manual's order
    pos = {}
    for name in TABS:
        el = next((x for x in soup.find_all(["button", "a", "li"]) if re.match(rf"\s*(\d+[.)]\s*)?{re.escape(name)}", _txt(x), re.I)), None)
        pos[name] = None if el is None else html.find(str(el)[:80])
    found = [n for n in TABS if pos[n] is not None]
    out["tabs"] = {"found": {n: pos[n] is not None for n in TABS},
                   "in_order": found == sorted(found, key=lambda n: pos[n]) and len(found) == len(TABS)}

    # 2. help: the second level as collapsed sections with tables; the first level before them
    summaries = [(s, _txt(s).lower()) for s in soup.find_all("summary")]
    helpd = {}
    for key, pat in HELP.items():
        hit = next((s for s, t in summaries if re.search(pat, t)), None)
        d = hit.find_parent("details") if hit else None
        tables = d.find_all("table") if d else []
        rows = sum(len([r for r in t.find_all("tr") if r.find("td")]) for t in tables)
        helpd[key] = {"collapsed_section": hit is not None, "tables": len(tables), "rows": rows,
                      "definition_list": bool(d and d.find("dl"))}
    out["help"] = helpd
    out["help"]["reading"]["seven_rules"] = helpd["reading"]["rows"] >= 7
    hh = next((h for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "b", "strong", "div", "p", "span"])
               if re.search(r"(?i)как читать отч", _txt(h)) and len(_txt(h)) < 80), None)
    box = hh.find_parent(["div", "section", "article"]) if hh else None
    if box is not None:
        from copy import copy
        box = copy(box)
        for d in box.find_all("details"):
            d.decompose()
    first = _txt(box) if box is not None else ""
    out["help_first_level"] = {k: bool(re.search(p, first, re.I)) for k, p in FIRST_LEVEL.items()}

    # 3. how it works: steps 0-11, "Как реализовано" on each, no formulas
    head = next((h for h in soup.find_all(["h1", "h2", "h3", "h4", "b", "strong", "button"])
                 if re.search(r"схема работы", _txt(h), re.I) and h.name != "button"), None)
    sec = head.find_parent(["section", "div"]) if head else None
    while sec is not None and len(_txt(sec)) < 500 and sec.parent is not None:
        sec = sec.find_parent(["section", "div"])
    st = _txt(sec) if sec else " ".join(((visible or {}).get("Схема работы") or "").split())
    nums = {int(n) for n in re.findall(r"(?i)шаг\s*(\d{1,2})", st)}           # "Шаг 3" (the code report)
    nums |= {int(n) for n in re.findall(r"(?:^|\s)(\d{1,2})\.\s", st)}        # "3. ..." (a numbered list)
    out["scheme"] = {"found": bool(st), "by": "heading" if sec else "tab" if st else None, "steps": sorted(n for n in nums if n <= 20),
                     "all_0_to_11": set(range(12)) <= nums, "how_implemented": len(re.findall(r"(?i)как реализовано", st)),
                     "formula_signs": len(re.findall(FORMULA, st))}

    # 4. cards: "Как гипотеза понята" as separate fields; the mechanism as triples with a legend
    heads = [h for h in soup.find_all(["h2", "h3", "h4", "h5", "b", "strong", "div", "p"])
             if re.match(r"\s*как гипотеза понята", _txt(h), re.I) and len(_txt(h)) < 40]
    out["cards_understood_heading"] = len(heads)
    if not heads:      # a report without that heading: each card is found by its first heading, "Текст гипотезы"
        heads = [h for h in soup.find_all(["h2", "h3", "h4", "h5", "b", "strong"])
                 if re.match(r"\s*текст гипотезы", _txt(h), re.I) and len(_txt(h)) < 40]
    cards = []
    for h in heads:
        box = h.find_parent(["div", "section", "details", "article"]) or h.parent
        for _ in range(4):            # widen to the whole card: the text and the reading may sit in two columns
            if re.search(r"(?i)механизм", _txt(box)) or box.parent is None:
                break
            box = box.parent
        labels = [_txt(x) for x in box.find_all(["li", "dt", "th", "b", "strong", "span", "td"])]
        fields = {k: any(re.match(p, l, re.I) for l in labels) for k, p in CARD_FIELDS.items()}
        cards.append(fields)
    boxes = []
    for h in heads:
        b = h.find_parent(["div", "section", "details", "article"]) or h.parent
        for _ in range(4):
            if re.search(r"(?i)механизм", _txt(b)) or b.parent is None:
                break
            b = b.parent
        boxes.append(b)
    mech = [h for b in boxes for h in b.find_all(["h2", "h3", "h4", "h5", "b", "strong", "div", "p"])
            if re.match(r"\s*механизм", _txt(h), re.I) and len(_txt(h)) < 40]
    steps = []
    for h in mech:
        lst = h.find_next(["ol", "ul"])
        steps += lst.find_all("li", recursive=False) if lst else []

    def plate(x) -> bool:
        return bool(re.search(r"subj|obj|bg-|plate|chip", " ".join(x.get("class") or [])) or "background" in (x.get("style") or ""))
    triples = [li for li in steps if "→" in _txt(li) and len([c for c in li.find_all(["span", "mark", "code"]) if plate(c) and _txt(c)]) >= 2]
    need = ("intervention", "population", "outcome")
    out["cards"] = {"understood_blocks": len(heads), "with_required_fields": sum(all(f[k] for k in need) for f in cards),
                    "with_comparator": sum(f["comparator"] for f in cards),
                    "legend": bool(re.search(r"(?i)что действует", text)), "mechanism_steps": len(steps),
                    "steps_as_triples": len(triples)}

    # 5. names: no bare codes in the visible text (a code in parentheses after a name is allowed)
    bare = {c: len(re.findall(rf"(?<![\w(`]){re.escape(c)}(?![\w)`])", text)) for c in CODES if "_" in c}
    whole = Counter(_txt(x) for x in soup.find_all(True) if not x.find(True))
    bare.update({c: whole[c] for c in CODES if "_" not in c})
    out["names"] = {"bare_codes": {c: n for c, n in bare.items() if n}, "bare_ids": len(re.findall(IDS, text))}

    out["pass"] = {
        "tabs": out["tabs"]["in_order"],
        "help_sections": all(v["collapsed_section"] for v in helpd.values()),
        "help_tables": all(v["tables"] or v["definition_list"] for k, v in helpd.items() if k != "provenance"),
        "reading_rules": out["help"]["reading"]["seven_rules"],
        "help_first_level": all(out["help_first_level"].values()),
        "scheme_steps": out["scheme"]["all_0_to_11"],
        "scheme_how_implemented": out["scheme"]["how_implemented"] >= 12,
        "scheme_no_formulas": out["scheme"]["formula_signs"] == 0,
        "card_fields": bool(cards) and out["cards"]["with_required_fields"] == len(cards),
        "mechanism_triples": out["cards"]["legend"] and bool(steps) and len(triples) == len(steps),
        "no_bare_codes": not out["names"]["bare_codes"] and out["names"]["bare_ids"] == 0,
    }
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report")
    ap.add_argument("--out")
    ap.add_argument("--no-render", action="store_true", help="parse the file as it is (a page without scripts)")
    a = ap.parse_args(argv)
    p = Path(a.report)
    r = {"html": p.read_text(encoding="utf-8"), "visible": {}} if a.no_render else render(p)
    res = check_html(r["html"], r["visible"])
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
