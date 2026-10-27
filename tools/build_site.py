"""Validate and copy the static explainer only. No application or database imports."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "site/index.html": "index.html",
    "site/style.css": "style.css",
    "site/appearance.js": "appearance.js",
    "docs/assets/workflow-obscur-wide.png": "workflow-obscur-wide.png",
    "docs/assets/workflow-obscur-narrow.png": "workflow-obscur-narrow.png",
    "docs/assets/workflow-obscur-wide.svg": "workflow-obscur-wide.svg",
    "docs/assets/workflow-obscur-narrow.svg": "workflow-obscur-narrow.svg",
    "docs/assets/v0.9.0/operator-05-narrow-resolved.png": "operator-05-narrow-resolved.png",
    "docs/workflow-rendering.json": "workflow-rendering.json",
    "docs/workflow-explainer.json": "workflow-explainer.json",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.images: list[dict] = []

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if attrs.get("id"):
            if attrs["id"] in self.ids:
                raise ValueError("Duplicate HTML identifier")
            self.ids.add(attrs["id"])
        if tag == "img":
            self.images.append(attrs)
            if not attrs.get("alt"):
                raise ValueError("Required image has no alternative")
        for key in ("href", "src"):
            if attrs.get(key):
                self.links.append(attrs[key])
        if attrs.get("srcset"):
            self.links.extend(item.strip().split()[0] for item in attrs["srcset"].split(","))


def validate(repository: Path) -> None:
    site_files = {p.name for p in (repository / "site").iterdir() if p.is_file()}
    if site_files != {"index.html", "style.css", "appearance.js"}:
        raise ValueError("Static source allowlist changed; review the new payload explicitly")
    for source in FILES:
        if not (repository / source).is_file():
            raise ValueError(f"Missing static source: {source}")
    html = (repository / "site/index.html").read_text(encoding="utf-8")
    page = Page()
    page.feed(html)
    if '<html lang="en" data-appearance="obscur">' not in html:
        raise ValueError("Static/no-JavaScript entry must be Obscur")
    for anchor in ("main", "workflow", "example", "run", "limits"):
        if anchor not in page.ids:
            raise ValueError(f"Missing visitor route: {anchor}")
    destinations = set(FILES.values()) | {"build-info.json"}
    for link in page.links:
        parsed = urlsplit(link)
        if parsed.scheme:
            if parsed.scheme != "https":
                raise ValueError("Only HTTPS external links are admitted")
            continue
        if parsed.netloc or parsed.path.startswith("/") or ".." in Path(unquote(parsed.path)).parts:
            raise ValueError("Unexpected static path")
        if parsed.path and parsed.path not in destinations:
            raise ValueError(f"Missing payload route: {link}")
        if not parsed.path and parsed.fragment and parsed.fragment not in page.ids:
            raise ValueError(f"Broken page anchor: {link}")
    record = json.loads((repository / "docs/workflow-rendering.json").read_text())
    for path, expected in {**record["inputs"], **record["outputs"]}.items():
        if digest(repository / path) != expected:
            raise ValueError(f"Stale conceptual-figure source/output: {path}")
    for source in (repository / "site").glob("*"):
        text = source.read_text(encoding="utf-8")
        if "file://" in text or "C:/Users/" in text or "fetch(" in text or "XMLHttpRequest" in text:
            raise ValueError("Static explainer must not depend on local files or an API")


def build(destination: Path, repository: Path = ROOT) -> dict:
    validate(repository)
    allowed = set(FILES.values()) | {"build-info.json"}
    if destination.exists() and any(p.name not in allowed for p in destination.iterdir()):
        raise ValueError("Preserve unexpected destination contents")
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in FILES.items():
        shutil.copyfile(repository / source, destination / target)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True, stderr=subprocess.DEVNULL).strip()
        tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repository, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        revision, tree = "fixture-or-archive", None
    record = {"source_revision": revision, "source_tree": tree,
              "kind": "static project explanation, not application hosting",
              "files": {target: digest(destination / target) for target in sorted(FILES.values())}}
    (destination / "build-info.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/site")
    args = parser.parse_args()
    result = build(args.output)
    print(f"Validated {len(result['files'])} static files; no application service started")
