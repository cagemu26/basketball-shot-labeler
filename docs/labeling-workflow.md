# Labeling Workflow

This tool is for event-level basketball shot labeling.

## Minimal Label

For each shot, mark:

- `time_s`: the time when the result is clear
- `result`: `make` or `miss`

Example:

```json
{"time_s": 6.2, "result": "miss"}
```

## Browser Workflow

The full collection loop can be done in the web UI:

1. Select the scene folder.
2. Import local video files.
3. Open an imported video from the left list.
4. Mark each shot result.
5. Save the video label.
6. Export `labels.json`.

Imported files are copied into `test_videos/<scene_type>/`.

## Optional Release Time

If the release moment is visible, mark it too:

```json
{"release_time_s": 5.85, "time_s": 6.2, "result": "miss"}
```

The result time is usually more important for make/miss evaluation. Release time is useful for analyzing shot timing latency.

## Miss Types

Use `miss_type` only for misses:

- `rim_hit`
- `backboard_miss`
- `airball`
- `blocked`
- `under_basket_interference`

Keep `result` as `miss` for all of these. The subtype is used for later diagnostics.

## What Not To Label As A Shot

Do not add a shot row for:

- dribbles
- passes
- pump fakes
- rebounds
- loose balls
- blocked balls before a clear release

If the ball clearly leaves the hand as a shot attempt, label it as a shot.
