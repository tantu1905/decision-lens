"""Learn an expected-threat (xT) grid from simulated matches.

Splits the pitch into 16 x 12 zones and, for every zone, measures from the
simulator's own actions how often players shoot, how often shots score, and
where successful passes and carries take the ball. xT is then solved with the
usual Markov iteration:

    xT(zone) = P(shot) * P(goal | shot) + P(move) * sum(P(zone -> z') * xT(z'))

The result is written to xt_grid.json, which generate_match.py picks up
automatically. Running a few rounds lets the simulator play with the learned
values and re-learn from that play.

Matches are played at the same 25 frames per second as generate_match.py, spread over
all CPU cores.

Usage: python3 learn_xt.py --matches 30 --rounds 2
"""
import argparse
import importlib
import json
import multiprocessing
import os
import sys

NX, NY = 16, 12
MIN_ACTIONS = 8  # zones with fewer actions fall back to the hand-written surface
ITERATIONS = 40

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generate_match as gm  # noqa: E402


def zone(x, y):
    cx = min(int(max(x, 0) / gm.PITCH_X * NX), NX - 1)
    cy = min(int(max(y, 0) / gm.PITCH_Y * NY), NY - 1)
    return cx, cy


def learn(matches):
    shots = [[0] * NY for _ in range(NX)]
    goals = [[0] * NY for _ in range(NX)]
    moves = [[0] * NY for _ in range(NX)]
    trans = {}
    for events in matches:
        for e in events:
            if "regret" not in e:
                continue
            t_idx = 0 if e["team_id"] == "NRV" else 1
            sx, sy = gm.to_af((e["x"], e["y"]), t_idx)
            ex, ey = gm.to_af((e["end_x"], e["end_y"]), t_idx)
            cx, cy = zone(sx, sy)
            if e["type"] == "shot":
                shots[cx][cy] += 1
                goals[cx][cy] += e["outcome"] == "goal"
            else:
                moves[cx][cy] += 1
                if e["outcome"] == "success":
                    key = ((cx, cy), zone(ex, ey))
                    trans[key] = trans.get(key, 0) + 1
    grid = [[0.0] * NY for _ in range(NX)]
    for _ in range(ITERATIONS):
        new = [[0.0] * NY for _ in range(NX)]
        for cx in range(NX):
            for cy in range(NY):
                total = shots[cx][cy] + moves[cx][cy]
                if total < MIN_ACTIONS:
                    x = (cx + 0.5) * gm.PITCH_X / NX
                    y = (cy + 0.5) * gm.PITCH_Y / NY
                    new[cx][cy] = gm.xt_formula(x, y)
                    continue
                p_shot = shots[cx][cy] / total
                p_goal = goals[cx][cy] / shots[cx][cy] if shots[cx][cy] else 0.0
                move_value = 0.0
                if moves[cx][cy]:
                    for (src, dst), n in trans.items():
                        if src == (cx, cy):
                            move_value += n / moves[cx][cy] * grid[dst[0]][dst[1]]
                new[cx][cy] = p_shot * p_goal + (1 - p_shot) * move_value
        grid = new
    return [[round(v, 5) for v in col] for col in grid]


def play(job):
    seed, hz = job
    m = gm.Match(seed, hz=hz)
    m.simulate()
    return m.events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=30)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--hz", type=int, default=25, help="frames per second (25 = same as generate_match.py)")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    args = ap.parse_args()
    for r in range(args.rounds):
        seeds = range(1000 + r * args.matches, 1000 + (r + 1) * args.matches)
        # a fresh pool each round, so the workers play with the grid learned in the previous round
        with multiprocessing.get_context("fork").Pool(args.workers) as pool:
            matches = pool.map(play, [(seed, args.hz) for seed in seeds])
        grid = learn(matches)
        with open(os.path.join(HERE, "xt_grid.json"), "w", encoding="utf-8") as f:
            json.dump({"zones_x": NX, "zones_y": NY, "matches": args.matches, "round": r + 1, "hz": args.hz,
                       "grid": grid}, f)
        importlib.reload(gm)  # next round plays with the learned grid
        edge = grid[13][6]
        print(f"round {r + 1}: {args.matches} matches, xT own box {grid[0][6]:.3f}, "
              f"centre circle {grid[8][6]:.3f}, edge of box {edge:.3f}, six-yard box {grid[15][6]:.3f}")


if __name__ == "__main__":
    main()
