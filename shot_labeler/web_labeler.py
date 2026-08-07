#!/usr/bin/env python3
"""Local browser-based shot labeler for basketball batch datasets."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import default as email_policy
import json
import mimetypes
import os
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from shot_labeler import (
    VIDEO_EXTENSIONS,
    count_result,
    infer_scene_type,
    load_labels,
    normalize_shots,
    resolve_path,
    video_id_for,
    write_labels,
)


STATIC_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_SCENE_TYPES = (
    "fixed_halfcourt",
    "handheld_landscape",
    "vertical_close",
    "far_fullcourt",
)
SCENE_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_IMPORT_BYTES = 64 * 1024 * 1024


class UploadTooLargeError(ValueError):
    """Raised before a browser upload is read into process memory."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local web UI for basketball shot labeling.")
    parser.add_argument("--labels", default="labels.json", help="labels.json to create or update.")
    parser.add_argument("--test-root", default="test_videos", help="Root for relative video_id values.")
    parser.add_argument(
        "--video-root",
        default="test_videos/fixed_halfcourt",
        help="Directory of videos to label.",
    )
    parser.add_argument("--scene-type", help="Override scene_type for saved labels.")
    parser.add_argument("--recursive", action="store_true", help="Recursively discover videos.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Preferred port.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = LabelerState(
        labels_path=resolve_path(args.labels),
        test_root=resolve_path(args.test_root),
        video_root=resolve_path(args.video_root),
        scene_type=args.scene_type,
        recursive=args.recursive,
    )
    server = make_server(args.host, args.port, state)
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}"
    print(f"Basketball web labeler: {url}", flush=True)
    print(f"Videos: {state.video_root}", flush=True)
    print(f"Labels: {state.labels_path}", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping labeler.", flush=True)
    finally:
        server.server_close()
    return 0


class LabelerState:
    def __init__(
        self,
        labels_path: Path,
        test_root: Path,
        video_root: Path,
        scene_type: str | None,
        recursive: bool,
    ) -> None:
        self.labels_path = labels_path
        self.test_root = test_root
        self.video_root = video_root
        self.scene_type_override = normalize_scene_type(scene_type) if scene_type else None
        self.recursive = recursive
        self.lock = threading.Lock()
        self.extra_video_paths: set[Path] = set()
        self.videos = self.discover_videos()

    def discover_videos(self) -> list[dict[str, Any]]:
        if not self.video_root.exists():
            self.video_root.mkdir(parents=True, exist_ok=True)
        iterator = self.video_root.rglob("*") if self.recursive else self.video_root.iterdir()
        video_paths = {
            item.resolve()
            for item in iterator
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
        }
        video_paths.update(
            path.resolve()
            for path in self.extra_video_paths
            if path.exists() and path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        )
        videos: list[dict[str, Any]] = []
        for index, path in enumerate(
            sorted(
                video_paths
            )
        ):
            videos.append(
                {
                    "index": index,
                    "path": path,
                    "video_id": video_id_for(path, self.test_root),
                    "scene_type": self.scene_type_for(path),
                    "media_url": f"/media/{index}",
                    "fps": read_fps(path),
                }
            )
        return videos

    def default_import_scene(self) -> str:
        if self.scene_type_override:
            return self.scene_type_override
        try:
            relative = self.video_root.resolve().relative_to(self.test_root.resolve())
            if relative.parts:
                return normalize_scene_type_or_default(relative.parts[0])
        except ValueError:
            pass
        return DEFAULT_SCENE_TYPES[0]

    def scene_type_for(self, path: Path) -> str:
        raw_scene = self.scene_type_override or infer_scene_type(path, self.test_root)
        return normalize_scene_type_or_default(raw_scene)

    def scene_options(self) -> dict[str, Any]:
        scenes = set(DEFAULT_SCENE_TYPES)
        if self.scene_type_override:
            scenes.add(self.scene_type_override)
        if self.test_root.exists():
            for path in self.test_root.iterdir():
                if not path.is_dir():
                    continue
                try:
                    scenes.add(normalize_scene_type(path.name))
                except ValueError:
                    continue
        default_scene = self.default_import_scene()
        scenes.add(default_scene)
        ordered = [scene for scene in DEFAULT_SCENE_TYPES if scene in scenes]
        ordered.extend(sorted(scenes.difference(ordered)))
        return {"default_scene_type": default_scene, "scene_types": ordered}

    def labels(self) -> dict[str, Any]:
        with self.lock:
            return load_labels(self.labels_path)

    def save_video_label(self, video_index: int, shots: list[dict[str, Any]], notes: str = "") -> dict[str, Any]:
        video = self.video_by_index(video_index)
        if video is None:
            raise ValueError(f"unknown video index: {video_index}")
        normalized = normalize_shots(shots)
        with self.lock:
            labels = load_labels(self.labels_path)
            item = find_or_create_label(labels, video["video_id"], video["path"])
            makes = count_result(normalized, "make")
            misses = count_result(normalized, "miss")
            item["video_id"] = video["video_id"]
            item["scene_type"] = video["scene_type"]
            item["true_shots"] = len(normalized)
            item["true_makes"] = makes
            item["true_misses"] = misses
            item["score_time"] = [shot["time_s"] for shot in normalized if shot.get("result") == "make"]
            item["shots"] = normalized
            item["notes"] = notes
            item["completed"] = True
            write_labels(self.labels_path, labels)
        return item

    def video_by_index(self, index: int) -> dict[str, Any] | None:
        if index < 0 or index >= len(self.videos):
            return None
        return self.videos[index]

    def import_videos(self, uploads: list[dict[str, Any]], scene_type: str | None) -> list[dict[str, Any]]:
        scene = normalize_scene_type(scene_type or self.default_import_scene())
        target_dir = (self.test_root / scene).resolve()
        try:
            target_dir.relative_to(self.test_root.resolve())
        except ValueError as exc:
            raise ValueError(f"invalid import directory: {target_dir}") from exc

        target_dir.mkdir(parents=True, exist_ok=True)
        saved: list[dict[str, Any]] = []
        for upload in uploads:
            filename = sanitize_video_filename(str(upload.get("filename") or ""))
            data = upload.get("data")
            if not isinstance(data, bytes) or not data:
                raise ValueError(f"empty upload: {filename}")
            destination = unique_destination(target_dir, filename)
            destination.write_bytes(data)
            self.extra_video_paths.add(destination.resolve())
            saved.append(
                {
                    "filename": destination.name,
                    "video_id": video_id_for(destination, self.test_root),
                    "scene_type": scene,
                    "size_bytes": destination.stat().st_size,
                }
            )
        if not saved:
            raise ValueError("no video files were uploaded")
        self.videos = self.discover_videos()
        return saved


def find_or_create_label(labels: dict[str, Any], video_id: str, video_path: Path) -> dict[str, Any]:
    candidates = {video_id, str(video_path.resolve())}
    for item in labels.get("videos", []):
        if not isinstance(item, dict):
            continue
        raw = str(item.get("video_id") or item.get("video") or item.get("id") or "")
        if raw in candidates:
            return item
    item = {"video_id": video_id}
    labels.setdefault("videos", []).append(item)
    return item


def read_fps(path: Path) -> float:
    try:
        import cv2  # type: ignore

        cap = cv2.VideoCapture(str(path))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        cap.release()
        if fps > 1 and fps == fps:
            return round(fps, 3)
    except Exception:
        pass
    return 30.0


def make_server(host: str, preferred_port: int, state: LabelerState) -> ThreadingHTTPServer:
    last_error: OSError | None = None
    for port in range(preferred_port, preferred_port + 30):
        try:
            handler = build_handler(state)
            return ThreadingHTTPServer((host, port), handler)
        except OSError as exc:
            last_error = exc
            if exc.errno not in {48, 98}:  # address already in use on macOS/Linux
                raise
    raise RuntimeError(f"could not bind port near {preferred_port}: {last_error}")


def build_handler(state: LabelerState) -> type[BaseHTTPRequestHandler]:
    class LabelerHandler(BaseHTTPRequestHandler):
        server_version = "BasketballShotLabeler/1.0"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            if parsed.path == "/" or parsed.path == "/index.html":
                return self.send_static("index.html")
            if parsed.path.startswith("/static/"):
                return self.send_static(parsed.path.removeprefix("/static/"))
            if parsed.path == "/api/videos":
                return self.send_json(videos_payload(state))
            if parsed.path == "/api/labels":
                return self.send_json(state.labels())
            if parsed.path == "/api/export":
                return self.send_export()
            if parsed.path.startswith("/media/"):
                return self.send_media(parsed.path)
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            if parsed.path == "/api/label":
                return self.save_label()
            if parsed.path == "/api/import":
                return self.import_videos()
            self.send_error(HTTPStatus.NOT_FOUND)

        def send_static(self, relative: str) -> None:
            target = (STATIC_DIR / relative).resolve()
            try:
                target.relative_to(STATIC_DIR.resolve())
            except ValueError:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not target.exists() or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_media(self, path: str) -> None:
            try:
                index = int(path.removeprefix("/media/").split("/", 1)[0])
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            video = state.video_by_index(index)
            if video is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            send_file_with_range(self, video["path"])

        def save_label(self) -> None:
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(raw.decode("utf-8") or "{}")
                video_index = int(payload.get("video_index"))
                shots = payload.get("shots")
                if not isinstance(shots, list):
                    raise ValueError("shots must be an array")
                notes = str(payload.get("notes") or "")
                item = state.save_video_label(video_index, shots, notes)
            except Exception as exc:  # noqa: BLE001 - local tool returns message to UI.
                return self.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            self.send_json({"ok": True, "label": item})

        def import_videos(self) -> None:
            try:
                fields, uploads = parse_multipart_upload(self)
                saved = state.import_videos(uploads, fields.get("scene_type"))
            except UploadTooLargeError as exc:
                return self.send_json(
                    {"ok": False, "error": str(exc)},
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
            except Exception as exc:  # noqa: BLE001 - local tool returns message to UI.
                return self.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            self.send_json({"ok": True, "saved": saved, "payload": videos_payload(state)})

        def send_export(self) -> None:
            data = json.dumps(state.labels(), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="labels.json"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            if self.path.startswith("/media/"):
                return
            super().log_message(format, *args)

    return LabelerHandler


def normalize_scene_type(raw: str) -> str:
    value = str(raw or "").strip()
    if not SCENE_TYPE_PATTERN.fullmatch(value):
        raise ValueError("scene_type must use letters, numbers, underscore, or dash")
    return value


def normalize_scene_type_or_default(raw: str) -> str:
    try:
        return normalize_scene_type(raw)
    except ValueError:
        return DEFAULT_SCENE_TYPES[0]


def sanitize_video_filename(raw: str) -> str:
    name = raw.replace("\\", "/").split("/")[-1].strip()
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError(f"unsupported video file type: {suffix or '(none)'}")
    stem = Path(name).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._") or "video"
    return f"{safe_stem}{suffix}"


def unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 10000):
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError(f"could not find a free filename for {filename}")


def parse_multipart_upload(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], list[dict[str, Any]]]:
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("request must be multipart/form-data")
    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    if content_length <= 0:
        raise ValueError("empty upload request")
    if content_length > MAX_IMPORT_BYTES:
        max_mb = MAX_IMPORT_BYTES // (1024 * 1024)
        raise UploadTooLargeError(
            f"browser import is limited to {max_mb} MB; copy larger videos into test_videos instead"
        )
    body = handler.rfile.read(content_length)
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    message = BytesParser(policy=email_policy).parsebytes(header + body)
    if not message.is_multipart():
        raise ValueError("invalid multipart upload")

    fields: dict[str, str] = {}
    uploads: list[dict[str, Any]] = []
    for part in message.iter_parts():
        field_name = part.get_param("name", header="content-disposition")
        if not field_name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            uploads.append({"filename": filename, "data": payload})
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[str(field_name)] = payload.decode(charset, errors="replace")
    return fields, uploads


def videos_payload(state: LabelerState) -> dict[str, Any]:
    labels = state.labels()
    label_by_id = {
        str(item.get("video_id") or item.get("video") or item.get("id") or ""): item
        for item in labels.get("videos", [])
        if isinstance(item, dict)
    }
    videos = []
    for video in state.videos:
        label = label_by_id.get(video["video_id"]) or {}
        shots = label.get("shots") if isinstance(label.get("shots"), list) else []
        completed = label_is_completed(label)
        videos.append(
            {
                "index": video["index"],
                "video_id": video["video_id"],
                "scene_type": video["scene_type"],
                "media_url": video["media_url"],
                "fps": video["fps"],
                "labeled": completed,
                "completed": completed,
                "shots": shots,
                "notes": label.get("notes") or "",
                "true_shots": label.get("true_shots"),
                "true_makes": label.get("true_makes"),
                "true_misses": label.get("true_misses"),
            }
        )
    return {
        "labels_path": str(state.labels_path),
        "test_root": str(state.test_root),
        "video_root": str(state.video_root),
        "import": state.scene_options(),
        "videos": videos,
    }


def label_is_completed(label: dict[str, Any]) -> bool:
    if not label:
        return False
    if bool(label.get("completed")):
        return True
    return any(
        key in label
        for key in ("shots", "true_shots", "true_makes", "true_misses", "score_time")
    )


def send_file_with_range(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.exists():
        handler.send_error(HTTPStatus.NOT_FOUND)
        return
    file_size = path.stat().st_size
    range_header = handler.headers.get("Range")
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    start = 0
    end = file_size - 1
    status = HTTPStatus.OK
    if range_header and range_header.startswith("bytes="):
        value = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
        try:
            if "-" in value:
                left, right = value.split("-", 1)
                if left:
                    start = max(0, int(left))
                    if right:
                        end = min(file_size - 1, int(right))
                elif right:
                    suffix_length = max(0, int(right))
                    start = max(file_size - suffix_length, 0)
            status = HTTPStatus.PARTIAL_CONTENT
        except ValueError:
            start = 0
            end = file_size - 1
            status = HTTPStatus.OK
        if start > end or start >= file_size:
            handler.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            handler.send_header("Content-Range", f"bytes */{file_size}")
            handler.end_headers()
            return

    length = end - start + 1
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(length))
    if status == HTTPStatus.PARTIAL_CONTENT:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
    handler.end_headers()
    with path.open("rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                break
            remaining -= len(chunk)


if __name__ == "__main__":
    raise SystemExit(main())
