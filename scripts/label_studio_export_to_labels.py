#!/usr/bin/env python3
"""Convert Label Studio basketball shot-event exports to labels.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


MISS_LABELS = {
    "miss_rim_hit": "rim_hit",
    "miss_backboard": "backboard_miss",
    "miss_airball": "airball",
    "miss_blocked": "blocked",
    "miss_under_basket_interference": "under_basket_interference",
    "miss_unknown": "",
}

RESULT_LABELS = {"make", *MISS_LABELS.keys()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Label Studio JSON export to basketball batch labels.json."
    )
    parser.add_argument("--input", required=True, help="Label Studio JSON export.")
    parser.add_argument("--output", required=True, help="labels.json output path.")
    parser.add_argument(
        "--release-max-gap",
        type=float,
        default=3.0,
        help="Maximum seconds between release and later result event.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exported = read_export(Path(args.input))
    labels = convert_export(exported, release_max_gap=args.release_max_gap)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} with {len(labels['videos'])} videos.")
    return 0


def read_export(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        return [item for item in data["tasks"] if isinstance(item, dict)]
    raise SystemExit(f"{path} must be a Label Studio JSON export list.")


def convert_export(tasks: list[dict[str, Any]], release_max_gap: float) -> dict[str, Any]:
    videos = [convert_task(task, release_max_gap) for task in tasks]
    return {
        "name": "basketball-shot-labels",
        "defaults": {
            "has_net": True,
            "timeout_seconds": 900,
            "tolerance": {
                "makes": 0,
                "misses": 0,
                "attempts": 0,
                "shot_time_s": 0.35,
            },
        },
        "videos": videos,
    }


def convert_task(task: dict[str, Any], release_max_gap: float) -> dict[str, Any]:
    data = task.get("data") if isinstance(task.get("data"), dict) else {}
    annotation = choose_annotation(task)
    results = annotation.get("result") if isinstance(annotation.get("result"), list) else []

    releases: list[float] = []
    result_events: list[dict[str, Any]] = []
    scene_type = str(data.get("scene_type") or "")
    notes: list[str] = []

    for result in results:
        if not isinstance(result, dict):
            continue
        value = result.get("value") if isinstance(result.get("value"), dict) else {}
        result_type = result.get("type")
        from_name = result.get("from_name")

        if result_type == "choices" and from_name == "scene_type":
            choices = value.get("choices")
            if isinstance(choices, list) and choices:
                scene_type = str(choices[0])
            continue

        if result_type == "textarea" and from_name == "notes":
            text = value.get("text")
            if isinstance(text, list):
                notes.extend(str(item) for item in text if item)
            elif text:
                notes.append(str(text))
            continue

        if result_type != "timelinelabels" or from_name != "shot_events":
            continue

        labels = value.get("timelinelabels")
        if not isinstance(labels, list) or not labels:
            continue
        label = str(labels[0])
        start = timeline_start(value)
        if start is None:
            continue
        if label == "release":
            releases.append(start)
        elif label in RESULT_LABELS:
            result_events.append({"label": label, "time_s": start})
        else:
            raise SystemExit(f"Unknown Label Studio timeline label: {label}")

    result_events.sort(key=lambda event: event["time_s"])
    releases.sort()
    shots = build_shots(result_events, releases, release_max_gap)
    makes = [shot for shot in shots if shot["result"] == "make"]
    misses = [shot for shot in shots if shot["result"] == "miss"]

    video_id = str(data.get("video_id") or infer_video_id(str(data.get("video") or "")))
    if not scene_type:
        scene_type = video_id.split("/", 1)[0] if "/" in video_id else "unknown"

    return {
        "video_id": video_id,
        "scene_type": scene_type,
        "true_shots": len(shots),
        "true_makes": len(makes),
        "true_misses": len(misses),
        "score_time": [shot["time_s"] for shot in makes],
        "shots": shots,
        "notes": "\n".join(notes),
    }


def choose_annotation(task: dict[str, Any]) -> dict[str, Any]:
    annotations = task.get("annotations")
    if not isinstance(annotations, list):
        return {}
    usable = [
        item
        for item in annotations
        if isinstance(item, dict) and isinstance(item.get("result"), list) and item.get("result")
    ]
    return usable[-1] if usable else {}


def timeline_start(value: dict[str, Any]) -> float | None:
    ranges = value.get("ranges")
    if isinstance(ranges, list) and ranges:
        first = ranges[0]
        if isinstance(first, dict) and first.get("start") is not None:
            return round_time(first["start"])
    if value.get("start") is not None:
        return round_time(value["start"])
    return None


def build_shots(
    result_events: list[dict[str, Any]],
    releases: list[float],
    release_max_gap: float,
) -> list[dict[str, Any]]:
    available_releases = list(releases)
    shots: list[dict[str, Any]] = []
    for event in result_events:
        label = str(event["label"])
        time_s = round_time(event["time_s"])
        shot: dict[str, Any] = {
            "attempt": len(shots) + 1,
            "time_s": time_s,
            "result_time_s": time_s,
            "result": "make" if label == "make" else "miss",
        }
        if label in MISS_LABELS and MISS_LABELS[label]:
            shot["miss_type"] = MISS_LABELS[label]

        release_index = nearest_prior_release_index(available_releases, time_s, release_max_gap)
        if release_index is not None:
            shot["release_time_s"] = available_releases.pop(release_index)
        shots.append(shot)
    return shots


def nearest_prior_release_index(
    releases: list[float],
    result_time: float,
    max_gap: float,
) -> int | None:
    match: int | None = None
    for index, release_time in enumerate(releases):
        if release_time > result_time:
            break
        if result_time - release_time <= max_gap:
            match = index
    return match


def infer_video_id(video_url: str) -> str:
    parsed = urlparse(video_url)
    path = parsed.path or video_url
    return path.lstrip("/") or video_url or "unknown"


def round_time(value: Any) -> float:
    return round(float(value), 2)


if __name__ == "__main__":
    raise SystemExit(main())
