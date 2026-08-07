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

1. Copy large recordings into `test_videos/<scene_type>/`. Browser import is only for files up to 64 MB.
2. Open a video from the left list.
3. Mark each shot result.
4. Save the video label. This also marks a zero-shot video as completed.
5. Export `labels.json`.

Small imported files are copied into `test_videos/<scene_type>/`.

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
