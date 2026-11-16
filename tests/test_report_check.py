"""The form check of an outside report (scripts/argon/report_check.py) on synthetic pages: it reports names and counts only."""
from scripts.argon import report_check as rc

HELP = "".join(f"<details><summary>{n}</summary><table><tr><th>a</th></tr>{rows}</table></details>" for n, rows in [
    ("Вес записи", "<tr><td>x</td></tr>"), ("Сила звена и баланс доказательств", "<tr><td>x</td></tr>"),
    ("Правила прочтения записи", "<tr><td>x</td></tr>" * 7), ("Новизна", "<tr><td>x</td></tr>"),
    ("Эксперимент, размах, реализуемость", "<tr><td>x</td></tr>"), ("Профили и АСПИД", "<tr><td>x</td></tr>"),
    ("Что поднимет оценку и версии", "<tr><td>x</td></tr>")]) + \
    "<details><summary>Происхождение</summary><p>p</p></details><details><summary>Словарь параметров</summary><dl><dt>a</dt></dl></details>"
GOOD = f"""<nav><button>Рейтинг</button><button>Карточки гипотез</button><button>Оценка</button><button>Схема работы</button>
<button>Справка</button></nav>
<div><h3>Как гипотеза понята</h3><ul><li>Вмешательство: X</li><li>Популяция: Y</li><li>Исход: Z</li></ul>
<h3>Механизм по шагам</h3><p><span class="subj">что действует</span> <span class="rel">как →</span> <span class="obj">на что</span></p>
<ol><li><span class="subj">A</span> <span class="rel">activates →</span> <span class="obj">B</span></li></ol></div>
<section><h2>Схема работы</h2>{''.join(f'<p>Шаг {i}. Что делает. Как реализовано: код.</p>' for i in range(12))}
<p>{'длинный текст ' * 40}</p></section>
<div><h2>Как читать отчёт</h2><p>Карточка гипотезы. Это не прогноз. Проспективный пул.</p>{HELP}</div>"""


def test_good_page_passes_every_item():
    r = rc.check_html(GOOD)
    assert all(r["pass"].values()), {k: v for k, v in r["pass"].items() if not v}


def test_defects_are_found_and_no_text_is_returned():
    bad = (GOOD.replace("Правила прочтения записи", "Чтение").replace("Шаг 11.", "")
           .replace('<span class="obj">B</span>', "B").replace("Вмешательство: X", "X")
           .replace("Как реализовано: код.</p>", "S = 1 / (1 + exp(-x))</p>", 1) + "<span>contested_link</span><span>outcome</span>")
    r = rc.check_html(bad)
    p = r["pass"]
    assert not p["reading_rules"] and not p["scheme_steps"] and not p["scheme_no_formulas"]
    assert not p["mechanism_triples"] and not p["card_fields"] and not p["no_bare_codes"] and not p["help_sections"]
    assert r["names"]["bare_codes"] == {"contested_link": 1, "outcome": 1}
    flat = str(r)
    assert "activates" not in flat and "exp(" not in flat and "длинный" not in flat   # numbers and our names only
