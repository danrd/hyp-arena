"""Builds docs/system/scheme.drawio and scheme.svg (preview) from the step table below; the text is docs/system/steps.md.
python docs/system/build_scheme.py"""
from pathlib import Path
from xml.sax.saxutils import escape

D = Path(__file__).resolve().parent
STATUS = {"пройдено": ("#E3F1E8", "#2E7D4F"), "частично": ("#FFF4DC", "#B7791F"), "не пройдено": ("#FDE8E6", "#C0392B"),
          "ждёт исходов": ("#ECEFF3", "#5A6B7B"), "не проверялось": ("#F1F1F1", "#888888")}
# (title, what, who, check, status)
STEPS = [
    ("Гипотезы на входе", "реестры испытаний; генерация по теме; версии лучших", "LLM + код", "правила версий проверяет код; качество новых гипотез не измерено", "частично"),
    ("Карточка гипотезы", "вмешательство, популяция, исход, шаги механизма, эксперимент", "LLM + код", "перефразирование: субъект, отношение, объект 1.00, контекст 0.80; механизм 6 из 8", "частично"),
    ("Поиск статей", "PubMed до даты среза для каждого шага", "LLM + код", "95% ключевых статей второго читателя найдено", "пройдено"),
    ("Чтение статей", "находки с дословной цитатой: за / против, дизайн, выборка", "LLM + код", "поля 92–96%; находки на своём шаге 19–52% — главная потеря", "частично"),
    ("Вес находки", "дизайн × точность × эффект × сравнение × контекст (GRADE)", "код", "поздние испытания того же шага: AUC 0.70", "пройдено"),
    ("Сила шага и баланс", "«за» и «против» → сила шага → баланс цепочки, покрытие", "код", "исходы прошлых испытаний: AUC 0.59", "частично"),
    ("Новизна", "расстояние до уже изученного до даты среза", "код", "второй читатель: κ 0.14–0.26, завышена", "не пройдено"),
    ("Эксперимент и альтернативы", "какие подкреплённые объяснения отсекает эксперимент", "LLM + код", "второй читатель: κ 0.35", "частично"),
    ("Прочие показатели", "реализуемость, конечная точка, рост внимания, роль ИИ", "LLM + код", "конечная точка κ 0.93; реализуемость не проверялась", "частично"),
    ("Ранжирование (АСПИД)", "порядок важности → случайные веса → балл и «в топ-5»", "код", "правило допуска показателей; профили в пределах 0.03", "частично"),
    ("Улучшения и версии", "исправимые пункты, их прирост, версии гипотез", "код + LLM", "восемь правил версий проверяются тестами", "частично"),
    ("Сквозная проверка", "60 идущих испытаний, оценки заморожены хешем", "код", "исходы 2026–2028", "ждёт исходов"),
]
BASE = [
    ("Чтение (шаги 1, 3, 7)", "GPT получает тот же текст, сравнение с тем же эталоном (второй читатель, известные факты)", "утечка не мешает"),
    ("Вес находки (шаг 4)", "GPT упорядочивает те же пары находок", "утечка не мешает"),
    ("Прогноз исхода (шаг 11)", "ответы GPT по 60 проспективным испытаниям закрепляются хешем рядом с нашими", "утечки нет: исходов ещё нет"),
    ("Прошлые испытания", "модели, спрошенные напрямую: AUC 0.76 против 0.59 у баланса", "утечка не исключена"),
]
W, H, GAP, X0, Y0 = 760, 74, 22, 40, 70


def cell(i, value, x, y, w, h, style, parent="1"):
    return f'<mxCell id="c{i}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="{parent}"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'


def edge(i, a, b):
    return f'<mxCell id="e{i}" style="endArrow=block;html=1;strokeColor=#1E4D40;" edge="1" parent="1" source="{a}" target="{b}"><mxGeometry relative="1" as="geometry"/></mxCell>'


def page_steps():
    out, n = [], 0
    out.append(cell("t", "<b>Схема системы (метод v3.8)</b> — шаги, кто их делает и чем проверены", X0, 20, W + 300, 30, "text;html=1;fontSize=18;align=left;"))
    for k, (t, what, who, check, st) in enumerate(STEPS):
        y = Y0 + k * (H + GAP)
        fill, line = STATUS[st]
        out.append(cell(f"s{k}", f"<b>Шаг {k}. {t}</b><br/><span style='font-size:11px'>{what}</span>", X0, y, 470, H,
                        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#1E4D40;align=left;spacingLeft=10;fontSize=13;"))
        out.append(cell(f"w{k}", who, X0 + 480, y + 22, 90, 30,
                        f"rounded=1;html=1;fontSize=11;fillColor={'#EEF0FB' if 'LLM' in who else '#F1F1F1'};strokeColor=none;"))
        out.append(cell(f"v{k}", f"<b>{st}</b><br/><span style='font-size:11px'>{check}</span>", X0 + 580, y, 480, H,
                        f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={line};align=left;spacingLeft=10;fontSize=12;"))
        if k:
            out.append(edge(k, f"c s{k-1}".replace(" ", ""), f"cs{k}"))
    y = Y0 + len(STEPS) * (H + GAP)
    legend = " ".join(f"<span style='background:{f};border:1px solid {l};padding:2px 6px'>{s}</span>" for s, (f, l) in STATUS.items())
    out.append(cell("leg", "Статусы: " + legend + "<br/>Подробно: docs/system/steps.md; числа и критерии — specs/", X0, y, W + 300, 40, "text;html=1;fontSize=11;align=left;"))
    return "".join(out)


def page_base():
    out = [cell("t2", "<b>Бейзлайн ChatGPT (GPT-5.x через API, без веб-поиска)</b>", X0, 20, 900, 30, "text;html=1;fontSize=18;align=left;")]
    for k, (lvl, how, leak) in enumerate(BASE):
        y = Y0 + k * 96
        out.append(cell(f"b{k}", f"<b>{lvl}</b>", X0, y, 230, 80, "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#1E4D40;fontSize=13;"))
        out.append(cell(f"h{k}", how, X0 + 240, y, 470, 80, "rounded=1;whiteSpace=wrap;html=1;fillColor=#F7F7F2;strokeColor=#CCCCCC;align=left;spacingLeft=10;fontSize=12;"))
        out.append(cell(f"l{k}", leak, X0 + 720, y, 220, 80, "rounded=1;whiteSpace=wrap;html=1;fillColor=#ECEFF3;strokeColor=#5A6B7B;fontSize=12;"))
    return "".join(out)


def drawio():
    def diagram(name, body):
        return (f'<diagram name="{name}"><mxGraphModel dx="1200" dy="900" grid="1" gridSize="10" page="1" pageWidth="1200" pageHeight="1400">'
                f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram>')
    return f'<mxfile host="hyp-arena">{diagram("Шаги", page_steps())}{diagram("Проверки и бейзлайн", page_base())}</mxfile>'


def svg():
    hgt = Y0 + len(STEPS) * (H + GAP) + 40
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{X0 + 1080}" height="{hgt}" font-family="Inter, Arial, sans-serif">',
         '<rect width="100%" height="100%" fill="#F8F7F2"/>',
         f'<text x="{X0}" y="40" font-size="18" font-weight="700" fill="#1E4D40">Схема системы (метод v3.8)</text>']
    for k, (t, what, who, check, st) in enumerate(STEPS):
        y = Y0 + k * (H + GAP); fill, line = STATUS[st]
        o.append(f'<rect x="{X0}" y="{y}" width="470" height="{H}" rx="10" fill="#fff" stroke="#1E4D40"/>')
        o.append(f'<text x="{X0 + 12}" y="{y + 28}" font-size="14" font-weight="700" fill="#1E4D40">{escape(f"Шаг {k}. {t}")}</text>')
        o.append(f'<text x="{X0 + 12}" y="{y + 52}" font-size="11" fill="#333">{escape(what)}</text>')
        o.append(f'<rect x="{X0 + 480}" y="{y + 22}" width="90" height="30" rx="8" fill="{"#EEF0FB" if "LLM" in who else "#F1F1F1"}"/>')
        o.append(f'<text x="{X0 + 525}" y="{y + 42}" font-size="11" text-anchor="middle" fill="#333">{escape(who)}</text>')
        o.append(f'<rect x="{X0 + 580}" y="{y}" width="480" height="{H}" rx="10" fill="{fill}" stroke="{line}"/>')
        o.append(f'<text x="{X0 + 592}" y="{y + 28}" font-size="13" font-weight="700" fill="{line}">{escape(st)}</text>')
        o.append(f'<text x="{X0 + 592}" y="{y + 52}" font-size="11" fill="#333">{escape(check)}</text>')
        if k:
            o.append(f'<line x1="{X0 + 235}" y1="{y - GAP}" x2="{X0 + 235}" y2="{y - 2}" stroke="#1E4D40" stroke-width="2" marker-end="url(#a)"/>')
    o.insert(1, '<defs><marker id="a" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#1E4D40"/></marker></defs>')
    o.append('</svg>')
    return "\n".join(o)


if __name__ == "__main__":
    (D / "scheme.drawio").write_text(drawio(), encoding="utf-8")
    (D / "scheme.svg").write_text(svg(), encoding="utf-8")
    print("ok")
