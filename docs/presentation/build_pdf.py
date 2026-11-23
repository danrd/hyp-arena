"""Clean inline code formatting (if needed) and export the HTML presentation to a 16:9 PDF via headless Chrome/Edge."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "hyp-arena-v4-2026-11-23.html"
PDF = HERE / "hyp-arena-v4-2026-11-23.pdf"

PLAIN_RE = re.compile(
    r"^(T|N|I|W|n|v\d[\d.]*|Sol-20|10x10-20|pack_26|A\d|BS\d|A\d/BS\d|A1\+BS1|A2\+BS2|A3/BS3|"
    r"H\d+|R2|R3|R3 ≈ [0-9,]+|0,36|0,60|−0,176|1,0|0,5|0,0|0,67|0,33|11/12|\$0,08|\$0,0015|\$0,0005|\$0,039|"
    r"O\(N²?\)|Evidence|Funding|Frontier|p1|ep|A1/BS1/A2/BS2|H09/H15|H01|H08|H09|H15|H19)$"
)


def clean_backticks(path: Path) -> int:
    html = path.read_text(encoding="utf-8")
    if "/* inline-code */" not in html:
        code_css = (
            "  /* inline-code */\n"
            "  code {\n"
            '    font-family: "Consolas", "Cascadia Code", ui-monospace, monospace;\n'
            "    font-size: 0.88em; background: rgba(29,106,82,0.09); color: #144B3A;\n"
            "    padding: 1px 5px; border-radius: 4px;\n"
            "  }\n"
            "  .card.soft-terra code { background: rgba(184,74,26,0.11); color: #8A330F; }\n"
            "  .card.navy code { background: rgba(255,255,255,0.14); color: #CFEAE0; }\n"
        )
        html = html.replace("  /* Footer */", code_css + "\n  /* Footer */")

    m_main = re.search(r"(<main.*?</main>)", html, re.S)
    assert m_main is not None

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        if PLAIN_RE.match(inner):
            return inner
        return f"<code>{inner}</code>"

    main_clean = re.sub(r"`([^`]+)`", repl, m_main.group(1))
    # Also fix any accidental Markdown **bold** inside main
    main_clean = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", main_clean)
    html = html[:m_main.start()] + main_clean + html[m_main.end():]
    path.write_text(html, encoding="utf-8")
    return main_clean.count("`")


def find_browser() -> Path:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in candidates:
        if p.exists():
            return p
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise SystemExit("No Chrome/Edge browser found for PDF export.")


def build_pdf(html: Path = HTML, pdf: Path = PDF) -> Path:
    browser = find_browser()
    with tempfile.TemporaryDirectory(prefix="hyp_deck_") as profile_dir:
        cmd = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--user-data-dir={profile_dir}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf.resolve()}",
            html.resolve().as_uri(),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0 or not pdf.exists():
            raise SystemExit(f"PDF export failed (rc={res.returncode}): {res.stderr[-400:]}")
    return pdf


if __name__ == "__main__":
    rem = clean_backticks(HTML)
    out = build_pdf()
    print(f"Cleaned backticks remaining: {rem}")
    print(f"Exported PDF: {out} ({out.stat().st_size:,} bytes)")
