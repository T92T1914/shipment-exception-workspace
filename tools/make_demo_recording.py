"""Cut two short GIFs from the Playwright videos of the installed browser run.

The input is the test-results folder of a run with WORKSPACE_RECORD_DEMO set.
Nothing here starts the application or touches a database.
"""
import argparse
import subprocess
import sys
from pathlib import Path

CASES = {
    # Output name: (test folder prefix, which video of that test to cut).
    # The stale tab test opens a second page. That page is the one that meets the conflict.
    "stale-tab-refused.gif": ("workspace-two-tabs-reject-a-stale", "shortest"),
    "retry-returns-saved-result.gif": ("workspace-retry-retrieves-a-committed", "only"),
}
MAX_BYTES = 6 * 1024 * 1024


def duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def pick(results: Path, prefix: str, which: str) -> Path:
    folders = [d for d in results.iterdir() if d.is_dir() and d.name.startswith(prefix)]
    if len(folders) != 1:
        raise SystemExit(f"Expected one test folder starting with {prefix}, found {len(folders)}")
    videos = sorted(folders[0].glob("*.webm"))
    if not videos:
        raise SystemExit(f"No video in {folders[0].name}")
    if which == "only":
        if len(videos) != 1:
            raise SystemExit(f"Expected one video in {folders[0].name}, found {len(videos)}")
        return videos[0]
    return min(videos, key=duration)


def to_gif(video: Path, target: Path) -> None:
    graph = "fps=8,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=none"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", graph, "-loop", "0", str(target)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, (prefix, which) in CASES.items():
        video = pick(args.results, prefix, which)
        target = args.output / name
        to_gif(video, target)
        size = target.stat().st_size
        print(f"{name}: {size} bytes from {video.parent.name}/{video.name} ({duration(video):.1f} s)")
        if size > MAX_BYTES:
            print(f"{name} is over {MAX_BYTES} bytes", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
