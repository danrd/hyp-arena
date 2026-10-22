"""Data bundle and build for the site (docs/site/index.html).

    python -m hyparena.site export --v2 runs/x.v2.json --elo runs/neg/L0_s0/g003.json --pool data/negatives/drugage/g003.json --out runs/site/g003.json
    python -m hyparena.site embed --bundle runs/site/g003.json                  # the page's built-in example run
    python -m hyparena.site examples --out runs/site/examples.json              # the five worked cards of the documentation
    python -m hyparena.site embed --bundle runs/site/examples.json --key examples
    python -m hyparena.site build                                               # docs/site/content/*.md -> the page

`export` writes one JSON bundle with the hypotheses of a v2 run, their cards and verification, the ranking under
each preference profile and, when given, the Elo ranking of a tournament run on the same texts. `--pool` names the
input file of both runs: its ids join the tournament's results to the v2 items (the i-th text of the pool is the
i-th item of the v2 run). Without it the v2 item ids are used and `--elo` is ignored. `build` renders the
markdown pages of the documentation into the page between the markers `<!--docs:begin-->` and `<!--docs:end-->`
(needs the `markdown` package: `pip install -e ".[site]"`)."""
from __future__ import annotations

import argparse
import html
import json
import re
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "site" / "index.html"
CONTENT = ROOT / "docs" / "site" / "content"
FIXTURES = ROOT / "tests" / "fixtures" / "cards"
QUOTE_MAX = 500
RECORDS_MAX = 12                     # per claim and side; the count of the rest is kept


def _title(text: str) -> str:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), text.strip())
    first = re.sub(r"^(?:Hypothesis|Title)\s*:\s*", "", first)
    return first if len(first) <= 140 else first[:137] + "..."


def _record(r: dict) -> dict:
    out = {k: r.get(k) for k in ("source", "record_id", "linked_pmid", "species", "strain", "sex", "dose", "endpoint",
                                 "effect", "effect_percent", "study_type", "quote_role", "human_rungs", "flags")}
    out["quote"] = (r.get("quote") or "")[:QUOTE_MAX]
    out["intervention_match"] = (r.get("qualifiers_match") or {}).get("intervention_match", "")
    out["mismatch"] = [k for k, v in (r.get("qualifiers_match") or {}).items() if v == "no" and k != "intervention_match"]
    return {k: v for k, v in out.items() if v not in (None, "", [], "unknown")}


def _records(rs: list) -> dict:
    return {"items": [_record(r) for r in rs[:RECORDS_MAX]], "more": max(0, len(rs) - RECORDS_MAX)}


def _claim(c: dict) -> dict:
    return {"id": c["id"], "role": c.get("role"), "relation": c.get("relation"), "subject": c["subject"]["label"],
            "object": c["object"]["label"], "qualifiers": {k: v for k, v in (c.get("qualifiers") or {}).items()
                                                            if v and v != "unknown"},
            "inherited": c.get("inherited_from_pico") or [], "span": c.get("source_span", ""), "note": c.get("note", "")}


def _item(x: dict, pid: str) -> dict:
    card, ver = x.get("card") or {}, x.get("verification") or {}
    claims = {c["id"]: c for c in card.get("claims", []) + card.get("declared_alternatives", [])}
    verified = []
    for cv in ver.get("claims", []):
        c = cv.get("claim") or claims.get(cv["id"])
        verified.append({"id": cv["id"], "claim": _claim(c) if c else None, "status": cv.get("status"),
                         "rung_status": cv.get("rung_status") or {}, "flags": cv.get("flags") or [],
                         "contrast": cv.get("contrast") or {}, "notes": cv.get("notes", ""),
                         "evidence": _records(cv.get("evidence", [])), "counter": _records(cv.get("counterevidence", [])),
                         "refusals": [{k: r.get(k) for k in ("type", "record_id", "notes")} for r in cv.get("refusals", [])]})
    p = card.get("pico") or {}
    return {"id": pid, "card_id": x["id"], "title": _title(x["text"]), "text": x["text"], "outcome": x["outcome"],
            "duplicate_of": x.get("duplicate_of"), "repeats": x.get("repeats", 0),
            "admission": x.get("admission"), "problems": x.get("problems") or [],
            "card": {"claim_plain": card.get("claim_plain", ""), "type": card.get("hypothesis_type", ""),
                     "population": p.get("population"), "intervention": p.get("intervention"),
                     "comparator": p.get("comparator"), "outcome": p.get("outcome"),
                     "claims": [_claim(c) for c in card.get("claims", [])],
                     "alternatives_declared": [_claim(c) for c in card.get("declared_alternatives", [])],
                     "decisive_experiment": card.get("decisive_experiment")} if card else None,
            "verification": {"claims": verified, "profile": ver.get("evidence_profile"),
                             "known_result": ver.get("known_result"),
                             "alternatives": [{k: a.get(k) for k in ("id", "type", "source", "status", "explanation",
                                                                     "discriminating_design", "record_id", "quote")}
                                              for a in ver.get("alternatives", [])],
                             "searched": len(ver.get("searched_pmids") or [])} if ver else None,
            "indicators": x.get("indicators")}


def bundle_from_result(res: dict, ids: list[str], elo: Optional[dict] = None, title: str = "") -> dict:
    """The site bundle of a v2 result (the dict `hyparena.card.pipeline.run` returns). `ids[i]` names the i-th item;
    `elo` is a tournament result in the ladder format whose hypothesis ids are `ids`."""
    to_pid = {x["id"]: pid for x, pid in zip(res["items"], ids)}
    items = [_item(x, pid) for x, pid in zip(res["items"], ids)]
    for it in items:
        if it["duplicate_of"]:
            it["duplicate_of"] = to_pid.get(it["duplicate_of"], it["duplicate_of"])
    profiles = {}
    for name, r in (res.get("ranking") or {}).items():
        profiles[name] = {"order": [to_pid[h] for h in r["order"]],
                          "expected": {to_pid[h]: v for h, v in r["expected"].items()},
                          "std": {to_pid[h]: v for h, v in (r.get("std") or {}).items()},
                          "quantiles": {to_pid[h]: v for h, v in r["quantiles"].items()},
                          "p_topk": {to_pid[h]: v for h, v in r["p_topk"].items()},
                          "p_best": {to_pid[h]: v for h, v in r["p_best"].items()},
                          "pairwise": {to_pid[a]: {to_pid[b]: p for b, p in row.items()} for a, row in r["pairwise"].items()},
                          "k": r.get("meta", {}).get("k_top") or res["meta"].get("k_top"),
                          "K": r.get("meta", {}).get("K"),
                          "mc_halfwidth": r.get("meta", {}).get("mc_halfwidth_max")}
    elo_out = None
    if elo:
        keep = set(ids)
        elo_out = {"rating": elo["config"].get("rating"), "config": elo["config"], "matches": elo.get("matches"),
                   "as_of": elo.get("as_of"), "families": elo.get("families"),
                   "ratings": {h: {"rating": v.get("combined"), "status": v.get("status"),
                                   "games": ((v.get("scores") or {}).get("overall") or {}).get("games")}
                               for h, v in elo["hypotheses"].items() if h in keep}}
    meta = res["meta"]
    return {"format": "hyparena-site@1", "title": title,
            "meta": {"created": meta.get("created"), "as_of": meta.get("as_of"), "calls": meta.get("calls"),
                     "verifiers": meta.get("verifiers"), "profiles": meta.get("profiles"),
                     "indicators": meta.get("indicators"), "k_top": meta.get("k_top")},
            "hypotheses": items, "profiles": profiles, "elo": elo_out,
            "lists": {"filtered": {to_pid.get(h, h): r for h, r in (res.get("filtered") or {}).items()},
                      "known_results": [to_pid.get(h, h) for h in res.get("known_results") or []],
                      "outcome_counts": res.get("outcome_counts")}}


def export(v2_path: str, elo_path: Optional[str] = None, pool_path: Optional[str] = None,
           title: str = "") -> dict:
    res = json.loads(Path(v2_path).read_text())
    ids = [x["id"] for x in res["items"]]
    if pool_path:
        from hyparena.data import load_imported
        ids = [h.id for h in load_imported(pool_path)][:len(res["items"])]
    elo = json.loads(Path(elo_path).read_text()) if elo_path and pool_path else None
    return bundle_from_result(res, ids, elo, title or Path(v2_path).stem)


def embed(bundle_path: str, page: Path = PAGE, key: str = "sample") -> None:
    """Replace a built-in bundle of the page: `sample` (the example run) or `examples` (the worked cards)."""
    s = page.read_text(encoding="utf-8")
    data = json.dumps(json.loads(Path(bundle_path).read_text()), ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    new, n = re.subn(rf'(<script id="{re.escape(key)}" type="application/json">).*?(</script>)',
                     lambda m: m.group(1) + data + m.group(2), s, count=1, flags=re.S)
    if n != 1:
        raise ValueError(f'the page has no <script id="{key}" type="application/json"> block')
    page.write_text(new, encoding="utf-8")


# ---- the worked cards of the documentation ----

EXAMPLES = [("ex1", "ex1_rapamycin_healthspan", "Пример 1 · Рапамицин и здоровая продолжительность жизни у людей"),
            ("ex2", "ex2_senolytics_function", "Пример 2 · Сенолитики и физическая функция"),
            ("ex3", "ex3_rapamycin_mechanism", "Пример 3 · Почему рапамицин продлевает жизнь (контраст)"),
            ("ex5", "ex5_resveratrol_endpoint", "Пример 5 · Ресвератрол и продолжительность жизни мышей")]
NOT_A_HYPOTHESIS = ("No intervention and no measurable outcome; as stated it cannot be refuted by one experiment. "
                    "Stored as a direction, not ranked.")


def examples_bundle(k_top: int = 2, K: int = 10000) -> dict:
    """The five worked cards (tests/fixtures/cards: declared and verified layers written by hand, quotes verbatim
    from PubMed abstracts) in the site format, ranked under every profile, plus the admission cases of Example 4."""
    import yaml

    from hyparena.aspid import load_profiles
    from hyparena.card import indicators as ind
    from hyparena.card.models import HypothesisCard, Verification
    from hyparena.card.rank import rank
    from hyparena.card.rules import finalize

    def load(name):
        return yaml.safe_load((FIXTURES / f"{name}.yaml").read_text(encoding="utf-8"))

    def extra_of(card):
        try:
            from hyparena.card.pipeline import _extra
            return _extra(card, None)
        except Exception:                                        # offline: path_to_human stays unknown
            return {}

    items, ids, titles, triples = [], [], {}, []
    ex4 = {c["name"]: c for c in load("ex4_admission")["cases"]}
    cases = [(pid, load(name), title) for pid, name, title in EXAMPLES]
    known = ex4["R-0004a known result"]
    cases.append(("ex4a", known, "Пример 4 · Уточнённый вариант: известный результат"))
    for pid, d, title in cases:
        card = HypothesisCard.model_validate(d["card"])
        ver = finalize(card, Verification.model_validate(d["verification"]))
        extra = extra_of(card)
        outcome = "filtered" if ver.evidence_profile.gate == "filtered" else "known_result" if ver.known_result else "ranked"
        items.append({"id": card.id, "text": d["raw"], "outcome": outcome, "duplicate_of": None, "repeats": 0,
                      "card": card.model_dump(by_alias=True), "verification": ver.model_dump(by_alias=True),
                      "indicators": ind.compute(card, ver, extra) if outcome == "ranked" else None,
                      "admission": None, "problems": []})
        ids.append(pid)
        titles[pid] = title
        triples.append((card, ver, extra))
    for pid, name, title, missing, reason in (
            ("ex4", "R-0004 vague", "Пример 4 · Расплывчатая гипотеза: нужно уточнение", ex4["R-0004 vague"]["expected"]["missing"], ""),
            ("ex4n", "R-0005 not a hypothesis", "Пример 4 · Не гипотеза", [], NOT_A_HYPOTHESIS)):
        decision = ex4[name]["expected"]["decision"]
        items.append({"id": pid.upper(), "text": ex4[name]["raw"], "outcome": decision, "duplicate_of": None, "repeats": 0,
                      "card": None, "verification": None, "indicators": None, "problems": [],
                      "admission": {"decision": decision, "missing_critical": missing, "reason": reason}})
        ids.append(pid)
        titles[pid] = title
    ranking = rank(triples, K=K, k_top=k_top)
    view = lambda r: {"order": r.order, "expected": r.expected, "std": r.std, "quantiles": r.quantiles, "p_topk": r.p_topk,
                      "p_best": r.p_best, "pairwise": r.pairwise, "meta": r.meta}
    # the ranking is keyed by card id; item ids of the bundle follow `ids`
    res = {"meta": {"created": time.strftime("%Y-%m-%d"), "as_of": None, "calls": 0, "verifiers": [], "k_top": k_top,
                    "profiles": {n: {"tiers": p.tiers, "version": p.version, "description": p.description}
                                 for n, p in load_profiles().items()},
                    "indicators": [{"id": s.id, "kind": s.kind, "levels": list(s.levels), "bounds": list(s.bounds), "note": s.note}
                                   for s in ind.INDICATORS]},
           "items": items, "ranking": {n: view(r) for n, r in ranking.by_profile.items()},
           "filtered": ranking.filtered, "known_results": ranking.known_results,
           "outcome_counts": {o: sum(1 for x in items if x["outcome"] == o) for o in
                              ("ranked", "filtered", "known_result", "needs_refinement", "not_a_hypothesis")}}
    bundle = bundle_from_result(res, ids, None, "Примеры из документации")
    for h in bundle["hypotheses"]:
        h["title"] = titles[h["id"]]
    return bundle


# ---- documentation pages ----

def _front(text: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n+", text, re.S)
    if not m:
        raise ValueError("a documentation page starts with a front matter block (id, title, lead)")
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def _render_page(meta: dict, body: str) -> tuple[str, list[tuple[str, str]]]:
    """The HTML of one documentation page and its second-level headings [(id, text)]."""
    import markdown
    md = markdown.Markdown(extensions=["tables", "attr_list", "sane_lists", "fenced_code"])
    out = md.convert(body)
    heads = [(m.group(1), re.sub(r"<[^>]+>", "", m.group(2))) for m in re.finditer(r'<h2 id="([^"]+)">(.*?)</h2>', out)]
    out = re.sub(r'<h2 id="([^"]+)">(.*?)</h2>',
                 lambda m: f'<h4 id="{m.group(1)}">{m.group(2)} <a class="anchor" href="#{m.group(1)}" aria-label="Ссылка на раздел">#</a></h4>', out)
    out = re.sub(r"<table>", '<div class="tablewrap"><table class="doctable">', out)
    out = out.replace("</table>", "</table></div>")
    out = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', out)
    page = (f'<article class="doc" id="docs-{meta["id"]}"><header class="doc-head"><h3>{html.escape(meta["title"])}</h3>'
            f'<p class="lead">{html.escape(meta.get("lead", ""))}</p></header>\n{out}\n</article>')
    return page, heads


def render_docs(content: Path = CONTENT) -> str:
    """The documentation section body: a table of contents and every page of `content/*.md`, in file order."""
    pages, toc = [], []
    for f in sorted(Path(content).glob("*.md")):
        meta, body = _front(f.read_text(encoding="utf-8"))
        page, heads = _render_page(meta, body)
        pages.append(page)
        toc.append(f'<li><a href="#docs-{meta["id"]}">{html.escape(meta["title"])}</a><ul>'
                   + "".join(f'<li><a href="#{i}">{html.escape(t)}</a></li>' for i, t in heads) + "</ul></li>")
    ids = re.findall(r'\sid="([^"]+)"', "".join(pages))
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate anchors in the documentation: {', '.join(dup)}")
    return ('<div class="docs-layout"><details class="doc-toc-wrap" id="docToc"><summary>Оглавление</summary>'
            f'<nav class="doc-toc" aria-label="Оглавление документации"><ol>{"".join(toc)}</ol></nav></details>'
            f'<div class="docs-content">{"".join(pages)}</div></div>')


def code_version() -> str:
    import tomllib
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


DOCS_SCRIPT = """
(() => {
  const toc = document.getElementById("docToc");
  const wide = matchMedia("(min-width: 901px)");
  const setOpen = () => { toc.open = wide.matches; };
  setOpen(); wide.addEventListener?.("change", setOpen);
  toc.addEventListener("click", e => { if (e.target.closest("a") && !wide.matches) toc.open = false; });
  const links = new Map([...toc.querySelectorAll("a[href^='#']")].map(a => [a.getAttribute("href").slice(1), a]));
  const targets = [...document.querySelectorAll("article.doc, article.doc h4[id]")];
  const mark = id => links.forEach((a, k) => k === id ? a.setAttribute("aria-current", "true") : a.removeAttribute("aria-current"));
  if ("IntersectionObserver" in window) {
    const seen = new Set();
    const io = new IntersectionObserver(es => {
      es.forEach(en => en.isIntersecting ? seen.add(en.target) : seen.delete(en.target));
      const first = targets.find(t => seen.has(t) && t.tagName === "H4") || targets.find(t => seen.has(t));
      mark(first ? first.id : null);
    }, {rootMargin: "-70px 0px -65% 0px"});
    targets.forEach(t => io.observe(t));
  }
  document.querySelectorAll("article.doc pre").forEach(pre => {
    pre.title = "Нажмите, чтобы скопировать";
    pre.addEventListener("click", () => { try { navigator.clipboard.writeText(pre.textContent); } catch { /* selection stays available */ } });
  });
})();
"""


def docs_page(index_html: str, docs: str, version: str) -> str:
    """The standalone documentation page: the style sheet and fonts of the home page, the pages of `content/`."""
    links = "\n".join(re.findall(r"<link [^>]*>", index_html))
    style = re.search(r"<style>.*?</style>", index_html, re.S).group(0)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Документация · Арена гипотез</title>
<meta name="description" content="Карточка гипотезы, статусы и правила проверки, показатели, профили и АСПИД, данные, примеры, запуск и границы применимости.">
<meta property="og:type" content="website">
<meta property="og:title" content="Документация · Арена гипотез о старении">
<meta property="og:description" content="Как гипотеза превращается в карточку, как проверяются утверждения и как считается рейтинг.">
<meta property="og:url" content="https://danrd.github.io/hyp-arena/site/docs/">
<meta property="og:locale" content="ru_RU">
<meta name="twitter:card" content="summary">
<meta name="hyparena-version" content="{version}">
{links}
{style}
</head>
<body>
<header class="top">
  <div class="wrap">
    <a class="brand" href="../">Арена гипотез</a>
    <nav class="sections" aria-label="Разделы">
      <a href="../">На главную</a><a href="https://github.com/danrd/hyp-arena" target="_blank" rel="noopener">GitHub ↗</a>
    </nav>
  </div>
</header>
<main class="wrap" id="top">
  <div class="doc-page-head"><p class="eyebrow">Документация</p><h1>Как это устроено</h1>
    <p class="muted"><a href="../">На главную</a></p></div>
  <section class="block" id="docs">{docs}</section>
</main>
<footer>
  <div class="wrap foot">
    <p><b>hyp-arena</b> · исследовательский прототип; рейтинги — результат исследования, а не медицинская рекомендация.</p>
    <dl class="footmeta"><div><dt>Версия кода</dt><dd>v{version}</dd></div><div><dt>Лицензия</dt><dd>MIT</dd></div></dl>
    <p class="footlinks"><a href="../">На главную</a> · <a href="https://github.com/danrd/hyp-arena" target="_blank" rel="noopener">GitHub</a></p>
  </div>
</footer>
<script>{DOCS_SCRIPT}</script>
</body>
</html>
"""


def build(page: Path = PAGE, content: Path = CONTENT, out: Path | None = None) -> None:
    """Render docs/site/content/*.md into the standalone documentation page and stamp the code version on both pages."""
    out = out or page.parent / "docs" / "index.html"
    s = page.read_text(encoding="utf-8")
    version = code_version()
    s, n = re.subn(r'(<meta name="hyparena-version" content=")[^"]*(")', lambda m: m.group(1) + version + m.group(2), s, count=1)
    if n != 1:
        raise ValueError('the page has no <meta name="hyparena-version"> tag')
    page.write_text(s, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(docs_page(s, render_docs(content), version), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--v2", required=True, help="full v2 output (hyparena.card.pipeline)")
    e.add_argument("--elo", default=None, help="tournament result on the same texts (ladder format)")
    e.add_argument("--pool", default=None, help="the input file of both runs")
    e.add_argument("--title", default="")
    e.add_argument("--out", required=True)
    x = sub.add_parser("examples", help="bundle of the worked cards of the documentation")
    x.add_argument("--out", required=True)
    m = sub.add_parser("embed")
    m.add_argument("--bundle", required=True)
    m.add_argument("--key", default="sample", choices=["sample", "examples"])
    sub.add_parser("build", help="render docs/site/content/*.md into docs/site/docs/index.html")
    a = ap.parse_args()
    if a.cmd == "export":
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(export(a.v2, a.elo, a.pool, a.title), ensure_ascii=False, indent=1))
        print(a.out)
    elif a.cmd == "examples":
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(examples_bundle(), ensure_ascii=False, indent=1))
        print(a.out)
    elif a.cmd == "build":
        build()
    else:
        embed(a.bundle, key=a.key)


if __name__ == "__main__":
    main()
