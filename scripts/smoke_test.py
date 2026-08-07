#!/usr/bin/env python3
"""Basic checks for the standalone labeler project."""

from __future__ import annotations

import json
import http.client
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shot_labeler"))

import shot_labeler  # noqa: E402
import web_labeler  # noqa: E402


def main() -> int:
    assert_normalization()
    assert_web_server_empty_dataset()
    assert_web_server_handles_nonstandard_folder_name()
    assert_label_studio_converter()
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
            import_payload = post_multipart(
                url + "/api/import",
                fields={"scene_type": "fixed_halfcourt"},
                files={"files": ("sample.mp4", b"fake mp4 bytes")},
            )
            assert import_payload["ok"] is True
            assert import_payload["saved"][0]["video_id"] == "fixed_halfcourt/sample.mp4"
            assert (videos / "sample.mp4").exists()
            saved = post_json(
                url + "/api/label",
                {"video_index": 0, "shots": [], "notes": "no shots in this video"},
            )
            assert saved["ok"] is True
            assert saved["label"]["completed"] is True
            with urllib.request.urlopen(url + "/api/videos", timeout=5) as res:
                payload = json.loads(res.read().decode("utf-8"))
            assert payload["videos"][0]["completed"] is True
            assert payload["videos"][0]["labeled"] is True
            assert payload["videos"][0]["shots"] == []
            assert_oversized_import_rejected(url)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def assert_web_server_handles_nonstandard_folder_name() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        videos = tmp / "8.6"
        videos.mkdir()
        (videos / "sample.mp4").write_bytes(b"fake mp4 bytes")
        proc = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "shot_labeler" / "web_labeler.py"),
                "--video-root",
                str(videos),
                "--test-root",
                str(tmp),
                "--labels",
                str(tmp / "labels.json"),
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
            assert payload["import"]["default_scene_type"] == "fixed_halfcourt"
            assert "8.6" not in payload["import"]["scene_types"]
            assert payload["videos"][0]["scene_type"] == "fixed_halfcourt"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def post_multipart(url: str, fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> dict:
    boundary = "----basketball-shot-labeler-smoke"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, data) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                b"Content-Type: video/mp4\r\n\r\n",
                data,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    with urllib.request.urlopen(request, timeout=5) as res:
        return json.loads(res.read().decode("utf-8"))


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as res:
        return json.loads(res.read().decode("utf-8"))


def assert_oversized_import_rejected(url: str) -> None:
    parsed = urlsplit(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request(
            "POST",
            "/api/import",
            body=b"",
            headers={
                "Content-Type": "multipart/form-data; boundary=unused",
                "Content-Length": str(web_labeler.MAX_IMPORT_BYTES + 1),
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 413
        assert payload["ok"] is False
        assert "limited to 64 MB" in payload["error"]
    finally:
        connection.close()


def wait_for_url(proc: subprocess.Popen[str]) -> str:
    deadline = time.time() + 8
    while time.time() < deadline:
        line = proc.stdout.readline() if proc.stdout else ""
        if "http://" in line:
            return line.rsplit(" ", 1)[-1].strip()
        if proc.poll() is not None:
            break
    raise RuntimeError("web server did not start")


def assert_label_studio_converter() -> None:
    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "labels.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "label_studio_export_to_labels.py"),
                "--input",
                str(ROOT / "examples" / "label_studio_export.example.json"),
                "--output",
                str(output),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        labels = json.loads(output.read_text(encoding="utf-8"))
        video = labels["videos"][0]
        assert video["video_id"] == "fixed_halfcourt/001.mp4"
        assert video["true_shots"] == 2
        assert video["true_makes"] == 1
        assert video["true_misses"] == 1
        assert video["shots"][0]["release_time_s"] == 2.96
        assert video["shots"][1]["miss_type"] == "airball"


if __name__ == "__main__":
    raise SystemExit(main())
