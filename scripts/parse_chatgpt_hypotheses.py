"""Parse a markdown dump of the ChatGPT hypothesis dialogue into structured JSON.

Usage: python scripts/parse_chatgpt_hypotheses.py conv.md data/chatgpt_hypotheses.json
Input: assistant messages separated by '### [assistant]' headers, hypotheses as '**N. Title**'.
"""
import json
import re
import sys

FIELDS = {
    "Гипотеза": "claim",
    "Готеза": "claim",  # typo present in the source dialogue (hypotheses 8 and 23)
    "Что уже известно": "known",
    "Решающий эксперимент": "experiment",
    "Специфическое предсказание": "prediction",
    "Что опровергнет гипотезу": "falsification",
    "Потенциальное вмешательство": "intervention",
}
CITATION = re.compile(r"\s*\ue200.*?\ue201", re.S)  # inline citation markers (refs are not recoverable)
TITLE = re.compile(r"^\*\*(\d+)\. (.+?)\*\*\s*$", re.M)
FIELD = re.compile(r"^\*\*([^*\n]{2,40})[.:]\*\*\s*", re.M)


def clean(s: str) -> str:
    s = CITATION.sub("", s)
    s = re.sub(r"\n-{3,}\s*$", "", s.strip())
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def parse(text: str):
    messages = re.split(r"\n### \[(?:assistant|user)\][^\n]*\n", text)[1:]
    roles = re.findall(r"\n### \[(assistant|user)\]", text)
    out, notes = [], {}
    for msg_idx, (role, msg) in enumerate(zip(roles, messages)):
        if role != "assistant":
            continue
        titles = list(TITLE.finditer(msg))
        for k, t in enumerate(titles):
            end = titles[k + 1].start() if k + 1 < len(titles) else len(msg)
            body = msg[t.end():end]
            marks = [m for m in FIELD.finditer(body) if m.group(1) in FIELDS]
            rec = {"id": int(t.group(1)), "title": t.group(2).strip(), "message": msg_idx}
            for j, m in enumerate(marks):
                stop = marks[j + 1].start() if j + 1 < len(marks) else len(body)
                value = clean(body[m.end():stop])
                if j + 1 == len(marks) and k + 1 == len(titles):
                    # last field of the last hypothesis: the assistant's closing remarks follow
                    first, _, tail = value.partition("\n\n")
                    value = first
                    notes[msg_idx] = clean(tail)
                rec[FIELDS[m.group(1)]] = value
            out.append(rec)
    return {"hypotheses": out, "assistant_notes": notes}


if __name__ == "__main__":
    data = parse(open(sys.argv[1], encoding="utf-8").read())
    json.dump(data, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(len(data["hypotheses"]), "hypotheses,", len(data["assistant_notes"]), "closing notes")
