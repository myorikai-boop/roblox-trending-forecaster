#!/usr/bin/env python3
"""Local contract test: synthetic history -> main.py -> schema check + simulated score."""
import json, math, os, random, shutil, subprocess, sys, tempfile

GAMES = [{"universe_id": 1000 + i, "name": f"Game {i}"} for i in range(40)]

def make_history(root, reads=26, hours=6.0, seed=7):
    rnd = random.Random(seed)
    order = [g["universe_id"] for g in GAMES]
    out = []
    t = 0.0
    for r in range(reads):
        # a few adjacent swaps, the way a chart drifts between reads
        for _ in range(rnd.randint(3, 9)):
            i = rnd.randrange(0, 18)
            j = min(len(order) - 1, i + rnd.randint(1, 3))
            order[i], order[j] = order[j], order[i]
        hour = int(t) % 24
        stamp = f"2026-10-{30 + (int(t) // 24) % 4:02d}T{hour:02d}:00:00Z"
        chart = [{"rank": i + 1, "universe_id": uid, "root_place_id": uid, "name": f"Game {uid}",
                  "playing": 1000 + i, "up_votes": 1, "down_votes": 1, "genre": "Adventure"}
                 for i, uid in enumerate(order)]
        out.append({"at": stamp, "source": "synthetic", "filters": None, "ok": True,
                    "top_trending": chart, "top_playing_now": None, "details": None, "responses": {}})
        t += hours
    with open(os.path.join(root, "history.ndjson"), "w", encoding="utf-8") as fh:
        for o in out:
            fh.write(json.dumps(o) + "\n")
    with open(os.path.join(root, "task.json"), "w", encoding="utf-8") as fh:
        json.dump({"history_until": out[-1]["at"], "places": 10,
                   "window": {"from": out[-1]["at"], "until": "end", "slots": 24, "slot_minutes": 60},
                   "output": "forecast.json", "snapshots": len(out)}, fh)
    ids = [[c["universe_id"] for c in o["top_trending"]] for o in out]
    return ids

def score(forecast, future_orders):
    """Official log score: mean over reads of sum over places of ln(p), floored at 1e-4."""
    per_place = {}
    for row in forecast["probabilities"]:
        per_place.setdefault(row["place"], []).append((row["universe_id"], row["p"]))
    scores = []
    for order in future_orders:
        chart = order[:40]
        s = 0.0
        for place in range(1, 11):
            truth = chart[place - 1]
            rows = per_place.get(place, [])
            named = {u: p for u, p in rows}
            if truth in named:
                p = named[truth]
            else:
                unnamed = max(0.0, 1.0 - sum(p for _, p in rows))
                rest = len(set(chart) - set(named)) or 1
                p = unnamed / rest
            s += math.log(max(p, 1e-4))
        scores.append(s)
    return sum(scores) / len(scores)

def persistence(history_orders):
    last = history_orders[-1]
    rows = [{"universe_id": uid, "place": i + 1, "p": 1.0} for i, uid in enumerate(last[:10])]
    return {"probabilities": rows, "top10": last[:10]}

def run(env_extra):
    env = dict(os.environ); env.update(env_extra)
    p = subprocess.run([sys.executable, "main.py"], env=env, capture_output=True, text=True)
    if p.returncode != 0:
        print("RUN FAILED", p.returncode, p.stdout[-800:], p.stderr[-1500:]); sys.exit(1)

work = tempfile.mkdtemp()
inp = os.path.join(work, "input"); out = os.path.join(work, "output")
os.makedirs(inp); os.makedirs(out)
orders = make_history(inp)
env = {"MAKEFUN_INPUT_DIR": inp, "MAKEFUN_OUTPUT_DIR": out}

run(env)
first = open(os.path.join(out, "forecast.json"), "rb").read()
run(env)
second = open(os.path.join(out, "forecast.json"), "rb").read()
print("deterministic:", first == second, "| bytes:", len(first))

fc = json.loads(first)
ok = True
ok &= set(fc.keys()) == {"probabilities", "top10"}
ok &= all(set(r) == {"universe_id", "place", "p"} for r in fc["probabilities"])
ok &= all(isinstance(r["universe_id"], int) and 1 <= r["place"] <= 10 and 0 <= r["p"] <= 1 for r in fc["probabilities"])
sums = {}
for r in fc["probabilities"]:
    sums[r["place"]] = sums.get(r["place"], 0.0) + r["p"]
ok &= all(v <= 1.0001 for v in sums.values())
ok &= len(set(fc["top10"])) == 10 and all(isinstance(u, int) for u in fc["top10"])
print("schema ok:", ok)
print("places named:", len(sums), "| rows:", len(fc["probabilities"]))
print("top10:", fc["top10"][:10])

rnd = random.Random(99)
order = orders[-1][:40]
future = []
for _ in range(24):
    order = order[:]
    for _ in range(rnd.randint(0, 3)):
        i = rnd.randrange(0, 12); j = min(39, i + rnd.randint(1, 4)); order[i], order[j] = order[j], order[i]
    future.append(order)
print("simulated log score :", round(score(fc, future), 4))
print("persistence baseline:", round(score(persistence(orders), future), 4))
print("floor per read      :", round(-9.210340 * 10, 3), "| best possible 0.0")
shutil.rmtree(work)
