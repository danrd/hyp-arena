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
import posixpath
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
#
# A directory of docs/site/content/ with a `_page.md` is one documentation page (its path is the address): `_page.md`
# holds title, label (short name for the tree), group, lead and order; every other `*.md` of that directory is one
# section in file order. A section is an <h2> whose `##` headings become <h3>;
# a section with `flat: true` has no title of its own and its `##` headings are the page's <h2>.

PAGE_BASE = "docs"


def _front(text: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n*", text, re.S)
    if not m:
        raise ValueError("a documentation file starts with a front matter block (title, lead; sections also id)")
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def _anchor(i: str) -> str:
    return f'<a class="anchor" href="#{i}" aria-label="Ссылка на раздел">#</a>'


def _render_section(meta: dict, body: str, root: str) -> dict:
    """One section: its HTML, the id and title that go into the navigation."""
    import markdown
    flat = meta.get("flat") == "true"
    body = body.replace("{ROOT}", root)
    out = markdown.Markdown(extensions=["tables", "attr_list", "sane_lists", "fenced_code"]).convert(body)
    level = 2 if flat else 3
    out = re.sub(r'<h2 id="([^"]+)">(.*?)</h2>',
                 lambda m: f'<h{level} id="{m.group(1)}"{" data-sec" if flat else ""}>{m.group(2)} {_anchor(m.group(1))}</h{level}>', out)
    out = out.replace("<table>", '<div class="tablewrap"><table class="doctable">').replace("</table>", "</table></div>")
    out = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', out)
    if flat:
        heads = [(m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).replace(" #", "").strip())
                 for m in re.finditer(r'<h2 id="([^"]+)" data-sec>(.*?)</h2>', out)]
        return {"flat": True, "html": f'<div class="doc flat">{out}</div>', "nav": heads}
    sid = f'docs-{meta["id"]}'
    html_ = (f'<article class="doc" id="{sid}" data-sec><header class="doc-head"><h2>{html.escape(meta["title"])} {_anchor(sid)}</h2>'
             f'<p class="lead">{html.escape(meta.get("lead", ""))}</p></header>\n{out}\n</article>')
    return {"flat": False, "html": html_, "nav": [(sid, meta["title"])]}


def load_pages(content: Path = CONTENT) -> list[dict]:
    """Every documentation page in order, with its rendered sections."""
    content = Path(content)
    pages = []
    for pf in content.rglob("_page.md"):
        d = pf.parent
        slug = d.relative_to(content).as_posix()
        meta, _ = _front(pf.read_text(encoding="utf-8"))
        root = "../" * (len(slug.split("/")) + 1)         # from docs/<slug>/ to the home page
        secs = []
        for f in sorted(d.glob("*.md")):
            if f.name.startswith("_"):
                continue
            smeta, body = _front(f.read_text(encoding="utf-8"))
            secs.append(_render_section(smeta, body, root))
        pages.append({"slug": slug, "title": meta["title"], "label": meta.get("label", meta["title"]),
                      "group": meta.get("group", meta["title"]), "lead": meta.get("lead", ""), "order": int(meta.get("order", 99)),
                      "sections": secs, "nav": [n for sec in secs for n in sec["nav"]]})
    pages.sort(key=lambda p: p["order"])
    ids = re.findall(r'\sid="([^"]+)"', "".join(sec["html"] for p in pages for sec in p["sections"]))
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate anchors in the documentation: {', '.join(dup)}")
    return pages


def link_targets(pages: list[dict]) -> dict[str, str]:
    """Anchor id -> the page that holds it."""
    return {i: p["slug"] for p in pages for sec in p["sections"] for i in re.findall(r'\sid="([^"]+)"', sec["html"])}


START_GROUP = "Попробовать у себя"   # the page of commands stands apart from the explanation and the reference
LEGACY_IDS = {"docs-run": "start"}   # anchors of the one-page documentation that no longer exist as elements


def _rel(frm: str, to: str) -> str:
    """Relative address of page `to` as seen from page `frm` (both are slugs under docs/)."""
    r = posixpath.relpath(to, start=frm)
    return "./" if r == "." else r + "/"


def _tree(pages: list[dict], cur: int) -> str:
    items, last = [], None
    cs = pages[cur]["slug"]
    for i, p in enumerate(pages):
        if p["group"] != last:
            items.append(f'<li class="grp">{html.escape(p["group"])}</li>')
        last = p["group"]
        href = _rel(cs, p["slug"])
        if i == cur:
            subs = "".join(f'<li><a href="#{sid}" data-spy="{sid}">{html.escape(t)}</a></li>' for sid, t in p["nav"])
            items.append(f'<li class="current"><a href="{href}" aria-current="page">{html.escape(p["label"])}</a><ul>{subs}</ul></li>')
        else:
            items.append(f'<li><a href="{href}">{html.escape(p["label"])}</a></li>')
    return f'<ul class="tree">{"".join(items)}</ul>'


def render_page(pages: list[dict], cur: int, version: str, index_html: str, targets: dict[str, str]) -> str:
    """One standalone documentation page: the style of the home page, the navigation and the sections."""
    p = pages[cur]
    here = {i for sec in p["sections"] for i in re.findall(r'\sid="([^"]+)"', sec["html"])}
    body = "".join(sec["html"] for sec in p["sections"])
    cs = p["slug"]
    body = re.sub(r'href="#([^"]+)"', lambda m: m.group(0) if m.group(1) in here or m.group(1) not in targets
                  else f'href="{_rel(cs, targets[m.group(1)])}#{m.group(1)}"', body)
    up = "../" * (len(cs.split("/")) + 1)                    # to the home page
    docs_up = "../" * len(cs.split("/"))                     # to docs/
    groups = []
    for q in pages:
        if q["group"] not in [g[0] for g in groups]:
            groups.append((q["group"], q["slug"]))
    links = "\n".join(re.findall(r"<link [^>]*>", index_html))
    style = re.search(r"<style>.*?</style>", index_html, re.S).group(0)
    top = "".join(f'<a href="{docs_up}{slug}/"{" aria-current=\"page\"" if g == p["group"] else ""}>{html.escape(g)}</a>' for g, slug in groups)
    prev = (f'<a rel="prev" href="{_rel(cs, pages[cur - 1]["slug"])}"><small>Назад</small> {html.escape(pages[cur - 1]["title"])}</a>' if cur > 0
            else f'<a rel="prev" href="{up}"><small>Назад</small> На главную</a>')
    nxt = (f'<a rel="next" href="{_rel(cs, pages[cur + 1]["slug"])}"><small>Дальше</small> {html.escape(pages[cur + 1]["title"])}</a>' if cur + 1 < len(pages)
           else f'<a rel="next" href="{up}"><small>Дальше</small> На главную</a>')
    first = groups[0][1]
    gfirst = next(slug for g, slug in groups if g == p["group"])
    if p["group"] == START_GROUP:
        crumbs = f'<li><a href="{_rel(cs, p["slug"])}">{html.escape(p["group"])}</a></li>'
    else:
        crumbs = f'<li><a href="{_rel(cs, first)}">Документация</a></li>'
        if p["group"] != p["label"]:
            crumbs += f'<li><a href="{_rel(cs, gfirst)}">{html.escape(p["group"])}</a></li>'
        crumbs += f'<li><a href="./">{html.escape(p["label"])}</a></li>'
    aside = "".join(f'<li><a href="#{sid}" data-spy="{sid}">{html.escape(t)}</a></li>' for sid, t in p["nav"])
    tree = _tree(pages, cur)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(p["title"])} · Документация · Арена гипотез</title>
<meta name="description" content="{html.escape(p["lead"])}">
<meta property="og:type" content="website">
<meta property="og:title" content="{html.escape(p["title"])} · Документация · Арена гипотез о старении">
<meta property="og:description" content="{html.escape(p["lead"])}">
<meta property="og:url" content="https://danrd.github.io/hyp-arena/site/{PAGE_BASE}/{p["slug"]}/">
<meta property="og:locale" content="ru_RU">
<meta name="twitter:card" content="summary">
<meta name="hyparena-version" content="{version}">
{links}
{style}
<style>{DOCS_CSS}</style>
</head>
<body>
<a class="skip" href="#docMain">К содержанию</a>
<header class="top" id="topbar">
  <div class="wrap">
    <a class="brand" href="{up}">Арена гипотез</a>
    <nav class="sections" aria-label="Документация">
      <a href="{up}">На главную</a>{top}<a href="https://github.com/danrd/hyp-arena" target="_blank" rel="noopener">GitHub ↗</a>
    </nav>
  </div>
</header>
<div class="docbar" id="docBar">
  <button type="button" id="docBarBtn" aria-expanded="false" aria-controls="docDrawer"><span class="docbar-t" id="docBarTitle">{html.escape(p["title"])}</span><span aria-hidden="true">▾</span></button>
</div>
<div class="scrim" id="docScrim" hidden></div>
<div class="drawer" id="docDrawer" role="dialog" aria-modal="true" aria-label="Навигация по документации" hidden>
  <button type="button" class="drawer-close" id="docClose">Закрыть</button>
  <nav aria-label="Разделы документации">{tree}</nav>
</div>
<main class="wrap docs-wrap" id="top">
  <div class="docs-shell">
    <aside class="doc-side" id="docSide" aria-label="Разделы документации"><nav>{tree}</nav></aside>
    <div class="doc-main" id="docMain" tabindex="-1">
      <nav class="crumbs" aria-label="Хлебные крошки"><ol>
        {crumbs}<li id="crumbCur" hidden></li>
      </ol></nav>
      <header class="doc-page-head"><h1>{html.escape(p["title"])}</h1><p class="lead">{html.escape(p["lead"])}</p></header>
      <div class="docs-content">{body}</div>
      <nav class="pager" aria-label="Соседние страницы">{prev}{nxt}</nav>
    </div>
    <aside class="doc-aside" id="docAside" aria-labelledby="asideH"><h2 id="asideH">На этой странице</h2><ol>{aside}</ol></aside>
  </div>
</main>
<footer>
  <div class="wrap foot">
    <p><b>hyp-arena</b> · исследовательский прототип; рейтинги — результат исследования, а не медицинская рекомендация.</p>
    <dl class="footmeta"><div><dt>Версия кода</dt><dd>v{version}</dd></div><div><dt>Лицензия</dt><dd>MIT</dd></div></dl>
    <p class="footlinks"><a href="{up}">На главную</a> · <a href="https://github.com/danrd/hyp-arena" target="_blank" rel="noopener">GitHub</a></p>
  </div>
</footer>
<button type="button" class="totop" id="toTop" hidden aria-label="Наверх">↑</button>
<script>{DOCS_SCRIPT}</script>
</body>
</html>
"""


def redirect_page(pages: list[dict], targets: dict[str, str]) -> str:
    """docs/index.html of the one-page documentation: sends the old address and its anchors to the right page."""
    mapping = {**targets, **LEGACY_IDS}
    first = pages[0]["slug"]
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Документация · Арена гипотез</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<noscript><meta http-equiv="refresh" content="0; url={first}/"></noscript>
<script>
(() => {{
  const map = {json.dumps(mapping, ensure_ascii=False)};
  const legacy = {json.dumps(list(LEGACY_IDS))};
  const h = decodeURIComponent(location.hash.slice(1));
  const slug = map[h] || "{first}";
  location.replace(slug + "/" + (h && map[h] && !legacy.includes(h) ? "#" + h : ""));
}})();
</script></head>
<body><p><a href="{first}/">Документация</a></p></body></html>
"""


def code_version() -> str:
    import tomllib
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


DOCS_CSS = r"""
.skip { position: absolute; left: -999px; top: 0; background: var(--accent); color: var(--accent-ink); padding: 8px 12px; z-index: 30; }
.skip:focus { left: 8px; top: 8px; }
nav.sections a[aria-current="page"] { color: var(--accent); font-weight: 600; border-bottom-color: var(--accent); }
.docs-wrap { max-width: 1240px; padding-block: 18px 40px; }
.docs-shell { display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 36px; align-items: start; }
.doc-aside { display: none; }
@media (min-width: 1200px) { .docs-shell { grid-template-columns: 250px minmax(0, 1fr) 210px; } .doc-aside { display: block; } }
.doc-side, .doc-aside { position: sticky; top: calc(var(--hdr, 52px) + 16px); max-height: calc(100vh - var(--hdr, 52px) - 32px); overflow-y: auto; font-size: var(--step--1); overscroll-behavior: contain; scrollbar-width: thin; }
.doc-aside h2 { font-family: var(--body); font-size: var(--step--1); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 8px; }
.doc-aside ol { list-style: none; margin: 0; padding: 0; border-left: 1px solid var(--line); display: grid; gap: 2px; }
.doc-aside a, .tree a { color: var(--muted); text-decoration: none; display: block; padding: 4px 10px; border-radius: 4px; }
.doc-aside a { border-left: 2px solid transparent; margin-left: -1px; border-radius: 0; }
.doc-aside a:hover, .tree a:hover { color: var(--ink); }
.doc-aside a[aria-current], .tree ul a[aria-current] { color: var(--accent); font-weight: 600; }
.doc-aside a[aria-current] { border-left-color: var(--accent); }
.tree, .tree ul { list-style: none; margin: 0; padding: 0; }
.tree .grp { text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.72rem; color: var(--muted); padding: 14px 10px 4px; }
.tree > li > a { color: var(--ink); font-weight: 600; padding: 6px 10px; }
.tree > li.current > a { background: var(--accent-soft); color: var(--accent); }
.tree ul { margin: 2px 0 8px 10px; border-left: 1px solid var(--line); }
.tree ul a[aria-current] { background: var(--accent-soft); }
a:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.doc-main { min-width: 0; max-width: 80ch; outline: none; }
.crumbs ol { list-style: none; margin: 0 0 6px; padding: 0; display: flex; flex-wrap: wrap; gap: 4px; font-size: var(--step--1); color: var(--muted); }
.crumbs li + li::before { content: "›"; margin-right: 4px; }
.crumbs a { color: var(--muted); }
.doc-page-head { padding: 4px 0 20px; display: grid; gap: 6px; }
.doc-page-head h1 { font-size: var(--step-3); }
.doc-page-head .lead { color: var(--muted); margin: 0; }
.docs-content { display: grid; gap: 48px; min-width: 0; }
.docs-content .doc.flat { display: grid; gap: 14px; }
article.doc { display: grid; gap: 14px; min-width: 0; }
article.doc, .doc.flat h2[data-sec], article.doc h3 { scroll-margin-top: calc(var(--hdr, 52px) + var(--bar, 0px) + 14px); }
.doc-head h2, .doc.flat h2 { font-size: var(--step-2); margin: 0; }
.doc.flat h2 { margin-top: 18px; }
.doc .lead { color: var(--muted); font-size: var(--step-0); margin: 6px 0 0; }
article.doc h3 { font-family: var(--display); font-size: var(--step-1); font-weight: 600; margin: 14px 0 -4px; }
.doc .anchor { color: var(--line); text-decoration: none; margin-left: 4px; font-family: var(--body); font-weight: 400; font-size: 0.8em; }
.doc :is(h2, h3):hover .anchor, .doc .anchor:focus { color: var(--accent); }
.doc p { margin: 0; }
.doc ul, .doc ol { margin: 0; padding-left: 1.3em; display: grid; gap: 4px; }
.doc code { background: var(--idle-soft); padding: 0 4px; border-radius: 3px; }
.doc .tablewrap { border: 1px solid var(--line); border-radius: 6px; overflow-x: auto; }
table.doctable { border-collapse: collapse; width: 100%; font-size: var(--step--1); }
table.doctable th { text-align: left; font-weight: 600; background: var(--paper); color: var(--muted); }
table.doctable th, table.doctable td { padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
table.doctable tr:last-child td { border-bottom: 0; }
.codewrap { position: relative; }
.doc pre { margin: 0; padding: 40px 14px 12px; background: var(--paper); border: 1px solid var(--line); border-radius: 5px; overflow-x: auto; font-family: var(--mono); font-size: var(--step--1); scrollbar-width: thin; }
.doc pre code { background: none; padding: 0; }
.codewrap .copy { position: absolute; top: 6px; right: 6px; font-size: 0.72rem; padding: 3px 9px; }
.pager { display: flex; justify-content: space-between; gap: 12px; margin-top: 48px; padding-top: 18px; border-top: 1px solid var(--line); }
.pager a { display: grid; gap: 2px; text-decoration: none; color: var(--ink); font-weight: 600; padding: 10px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); min-width: 0; }
.pager a[rel="next"] { text-align: right; margin-left: auto; }
.pager a:hover { border-color: var(--accent); }
.pager small { color: var(--muted); font-weight: 400; }
.docbar, .drawer, .scrim { display: none; }
.totop { position: fixed; right: max(16px, env(safe-area-inset-right, 0px)); bottom: max(16px, env(safe-area-inset-bottom, 0px)); width: 44px; height: 44px; border-radius: 50%; border: 1px solid var(--line); background: var(--surface); color: var(--ink); font-size: 1.2rem; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.18); z-index: 12; }
.totop[hidden] { display: none; }
@media (max-width: 900px) {
  .docs-shell { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .doc-side { display: none; }
  .docbar { display: block; position: sticky; top: var(--hdr, 52px); z-index: 8; background: var(--surface); border-bottom: 1px solid var(--line); }
  .docbar button { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 11px max(16px, env(safe-area-inset-left, 0px)); border: 0; border-radius: 0; background: transparent; font-weight: 600; text-align: left; }
  .docbar-t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .docbar button[aria-expanded="true"] span[aria-hidden] { transform: rotate(180deg); }
  .scrim:not([hidden]) { display: block; position: fixed; inset: 0; background: rgba(0,0,0,0.45); z-index: 20; }
  .drawer:not([hidden]) { display: block; position: fixed; z-index: 21; left: 0; right: 0; top: calc(var(--hdr, 52px) + var(--bar, 0px)); max-height: calc(100vh - var(--hdr, 52px) - var(--bar, 0px) - 24px); overflow-y: auto; background: var(--surface); border-bottom: 1px solid var(--line); box-shadow: 0 8px 24px rgba(0,0,0,0.25); padding: 8px max(16px, env(safe-area-inset-left, 0px)) 16px; }
  .drawer-close { margin: 4px 0 8px auto; display: block; font-size: var(--step--1); }
  .tree a { padding: 9px 10px; }
  .doc pre { white-space: pre-wrap; overflow-wrap: anywhere; }
  .doc-page-head h1 { font-size: var(--step-2); }
  .pager { flex-direction: column; }
  .pager a[rel="next"] { text-align: left; margin-left: 0; }
}
"""

DOCS_SCRIPT = r"""
(() => {
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const top = $("#topbar"), bar = $("#docBar");
  const setVars = () => {
    document.documentElement.style.setProperty("--hdr", top.offsetHeight + "px");
    document.documentElement.style.setProperty("--bar", (getComputedStyle(bar).display === "none" ? 0 : bar.offsetHeight) + "px");
  };
  setVars(); addEventListener("resize", setVars);

  /* the section in view: the last section heading above the reading line */
  const secs = $$("[data-sec]");
  const links = $$("[data-spy]");
  const crumb = $("#crumbCur"), barTitle = $("#docBarTitle"), pageTitle = barTitle.textContent;
  const titleOf = el => (el.querySelector("h2") || el).firstChild.textContent.trim();
  let active = null;
  const reveal = (a) => {                     // keep the active item visible inside a scrolling panel
    const box = a.closest(".doc-side, .doc-aside"); if (!box || box.offsetParent === null) return;
    const r = a.getBoundingClientRect(), b = box.getBoundingClientRect();
    if (r.top < b.top + 8) box.scrollTop -= b.top + 8 - r.top; else if (r.bottom > b.bottom - 8) box.scrollTop += r.bottom - b.bottom + 8;
  };
  const spy = () => {
    const line = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--hdr")) + (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--bar")) || 0) + 40;
    let cur = null;
    for (const s of secs) { if (s.getBoundingClientRect().top <= line) cur = s; else break; }
    if (cur === active) return; active = cur;
    links.forEach(a => { const on = cur && a.dataset.spy === cur.id; if (on) { a.setAttribute("aria-current", "location"); reveal(a); } else a.removeAttribute("aria-current"); });
    const t = cur ? titleOf(cur) : "";
    crumb.hidden = !t; crumb.textContent = t;
    barTitle.textContent = t || pageTitle;
  };
  let tick = false;
  addEventListener("scroll", () => { if (!tick) { tick = true; requestAnimationFrame(() => { tick = false; spy(); toggleTop(); }); } }, {passive: true});
  addEventListener("hashchange", () => setTimeout(spy, 60));

  /* mobile drawer */
  const btn = $("#docBarBtn"), drawer = $("#docDrawer"), scrim = $("#docScrim");
  const open = () => { drawer.hidden = false; scrim.hidden = false; btn.setAttribute("aria-expanded", "true"); (drawer.querySelector("a[aria-current]") || drawer.querySelector("a") || drawer).focus(); };
  const close = (back = true) => { drawer.hidden = true; scrim.hidden = true; btn.setAttribute("aria-expanded", "false"); if (back) btn.focus(); };
  btn.addEventListener("click", () => drawer.hidden ? open() : close());
  scrim.addEventListener("click", () => close());
  $("#docClose").addEventListener("click", () => close());
  drawer.addEventListener("click", e => { if (e.target.closest("a")) close(false); });
  document.addEventListener("keydown", e => {
    if (drawer.hidden) return;
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key === "Tab") {                    // keep focus inside the open panel
      const f = [...drawer.querySelectorAll("a, button")]; if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  matchMedia("(min-width: 901px)").addEventListener?.("change", e => { if (e.matches) close(false); });

  /* back to top after a couple of screens */
  const totop = $("#toTop");
  const toggleTop = () => { totop.hidden = scrollY < innerHeight * 2; };
  totop.addEventListener("click", () => { scrollTo({top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"}); });

  /* copy buttons on command blocks */
  $$(".doc pre").forEach(pre => {
    const wrap = document.createElement("div"); wrap.className = "codewrap";
    pre.replaceWith(wrap); wrap.appendChild(pre);
    const b = document.createElement("button"); b.type = "button"; b.className = "copy"; b.textContent = "Копировать";
    b.addEventListener("click", () => {
      const done = ok => { b.textContent = ok ? "Скопировано" : "Выделите вручную"; setTimeout(() => { b.textContent = "Копировать"; }, 1800); };
      try { navigator.clipboard.writeText(pre.textContent).then(() => done(true), () => done(false)); } catch { done(false); }
    });
    wrap.appendChild(b);
  });
  spy(); toggleTop();
})();
"""


def build(page: Path = PAGE, content: Path = CONTENT, out: Path | None = None) -> None:
    """Render docs/site/content/<page>/*.md into docs/site/docs/<page>/index.html, the redirect at docs/index.html,
    and stamp the code version on the home page."""
    out = out or page.parent / PAGE_BASE
    s = page.read_text(encoding="utf-8")
    version = code_version()
    s, n = re.subn(r'(<meta name="hyparena-version" content=")[^"]*(")', lambda m: m.group(1) + version + m.group(2), s, count=1)
    if n != 1:
        raise ValueError('the page has no <meta name="hyparena-version"> tag')
    page.write_text(s, encoding="utf-8")
    pages = load_pages(content)
    targets = link_targets(pages)
    for i, p in enumerate(pages):
        (out / p["slug"]).mkdir(parents=True, exist_ok=True)
        (out / p["slug"] / "index.html").write_text(render_page(pages, i, version, s, targets), encoding="utf-8")
    (out / "index.html").write_text(redirect_page(pages, targets), encoding="utf-8")


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
    sub.add_parser("build", help="render docs/site/content/<page>/*.md into docs/site/docs/<page>/index.html")
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
