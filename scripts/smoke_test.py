#!/usr/bin/env python3
"""Basic checks for the standalone labeler project."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shot_labeler"))

import shot_labeler  # noqa: E402


def main() -> int:
    assert_normalization()
    assert_web_server_empty_dataset()
    print("smoke test ok")
    return 0


def assert_normalization() -> None:
    shots = shot_labeler.normalize_shots(
        [
            {"time_s": 3.21, "result": "miss", "miss_type": "airball"},
            {"time_s": 1.23, "result": "make", "release_time_s": 0.98},
        ]
    )
    assert [shot["attempt"] for shot in shots] == [1, 2]
    assert shots[0]["result"] == "make"
    assert shots[1]["miss_type"] == "airball"


def assert_web_server_empty_dataset() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        videos = tmp / "test_videos" / "fixed_halfcourt"
        videos.mkdir(parents=True)
        labels = tmp / "labels.json"
        proc = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "shot_labeler" / "web_labeler.py"),
                "--video-root",
                str(videos),
                "--test-root",
                str(tmp / "test_videos"),
                "--labels",
                str(labels),
                "--scene-type",
                "fixed_halfcourt",
                "--port",
                "0",
                "--no-open",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            url = wait_for_url(proc)
            with urllib.request.urlopen(url + "/api/videos", timeout=5) as res:
                payload = json.loads(res.read().decode("utf-8"))
            assert payload["videos"] == []
            with urllib.request.urlopen(url + "/api/export", timeout=5) as res:
                exported = json.loads(res.read().decode("utf-8"))
            assert exported["videos"] == []
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def wait_for_url(proc: subprocess.Popen[str]) -> str:
    deadline = time.time() + 8
    while time.time() < deadline:
        line = proc.stdout.readline() if proc.stdout else ""
        if "http://" in line:
            return line.rsplit(" ", 1)[-1].strip()
        if proc.poll() is not None:
            break
    raise RuntimeError("web server did not start")


if __name__ == "__main__":
    raise SystemExit(main())
