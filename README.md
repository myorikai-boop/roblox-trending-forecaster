# Roblox Top Trending forecaster

Entry for the make.fun competition `roblox-trending-forecast-01`.

Reads `/input/history.ndjson` and `/input/task.json` and writes
`/output/forecast.json`: a probability for each game at each of the top 10
places, plus a best-guess top 10.

## Model

A game's place in the chart moves as a random walk. The per-hour step size is
measured on the history itself: every pair of consecutive reads contributes
`(place change)^2 / hours`, which is the diffusion coefficient of that walk.
The chance that the top 10 is entered from below is measured the same way, as
the fraction of each read's top 10 that was outside the previous read's top 10.

The scored window is 24 hourly reads and the forecast is a single static file,
so the program averages the walk over the window's hours instead of betting on
one of them. Each place's named rows are capped at 0.90, which leaves the
unnamed share to spread over the rest of the chart: a game nobody named still
scores, and a surprise arrival costs far less than a confident wrong call.

## Run

```sh
MAKEFUN_INPUT_DIR=./example/input MAKEFUN_OUTPUT_DIR=/tmp/out python3 main.py
python3 run_local_test.py     # contract test on a synthetic history
```

Standard library only, no network, deterministic.
