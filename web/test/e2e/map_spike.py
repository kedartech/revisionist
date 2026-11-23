"""The map spike: the 1941 map's data for the proof page, and the frame-time measurement.

uv run --frozen python web/test/e2e/map_spike.py data
    writes docs/web-design/map-spike/map-data.js from the built 1941 map and its world file.

python web/test/e2e/map_spike.py measure [OUT_DIR]
    opens the proof page from the file system, screenshots it at 1440 by 900 and 390 by 844,
    then pans and zooms the map for ten seconds three ways at both sizes with the processor
    slowed four times, and writes results.json and the shots to OUT_DIR (default: the
    spike's folder). Needs Playwright with Chromium (the Playwright image). With
    `--slowdown N` the processor is slowed N times instead and the numbers go to
    results-Nx.json, and no shots are taken.
"""

import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPIKE = ROOT / "docs" / "web-design" / "map-spike"
WORLD = ROOT / "worlds" / "autumn-1941.yaml"

METHODS = ("viewbox", "transform", "canvas")
SIZES = {
    "desktop": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1},
    "phone": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
}
SLOWDOWN = 4
RUN_MS = 10_000
WARM_MS = 1_000
RUNS = 2
PHONE_LINE_MS = (
    33.0  # [proposed] the transform is chosen if its 95th percentile on the phone is at most this
)


def data() -> int:
    import yaml

    world = yaml.safe_load(WORLD.read_text())
    entry = world["map"]
    path = WORLD.parent / "maps" / entry["file"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        print(f"{path} does not match the sha256 in {WORLD}", file=sys.stderr)
        return 1
    areas = [
        {"key": a["key"], "name": a["name"], "region": a.get("region"), "kind": kind}
        for kind, group in (("land", "territories"), ("sea", "sea_zones"))
        for a in world[group]
    ]
    regions = [
        {"key": r["key"], "name": r["name"], "parent": r.get("parent")} for r in world["regions"]
    ]
    out = SPIKE / "map-data.js"
    out.write_text(
        f"// Written by web/test/e2e/map_spike.py data from {path.relative_to(ROOT)}"
        f" (sha256 {entry['sha256']}) and {WORLD.relative_to(ROOT)}. Do not edit.\n"
        f"window.SPIKE_MAP = {raw.decode().strip()};\n"
        f"window.SPIKE_WORLD = {json.dumps({'areas': areas, 'regions': regions})};\n"
    )
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes, {len(areas)} areas)")
    return 0


def summary(times: list[float], frames: bool = True) -> dict[str, float]:
    ordered = sorted(times)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    out = {
        "count": len(ordered),
        "median_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(ordered[-1], 2),
    }
    if frames:
        out["fps"] = round(1000 * len(ordered) / sum(ordered), 1)
    return out


def measure(out: Path, slowdown: int = SLOWDOWN) -> int:
    from playwright.sync_api import sync_playwright

    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    page_url = (SPIKE / "index.html").as_uri()
    problems: list[str] = []
    results: dict[str, Any] = {
        "slowdown": slowdown,
        "run_ms": RUN_MS,
        "warm_ms": WARM_MS,
        "runs": {},
    }
    load = Path("/proc/loadavg")
    if load.is_file():
        results["host_load_start"] = load.read_text().split()[:3]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        results["browser"] = f"chromium {browser.version}"
        for size, opts in SIZES.items():
            ctx = browser.new_context(**opts)  # type: ignore[arg-type]
            page = ctx.new_page()
            page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
            page.on(
                "console", lambda m: m.type == "error" and problems.append(f"console: {m.text}")
            )
            page.goto(page_url)
            page.wait_for_function("window.spikeProof && window.spikeProof.ready", timeout=60_000)
            width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            results.setdefault("proof", {})[size] = {
                "panels": page.evaluate("window.spikeProof.panels"),
                "scroll_width": width[0],
                "inner_width": width[1],
            }
            if slowdown == SLOWDOWN:
                page.screenshot(path=str(shots / f"proof-{size}.png"), full_page=True, scale="css")
            page.close()
            order = METHODS if size == "desktop" else tuple(reversed(METHODS))
            for run in range(RUNS):
                for method in order if run % 2 == 0 else tuple(reversed(order)):
                    page = ctx.new_page()
                    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
                    page.goto(f"{page_url}?bench={method}")
                    page.wait_for_function(
                        "window.spikeBench && window.spikeBench.ready", timeout=60_000
                    )
                    if run == 0 and slowdown == SLOWDOWN:
                        page.screenshot(path=str(shots / f"bench-{method}-{size}.png"), scale="css")
                    cdp = ctx.new_cdp_session(page)
                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": slowdown})
                    got = page.evaluate(f"window.spikeBench.run({RUN_MS}, {WARM_MS})")
                    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
                    key = f"{size}/{method}"
                    results["runs"].setdefault(key, []).append(
                        {
                            "frame": summary(got["frames"]),
                            "work": summary(got["work"], frames=False),
                        }
                    )
                    results.setdefault("raw", {}).setdefault(key, []).append(
                        [round(f, 2) for f in got["frames"]]
                    )
                    print(key, run + 1, results["runs"][key][-1]["frame"], flush=True)
                    page.close()
            ctx.close()
        browser.close()
    pooled: dict[str, Any] = {}
    for key, frames in results["raw"].items():
        pooled[key] = summary([f for run in frames for f in run])
    results["pooled"] = pooled
    if load.is_file():
        results["host_load_end"] = load.read_text().split()[:3]
    phone_p95 = pooled["phone/transform"]["p95_ms"]
    results["recommendation"] = "transform" if phone_p95 <= PHONE_LINE_MS else "canvas"
    results["rule"] = f"transform if its phone p95 <= {PHONE_LINE_MS} ms, else canvas"
    results["problems"] = problems
    name = "results.json" if slowdown == SLOWDOWN else f"results-{slowdown}x.json"
    (out / name).write_text(json.dumps(results, indent=1) + "\n")
    print(json.dumps({"pooled": pooled, "recommendation": results["recommendation"]}, indent=1))
    print("problems:", problems or "none")
    return 1 if problems else 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "data":
        return data()
    args = sys.argv[1:]
    if args[:1] == ["measure"]:
        slowdown = SLOWDOWN
        if "--slowdown" in args:
            at = args.index("--slowdown")
            slowdown = int(args[at + 1])
            del args[at : at + 2]
        return measure(Path(args[1]) if len(args) > 1 else SPIKE, slowdown)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
