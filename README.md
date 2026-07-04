# Basketball Shot Labeler

Local annotation tools for basketball shot-event datasets.

This project helps you label videos for downstream batch evaluation of basketball shot detection and make/miss judgment. It does not train a model. It creates a `labels.json` file with shot timestamps, results, optional release timestamps, and miss subtypes.

## What It Labels

Each real shot attempt should become one row:

```json
{
  "attempt": 1,
  "time_s": 3.42,
  "result": "make",
  "result_time_s": 3.42,
  "release_time_s": 2.96
}
```

For missed shots, you can optionally add a `miss_type`:

```json
{
  "attempt": 2,
  "time_s": 6.2,
  "result": "miss",
  "result_time_s": 6.2,
  "miss_type": "airball"
}
```

The generated `labels.json` also summarizes:

- `true_shots`
- `true_makes`
- `true_misses`
- `score_time`
- `shots[]`

## Environment

Tested with:

- macOS
- Windows
- Linux
- Python 3.9+
- Modern Chrome, Safari, or Edge for the web UI

Dependencies:

- Web UI: Python standard library is enough. `opencv-python` is optional and used only to read video FPS more accurately.
- OpenCV desktop labeler: requires `opencv-python`.

## Install On macOS / Linux

```bash
git clone https://github.com/cagemu26/basketball-shot-labeler.git
cd basketball-shot-labeler

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Install On Windows PowerShell

```powershell
git clone https://github.com/cagemu26/basketball-shot-labeler.git
cd basketball-shot-labeler

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install -r requirements.txt
```

If PowerShell blocks activation for the current terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Prepare Videos

Recommended layout:

```text
test_videos/
  fixed_halfcourt/
    001.mp4
    002.mp4
```

For the first dataset, fixed half-court videos are enough. Keep user/private videos out of Git.

You can also import videos from the web UI. The browser import button copies files into:

```text
test_videos/<scene_type>/
```

## Run The Web Labeler

macOS / Linux:

```bash
python3 shot_labeler/web_labeler.py \
  --video-root test_videos \
  --test-root test_videos \
  --labels labels.json \
  --recursive
```

Windows PowerShell:

```powershell
py -3 shot_labeler\web_labeler.py `
  --video-root test_videos `
  --test-root test_videos `
  --labels labels.json `
  --recursive
```

Open the printed local URL, usually:

```text
http://127.0.0.1:8765
```

The UI runs locally and writes directly to `labels.json`.

## Web UI Workflow

1. Choose a `Scene` in the left panel.
2. Select one or more local files in `Videos`.
3. Click `Import Videos`; files are copied into `test_videos/<scene>/`.
4. Pick a video from the left list.
5. Play or scrub to the moment where the shot result is clear.
6. Optionally press `s` to mark release time.
7. Press `m` for make or `x` for miss.
8. For a miss, choose the row-level `Type` in the `Shots` table.
9. Press `Save` or `Save Next`.
10. Press `Export JSON` to save the current video and download the full `labels.json`.

Keyboard shortcuts:

- `space`: play or pause
- `a` / `d`: previous or next frame
- `j` / `l`: jump backward or forward 1 second
- `[` / `]`: jump backward or forward 5 seconds
- `s`: mark release time for the next shot
- `m`: add a made shot at the current result time
- `x`: add a missed shot at the current result time
- `u`: undo the last shot
- `c`: clear pending release marker
- `n`: save and load next video
- `q`: save current video

## Run The OpenCV Labeler

The OpenCV version is useful when you prefer a simple desktop window:

```bash
python3 shot_labeler/shot_labeler.py \
  --video-root test_videos/fixed_halfcourt \
  --test-root test_videos \
  --labels labels.json \
  --scene-type fixed_halfcourt
```

## Labeling Rules

Label one `shots[]` item for every real shot attempt.

- Made shot: `result = "make"`
- Missed shot: `result = "miss"`
- Rim hit miss: `miss_type = "rim_hit"`
- Backboard miss: `miss_type = "backboard_miss"`
- Airball: `miss_type = "airball"`
- Blocked shot after clear release: usually `miss_type = "blocked"`
- Fake, pass, dribble, rebound, or loose ball with no real shot attempt: do not add a shot row.

For first-pass labeling, `time_s + result` is enough. Add `release_time_s` when you need tighter analysis of shot timing.

## Output Example

```json
{
  "name": "basketball-shot-labels",
  "defaults": {
    "has_net": true,
    "timeout_seconds": 900,
    "tolerance": {
      "makes": 0,
      "misses": 0,
      "attempts": 0,
      "shot_time_s": 0.35
    }
  },
  "videos": [
    {
      "video_id": "fixed_halfcourt/001.mp4",
      "scene_type": "fixed_halfcourt",
      "true_shots": 2,
      "true_makes": 1,
      "true_misses": 1,
      "score_time": [3.42],
      "shots": [
        {
          "attempt": 1,
          "time_s": 3.42,
          "result": "make",
          "result_time_s": 3.42,
          "release_time_s": 2.96
        },
        {
          "attempt": 2,
          "time_s": 6.2,
          "result": "miss",
          "result_time_s": 6.2,
          "miss_type": "airball"
        }
      ],
      "notes": ""
    }
  ]
}
```

## Validate Installation

```bash
python3 -m py_compile shot_labeler/shot_labeler.py shot_labeler/web_labeler.py
python3 scripts/smoke_test.py
```

## Privacy Notes

Do not commit real user videos or private labels. This repository ignores common video files and generated local datasets by default.

If you collect user-submitted videos, get explicit consent and review labels manually before adding them to a formal evaluation dataset.
