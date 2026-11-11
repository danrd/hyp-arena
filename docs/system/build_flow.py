"""Builds the flow scheme of the system (method v3.9): a base for a paper or a slide, and optional layers.

User decisions 2026-11-11: left to right, Russian for now; the base is simple, as in the report (stage name + what comes out);
the rest is optional by purpose: the implementation layer (LLM and code), the check layer (one block, two parts: our own
checks and against a plain-LLM baseline), the reasons layer. Stages are balanced by content; only the record weight and the
link strength are one stage (both are the summary of the evidence); different things are not grouped.

    python docs/system/build_flow.py      # writes flow_<variant>.drawio for every variant in VARIANTS

PNG: render each .drawio with mxgraph (see docs/system/README or the session notes)."""
from pathlib import Path
from xml.sax.saxutils import escape

D = Path(__file__).resolve().parent

# stage: name, kind ("llm" = a language model with code checks, "code" = code only), base lines, layers
STAGES = [
    dict(name="1. Гипотезы на входе", kind="llm",
         base=["Записи реестров испытаний, гипотезы, созданные по теме, улучшенные версии.",
               "Дата среза T: всё, что вышло позже, системе недоступно."],
         llm=["Пишет гипотезу по теме в одном из режимов: свободно, по шаблону карточки или под цель профиля."],
         code=['Берёт поля реестра, включая дизайн, группы и плановую выборку; созданную гипотезу проверяет по требованиям режима; дубль отправляет переписать один раз.'],
         own=["Разнообразие пула; внешний читатель: новизна, правдоподобие, проверяемость."],
         base_llm=["LLM пишет гипотезы по той же теме; 5 судей других семей сравнивают попарно."],
         why=["У гипотез из реестров есть дата и будущий исход: отбор проверяется без утечки."]),
    dict(name="2. Карточка гипотезы", basis="PICO [1]; типы звеньев — адаптация «трёх опор» [2] и пути неблагоприятного исхода (AOP) [3]", kind="llm",
         base=["Текст → вмешательство, популяция, исход, эксперимент.",
               "Механизм — цепочка звеньев «субъект — отношение — объект»."],
         llm=['Разбирает текст по схеме и закрытым спискам; два независимых разбора при температуре 0.'],
         code=['Проверяет схему и дословность опор; при ошибке возвращает модели её ответ со списком ошибок (до 3 попыток); звено без дословной опоры выбрасывает; объединяет два разбора.'],
         own=["Тот же текст в другом стиле → та же карточка; ручная разметка механизма."],
         base_llm=["LLM по той же схеме против той же ручной разметки."],
         why=["Ценность гипотезы — в механизме: каждое звено проверяется отдельно."]),
    dict(name="3. Поиск статей", kind="llm",
         base=["Для каждого звена — статьи PubMed, вышедшие до даты среза."],
         llm=['Пишет 4 запроса PubMed на звено; слова исхода, названия испытаний и авторы запрещены.'],
         code=['Выполняет запросы до даты среза; добавляет ссылки и цитирования 5 лучших статей; добирает ключевыми словами до 20; отозванные исключает.'],
         own=["Доля эталонных статей среди найденных."],
         base_llm=["Ссылки, которые LLM даёт без поиска: существуют ли, до T ли."],
         why=["Запросы модели находят эталонные статьи втрое чаще ключевых слов."]),
    dict(name="4. Чтение статей", basis="поля находки — как сбор данных в Cochrane [9]; «за / против» по звену с дословной опорой — как evidence inference [10] и SciFact [11]", kind="llm",
         base=["Из статьи — находка по звену: за или против,",
               "с дословной цитатой, дизайном и размером выборки."],
         llm=['По 20 аннотациям звена (у открытых статей — и разделы результатов) выписывает находки: сторона, цитата, дизайн, выборка, эффект.'],
         code=['Недословная цитата — ответ модели со списком ошибок, повтор, затем другая семья моделей; что не прошло — выбрасывает; класс эффекта считает сам; находки одного испытания объединяет.'],
         own=["Ручная разметка; ключевые статьи внешнего читателя; известные факты из баз."],
         base_llm=["LLM на тех же парах «звено — статья» и том же эталоне."],
         why=["Цитата делает каждую оценку проверяемой и не даёт модели подставить память."]),
    dict(name="5. Сводка доказательств", basis="вес находки — домены GRADE [4]; сила звена — по образцу веса доказательств связи в AOP [3]", kind="code",
         base=["Вес находки по надёжности (дизайн, выборка, эффект, сравнение, контекст).",
               "Сила звена и баланс доказательств цепочки."],
         code=["Вес по доменам GRADE; сила звена из суммы «за» и «против»; баланс — среднее по звеньям с данными."],
         own=["Предсказывают ли веса более поздние РКИ того же звена; порядок пар у внешнего читателя."],
         base_llm=["Модели, спрошенные «подтвердится ли», угадывают лучше — но с утечкой; честно только проспективно."],
         why=["Общепринятые домены GRADE; уровни выбраны по эталонам, а не по исходам."]),
    dict(name="6. Новизна", kind="code",
         base=["Насколько вопрос далёк от изученного до даты среза:",
               "от «новый контекст» до «новое звено»."],
         code=["Лестница уровней по найденным записям; новое звено — по подсчёту PubMed."],
         own=["Ближайшая прежняя работа по мнению внешнего читателя."],
         base_llm=["LLM называет ближайшую прежнюю работу; доля совпадений."],
         why=["Суждение модели о новизне ненадёжно; отсутствие данных — не новизна."]),
    dict(name="7. Эксперимент и альтернативы", basis="решающий эксперимент, отсекающий альтернативы, — strong inference [5]", kind="llm",
         base=["Какие конкурирующие объяснения возможны",
               "и какие из них отсекает заявленный эксперимент."],
         llm=['Называет альтернативы; по тексту реестра для каждой группы пишет, что предсказывают гипотеза и альтернатива, с дословной фразой.'],
         code=['Опору альтернатив ищет и читает, как звенья; «отсекает» без дословной фразы понижает до «ослабляет»; считает информативность.'],
         own=["Согласие с внешним читателем по «отсекает ли»."],
         base_llm=["Тот же вопрос LLM по тем же протоколам."],
         why=["Придуманная альтернатива без опоры ничего не добавляет."]),
    dict(name="8. Прочие показатели", basis="клиничность конечной точки — классы биомаркеров BEST FDA–NIH [6]", kind="llm",
         base=["Реализуемость эксперимента, клиничность конечной точки,",
               "размах механизма, рост внимания к теме."],
         llm=['Относит главный исход к уровню (биомаркер … клиническое событие); две семьи моделей независимо.'],
         code=['Засчитывает уровень только при совпадении семей; реализуемость — по формуле; рост внимания — подсчёт PubMed.'],
         own=["Правило допуска показателя: надёжен, различает, не дублирует."],
         base_llm=["Конечная точка: LLM против согласия двух семей."],
         why=["Профилю «Финансирование» нужны цена и готовность."]),
    dict(name="9. Ранжирование", basis="SMAA [7] с порядком важности показателей (АСПИД) [8]", kind="code",
         base=["Показатели сводятся в балл по профилю:",
               "Доказательность, Финансирование, Фронтир."],
         code=["Профиль задаёт только порядок важности; АСПИД разыгрывает веса и даёт балл и «в топ-5»."],
         own=["Устойчивость места; чувствительность к порядку профиля."],
         base_llm=["LLM ранжирует тот же пул напрямую."],
         why=["Точные веса обосновать нельзя, порядок важности — можно."]),
    dict(name="10. Улучшения и версии", kind="llm",
         base=["Что поднимет оценку и на сколько;",
               "по списку пишутся версии и снова проходят этапы 2–9."],
         llm=['Переписывает гипотезу по пунктам с фактами; версия, сдвинувшаяся к известному, возвращается автору с причиной один раз.'],
         code=['Строит пункты и ожидаемый прирост; версия проходит этапы 2–9 заново; проверяет восемь правил версий.'],
         own=["Ожидаемый прирост против полученного; внешний читатель по парам."],
         base_llm=["«LLM, улучши гипотезу» без правил; судьи по парам."],
         why=["Без правил прирост получается подгонкой к найденным статьям."]),
    dict(name="11. Сквозная проверка", basis="предрегистрация [12]; проспективная (временная) проверка модели прогноза [13]", kind="code",
         base=["Оценки пула закреплены хешем до результатов испытаний;",
               "порядок оценок сравнивается с исходами."],
         code=["Хеш файла оценок; исходы собираются из реестров."],
         own=["Порядок оценок против исходов идущих испытаний."],
         base_llm=["Ответ LLM «подтвердится ли», закреплённый так же; и сочетание с нашим балансом."],
         why=["Единственная проверка без утечки."]),
]

# checked 2026-11-11 (PubMed and publisher records; ASPID: the book's details to be confirmed in a library catalogue)
REFS = [
    "Richardson WS et al. The well-built clinical question. ACP J Club 1995;123:A12-3.",
    "Morgan P et al. Can the flow of medicines be improved? Drug Discov Today 2012;17:419-24 (Pfizer, «три опоры»: экспозиция в месте действия, связывание с мишенью, фармакологическая активность).",
    "Ankley GT et al. Adverse outcome pathways. Environ Toxicol Chem 2010;29:730-41; OECD AOP Users' Handbook.",
    "Guyatt GH et al. GRADE: an emerging consensus. BMJ 2008;336:924-6.",
    "Platt JR. Strong inference. Science 1964;146:347-53.",
    "FDA-NIH Biomarker Working Group. BEST (Biomarkers, EndpointS, and other Tools) Resource.",
    "Lahdelma R, Hokkanen J, Salminen P. SMAA. Eur J Oper Res 1998;106:137-43.",
    "Хованов Н.В. Анализ и синтез показателей при информационном дефиците (АСПИД), СПбГУ.",
    "Li T, Higgins JPT, Deeks JJ. Collecting data. Cochrane Handbook for Systematic Reviews of Interventions, ch. 5.",
    "Lehman E, DeYoung J, Barzilay R, Wallace BC. Inferring which medical treatments work from reports of clinical trials (evidence inference). NAACL 2019:3705-17.",
    "Wadden D et al. Fact or fiction: verifying scientific claims (SciFact). EMNLP 2020:7534-50.",
    "Nosek BA et al. The preregistration revolution. PNAS 2018;115:2600-6.",
    "Moons KG et al. TRIPOD: explanation and elaboration. Ann Intern Med 2015;162:W1-73 (виды проверки модели, в т. ч. временная).",
]

VARIANTS = {"base": [], "impl": ["impl"], "check": ["check"], "full": ["impl", "check", "why"]}

PER_ROW, BW, GAP_X, GAP_Y, X0, Y0 = 4, 400, 60, 50, 30, 110
FONT, LINE = 13, 18
COL = {"llm": ("#E8ECFA", "#5A6FB0"), "code": ("#FFFFFF", "#8A8A80")}


def nlines(t: str, width: int, font: int = FONT) -> int:
    per = max(10, int((width - 24) / (font * 0.52)))
    return max(1, -(-len(t) // per))


def section(title: str, items: list[str], width: int) -> tuple[str, int]:
    body = "".join(f"<div>{escape(t)}</div>" for t in items)
    html = f"<div style='margin-top:8px;font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.5px'>{title}</div>" \
           f"<div style='font-size:12px'>{body}</div>"
    return html, 1 + sum(nlines(t, width, 12) for t in items)


def cell(cid, value, x, y, w, h, style):
    v = escape(value, {'"': "&quot;"})
    return f'<mxCell id="{cid}" value="{v}" style="{style}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'


def edge(eid, a, b, style="", points=()):
    pts = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points)
    geo = f'<mxGeometry relative="1" as="geometry"><Array as="points">{pts}</Array></mxGeometry>' if pts else '<mxGeometry relative="1" as="geometry"/>'
    return (f'<mxCell id="{eid}" style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;strokeColor=#1E4D40;'
            f'strokeWidth=2;{style}" edge="1" parent="1" source="{a}" target="{b}">{geo}</mxCell>')


def stage_html(s: dict, layers: list[str]) -> tuple[str, int]:
    html = f"<div style='font-size:16px;color:#1E4D40'><b>{escape(s['name'])}</b></div>" \
           f"<div style='margin-top:4px'>{'<br/>'.join(escape(t) for t in s['base'])}</div>"
    n = 2 + sum(nlines(t, BW) for t in s["base"])
    if s.get("basis"):                     # the accepted scheme a stage adapts (user 2026-11-11: say whose idea we adapt)
        html += f"<div style='margin-top:6px;font-size:12px;color:#7A5C1E'><i>Основа: {escape(s['basis'])}</i></div>"
        n += nlines(s["basis"], BW, 12) + 1
    if "impl" in layers:
        if s["kind"] == "llm":
            for t, items in (("LLM", s["llm"]), ("Код", s["code"])):
                h, k = section(t, items, BW)
                html += h
                n += k
        else:
            h, k = section("Только код", s["code"], BW)
            html += h
            n += k
    if "check" in layers:
        h, k = section("Как проверяем: сами", s["own"], BW)
        h2, k2 = section("Как проверяем: против LLM напрямую", s["base_llm"], BW)
        html += "<div style='margin-top:8px;border-top:1px dashed #B7791F'></div>" + h + h2
        n += k + k2 + 1
    if "why" in layers:
        h, k = section("Почему так", s["why"], BW)
        html += h
        n += k
    return html, n


def build(layers: list[str]) -> str:
    out = []
    rows = [STAGES[i:i + PER_ROW] for i in range(0, len(STAGES), PER_ROW)]
    total_w = PER_ROW * BW + (PER_ROW - 1) * GAP_X
    sub = {(): "Этапы оценки гипотезы", ("impl",): "Этапы и их реализация: что делает языковая модель, что делает код",
           ("check",): "Этапы и их проверка: сами и против языковой модели, спрошенной напрямую",
           ("impl", "check", "why"): "Этапы: реализация, проверка, обоснование"}[tuple(layers)]
    out.append(cell("title", f"<b>Как система оценивает гипотезу (метод v3.9)</b><br/><span style='font-size:13px;color:#555'>{sub}</span>",
                    X0, 20, total_w, 56, "text;html=1;fontSize=22;align=left;verticalAlign=top;fillColor=none;strokeColor=none;fontColor=#1E4D40;"))
    y, ids, row_y = Y0, [], []
    for r, row in enumerate(rows):
        row_y.append(y)
        hs = [stage_html(s, layers) for s in row]
        h = max(n for _, n in hs) * LINE + 24
        for k, (s, (html, _)) in enumerate(zip(row, hs)):
            x = X0 + k * (BW + GAP_X)
            fill, stroke = COL[s["kind"]]
            cid = f"s{len(ids)}"
            ids.append(cid)
            out.append(cell(cid, html, x, y, BW, h,
                            f"rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth=1.5;fontSize={FONT};"
                            "fontColor=#1A202C;align=left;verticalAlign=top;spacingLeft=12;spacingRight=10;spacingTop=10;"))
        y += h + GAP_Y
    for i in range(len(ids) - 2):     # 1..10 in order; 11 hangs off ranking
        a, b = ids[i], ids[i + 1]
        if (i + 1) % PER_ROW == 0:     # wrap to the next row: down from the last block of a row to the first of the next
            out.append(edge(f"e{i}", a, b, "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"))
        else:
            out.append(edge(f"e{i}", a, b, "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"))
    gx = X0 + 2 * BW + GAP_X + GAP_X // 2          # the gap between the second and the third column
    out.append(edge("e_loop", ids[9], ids[1], "dashed=1;exitX=1;exitY=0.25;entryX=0.5;entryY=0;strokeColor=#B7791F;",
                    [(gx, row_y[2] + 30), (gx, Y0 - 20), (X0 + BW + GAP_X + BW // 2, Y0 - 20)]))
    out.append(edge("e_final", ids[8], ids[10], "exitX=0.5;exitY=1;entryX=0.5;entryY=1;strokeColor=#555555;dashed=1;"))
    legend = ("<span style='background:#E8ECFA;border:1px solid #5A6FB0;padding:0 8px'>&nbsp;</span> языковая модель, её ответ "
              "проверяет код &nbsp;&nbsp; <span style='border:1px solid #8A8A80;padding:0 8px'>&nbsp;</span> только код &nbsp;&nbsp; "
              "<span style='color:#B7791F'>- - →</span> версия гипотезы проходит этапы заново &nbsp;&nbsp; "
              "<span style='color:#555'>- - →</span> оценки пула закрепляются до результатов")
    out.append(cell("legend", legend, X0, y, total_w, 26, "text;html=1;fontSize=12;align=left;fontColor=#333;fillColor=none;strokeColor=none;"))
    y += 30
    refs = "<b>Основа этапов</b> (этапы без пометки — наша разработка): " + " ".join(f"[{i}] {escape(r)}" for i, r in enumerate(REFS, 1))
    rh = (nlines(" ".join(REFS), total_w, 11) + 1) * 15 + 10
    out.append(cell("refs", refs, X0, y, total_w, rh, "text;html=1;whiteSpace=wrap;fontSize=11;align=left;verticalAlign=top;fontColor=#555;fillColor=none;strokeColor=none;"))
    y += rh
    page_h = y + 30
    body = "".join(out)
    W = total_w + 2 * X0
    return (f'<mxfile host="hyp-arena"><diagram name="Схема"><mxGraphModel dx="{W}" dy="{page_h}" grid="0" page="1" '
            f'pageWidth="{W}" pageHeight="{page_h}"><root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel>'
            f'</diagram></mxfile>')


if __name__ == "__main__":
    for name, layers in VARIANTS.items():
        (D / f"flow_{name}.drawio").write_text(build(layers), encoding="utf-8")
    print("ok:", ", ".join(f"flow_{n}.drawio" for n in VARIANTS))
