"""Render .drawio schemes (built by build_flow.py and build_scheme.py) to 2x PNGs via headless Chrome/Edge.

No Node/npm or mxgraph dependency required: parses the explicit <mxCell> geometry and orthogonal
edges of scripts/docs/*.drawio into standalone HTML + SVG and screenshots with local Chrome or Edge.

Usage:
    python scripts/docs/render_schemes_png.py
"""
from __future__ import annotations

import html as html_mod
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent.parent / "docs" / "method" / "schemes"


def _find_browser() -> str:
    candidates = [
        os.environ.get("CHROME_BIN", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
        shutil.which("chrome") or "",
        shutil.which("msedge") or "",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise RuntimeError("No headless browser (Chrome / Chromium / Edge) found on this machine.")


def _parse_style(style_str: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (style_str or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[part] = "1"
    return out


def _anchor_point(box: tuple[float, float, float, float], rx: float, ry: float) -> tuple[float, float]:
    x, y, w, h = box
    return x + w * rx, y + h * ry


def _route_orthogonal(
    src_box: tuple[float, float, float, float],
    dst_box: tuple[float, float, float, float],
    st: dict[str, str],
    waypoints: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    ex_x = float(st.get("exitX", "1"))
    ex_y = float(st.get("exitY", "0.5"))
    en_x = float(st.get("entryX", "0"))
    en_y = float(st.get("entryY", "0.5"))
    p0 = _anchor_point(src_box, ex_x, ex_y)
    p1 = _anchor_point(dst_box, en_x, en_y)

    if waypoints:
        pts: list[tuple[float, float]] = [p0]
        cur = p0
        for wp in waypoints:
            if abs(cur[0] - wp[0]) > 0.5 and abs(cur[1] - wp[1]) > 0.5:
                if ex_x in (0.0, 1.0) and cur == p0:
                    pts.append((wp[0], cur[1]))
                else:
                    pts.append((cur[0], wp[1]))
            pts.append(wp)
            cur = wp
        if abs(cur[0] - p1[0]) > 0.5 and abs(cur[1] - p1[1]) > 0.5:
            if en_y in (0.0, 1.0):
                pts.append((p1[0], cur[1]))
            else:
                pts.append((cur[0], p1[1]))
        pts.append(p1)
        return pts

    # Bottom-to-bottom U-route (e.g. stage 9 -> stage 11)
    if ex_y == 1.0 and en_y == 1.0:
        drop_y = max(p0[1], p1[1]) + 22.0
        return [p0, (p0[0], drop_y), (p1[0], drop_y), p1]

    # Bottom-to-top wrap between rows
    if ex_y == 1.0 and en_y == 0.0:
        mid_y = (p0[1] + p1[1]) / 2.0
        if abs(p0[0] - p1[0]) < 1.0:
            return [p0, p1]
        return [p0, (p0[0], mid_y), (p1[0], mid_y), p1]

    # Top-to-bottom vertical arrow (e.g. stage 7 -> stage 3)
    if ex_y == 0.0 and en_y == 1.0:
        if abs(p0[0] - p1[0]) < 1.0:
            return [p0, p1]
        mid_y = (p0[1] + p1[1]) / 2.0
        return [p0, (p0[0], mid_y), (p1[0], mid_y), p1]

    # Left-to-right horizontal arrow
    if abs(p0[1] - p1[1]) < 1.0 or abs(p0[0] - p1[0]) < 1.0:
        return [p0, p1]
    mid_x = (p0[0] + p1[0]) / 2.0
    return [p0, (mid_x, p0[1]), (mid_x, p1[1]), p1]


def _rounded_svg_path(pts: list[tuple[float, float]], radius: float = 7.0) -> str:
    if len(pts) < 2:
        return ""
    if len(pts) == 2:
        return f"M {pts[0][0]:.1f} {pts[0][1]:.1f} L {pts[1][0]:.1f} {pts[1][1]:.1f}"
    cmds = [f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(1, len(pts) - 1):
        prev_pt, cur_pt, next_pt = pts[i - 1], pts[i], pts[i + 1]
        dx1, dy1 = cur_pt[0] - prev_pt[0], cur_pt[1] - prev_pt[1]
        dx2, dy2 = next_pt[0] - cur_pt[0], next_pt[1] - cur_pt[1]
        len1 = (dx1 * dx1 + dy1 * dy1) ** 0.5
        len2 = (dx2 * dx2 + dy2 * dy2) ** 0.5
        if len1 < 1.0 or len2 < 1.0:
            cmds.append(f"L {cur_pt[0]:.1f} {cur_pt[1]:.1f}")
            continue
        r = min(radius, len1 / 2.0, len2 / 2.0)
        sx = cur_pt[0] - (dx1 / len1) * r
        sy = cur_pt[1] - (dy1 / len1) * r
        ex = cur_pt[0] + (dx2 / len2) * r
        ey = cur_pt[1] + (dy2 / len2) * r
        cmds.append(f"L {sx:.1f} {sy:.1f} Q {cur_pt[0]:.1f} {cur_pt[1]:.1f} {ex:.1f} {ey:.1f}")
    cmds.append(f"L {pts[-1][0]:.1f} {pts[-1][1]:.1f}")
    return " ".join(cmds)


def drawio_to_html(drawio_path: Path) -> tuple[str, int, int]:
    tree = ET.parse(drawio_path)
    root = tree.getroot()
    model = root.find(".//mxGraphModel")
    assert model is not None, f"Missing mxGraphModel in {drawio_path}"
    page_w = int(float(model.attrib.get("pageWidth", "1800")))
    page_h = int(float(model.attrib.get("pageHeight", "1200")))

    vertices: dict[str, tuple[float, float, float, float]] = {}
    divs: list[str] = []
    edges_raw: list[ET.Element] = []

    max_x, max_y = 0.0, 0.0

    for cell in model.findall(".//mxCell"):
        cid = cell.attrib.get("id", "")
        if cid in ("0", "1"):
            continue
        if cell.attrib.get("edge") == "1":
            edges_raw.append(cell)
            continue
        if cell.attrib.get("vertex") != "1":
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        x = float(geo.attrib.get("x", "0"))
        y = float(geo.attrib.get("y", "0"))
        w = float(geo.attrib.get("width", "100"))
        h = float(geo.attrib.get("height", "40"))
        vertices[cid] = (x, y, w, h)
        max_x = max(max_x, x + w)
        max_y = max(max_y, y + h)

        st = _parse_style(cell.attrib.get("style", ""))
        val = cell.attrib.get("value", "")

        fill = st.get("fillColor", "#FFFFFF")
        bg = "transparent" if fill == "none" else fill
        stroke = st.get("strokeColor", "none")
        sw = float(st.get("strokeWidth", "1"))
        border = "none" if stroke == "none" else f"{sw}px solid {stroke}"
        rounded = st.get("rounded", "0") == "1"
        arc_pct = float(st.get("arcSize", "6")) / 100.0
        radius = f"{max(6, int(min(w, h) * arc_pct))}px" if rounded else "0px"
        fs = st.get("fontSize", "12")
        fc = st.get("fontColor", "#1A202C")
        align = st.get("align", "left")
        valign = st.get("verticalAlign", "middle" if "rounded=0" in cell.attrib.get("style", "") and cid.startswith("h") else "top")
        pad_l = st.get("spacingLeft", "6" if border != "none" else "0")
        pad_r = st.get("spacingRight", "6" if border != "none" else "0")
        pad_t = st.get("spacingTop", "4" if border != "none" else "0")

        flex_css = ""
        if valign == "middle":
            flex_css = "display:flex;align-items:center;justify-content:center;text-align:center;"
            pad_t = "0"

        css = (
            f"position:absolute;left:{x:.1f}px;top:{y:.1f}px;width:{w:.1f}px;height:{h:.1f}px;"
            f"box-sizing:border-box;background:{bg};border:{border};border-radius:{radius};"
            f"font-size:{fs}px;color:{fc};text-align:{align};"
            f"padding:{pad_t}px {pad_r}px 4px {pad_l}px;line-height:1.22;overflow:visible;{flex_css}"
        )
        divs.append(f'<div id="cell-{html_mod.escape(cid)}" data-vertex="1" style="{css}">{val}</div>')

    # Build SVG markers and paths for edges
    marker_colors: dict[str, str] = {}
    svg_paths: list[str] = []

    for ecell in edges_raw:
        src = ecell.attrib.get("source", "")
        dst = ecell.attrib.get("target", "")
        if src not in vertices or dst not in vertices:
            continue
        st = _parse_style(ecell.attrib.get("style", ""))
        stroke = st.get("strokeColor", "#1E4D40")
        sw = float(st.get("strokeWidth", "2"))
        dashed = st.get("dashed", "0") == "1"
        mid = marker_colors.setdefault(stroke, f"arr{len(marker_colors)}")

        wps: list[tuple[float, float]] = []
        geo = ecell.find("mxGeometry")
        if geo is not None:
            arr = geo.find("Array")
            if arr is not None:
                for pt in arr.findall("mxPoint"):
                    wps.append((float(pt.attrib["x"]), float(pt.attrib["y"])))

        pts = _route_orthogonal(vertices[src], vertices[dst], st, wps)
        for px, py in pts:
            max_y = max(max_y, py + 12)
        # Shorten final segment slightly so line ends cleanly inside arrowhead base
        if len(pts) >= 2:
            p_prev, p_end = pts[-2], pts[-1]
            dx, dy = p_end[0] - p_prev[0], p_end[1] - p_prev[1]
            seg_len = (dx * dx + dy * dy) ** 0.5
            if seg_len > 4.0:
                trim = 3.0
                pts[-1] = (p_end[0] - (dx / seg_len) * trim, p_end[1] - (dy / seg_len) * trim)

        d = _rounded_svg_path(pts, radius=7.0 if st.get("rounded", "1") == "1" else 0.0)
        dash_attr = ' stroke-dasharray="6,5"' if dashed else ""
        svg_paths.append(
            f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{sw}"{dash_attr} marker-end="url(#{mid})"/>'
        )

    defs = "".join(
        f'<marker id="{mid}" viewBox="0 0 10 10" refX="7.5" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">'
        f'<path d="M 0 1.2 L 9 5 L 0 8.8 z" fill="{color}"/></marker>'
        for color, mid in marker_colors.items()
    )

    canvas_w = max(page_w, int(max_x + 24))
    canvas_h = max(page_h, int(max_y + 24))

    svg = (
        f'<svg width="{canvas_w}" height="{canvas_h}" '
        f'style="position:absolute;left:0;top:0;pointer-events:none;z-index:5">'
        f"<defs>{defs}</defs>{''.join(svg_paths)}</svg>"
    )

    doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: #FFFFFF;
    font-family: Arial, Helvetica, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  #canvas {{
    position: relative;
    width: {canvas_w}px;
    height: {canvas_h}px;
    background: #FFFFFF;
    overflow: hidden;
  }}
</style>
</head>
<body>
<div id="canvas">
{''.join(divs)}
{svg}
</div>
</body>
</html>
"""
    return doc, canvas_w, canvas_h


def render_all(names: list[str] | None = None) -> None:
    browser = _find_browser()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    drawios = (
        [HERE / f"{n}.drawio" for n in names]
        if names
        else sorted(HERE.glob("*.drawio"))
    )
    with tempfile.TemporaryDirectory(prefix="hyp_schemes_") as tmp:
        tmp_dir = Path(tmp)
        profile_dir = tmp_dir / "chrome_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        for dp in drawios:
            html_str, w, h = drawio_to_html(dp)
            hp = tmp_dir / f"{dp.stem}.html"
            hp.write_text(html_str, encoding="utf-8")
            out_png = OUT_DIR / f"{dp.stem}.png"
            cmd = [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--hide-scrollbars",
                f"--user-data-dir={profile_dir}",
                "--force-device-scale-factor=2",
                f"--window-size={w},{h}",
                f"--screenshot={out_png}",
                hp.as_uri(),
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"{out_png.name}: {w}x{h} (2x -> {w*2}x{h*2}px)")


if __name__ == "__main__":
    import sys

    render_all(sys.argv[1:] or None)
