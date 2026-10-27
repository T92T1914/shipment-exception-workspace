"""Render the saved conceptual workflow, without importing the application."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib import pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "docs/workflow-explainer.json"
RECEIPT = ROOT / "docs/workflow-rendering.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fonts(directory: Path) -> tuple[dict, list]:
    resolved, records = {}, []
    for label, file, weight, italic in [
        ("regular", "Inter-Regular.ttf", 400, False),
        ("semibold", "Inter-SemiBold.ttf", 600, False),
        ("bold", "Inter-Bold.ttf", 700, False),
    ]:
        path = directory / file
        with TTFont(path) as font:
            family = font["name"].getDebugName(1)
            if "Inter" not in family or font["OS/2"].usWeightClass != weight:
                raise ValueError(f"Unexpected face: {file}")
            if bool(font["head"].macStyle & 2) != italic:
                raise ValueError(f"Unexpected italic: {file}")
            glyphs = font.getBestCmap()
            missing = sorted({c for c in MODEL.read_text(encoding="utf-8")
                              if ord(c) >= 32 and ord(c) not in glyphs})
            if missing:
                raise ValueError(f"Missing text glyphs in {file}: {missing}")
        resolved[label] = font_manager.FontProperties(fname=path)
        records.append({"file": file, "family": family, "weight": weight,
                        "italic": italic, "sha256": sha(path)})
    return resolved, records


def render(data: dict, faces: dict, folder: Path, narrow: bool) -> list[Path]:
    width, height = (960, 1720) if narrow else (1800, 840)
    colors = data["obscur"]
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100,
                     facecolor=colors["canvas"])
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set(xlim=(0, width), ylim=(height, 0))
    ax.axis("off")

    def text(x, y, value, size=30, face="regular", color="text"):
        artists = []
        for line, content in enumerate(value.split("\n")):
            artists.append(ax.text(x, y + line * size * 1.28, content,
                                   fontsize=size * .72, fontproperties=faces[face],
                                   color=colors[color], va="top"))
        return artists

    text(60, 36, "SHIPMENT EXCEPTION WORKSPACE", 24 if not narrow else 31,
         "semibold", "accent")
    text(60, 91, data["title"], 54 if not narrow else 55, "bold")
    if narrow:
        text(60, 174, "An authorized operator workflow\nwith synthetic records.", 35,
             color="muted")
        boxes = [(60, 280 + i * 270, 840, 245) for i in range(4)]
        body, title = 40, 45
    else:
        text(60, 174, data["subtitle"], 30, color="muted")
        boxes = [(60 + i * 433, 275, 395, 260) for i in range(4)]
        body, title = 26, 30
    bounded = []
    for index, (step, (x, y, w, h)) in enumerate(zip(data["steps"], boxes)):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=16",
                                   facecolor=colors["panel"], edgecolor=colors["border"],
                                   linewidth=1.2))
        labels = text(x + 24, y + 23, step["title"], title, "semibold", "accent")
        labels += text(x + 24, y + 80, "\n".join(step["lines"]), body)
        bounded.append((labels, (x, y, w, h)))
        if index < 3:
            if narrow:
                start, end = (width / 2, y + h + 4), (width / 2, y + 264)
            else:
                start, end = (x + w + 4, y + h / 2), (x + 427, y + h / 2)
            ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=17,
                                        linewidth=1.5, color=colors["accent"]))
    y = 1380 if narrow else 595
    if narrow:
        text(60, y, "Then resolve at version 4.\nFour events. Retry added none.", 37, "semibold")
        text(60, y + 118, "Current access remains authoritative.\nRefresh after the historical response.\nNo automatic business POST on recovery.", 31,
             color="muted")
        text(60, 1660, "Conceptual example. See the source and limits.", 26, color="muted")
    else:
        text(60, y, data["result"], 33, "semibold")
        text(60, y + 65, "\n".join(data["limits"]), 26, color="muted")
        text(60, 790, "Conceptual example. Source: docs/DESIGN.md and the installed v0.9.0 walkthrough.", 22,
             color="muted")
    stem = "workflow-obscur-narrow" if narrow else "workflow-obscur-wide"
    fig.canvas.draw()
    for label in ax.texts:
        actual = label.get_window_extent(fig.canvas.get_renderer())
        if actual.x0 < 0 or actual.x1 > width or actual.y0 < 0 or actual.y1 > height:
            raise ValueError(f"Workflow label exceeds the canvas: {label.get_text()}")
    for labels, (x, y, w, h) in bounded:
        for label in labels:
            box = label.get_window_extent(fig.canvas.get_renderer()).transformed(ax.transData.inverted())
            if box.x0 < x + 8 or box.x1 > x + w - 8 or min(box.y0, box.y1) < y + 8 or max(box.y0, box.y1) > y + h - 8:
                raise ValueError(f"Workflow label exceeds its card: {label.get_text()}, bounds={box.bounds}, card={(x, y, w, h)}")
    outputs = []
    for extension in ("png", "svg"):
        path = folder / f"{stem}.{extension}"
        if extension == "svg":
            with path.open("wb") as stream:
                fig.savefig(stream, format="svg", dpi=100, facecolor=colors["canvas"],
                            transparent=False, metadata={"Date": None})
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
        else:
            fig.savefig(path, dpi=100, facecolor=colors["canvas"], transparent=False,
                        metadata={})
        outputs.append(path)
    plt.close(fig)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, default=os.environ.get("INTER_FONT_DIR"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.font_dir is None:
        parser.error("Supply --font-dir pointing to official static Inter TTF files")
    faces, font_records = fonts(Path(args.font_dir))
    matplotlib.rcParams.update({"svg.fonttype": "path", "svg.hashsalt": "shipment-workflow-v1"})
    data = json.loads(MODEL.read_text(encoding="utf-8"))
    target = ROOT / "docs/assets"
    with tempfile.TemporaryDirectory(prefix="shipment-workflow-") as temporary:
        folder = Path(temporary) if args.check else target
        outputs = render(data, faces, folder, False) + render(data, faces, folder, True)
        record = {"kind": data["kind"], "theme_source": data["theme_source"],
                  "renderer": {"matplotlib": matplotlib.__version__, "svg_text": "Inter glyph outlines"},
                  "fonts": font_records,
                  "inputs": {"tools/render_workflow_explainer.py": sha(Path(__file__)),
                             "docs/workflow-explainer.json": sha(MODEL)},
                  "outputs": {f"docs/assets/{p.name}": sha(p) for p in outputs}}
        if args.check:
            if not RECEIPT.exists() or json.loads(RECEIPT.read_text()) != record:
                raise SystemExit("Conceptual workflow receipt is stale")
            for path in outputs:
                if path.read_bytes() != (target / path.name).read_bytes():
                    raise SystemExit(f"Stale output: {path.name}")
            print("Conceptual workflow source, font and output identities match")
        else:
            RECEIPT.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
            print("Rendered four Obscur outputs from the saved conceptual model")


if __name__ == "__main__":
    main()
