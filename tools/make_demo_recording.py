"""Cut two short GIFs from the Playwright videos of the installed browser run.

The input is the test-results folder of a run with WORKSPACE_RECORD_DEMO set.
Nothing here starts the application or touches a database.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

CASES = {
    # Output name: (test title, which video of that test to cut).
    # The stale tab test opens a second page without signing in. Its video is the smaller of the two.
    "stale-tab-refused.gif": ("two tabs reject a stale assignment and refresh before a new change", "smallest"),
    "retry-returns-saved-result.gif": ("retry retrieves a committed assignment after its real HTTP response is dropped", "only"),
}
MAX_BYTES = 6 * 1024 * 1024


def collect(results: Path) -> dict:
    """Map each test title to its video files, read from the JSON report."""
    report = json.loads((results / "results.json").read_text(encoding="utf-8"))
    found: dict = {}

    def walk(suite):
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                for run in test.get("results", []):
                    for item in run.get("attachments", []):
                        if item.get("contentType") == "video/webm" and item.get("path"):
                            found.setdefault(spec["title"], []).append(Path(item["path"]))
        for child in suite.get("suites", []):
            walk(child)

    for suite in report.get("suites", []):
        walk(suite)
    return found


def pick(found: dict, title: str, which: str) -> Path:
    videos = [v for v in found.get(title, []) if v.exists()]
    if not videos:
        raise SystemExit(f"No video for the test: {title}. Tests with video: {sorted(found)}")
    if which == "only":
        if len(videos) != 1:
            raise SystemExit(f"Expected one video for {title}, found {len(videos)}")
        return videos[0]
    return min(videos, key=lambda v: v.stat().st_size)


def to_gif(video: Path, target: Path) -> None:
    graph = "setpts=2.0*PTS,fps=8,scale=800:-1:flags=lanczos,tpad=stop_mode=clone:stop_duration=3,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=none"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", graph, "-loop", "0", str(target)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    found = collect(args.results)
    for name, (title, which) in CASES.items():
        video = pick(found, title, which)
        target = args.output / name
        to_gif(video, target)
        size = target.stat().st_size
        print(f"{name}: {size} bytes from {video.parent.name}/{video.name}")
        if size > MAX_BYTES:
            print(f"{name} is over {MAX_BYTES} bytes", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
