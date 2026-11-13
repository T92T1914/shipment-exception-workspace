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
from matplotlib.backends.backend_agg import RendererAgg
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


def measure(value: str, face: font_manager.FontProperties, pt: float) -> float:
    prop = face.copy()
    prop.set_size(pt)
    return RendererAgg(8, 8, 100).get_text_width_height_descent(value, prop, False)[0]


def wrap(value: str, face: font_manager.FontProperties, pt: float, limit: float) -> list[str]:
    """Wrap by measured width. A word that cannot fit is an error, never a smaller size."""
    lines, current = [], ""
    for word in value.split():
        trial = f"{current} {word}".strip()
        if measure(trial, face, pt) <= limit:
            current = trial
        elif not current:
            raise ValueError(f"Word does not fit the layout: {word}")
        else:
            lines.append(current)
            current = word
    return lines + [current]


def render(data: dict, faces: dict, folder: Path, narrow: bool) -> list[Path]:
    """Draw one edition from the Obscur rules in the desk's obscur.md.

    Sizes are points at 100 dpi. Card height comes from measured text plus fixed
    padding. The wide canvas grows to hold all four 500 px cards.
    """
    colors = data["obscur"]
    count = len(data["steps"])
    margin = 48 if narrow else 72
    card_w, gap = (864, 24) if narrow else (500, 78)
    width = 960 if narrow else 2 * margin + count * card_w + (count - 1) * gap
    sizes = ({"subtitle": 33, "card": 34, "body": 33, "footer": 33} if narrow
             else {"subtitle": 30, "card": 32, "body": 30, "footer": 30})
    px = lambda pt: pt * 100 / 72
    drawn = []  # (x, y, line, pt, face, color, bounds)

    def block(x, y, value, pt, face, color, limit, bounds=None, spacing=1.3):
        for line in wrap(value, faces[face], pt, limit):
            drawn.append((x, y, line, pt, face, color, bounds))
            y += px(pt) * spacing
        return y

    y = margin
    y = block(margin, y, data["title"], 40, "bold", "text", width - 2 * margin)
    y = block(margin, y + 14, data["subtitle"], sizes["subtitle"], "regular", "muted",
              width - 2 * margin) + 48
    inner = card_w - 56
    cards = []
    for step in data["steps"]:
        height = 32 + sum(px(sizes["card"]) * 1.3 for _ in wrap(step["title"], faces["semibold"], sizes["card"], inner)) + 20
        for index, line in enumerate(step["lines"]):
            height += px(sizes["body"]) * 1.3 * len(wrap(line, faces["regular"], sizes["body"], inner))
            height += 14 if index < len(step["lines"]) - 1 else 0
        cards.append(height + 32)
    top, cursor, boxes = y, y, []
    row = max(cards)
    for index, step in enumerate(data["steps"]):
        if narrow:
            box = (margin, cursor, card_w, cards[index])
            cursor += cards[index] + gap
        else:
            box = (margin + index * (card_w + gap), top, card_w, row)
        boxes.append(box)
        x, by, w, h = box
        ty = block(x + 28, by + 32, step["title"], sizes["card"], "semibold", "text", inner, box) + 20
        for line in step["lines"]:
            ty = block(x + 28, ty, line, sizes["body"], "regular", "text", inner, box) + 14
    y = (cursor - gap if narrow else top + row) + 48
    y = block(margin, y, data["result"], sizes["card"], "semibold", "text", width - 2 * margin) + 20
    for line in data["limits"]:
        y = block(margin, y, line, sizes["body"], "regular", "muted", width - 2 * margin) + 14
    y = block(margin, y + 34, data["footer"], sizes["footer"], "semibold", "muted", width - 2 * margin)
    height = int(round(y + 49))

    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100, facecolor=colors["canvas"])
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set(xlim=(0, width), ylim=(height, 0))
    ax.axis("off")
    for x, by, w, h in boxes:
        ax.add_patch(FancyBboxPatch((x, by), w, h, boxstyle="round,pad=0,rounding_size=18",
                                   facecolor=colors["panel"], edgecolor=colors["border"],
                                   linewidth=2 * .72))
    for (x, by, w, h), (nx, ny, nw, nh) in zip(boxes, boxes[1:]):
        if narrow:
            start, end = (width / 2, by + h + 3), (width / 2, ny - 3)
        else:
            start, end = (x + w + 6, by + h / 2), (nx - 6, by + h / 2)
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>,head_length=.45,head_width=.25",
                                    mutation_scale=20, linewidth=2.5 * .72, color=colors["text"],
                                    shrinkA=0, shrinkB=0))
    labels = []
    for x, ty, line, pt, face, color, bounds in drawn:
        prop = faces[face].copy()
        prop.set_size(pt)
        labels.append((ax.text(x, ty, line, fontproperties=prop, color=colors[color], va="top"), bounds))
    stem = "workflow-obscur-narrow" if narrow else "workflow-obscur-wide"
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for label, bounds in labels:
        box = label.get_window_extent(renderer).transformed(ax.transData.inverted())
        if min(box.x0, box.x1) < 12 or max(box.x0, box.x1) > width - 12 \
                or min(box.y0, box.y1) < 12 or max(box.y0, box.y1) > height - 12:
            raise ValueError(f"Workflow label exceeds the canvas: {label.get_text()}")
        if bounds:
            x, by, w, h = bounds
            if min(box.x0, box.x1) < x + 12 or max(box.x0, box.x1) > x + w - 12 \
                or min(box.y0, box.y1) < by + 12 or max(box.y0, box.y1) > by + h - 12:
                raise ValueError(f"Workflow label exceeds its card: {label.get_text()}, "
                                 f"bounds={box.bounds}, card={bounds}")
    outputs = []
    for extension in ("png", "svg"):
        path = folder / f"{stem}.{extension}"
        if extension == "svg":
            with path.open("wb") as stream:
                fig.savefig(stream, format="svg", dpi=100, facecolor=colors["canvas"],
                            transparent=False, metadata={"Date": None})
            path.write_bytes(path.read_bytes().replace(bytes([13, 10]), bytes([10])))
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
