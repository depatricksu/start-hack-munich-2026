"""Points per round for EVERY team, from the public leaderboard (no key). Owner: Riky.

GET /v1/board shows only running totals. This tool keeps a snapshot each time it runs (data/board_history.jsonl,
git-ignored) and turns consecutive snapshots into per-team gains, so we see where the leaders beat us and which
rounds made everybody fall (= a 5U hourly change).

    python3 -m audit.board            # take a snapshot now and print the table
    python3 -m audit.board --watch    # a snapshot every 30 s, print the table when a round closes (own Terminal)

How to read a gain: ~60 = accepted, full price + time; ~70 = the same + tracking bonus; 0 = rejected or missed;
a jump of hundreds at the hour = the hourly LLM-cost points.
"""
import json, os, sys, time, urllib.request

BASE = os.environ.get("FIVEU_BASE_URL", "https://api.start-hack.5u.ai")
HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "board_history.jsonl")
US = os.environ.get("TEAM_NAME", "Google")


def fetch():
    with urllib.request.urlopen(BASE + "/v1/board", timeout=10) as r:
        return json.load(r)


def snapshot():
    d = fetch()
    closed = max([r["round_no"] for r in d.get("rounds", []) if r.get("status") != "open"] or [0])
    row = {"t": time.time(), "closed": closed, "rounds": d.get("rounds", []),
           "totals": {t["team"]: t["total"] for t in d.get("ranking", [])},
           "accepted": {t["team"]: t["accepted"] for t in d.get("ranking", [])}}
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    with open(HIST, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def history():
    if not os.path.exists(HIST):
        return []
    rows = []
    for line in open(HIST):
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def per_round(rows):
    """{closed round number: {team: gain since the previous closed round}} from the last snapshot of each round."""
    last = {}
    for r in rows:
        last[r["closed"]] = r
    keys = sorted(last)
    out = {}
    for a, b in zip(keys, keys[1:]):
        out[b] = {team: round(total - last[a]["totals"].get(team, 0), 1) for team, total in last[b]["totals"].items()}
    return out


def table(rows, top=6, last_n=8):
    if not rows:
        return "no snapshots yet"
    gains = per_round(rows)
    now = rows[-1]["totals"]
    leaders = sorted(now, key=lambda t: -now[t])[:top]
    if US in now and US not in leaders:
        leaders.append(US)
    rounds = sorted(gains)[-last_n:]
    lines = ["round  " + "  ".join(f"{t[:12]:>12}" for t in leaders)]
    for rd in rounds:
        lines.append(f"{rd:>5}  " + "  ".join(f"{gains[rd].get(t, 0):>12.1f}" for t in leaders))
    lines.append("total  " + "  ".join(f"{now[t]:>12.1f}" for t in leaders))
    hard = [rd for rd in rounds if sum(1 for v in gains[rd].values() if v >= 30) <= len(gains[rd]) // 3]
    if hard:
        lines.append("hard rounds (most teams scored ~0, look for a 5U change): " + ", ".join(map(str, hard)))
    if US in now and rounds:
        behind = [rd for rd in rounds if max(gains[rd].values()) - gains[rd].get(US, 0) >= 5]
        if behind:
            lines.append(f"rounds where {US} got 5+ points less than the best team: " + ", ".join(map(str, behind)))
    return "\n".join(lines)


def main(argv):
    if "--watch" in argv:
        seen = None
        while True:
            try:
                row = snapshot()
                if row["closed"] != seen:
                    seen = row["closed"]
                    print(time.strftime("%H:%M:%S"), "round", seen, "closed\n" + table(history()) + "\n", flush=True)
            except Exception as e:
                print("board error:", e, flush=True)
            time.sleep(30)
    snapshot()
    print(table(history()))


if __name__ == "__main__":
    main(sys.argv[1:])
