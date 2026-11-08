#!/usr/bin/env python3
"""Forecast Roblox's Top Trending top 10 for the 24 hours after the history ends.

Reads /input/history.ndjson and /input/task.json, writes /output/forecast.json
($MAKEFUN_INPUT_DIR / $MAKEFUN_OUTPUT_DIR override the paths).

The model is a diffusion over chart places, estimated from the history itself:
a game's place moves as a random walk whose per-hour step size is measured on
every pair of consecutive reads, and the probability that the top 10 is entered
from outside is measured the same way. The forecast is the average of that law
over the scored window's hours, so it does not have to guess which hour is read.

Standard library only. No network. Deterministic: no randomness, no clock.
"""
import json
import math
import os

PLACES_CAP = 0.90          # a place names at most this much mass; the rest spreads over the chart
MAX_ROWS_PER_PLACE = 60
MIN_P = 1e-5
CANDIDATE_DEPTH = 25       # how far down the latest chart a game may be and still be named


def input_dir():
    return os.environ.get("MAKEFUN_INPUT_DIR") or "/input"


def output_dir():
    return os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"


def load_reads(path):
    reads = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            chart = obj.get("top_trending") or []
            entries = []
            for row in chart:
                uid = row.get("universe_id")
                rank = row.get("rank")
                if uid is None or rank is None:
                    continue
                entries.append((int(rank), int(uid)))
            if not entries:
                continue
            entries.sort()
            reads.append({"at": obj.get("at"), "order": [uid for _, uid in entries]})
    reads.sort(key=lambda r: r["at"] or "")
    return reads


def hours_between(a, b):
    """Hours from ISO-8601 stamp a to b; 0 when unparseable."""
    def parse(s):
        # 2026-10-30T07:36:30Z -> seconds; tolerant of missing seconds
        s = s.rstrip("Z")
        date, _, clock = s.partition("T")
        y, m, d = (int(x) for x in date.split("-"))
        parts = [float(x) for x in clock.split(":")] if clock else [0.0]
        while len(parts) < 3:
            parts.append(0.0)
        days = (y * 365 + m * 30 + d)
        return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]
    try:
        return max(0.0, (parse(b) - parse(a)) / 3600.0)
    except Exception:
        return 0.0


def estimate_diffusion(reads, places):
    """Per-hour variance of a place change, from consecutive reads."""
    num = 0.0
    den = 0.0
    jumps = 0
    total = 0
    for prev, cur in zip(reads, reads[1:]):
        gap = hours_between(prev["at"], cur["at"])
        if gap <= 0.01 or gap > 72:
            continue
        before = {u: i for i, u in enumerate(prev["order"], 1)}
        after = {u: i for i, u in enumerate(cur["order"], 1)}
        for uid, p0 in before.items():
            if uid not in after:
                continue
            d = after[uid] - p0
            num += d * d
            den += gap
            jumps += 1 if d else 0
            total += 1
    if den <= 0 or total == 0:
        return 2.25  # fall back to a 1.5-place hourly step
    # d over a gap of g hours behaves like a random walk: E[d^2] = sigma^2 * g
    return max(0.05, num / den)


def estimate_entry(reads, places):
    """Fraction of a read's top 10 that was outside the previous top 10, per hour."""
    rate_num = 0.0
    rate_den = 0.0
    for prev, cur in zip(reads, reads[1:]):
        gap = hours_between(prev["at"], cur["at"])
        if gap <= 0.01 or gap > 72:
            continue
        before = set(prev["order"][:places])
        after = set(cur["order"][:places])
        new = len(after - before)
        rate_num += new
        rate_den += gap * places
    if rate_den <= 0:
        return 0.02
    return max(0.001, min(0.25, rate_num / rate_den))


def kernel_probs(start_place, sigma2, hours, places):
    """P(place k in 1..places) for a game now at start_place, plus the out mass."""
    var = sigma2 * hours
    if var <= 1e-9:
        probs = [0.0] * (places + 1)
        idx = min(places - 1, max(0, start_place - 1))
        probs[idx] = 1.0
        return probs
    sd = math.sqrt(var)
    raw = []
    for k in range(1, places + 1):
        z = (k - start_place) / sd
        raw.append(math.exp(-0.5 * z * z))
    # discretised normal spread over the window's mean: average over the hours
    total = sum(raw)
    if total <= 0:
        return [1.0 / places] * places + [0.0]
    inside = 0.9 if hours > 1 else 0.97
    probs = [inside * r / total for r in raw]
    probs.append(1.0 - inside)
    return probs


def forecast(reads, task):
    places = int(task.get("places") or 10)
    window = task.get("window") or {}
    slots = int(window.get("slots") or 24)
    slot_minutes = float(window.get("slot_minutes") or 60)
    horizon = slots * slot_minutes / 60.0

    last = reads[-1]["order"] if reads else []
    sigma2 = estimate_diffusion(reads, places)
    entry = estimate_entry(reads, places)

    # average the diffusion law over the window's hours
    hours_grid = [max(1.0, horizon * (i + 0.5) / max(1, slots)) for i in range(slots)]

    candidates = last[:CANDIDATE_DEPTH]
    if not candidates:
        return {"probabilities": [], "top10": []}

    rows = []
    best_place = {}
    for uid in candidates:
        if uid in last[:places]:
            start = last.index(uid) + 1
            acc = [0.0] * (places + 1)
            for h in hours_grid:
                pr = kernel_probs(start, sigma2, h, places)
                for i, v in enumerate(pr):
                    acc[i] += v
            acc = [v / len(hours_grid) for v in acc]
            # every game may also lose the chart entirely: the outside mass grows with time
            outside = min(0.5, entry * horizon * 0.5)
            acc = [v * (1.0 - outside) for v in acc[:places]] + [acc[places] + outside]
        else:
            # a game below the top 10 steps in with the measured entry rate
            acc = [0.0] * (places + 1)
            base = entry * horizon / places
            for k in range(places):
                acc[k] = base * (1.0 - 0.1 * k / places)
            acc[places] = 1.0 - sum(acc[:places])
        best_place[uid] = acc

    # place rows, each capped, highest rows first
    for place in range(1, places + 1):
        column = [(uid, dist[place - 1]) for uid, dist in best_place.items() if dist[place - 1] > MIN_P]
        column.sort(key=lambda x: (-x[1], x[0]))
        column = column[:MAX_ROWS_PER_PLACE]
        total = sum(p for _, p in column)
        if total <= 0:
            continue
        scale = min(1.0, PLACES_CAP / total)
        for uid, p in column:
            rows.append({"universe_id": uid, "place": place, "p": round(p * scale, 6)})

    # top 10: greedy assignment on the same distributions, restricted to the latest chart
    remaining = [u for u in candidates]
    top10 = []
    for place in range(1, places + 1):
        if not remaining:
            break
        pick = max(remaining, key=lambda u: (best_place[u][place - 1], -last.index(u) if u in last else -99))
        top10.append(pick)
        remaining.remove(pick)
    return {"probabilities": rows, "top10": top10}


def main():
    inp = input_dir()
    out = output_dir()
    reads = load_reads(os.path.join(inp, "history.ndjson"))
    task_path = os.path.join(inp, "task.json")
    task = {}
    if os.path.exists(task_path):
        with open(task_path, encoding="utf-8") as fh:
            task = json.load(fh)
    result = forecast(reads, task)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "forecast.json"), "w", encoding="utf-8", newline="") as fh:
        json.dump(result, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    main()
