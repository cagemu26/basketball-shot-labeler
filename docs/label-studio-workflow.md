# Label Studio Workflow

This is an optional workflow for teams that want review queues, multiple
annotators, or Label Studio project management. The built-in browser labeler is
still the fastest path when one person is creating `labels.json` directly.

## When To Use Label Studio

Use Label Studio when you need:

- Multiple annotators or reviewer approval.
- A second-pass QA workflow for difficult misses.
- A shared labeling project that is separate from this repository.

Use the built-in local labeler when you need:

- Fast single-person labeling.
- Direct `labels.json` export with no conversion step.
- A simple local-only workflow for private videos.

## Labeling Design

The batch-eval contract needs event-level shot labels:

- `video_id`
- `scene_type`
- `true_shots`
- `true_makes`
- `true_misses`
- `score_time`
- `shots[]`
- `notes`

In Label Studio, represent each shot with one result event on the video
timeline. Use `release` only when the release frame is visible and worth
capturing.

Result labels:

- `make`: made basket.
- `miss_rim_hit`: miss that hits the rim.
- `miss_backboard`: miss that hits the backboard.
- `miss_airball`: miss with no rim or backboard contact.
- `miss_blocked`: released shot that is blocked.
- `miss_under_basket_interference`: miss affected by under-basket traffic.
- `miss_unknown`: miss where the subtype is not clear.
- `release`: optional shot release marker.

Rules:

- Add exactly one result event for each real shot attempt.
- Use a single-frame click or a very short segment at the moment where the
  result is clear.
- Sort order on the timeline becomes `attempt` order.
- Do not label passes, rebounds, loose balls, dribbles, or pump fakes as shots.
- If a release marker is present, the converter pairs it with the nearest later
  result event.

## Prepare Videos

Label Studio video playback depends on browser support. Prefer MP4 files with
H.264 video, AAC audio, and constant frame rate. A safe conversion command is:

```bash
ffmpeg -i input.mp4 \
  -c:v libx264 -profile:v high -level 4.0 -pix_fmt yuv420p -r 30 \
  -c:a aac -b:a 128k \
  output.mp4
```

Recommended folder layout:

```text
test_videos/
  fixed_halfcourt/
    001.mp4
    002.mp4
```

Serve the videos locally so Label Studio can load them by URL:

```bash
python3 -m http.server 9000 --directory test_videos
```

For Docker-based Label Studio, `localhost` inside the container is not your host
machine. Use host networking, a mounted local storage integration, or a URL that
the container can reach.

## Create The Project

1. Start Label Studio.
2. Create a new project.
3. Open the labeling interface settings.
4. Paste `label_studio/shot_event_config.xml`.
5. Import tasks in the shape of `label_studio/tasks.example.json`.

Example task:

```json
{
  "data": {
    "video": "http://localhost:9000/fixed_halfcourt/001.mp4",
    "video_id": "fixed_halfcourt/001.mp4",
    "scene_type": "fixed_halfcourt",
    "fps": 30
  }
}
```

## Install Label Studio

macOS / Linux:

```bash
python3 -m venv .venv-label-studio
source .venv-label-studio/bin/activate
python3 -m pip install label-studio
label-studio start
```

Windows PowerShell:

```powershell
py -3 -m venv .venv-label-studio
.\.venv-label-studio\Scripts\Activate.ps1
py -3 -m pip install label-studio
label-studio start
```

## Export And Convert

Export the Label Studio project as JSON. Then convert it into this repository's
batch-eval label format:

```bash
python3 scripts/label_studio_export_to_labels.py \
  --input exported_annotations.json \
  --output labels.json
```

The converter maps timeline labels like this:

```text
make                             -> result=make
miss_rim_hit                     -> result=miss, miss_type=rim_hit
miss_backboard                   -> result=miss, miss_type=backboard_miss
miss_airball                     -> result=miss, miss_type=airball
miss_blocked                     -> result=miss, miss_type=blocked
miss_under_basket_interference   -> result=miss, miss_type=under_basket_interference
miss_unknown                     -> result=miss
release                          -> release_time_s on nearest later result
```

## QA Pass

Before using the exported labels in batch eval:

1. Check that every real shot attempt has exactly one result label.
2. Check that all made baskets use `make`, not a miss subtype.
3. Check that unclear misses use `miss_unknown` instead of guessing.
4. Spot-check `score_time` values after conversion.
5. Keep private videos and exported real labels out of Git.

## Official References

- Video tag: https://labelstud.io/tags/video
- TimelineLabels tag: https://labelstud.io/tags/timelinelabels
- Video object detection/tracking template: https://labelstud.io/templates/video_object_detector
