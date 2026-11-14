"""Gradio demo: paste or generate a few hypotheses, get a ranking (interface in Russian).

    pip install gradio
    ALLOW_PAID=1 COMET_API_KEY=... python -m hyparena.app            # http://127.0.0.1:7860
    python -m hyparena.app --share                                    # temporary public link (embeddable)

Two tabs: a saved example (opens instantly, for demonstrations; results in data/demo/*.json) and a new run
(3-6 minutes for five hypotheses on the cheap models, progress shown by stage). The page can be embedded
in another page with an iframe."""
from __future__ import annotations

import argparse
import json
import os
import queue
import tempfile
import threading
from pathlib import Path

import gradio as gr

from hyparena import showcase
from hyparena.llm.providers import ALLOW_PAID_ENV

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "data" / "demo"
MODELS = {"Дешёвые платные модели (CometAPI)": ("configs/paid-test.yaml", False),
          "Бесплатные модели (OpenRouter)": ("configs/models.yaml", False),
          "Без моделей: проверка интерфейса": ("configs/paid-test.yaml", True)}
WRITERS = {"неизвестен": "unknown", "OpenAI": "openai", "Google": "google", "Anthropic": "anthropic",
           "Zhipu (GLM)": "zhipu", "Qwen": "qwen", "DeepSeek": "deepseek", "человек": "human"}


def _examples() -> dict[str, Path]:
    out = {}
    for p in sorted(EXAMPLES.glob("*.json")):
        try:
            meta = json.loads(p.read_text())["meta"]
        except (ValueError, KeyError):
            continue
        out[f"{p.stem} · {meta.get('created', '')[:10]}"] = p
    return out


def show_example(name: str) -> str:
    path = _examples().get(name)
    return showcase.render(json.loads(path.read_text())) if path else "<p>Пример не найден.</p>"


def _files(result: dict) -> list[str]:
    tmp = Path(tempfile.mkdtemp(prefix="hyparena-"))
    (tmp / "ranking.html").write_text(showcase.render(result, standalone=True), encoding="utf-8")
    (tmp / "ranking.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [str(tmp / "ranking.html"), str(tmp / "ranking.json")]


def new_run(source, text, goal, count, writer, models, search):
    """Generator for Gradio: yields (status markdown, result html, files) as the run goes."""
    config, fake = MODELS[models]
    texts = showcase.split_hypotheses(text) if source == "Вставить" else []
    if source == "Вставить" and not texts:
        yield "Вставьте хотя бы две гипотезы (нумерованным списком или через пустую строку).", "", gr.update(visible=False)
        return
    if not fake and "paid" in config and os.environ.get(ALLOW_PAID_ENV) != "1":
        yield f"Платные модели выключены: запустите приложение с {ALLOW_PAID_ENV}=1.", "", gr.update(visible=False)
        return
    events, box = queue.Queue(), {}

    def work():
        try:
            box["result"] = showcase.run(texts, goal.strip(), 0 if texts else int(count), WRITERS[writer], config,
                                         fake, "europepmc" if search else "none",
                                         on_stage=lambda node, msg: events.put(msg))
        except Exception as e:                       # shown to the presenter, not raised into Gradio
            box["error"] = f"{type(e).__name__}: {e}"
        events.put(None)

    threading.Thread(target=work, daemon=True).start()
    what = f"{len(texts)} гипотез" if texts else f"генерация {int(count)} гипотез"
    log = [f"**Идёт прогон** ({what}; для пяти гипотез на дешёвых моделях обычно 3–6 минут)"]
    yield "\n\n".join(log), "", gr.update(visible=False)
    while True:
        msg = events.get()
        if msg is None:
            break
        log.append(f"- {msg}")
        yield "\n".join(log), "", gr.update(visible=False)
    if "error" in box:
        yield "\n".join(log + [f"\n**Ошибка:** {box['error']}"]), "", gr.update(visible=False)
        return
    result = box["result"]
    log[0] = f"**Готово** за {result['meta']['seconds'] // 60} мин {result['meta']['seconds'] % 60} с"
    yield "\n".join(log), showcase.render(result), gr.update(value=_files(result), visible=True)


def build() -> gr.Blocks:
    with gr.Blocks(title="Арена гипотез") as demo:
        gr.Markdown("## Арена гипотез: ранжирование научных гипотез\n"
                    "Гипотезы разбираются в карточки, для каждой ищется литература, рецензенты пишут замечания, "
                    "судьи из независимых семейств моделей сравнивают их попарно по четырём критериям, а итоговый "
                    "порядок получается без числовых весов, по порядку важности критериев.")
        examples = _examples()
        with gr.Tab("Готовый пример"):
            pick = gr.Dropdown(list(examples), value=next(iter(examples), None), label="Сохранённый прогон")
            example_html = gr.HTML(show_example(next(iter(examples), "")) if examples else
                                   "<p>Сохранённых прогонов пока нет.</p>")
            pick.change(show_example, pick, example_html)
        with gr.Tab("Новый прогон"):
            with gr.Row():
                with gr.Column(scale=3):
                    source = gr.Radio(["Вставить", "Сгенерировать"], value="Вставить", label="Откуда гипотезы")
                    text = gr.Textbox(lines=12, label="Гипотезы",
                                      placeholder="1. Первая гипотеза…\n\n2. Вторая гипотеза…")
                    goal = gr.Textbox(label="Цель исследования (для генерации и для судей)",
                                      placeholder=showcase.DEFAULT_GOAL)
                with gr.Column(scale=2):
                    count = gr.Slider(3, 8, value=5, step=1, label="Сколько сгенерировать", visible=False)
                    writer = gr.Dropdown(list(WRITERS), value="неизвестен", label="Автор вставленных гипотез",
                                         info="Судьи никогда не берутся из семейства автора")
                    models = gr.Dropdown(list(MODELS), value=next(iter(MODELS)), label="Модели")
                    search = gr.Checkbox(True, label="Искать литературу (Europe PMC)")
                    sample = gr.Button("Подставить пример")
                    go = gr.Button("Ранжировать", variant="primary")
            status = gr.Markdown()
            result_html = gr.HTML()
            files = gr.File(label="Скачать результат (HTML, JSON)", file_count="multiple", visible=False)
            source.change(lambda s: (gr.update(visible=s == "Вставить"), gr.update(visible=s == "Вставить"),
                                     gr.update(visible=s != "Вставить"), gr.update(visible=s == "Вставить")),
                          source, [text, writer, count, sample])
            sample_text = (EXAMPLES / "example_input.txt")
            sample.click(lambda: sample_text.read_text(encoding="utf-8") if sample_text.exists() else "", None, text)
            go.click(new_run, [source, text, goal, count, writer, models, search], [status, result_html, files])
    return demo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--share", action="store_true", help="temporary public link from Gradio")
    args = ap.parse_args()
    build().queue().launch(server_name=args.host, server_port=args.port, share=args.share)


if __name__ == "__main__":
    main()
