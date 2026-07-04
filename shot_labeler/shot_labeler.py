#!/usr/bin/env python3
"""Interactive video labeler for basketball shot-event datasets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Annotate basketball shot events into batch-eval labels.json."
    )
    parser.add_argument(
        "--labels",
        default="labels.json",
        help="labels.json to create or update.",
    )
    parser.add_argument(
        "--test-root",
        default="test_videos",
        help="Root used to write relative video_id values.",
    )
    parser.add_argument(
        "--video-root",
        default="test_videos/fixed_halfcourt",
        help="Directory of videos to label when --video is not provided.",
    )
    parser.add_argument(
        "--video",
        action="append",
        help="Specific video path to label. Repeatable.",
    )
    parser.add_argument(
        "--scene-type",
        help="Scene type written to labels. Defaults to path relative to --test-root.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively discover videos under --video-root.",
    )
    parser.add_argument(
        "--skip-labeled",
        action="store_true",
        help="Skip videos that already have shots[] labels.",
    )
    parser.add_argument(
        "--require-release",
        action="store_true",
        help="Require pressing 's' before adding make/miss labels.",
    )
    parser.add_argument(
        "--max-display-width",
        type=int,
        default=1280,
        help="Resize displayed video frames to this max width.",
    )
    parser.add_argument(
        "--window-name",
        default="Basketball Shot Labeler",
        help="OpenCV window name.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cv2 = import_cv2()

    labels_path = resolve_path(args.labels)
    test_root = resolve_path(args.test_root)
    videos = discover_videos(args)
    if not videos:
        raise SystemExit("No videos found.")

    labels = load_labels(labels_path)
    print_controls()

    should_quit = False
    for index, video_path in enumerate(videos, start=1):
        video_id = video_id_for(video_path, test_root)
        label = find_label(labels, video_id, video_path)
        existing_shots = list(label.get("shots") or []) if label else []
        if args.skip_labeled and existing_shots:
            print(f"[skip] {video_id} already has {len(existing_shots)} shot labels")
            continue

        print(f"\n[{index}/{len(videos)}] {video_id}")
        result = annotate_video(cv2, video_path, video_id, existing_shots, args)
        if result["action"] == "abort":
            should_quit = True
            break
        if result["save"]:
            shots = normalize_shots(result["shots"])
            upsert_label(
                labels=labels,
                video_id=video_id,
                video_path=video_path,
                test_root=test_root,
                scene_type=args.scene_type or infer_scene_type(video_path, test_root),
                shots=shots,
            )
            write_labels(labels_path, labels)
            print(f"[saved] {video_id}: {len(shots)} shots")
        if result["action"] == "quit":
            should_quit = True
            break

    cv2.destroyAllWindows()
    if should_quit:
        print("Stopped.")
    print(f"Labels: {labels_path}")
    return 0


def import_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "OpenCV is required for the labeler. Install it with: "
            "python3 -m pip install opencv-python"
        ) from exc
    return cv2


def resolve_path(raw: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(raw)))).resolve()


def discover_videos(args: argparse.Namespace) -> list[Path]:
    if args.video:
        return [resolve_path(path) for path in args.video]
    root = resolve_path(args.video_root)
    if not root.exists():
        raise SystemExit(f"video root not found: {root}")
    iterator = root.rglob("*") if args.recursive else root.iterdir()
    return sorted(
        path.resolve()
        for path in iterator
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def load_labels(path: Path) -> dict[str, Any]:
    if not path.exists():
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
            "videos": [],
        }
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"name": path.stem, "videos": data}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object or array.")
    data.setdefault("videos", [])
    if not isinstance(data["videos"], list):
        raise SystemExit(f"{path} videos must be an array.")
    return data


def write_labels(path: Path, labels: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def video_id_for(video_path: Path, test_root: Path) -> str:
    try:
        return video_path.resolve().relative_to(test_root.resolve()).as_posix()
    except ValueError:
        return str(video_path.resolve())


def infer_scene_type(video_path: Path, test_root: Path) -> str:
    try:
        relative = video_path.resolve().relative_to(test_root.resolve())
        if len(relative.parts) > 1:
            return relative.parts[0]
    except ValueError:
        pass
    return video_path.parent.name


def find_label(labels: dict[str, Any], video_id: str, video_path: Path) -> dict[str, Any] | None:
    candidates = {video_id, str(video_path.resolve())}
    for item in labels.get("videos", []):
        if not isinstance(item, dict):
            continue
        raw = str(item.get("video_id") or item.get("video") or item.get("id") or "")
        if raw in candidates:
            return item
    return None


def upsert_label(
    labels: dict[str, Any],
    video_id: str,
    video_path: Path,
    test_root: Path,
    scene_type: str,
    shots: list[dict[str, Any]],
) -> None:
    item = find_label(labels, video_id, video_path)
    if item is None:
        item = {"video_id": video_id}
        labels.setdefault("videos", []).append(item)

    makes = [shot for shot in shots if shot.get("result") == "make"]
    misses = [shot for shot in shots if shot.get("result") == "miss"]
    item["video_id"] = video_id_for(video_path, test_root)
    item["scene_type"] = scene_type
    item["true_shots"] = len(shots)
    item["true_makes"] = len(makes)
    item["true_misses"] = len(misses)
    item["score_time"] = [shot["time_s"] for shot in makes]
    item["shots"] = shots
    item.setdefault("notes", "")


def annotate_video(
    cv2: Any,
    video_path: Path,
    video_id: str,
    existing_shots: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[error] could not open video: {video_path}")
        return {"action": "next", "save": False, "shots": existing_shots}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if fps <= 1 or fps != fps:
        fps = 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frame_index = 0
    playing = False
    draft_release: float | None = None
    message = "Loaded. Press space to play."
    shots = normalize_shots(existing_shots)

    cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)

    while True:
        frame = read_frame(cv2, cap, frame_index)
        if frame is None:
            frame_index = max(total_frames - 1, 0)
            frame = read_frame(cv2, cap, frame_index)
            if frame is None:
                break

        time_s = frame_index / fps
        display = draw_overlay(
            cv2=cv2,
            frame=frame,
            video_id=video_id,
            frame_index=frame_index,
            total_frames=total_frames,
            fps=fps,
            time_s=time_s,
            shots=shots,
            draft_release=draft_release,
            message=message,
            max_width=args.max_display_width,
        )
        cv2.imshow(args.window_name, display)
        delay = max(int(1000 / fps), 1) if playing else 0
        key = cv2.waitKeyEx(delay)

        if key == -1:
            if playing:
                frame_index = clamp_frame(frame_index + 1, total_frames)
            continue

        char = chr(key & 0xFF).lower() if 0 <= (key & 0xFF) < 128 else ""
        if key == 27:
            return {"action": "abort", "save": False, "shots": shots}
        if char == " ":
            playing = not playing
            message = "Playing." if playing else "Paused."
        elif char == "a":
            playing = False
            frame_index = clamp_frame(frame_index - 1, total_frames)
        elif char == "d":
            playing = False
            frame_index = clamp_frame(frame_index + 1, total_frames)
        elif char == "j":
            playing = False
            frame_index = clamp_frame(frame_index - int(round(fps)), total_frames)
        elif char == "l":
            playing = False
            frame_index = clamp_frame(frame_index + int(round(fps)), total_frames)
        elif char == "[":
            playing = False
            frame_index = clamp_frame(frame_index - int(round(fps * 5)), total_frames)
        elif char == "]":
            playing = False
            frame_index = clamp_frame(frame_index + int(round(fps * 5)), total_frames)
        elif char == "s":
            draft_release = round_time(time_s)
            message = f"Release marked at {draft_release:.2f}s."
        elif char in {"m", "x"}:
            if args.require_release and draft_release is None:
                message = "Press 's' to mark release before make/miss."
                continue
            result = "make" if char == "m" else "miss"
            shot = {
                "attempt": len(shots) + 1,
                "time_s": round_time(time_s),
                "result": result,
                "result_time_s": round_time(time_s),
            }
            if draft_release is not None:
                shot["release_time_s"] = draft_release
            shots.append(shot)
            shots = normalize_shots(shots)
            draft_release = None
            message = f"Added {result} at {round_time(time_s):.2f}s."
        elif char == "u":
            if shots:
                removed = shots.pop()
                message = (
                    f"Removed shot #{removed.get('attempt')} "
                    f"{removed.get('result')} at {removed.get('time_s')}s."
                )
            else:
                message = "No shot to undo."
        elif char == "c":
            draft_release = None
            message = "Release marker cleared."
        elif char == "p":
            return {"action": "next", "save": False, "shots": shots}
        elif char == "n":
            return {"action": "next", "save": True, "shots": shots}
        elif char == "q":
            return {"action": "quit", "save": True, "shots": shots}
        elif char == "h":
            print_controls()
            message = "Controls printed in terminal."
        else:
            message = f"Unhandled key: {key}"

        if playing:
            frame_index = clamp_frame(frame_index + 1, total_frames)

    return {"action": "next", "save": True, "shots": shots}


def read_frame(cv2: Any, cap: Any, frame_index: int) -> Any | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    return frame if ok else None


def draw_overlay(
    cv2: Any,
    frame: Any,
    video_id: str,
    frame_index: int,
    total_frames: int,
    fps: float,
    time_s: float,
    shots: list[dict[str, Any]],
    draft_release: float | None,
    message: str,
    max_width: int,
) -> Any:
    display = resize_for_display(cv2, frame, max_width)
    lines = [
        f"{video_id}",
        f"time={time_s:.2f}s frame={frame_index + 1}/{max(total_frames, 1)} fps={fps:.2f}",
        f"shots={len(shots)} make={count_result(shots, 'make')} miss={count_result(shots, 'miss')}",
        f"release={format_time(draft_release)} message={message}",
        "space play | a/d frame | j/l 1s | [/ ] 5s | s release | m make | x miss",
        "u undo | c clear release | n save next | p skip | q save quit | esc abort",
    ]
    recent = shots[-5:]
    for shot in recent:
        lines.append(
            f"#{shot.get('attempt')} {shot.get('result')} "
            f"t={shot.get('time_s')} release={shot.get('release_time_s', '-')}"
        )

    y = 24
    for line in lines:
        draw_text(cv2, display, line, 12, y)
        y += 24
    return display


def resize_for_display(cv2: Any, frame: Any, max_width: int) -> Any:
    height, width = frame.shape[:2]
    if width <= max_width:
        return frame.copy()
    scale = max_width / float(width)
    return cv2.resize(frame, (max_width, int(round(height * scale))))


def draw_text(cv2: Any, image: Any, text: str, x: int, y: int) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.62
    thickness = 2
    (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, thickness)
    cv2.rectangle(
        image,
        (x - 4, y - text_h - baseline - 4),
        (x + text_w + 4, y + baseline + 4),
        (0, 0, 0),
        -1,
    )
    cv2.putText(image, text, (x, y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def normalize_shots(raw_shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for shot in raw_shots:
        if not isinstance(shot, dict):
            continue
        result = normalize_result(shot.get("result"))
        time_s = as_float(
            shot.get("time_s")
            if "time_s" in shot
            else shot.get("timeS", shot.get("timestamp", shot.get("result_time_s")))
        )
        if result not in {"make", "miss"} or time_s is None:
            continue
        result_time = as_float(shot.get("result_time_s"))
        item: dict[str, Any] = {
            "time_s": round_time(time_s),
            "result": result,
            "result_time_s": round_time(result_time if result_time is not None else time_s),
        }
        release = as_float(shot.get("release_time_s"))
        if release is not None:
            item["release_time_s"] = round_time(release)
        for key in ("miss_type", "shot_type", "notes"):
            if shot.get(key):
                item[key] = shot[key]
        normalized.append(item)

    normalized.sort(key=lambda item: item["time_s"])
    for index, shot in enumerate(normalized, start=1):
        shot["attempt"] = index
    return normalized


def normalize_result(value: Any) -> str | None:
    if isinstance(value, bool):
        return "make" if value else "miss"
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"make", "made", "hit", "score", "scored", "true", "1"}:
        return "make"
    if text in {"miss", "missed", "false", "0"}:
        return "miss"
    return text or None


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def count_result(shots: list[dict[str, Any]], result: str) -> int:
    return sum(1 for shot in shots if shot.get("result") == result)


def round_time(value: float) -> float:
    return round(float(value), 2)


def format_time(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}s"


def clamp_frame(frame_index: int, total_frames: int) -> int:
    if total_frames <= 0:
        return max(frame_index, 0)
    return max(0, min(frame_index, total_frames - 1))


def print_controls() -> None:
    print(
        "\nControls:\n"
        "  space  play/pause\n"
        "  a/d    previous/next frame\n"
        "  j/l    jump -/+ 1 second\n"
        "  [/]    jump -/+ 5 seconds\n"
        "  s      mark release time for the next shot\n"
        "  m      add make at current result time\n"
        "  x      add miss at current result time\n"
        "  u      undo last shot\n"
        "  c      clear pending release marker\n"
        "  n      save labels and move to next video\n"
        "  p      skip current video without saving\n"
        "  q      save labels and quit\n"
        "  esc    abort without saving current video\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
