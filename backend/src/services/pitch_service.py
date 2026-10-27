"""PitchService: turns a match into 2D and plays it. From a tracking file (Metrica or our synthetic format)
it gives the positions of everyone, home team attacking +x; from the positions it finds the on-ball events, each player's top speed, position and running direction,
draws a moment from above and serves the frames for the replay."""
from __future__ import annotations

import gzip
import io
import math
import textwrap

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patheffects import withStroke
from mplsoccer import Pitch

from src.core.utils import (
    AIM_MS,
    AWAY,
    BACKGROUND,
    BadInput,
    CARRY_MIN_M,
    CARRY_START_M,
    CENTRE_SPOT_M,
    CONTROL_M,
    CONTROL_SPEED,
    CONTROL_Z,
    CORNER_SPOT_M,
    DEFENCE_COLOUR,
    DEFENCE_LABELS,
    DISTANCE_MAX_SPEED,
    DPI,
    DRIBBLE_OPP_M,
    EDGE_M,
    FIG_W,
    FLICKER_MS,
    GAP_FILL_MS,
    GOAL_AREA_X,
    GOAL_AREA_Y,
    GOAL_HALF_WIDTH,
    GOAL_Y,
    GRASS,
    HIGH_BALL_Z,
    HOME,
    KICKOFF_GAP_MS,
    KICKOFF_MAX_TOUCHES,
    KICKOFF_SPOT_M,
    KICKOFF_STILL_MS,
    KICKOFF_WINDOW_MS,
    KICK_GAIN,
    KICK_GAP_MS,
    KICK_LOOK_MS,
    KICK_BACK_DEG,
    KICK_BACK_M,
    KICK_M,
    KICK_OUT_SPEED,
    KICK_RIVAL_M,
    KICK_TURN_DEG,
    LEGEND_ROWS,
    LINE_COLOR,
    LONG_PASS_M,
    MARKS,
    MARK_GAP,
    MARK_WIDTH,
    MIN_TOUCH_MS,
    NEXT_TOUCH_MS,
    PASS_BY_DECEL,
    PASS_BY_GAIN_M,
    PASS_BY_LONG_MS,
    PASS_BY_MIN_SPEED,
    PASS_BY_MS,
    PASS_BY_SPEED_CHANGE,
    PASS_BY_TURN_DEG,
    PITCH_H_IN,
    PITCH_X,
    PITCH_Y,
    PLAYER_PT,
    PROFILE_DEF_SHARE,
    PROFILE_FWD_SHARE,
    PROFILE_MOVING,
    PROFILE_SPEED_CAP,
    PROFILE_SPEED_Q,
    PROFILE_WIDE_M,
    PROFILE_WINDOW_MS,
    REPLAY_HZ,
    RESTART_STILL_M,
    RESTART_STILL_MS,
    RUN_MIN_GAIN_M,
    SHOT_DETECT_RANGE_M,
    SHOT_NEAR_M,
    SHOT_SPEED,
    SHOT_SPEED_NEAR,
    SPEED_LOOK_MS,
    STRIPE,
    TACKLE_GAP_MS,
    TACKLE_M,
    TEXT_H_IN,
    TITLE_H_IN,
    TOUCHLINE_M,
    TOUCH_HOLE_MS,
    TRACKING_COLS,
    WIDE_SHOT_Y,
    WIDE_Y,
    aimed_at_goal,
    base,
    behind_goal_line,
    clock_of,
    contested,
    goal_x,
    smooth_window,
    label_spot,
    spread,
    word,
    zoom,
)


class PitchService:
    @staticmethod
    def player_speeds(tracking: pd.DataFrame) -> pd.Series:
        """Each player's speed (m/s) at every row, over PROFILE_WINDOW_MS, never across a hole in his data."""
        pl = tracking[tracking.object_id != "ball"].sort_values(["object_id", "ts_ms"])
        step = pl.groupby("object_id").ts_ms.diff()
        lag = max(1, int(round(PROFILE_WINDOW_MS / float(step.median() or 40))))
        g = pl.groupby("object_id")
        dt = (pl.ts_ms - g.ts_ms.shift(lag)) / 1000
        d = np.hypot(pl.x - g.x.shift(lag), pl.y - g.y.shift(lag))
        ok = (dt > 0) & (dt <= (PROFILE_WINDOW_MS + GAP_FILL_MS) / 1000)
        return (d / dt).where(ok)

    @staticmethod
    def top_speeds(tracking: pd.DataFrame) -> dict[str, float]:
        """A high quantile of the speeds, not the single highest one (one bad position makes a 15 m/s spike)."""
        speed = PitchService.player_speeds(tracking)
        ids = tracking.loc[speed.index, "object_id"]
        top = speed.groupby(ids).quantile(PROFILE_SPEED_Q)
        return {pid: round(float(np.clip(v, *PROFILE_SPEED_CAP)), 2) for pid, v in top.dropna().items()}

    @staticmethod
    def distances(tracking: pd.DataFrame) -> dict[str, float]:
        """Metres each player ran: the sum of his frame-to-frame steps, never across a hole in his data
        (over GAP_FILL_MS) and never a jump faster than DISTANCE_MAX_SPEED (a bad position)."""
        pl = tracking[tracking.object_id != "ball"].sort_values(["object_id", "ts_ms"])
        g = pl.groupby("object_id")
        dt = g.ts_ms.diff() / 1000
        d = np.hypot(g.x.diff(), g.y.diff())
        ok = (dt > 0) & (dt <= GAP_FILL_MS / 1000) & (d <= DISTANCE_MAX_SPEED * dt)
        return {pid: round(float(v), 1) for pid, v in d.where(ok).groupby(pl.object_id).sum().items()}

    @staticmethod
    def shot_speeds(tracking: pd.DataFrame, events: pd.DataFrame) -> dict[str, float]:
        """Each goal's shot: the ball's top speed just after it was struck (m/s), by event_id."""
        ball = PitchService.ball_track(PitchService.clean(tracking))
        goals = events[(events.type == "shot") & (events.outcome == "goal")]
        return {e.event_id: round(PitchService.speed(PitchService.flight(ball, e.ts_ms, e.ts_ms + SPEED_LOOK_MS)), 2)
                for e in goals.itertuples()}

    @staticmethod
    def home_to_right(tracking: pd.DataFrame, home_id: str) -> pd.DataFrame:
        """Turns the pitch round in every period where the home team attacks to the left (it stands, on average,
        to the right of the away team), so every table we keep has home -> +x in both halves."""
        pl = tracking[tracking.object_id != "ball"]
        means = pl.groupby(["period", pl.team_id.eq(home_id)]).x.mean()
        flip = [p for p in pl.period.unique()
                if (p, True) in means and (p, False) in means and means[(p, True)] > means[(p, False)]]
        if not flip:
            return tracking
        out = tracking.copy()
        rows = out.period.isin(flip)
        out.loc[rows, "x"], out.loc[rows, "y"] = PITCH_X - out.loc[rows, "x"], PITCH_Y - out.loc[rows, "y"]
        return out

    @staticmethod
    def keepers_of(tracking: pd.DataFrame, home_id: str, known: set) -> set:
        """The known keepers plus, for a team with none known, the player who stood deepest on average (Metrica
        files do not say who keeps goal; the table has the home team attacking +x)."""
        pl = tracking[tracking.object_id != "ball"]
        mean = pl.groupby("object_id").agg(team=("team_id", "first"), x=("x", "mean"))
        mean.loc[mean.team != home_id, "x"] = PITCH_X - mean.loc[mean.team != home_id, "x"]
        out = set(known)
        for _, team in mean.groupby("team"):
            if not out & set(team.index):
                out.add(team.x.idxmin())
        return out

    @staticmethod
    def positions(tracking: pd.DataFrame, home_id: str, keepers: set) -> dict[str, str]:
        """GK, CB/LB/RB, CM/LM/RM, ST/LW/RW from the average spot. The table has the home team attacking +x, so
        the away team's spots are turned round first; then the deepest share of each team is the back line, the
        furthest forward the attack, and the side comes from how far from the middle he stood."""
        pl = tracking[tracking.object_id != "ball"]
        mean = pl.groupby("object_id").agg(team=("team_id", "first"), x=("x", "mean"), y=("y", "mean"))
        away = mean.team != home_id
        mean.loc[away, "x"] = PITCH_X - mean.loc[away, "x"]
        mean.loc[away, "y"] = PITCH_Y - mean.loc[away, "y"]
        out = {pid: "GK" for pid in mean.index if pid in keepers}
        for _, team in mean[~mean.index.isin(keepers)].groupby("team"):
            depth = team.x.rank(method="first") / len(team)        # 0 = deepest, 1 = furthest forward
            for pid, r in team.iterrows():
                line = "def" if depth[pid] <= PROFILE_DEF_SHARE else "fwd" if depth[pid] > 1 - PROFILE_FWD_SHARE else "mid"
                side = r.y - PITCH_Y / 2                            # attacking +x, the left side is y up
                wide = abs(side) > PROFILE_WIDE_M
                left = side > 0
                out[pid] = {("def", False): "CB", ("def", True): "LB" if left else "RB",
                            ("mid", False): "CM", ("mid", True): "LM" if left else "RM",
                            ("fwd", False): "ST", ("fwd", True): "LW" if left else "RW"}[(line, wide)]
        return out

    @staticmethod
    def motion(frames, ts: int) -> dict[str, tuple[float, float, float | None]]:
        """{player: (vx, vy, facing)} at ts from the frames just before and after (Frames of event_detection).
        facing = the direction he runs (degrees, 0 = +x); None when he stands, as a standing player may face anywhere."""
        near = frames.between(ts - PROFILE_WINDOW_MS // 2, ts + PROFILE_WINDOW_MS // 2)
        runs = np.split(near, np.flatnonzero(np.diff(near) > GAP_FILL_MS) + 1)   # not across a hole in the data
        run = next((r for r in runs if len(r) and r[0] <= frames.nearest(ts) <= r[-1]), near)
        if len(run) < 2:
            return {}
        t0, t1 = int(run[0]), int(run[-1])
        ids0, _, xy0 = frames[t0]
        ids1, _, xy1 = frames[t1]
        before = dict(zip(ids0, xy0))
        dt = (t1 - t0) / 1000
        out = {}
        for pid, p in zip(ids1, xy1):
            if pid not in before:
                continue
            vx, vy = (p - before[pid]) / dt
            moving = np.hypot(vx, vy) >= PROFILE_MOVING
            out[pid] = (round(float(vx), 2), round(float(vy), 2),
                        round(float(np.degrees(np.arctan2(vy, vx))) % 360, 1) if moving else None)
        return out

    @staticmethod
    # ---------- 1. frames ----------
    def ball_track(tracking: pd.DataFrame) -> pd.DataFrame:
        """One ball row per frame, gaps up to GAP_FILL_MS filled in a straight line."""
        stamps = np.sort(tracking.ts_ms.unique())
        ball = tracking[tracking.object_id == "ball"].drop_duplicates("ts_ms").set_index("ts_ms")
        ball = ball.reindex(stamps)
        ball["seen"] = ball.x.notna()
        if "z" not in ball:
            ball["z"] = np.nan
        ball["z"] = pd.to_numeric(ball.z, errors="coerce")
        step = float(np.median(np.diff(stamps))) if len(stamps) > 1 else 40.0
        ball["period"] = tracking.groupby("ts_ms").period.first().reindex(stamps).values
        # fill only gaps that are short in time: frames without a pitch (replays) leave no rows at all, so counting
        # rows would join the ball across a whole replay, or across half-time
        seen_ts = pd.Series(np.where(ball.seen, ball.index, np.nan), index=ball.index)
        gap = seen_ts.bfill() - seen_ts.ffill()
        fill = (gap <= GAP_FILL_MS) & ~ball.seen & (ball.period.bfill() == ball.period.ffill())
        w = smooth_window(step)
        for col in ("x", "y", "z"):
            filled = ball[col].interpolate(method="index", limit_area="inside")
            ball[col] = ball[col].where(ball.seen, filled.where(fill))
            if w > 1 and col != "z":                     # position jitter looks like fast kicks
                ball[col] = ball.groupby("period")[col].transform(lambda c: c.rolling(w, center=True, min_periods=1).median())
        dt = np.diff(stamps, prepend=stamps[0] - step) / 1000
        ball["speed"] = np.hypot(ball.x.diff(), ball.y.diff()).to_numpy() / np.where(dt > 0, dt, 1)
        return ball[["period", "x", "y", "z", "seen", "speed"]]

    class Frames(dict):
        """{ts_ms: (ids, teams, xy array)}, with the frame times also kept sorted in .stamps for range lookups."""

        def __init__(self, items):
            super().__init__(items)
            self.stamps = np.array(sorted(self), dtype=np.int64)

        def between(self, start: int, end: int) -> np.ndarray:
            return self.stamps[np.searchsorted(self.stamps, start):np.searchsorted(self.stamps, end, side="right")]

        def nearest(self, ts: int) -> int:
            i = int(np.clip(np.searchsorted(self.stamps, ts), 1, len(self.stamps) - 1))
            return int(self.stamps[i - 1] if ts - self.stamps[i - 1] <= self.stamps[i] - ts else self.stamps[i])

    @staticmethod
    def player_frames(tracking: pd.DataFrame) -> PitchService.Frames:
        """Every frame's players, positions smoothed over SMOOTH_MS. Built with one sort and one split (a groupby per
        frame takes about a minute on a whole match)."""
        pl = tracking[tracking.object_id != "ball"].sort_values(["object_id", "ts_ms"])
        stamps = np.sort(tracking.ts_ms.unique())
        w = smooth_window(float(np.median(np.diff(stamps))) if len(stamps) > 1 else 40.0)
        xy = pl[["x", "y"]].astype(float)
        if w > 1:
            # never across a hole in a player's data: out of play the rows are gone while everyone walks on
            run = ((pl.object_id != pl.object_id.shift()) | (pl.ts_ms.diff() > GAP_FILL_MS)).cumsum()
            xy = xy.groupby(run.to_numpy()).rolling(w, center=True, min_periods=1).mean().droplevel(0)
        pl = pl.assign(x=xy.x, y=xy.y).sort_values("ts_ms", kind="stable")
        ts = pl.ts_ms.to_numpy()
        cut = np.flatnonzero(np.diff(ts)) + 1
        keys = ts[np.r_[0, cut]] if len(ts) else []
        ids, teams, pts = (np.split(a, cut) for a in (pl.object_id.to_numpy(), pl.team_id.to_numpy(),
                                                      pl[["x", "y"]].to_numpy(float)))
        return PitchService.Frames(zip((int(k) for k in keys), zip(ids, teams, pts)))

    @staticmethod
    # ---------- 2. who has the ball ----------
    def owners(ball: pd.DataFrame, players: dict) -> pd.DataFrame:
        rows = []
        for ts, b in ball.iterrows():
            owner = team = None
            controllable = (np.isnan(b.z) or b.z <= CONTROL_Z) and not (b.speed > CONTROL_SPEED)
            if not np.isnan(b.x) and ts in players and controllable:
                ids, teams, xy = players[ts]
                d = np.hypot(xy[:, 0] - b.x, xy[:, 1] - b.y)
                i = int(np.argmin(d)) if len(d) else -1
                if i >= 0 and d[i] <= CONTROL_M:
                    owner, team = ids[i], teams[i]
            rows.append((ts, owner, team))
        return pd.DataFrame(rows, columns=["ts_ms", "owner", "team"]).set_index("ts_ms")

    @staticmethod
    # ---------- 3. touches ----------
    def touches(own: pd.DataFrame, ball: pd.DataFrame, players: dict | None = None) -> list[dict]:
        """Runs of frames with the same owner, at least MIN_TOUCH_MS long."""
        out, cur = [], None
        for ts, r in own.iterrows():
            has = pd.notna(r.owner)
            if has and cur and cur["player_id"] == r.owner:
                cur["end"] = ts
                continue
            if cur:
                out.append(cur)
            cur = {"player_id": r.owner, "team_id": r.team, "start": ts, "end": ts} if has else None
        if cur:
            out.append(cur)
        keep = [t for t in out if t["end"] - t["start"] >= MIN_TOUCH_MS]
        merged = []
        for t in keep:                                   # a short flicker between two touches of one player
            if merged and merged[-1]["player_id"] == t["player_id"] and t["start"] - merged[-1]["end"] <= FLICKER_MS:
                merged[-1]["end"] = t["end"]
            else:
                merged.append(t)
        for t in merged:
            s, e = ball.loc[t["start"]], ball.loc[t["end"]]
            t.update(period=int(s.period), x=s.x, y=s.y, end_x=e.x, end_y=e.y)
            for k, top in (("x", PITCH_X), ("end_x", PITCH_X), ("y", PITCH_Y), ("end_y", PITCH_Y)):
                t[k] = min(max(t[k], 0.0), top)      # a throw-in is taken from the line, not beside it
        return [t for t in merged if not behind_goal_line(ball.loc[t["end"]].x) and not PitchService.passing_by(t, ball, players)]

    @staticmethod
    def passing_by(t: dict, ball: pd.DataFrame, players: dict | None = None) -> bool:
        """A "touch" during which the ball kept its line and pace: it rolled past the player, untouched. A brief one
        always; a longer one (up to PASS_BY_LONG_MS) when the ball also left him behind, so a player running with
        the ball at his feet is not taken for one."""
        span = t["end"] - t["start"]
        if span > PASS_BY_MS and (players is None or span > PASS_BY_LONG_MS
                                  or PitchService.ball_gain(t, ball, players) < PASS_BY_GAIN_M):
            return False
        before = ball.loc[t["start"] - KICK_LOOK_MS:t["start"]].dropna(subset=["x"])
        after = ball.loc[t["end"]:t["end"] + KICK_LOOK_MS].dropna(subset=["x"])
        if len(before) < 2 or len(after) < 2:
            return False
        v_in = np.array([before.x.iat[-1] - before.x.iat[0], before.y.iat[-1] - before.y.iat[0]]) / max(1, before.index[-1] - before.index[0])
        v_out = np.array([after.x.iat[-1] - after.x.iat[0], after.y.iat[-1] - after.y.iat[0]]) / max(1, after.index[-1] - after.index[0])
        s_in, s_out = np.hypot(*v_in) * 1000, np.hypot(*v_out) * 1000
        if s_in < PASS_BY_MIN_SPEED or s_out < PASS_BY_MIN_SPEED:
            return False                                   # the ball stopped or started: a real touch
        turn = math.degrees(math.acos(np.clip(v_in @ v_out / (np.hypot(*v_in) * np.hypot(*v_out)), -1, 1)))
        slowed = PASS_BY_SPEED_CHANGE + PASS_BY_DECEL * max(0, span - PASS_BY_MS) / 1000   # a rolling ball slows down
        return turn < PASS_BY_TURN_DEG and -PASS_BY_SPEED_CHANGE < s_in - s_out < slowed

    @staticmethod
    def ball_gain(t: dict, ball: pd.DataFrame, players: dict) -> float:
        """How much further the ball went than the player during his touch (m)."""
        def spot(ts):
            ids, _, xy = players[players.nearest(ts)]
            i = np.flatnonzero(ids == t["player_id"])
            return xy[i[0]] if len(i) else None
        a, b = spot(t["start"]), spot(t["end"])
        if a is None or b is None:
            return 0.0
        s, e = ball.loc[t["start"]], ball.loc[t["end"]]
        return float(math.hypot(e.x - s.x, e.y - s.y) - math.hypot(*(b - a)))

    @staticmethod
    def kicks(ball: pd.DataFrame, players: dict, own: pd.DataFrame) -> list[dict]:
        """One-touch kicks and headers: the ball is never slow near the player, so no touch is seen. Instead the
        ball's path turns sharply (or speeds up) next to him. Each kick becomes a touch of one frame."""
        stamps = ball.index.to_numpy()
        step = float(np.median(np.diff(stamps))) if len(stamps) > 1 else 40.0
        k = max(1, int(round(KICK_LOOK_MS / step)))
        xy = ball[["x", "y"]].to_numpy(float)
        dt = k * step / 1000
        v_in = (xy[k:-k] - xy[:-2 * k]) / dt
        v_out = (xy[2 * k:] - xy[k:-k]) / dt
        s_in, s_out = np.hypot(*v_in.T), np.hypot(*v_out.T)
        cos = (v_in * v_out).sum(axis=1) / np.where(s_in * s_out > 0, s_in * s_out, np.nan)
        turn = np.degrees(np.arccos(np.clip(cos, -1, 1)))
        hit = (s_out >= KICK_OUT_SPEED) & ((turn >= KICK_TURN_DEG) | (s_out - s_in >= KICK_GAIN))
        out, last = [], -10**9
        for j in np.flatnonzero(hit):
            ts = int(stamps[j + k])
            if ts - last < 3 * k * step or pd.notna(own.owner.get(ts)) or ts not in players:
                continue
            ids, teams, pxy = players[ts]
            d = np.hypot(pxy[:, 0] - xy[j + k, 0], pxy[:, 1] - xy[j + k, 1])
            i = int(np.argmin(d)) if len(d) else -1
            if i < 0 or d[i] > (KICK_BACK_M if turn[j] >= KICK_BACK_DEG else KICK_M):   # a ball does not turn back
                continue                                                           # by itself: tracking lags
            just = own.owner.loc[ts - 3 * k * step:ts - 1].dropna()
            if len(just) and just.iat[-1] != ids[i]:      # the ball has just left another player's foot: that
                continue                                  # kick is the turn, not a touch of this one passing by
            b = ball.loc[ts]
            if behind_goal_line(b.x):                    # dead ball, as for ordinary touches
                continue
            x, y = min(max(b.x, 0.0), PITCH_X), min(max(b.y, 0.0), PITCH_Y)
            rival = d[teams != teams[i]]                 # an opponent as close: who touched it cannot be told
            out.append({"player_id": ids[i], "team_id": teams[i], "start": ts, "end": ts, "period": int(b.period),
                        "x": x, "y": y, "end_x": x, "end_y": y, "kick": True,
                        "crowded": bool(len(rival) and rival.min() <= d[i] + KICK_RIVAL_M)})
            last = ts
        return out

    @staticmethod
    def with_kicks(tch: list[dict], kk: list[dict]) -> list[dict]:
        """Adds the kicks that fall between touches (not inside one, not right next to the same player's touch)."""
        starts = np.array([t["start"] for t in tch]) if tch else np.array([], dtype=int)
        keep = []
        for kick in kk:
            i = int(np.searchsorted(starts, kick["start"]))
            prev = tch[i - 1] if i > 0 else None
            nxt = tch[i] if i < len(tch) else None
            if prev and prev["end"] >= kick["start"]:
                continue
            if (prev and prev["player_id"] == kick["player_id"] and kick["start"] - prev["end"] <= KICK_GAP_MS) or \
                    (nxt and nxt["player_id"] == kick["player_id"] and nxt["start"] - kick["start"] <= KICK_GAP_MS):
                continue                                 # the player's own touch already holds this moment
            keep.append(kick)
        return sorted(tch + keep, key=lambda t: t["start"])

    @staticmethod
    # ---------- 4. what happened ----------
    def attack_sign(tracking: pd.DataFrame, home_id: str) -> dict:
        """{(period, team): +1 or -1}: the direction each team attacks. Of the two teams, the one that stands further
        left on average attacks to the right (a team pushing for a goal can stand mostly in the other half, so the
        halfway line itself is not a safe guide)."""
        out = {}
        means = tracking[tracking.object_id != "ball"].groupby(["period", "team_id"]).x.mean()
        for period in means.index.get_level_values(0).unique():
            m = means.loc[period].sort_values()
            for rank, team in enumerate(m.index):
                out[(period, team)] = 1 if (rank == 0 if len(m) > 1 else m.iat[0] < PITCH_X / 2) else -1
        return out

    @staticmethod
    def flight(ball: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
        return ball.loc[start:end]

    @staticmethod
    def direction(fl: pd.DataFrame, x1, y1) -> tuple[float, float]:
        """Where the ball was heading: its position a moment after the kick (AIM_MS). The next touch can come much
        later and somewhere else (a goal, then the kick-off), so it is not a safe guide to the aim."""
        seen = fl.dropna(subset=["x"])
        early = seen[seen.index <= seen.index[0] + AIM_MS] if len(seen) else seen
        return (early.x.iat[-1], early.y.iat[-1]) if len(early) > 1 else (x1, y1)

    @staticmethod
    def left_pitch(fl: pd.DataFrame):
        """The first moment the ball is off the pitch, after it has been on it (a throw-in starts off the pitch)."""
        off = (fl.x < 0) | (fl.x > PITCH_X) | (fl.y < 0) | (fl.y > PITCH_Y)
        on = (~off & fl.x.notna()).cummax()
        out = fl[off & on]
        return out.iloc[0] if len(out) else None

    @staticmethod
    def speed(fl: pd.DataFrame) -> float:
        """Highest ball speed in the first half second of a flight, m/s (by time, so any frame rate works)."""
        fl = fl.dropna(subset=["x"])
        head = fl.loc[:fl.index[0] + SPEED_LOOK_MS] if len(fl) else fl
        if len(head) < 2:
            return 0.0
        d = np.hypot(np.diff(head.x), np.diff(head.y))
        dt = np.diff(head.index.to_numpy()) / 1000
        return float(np.max(d / np.where(dt > 0, dt, 1)))

    @staticmethod
    def between(a: dict, b: dict | None, ball: pd.DataFrame, sign: int, keepers: set, later: list = ()) -> dict:
        """The event that ends touch a, judged from the ball's flight until touch b."""
        fl = PitchService.flight(ball, a["end"], b["start"] if b else a["end"] + 4000)
        x0, y0 = a["end_x"], a["end_y"]
        out = PitchService.left_pitch(fl)
        last = fl.dropna(subset=["x"]).iloc[-1] if fl.x.notna().any() else None
        x1, y1 = (out.x, out.y) if out is not None else ((b["x"], b["y"]) if b else (last.x, last.y) if last is not None else (x0, y0))
        gx = goal_x(sign)
        dist = math.hypot(gx - x0, GOAL_Y - y0)
        near_goal = dist <= SHOT_DETECT_RANGE_M
        fast = PitchService.speed(fl) >= (SHOT_SPEED_NEAR if dist <= SHOT_NEAR_M else SHOT_SPEED)
        ev = {"type": "pass", "end_x": x1, "end_y": y1, "recipient_id": None, "outcome": "fail"}
        if out is not None:                                       # the ball left the pitch
            over_goal_line = (out.x > PITCH_X) if sign > 0 else (out.x < 0)
            between_posts = abs(out.y - GOAL_Y) <= GOAL_HALF_WIDTH and (np.isnan(out.z) or out.z <= 2.44)
            own_line = (out.x < 0) if sign > 0 else (out.x > PITCH_X)
            if over_goal_line and between_posts and near_goal and PitchService.kickoff_after(a, later, ball):
                ev.update(type="shot", outcome="goal")
            elif own_line and between_posts and PitchService.kickoff_after(a, later, ball, a["team_id"]):
                ev.update(type="duel", into_own_goal=True)   # a keeper's or defender's touch on the way in
            elif over_goal_line and near_goal and fast and (aimed_at_goal(x0, y0, out.x, out.y, sign)
                                                            or (abs(out.y - GOAL_Y) <= WIDE_SHOT_Y and abs(y0 - GOAL_Y) <= WIDE_SHOT_Y)):
                ev.update(type="shot", outcome="off_target")
            return ev
        if b is None:
            return ev
        ax, ay = PitchService.direction(fl, x1, y1)
        if near_goal and fast and aimed_at_goal(x0, y0, ax, ay, sign) and b["team_id"] != a["team_id"]:
            ev.update(type="shot", outcome="goal" if PitchService.kickoff_after(a, later, ball) else "saved" if b["player_id"] in keepers else "blocked")
            return ev
        if b["team_id"] == a["team_id"]:
            ev.update(outcome="success", recipient_id=b["player_id"])
        return ev

    @staticmethod
    def kickoff_after(a: dict, later: list, ball: pd.DataFrame, kicker: str | None = None) -> bool:
        """A goal is confirmed by the other team kicking off from the centre spot a while later (players may touch
        the ball in the net first). The ball's height is often unknown (one camera, or data without z), so crossing
        the line between the posts is not enough: a shot over the bar would look the same. A kick-off is a dead ball:
        it lies still on the spot for KICKOFF_STILL_MS before the touch. kicker: the team that kicks off (by default
        the other team; the touching team itself when the ball went into its own goal)."""
        for n, b in enumerate(later):
            if n > KICKOFF_MAX_TOUCHES:
                return False                               # play went on: this shot was not the goal
            if kicker is None and b["team_id"] == a["team_id"] and not behind_goal_line(ball.loc[b["start"]].x):
                return False                               # his own team had the ball again on the pitch: a rebound
            kicks_off = b["team_id"] == kicker if kicker else b["team_id"] != a["team_id"]
            if not (b["period"] == a["period"] and kicks_off
                    and KICKOFF_GAP_MS <= b["start"] - a["end"] <= KICKOFF_WINDOW_MS
                    and math.hypot(b["x"] - PITCH_X / 2, b["y"] - GOAL_Y) <= KICKOFF_SPOT_M):
                continue
            before = ball.loc[b["start"] - KICKOFF_STILL_MS:b["start"]].dropna(subset=["x"])
            if len(before) and (np.hypot(before.x - PITCH_X / 2, before.y - GOAL_Y) <= KICKOFF_SPOT_M).all():
                return True
        return False

    @staticmethod
    def pass_kind(x0, y0, x1, y1, sign, zmax) -> tuple[str, str | None]:
        """(pass_type, pass_height): cross from wide into the box, long ball over LONG_PASS_M, else ground."""
        height = None if np.isnan(zmax) else ("high" if zmax >= HIGH_BALL_Z else "ground")
        gx = goal_x(sign)
        wide = y0 < WIDE_Y or y0 > PITCH_Y - WIDE_Y
        in_final_third = abs(gx - x0) < PITCH_X / 3
        into_box = abs(gx - x1) < 16.5 and abs(y1 - GOAL_Y) < 20.16
        if wide and in_final_third and into_box:
            return "cross", height
        if math.hypot(x1 - x0, y1 - y0) >= LONG_PASS_M:
            return "long", height
        return "ground", height

    @staticmethod
    # ---------- 5. inside a touch ----------
    def carry_or_dribble(t: dict, ball: pd.DataFrame, players: dict, opp_of, sign: int = 1) -> dict | None:
        """The player ran with the ball CARRY_MIN_M or more: a carry, or a dribble when an opponent came close.
        It starts when the ball first moves (a player often stands on the ball for a while before setting off)."""
        moved = math.hypot(t["end_x"] - t["x"], t["end_y"] - t["y"])
        if moved < CARRY_MIN_M:
            return None
        seg = ball.loc[t["start"]:t["end"]].dropna(subset=["x"])
        off = np.hypot(seg.x - t["x"], seg.y - t["y"]) > CARRY_START_M
        start = int(seg.index[off.argmax()]) if off.any() else t["start"]
        return {"type": "dribble" if PitchService.took_on(t, start, players, opp_of, sign) else "carry", "outcome": "success",
                "ts": start, "x": float(seg.x.get(start, t["x"])), "y": float(seg.y.get(start, t["y"]))}

    @staticmethod
    def took_on(t: dict, start: int, players: dict, opp_of, sign: int) -> bool:
        """A dribble (take-on): an opponent stood close in front of the player (towards the goal he attacks) and
        by the end of the carry the player had gone past him. Running near an opponent is not enough."""
        stamps = players.between(start, t["end"])
        if not len(stamps):
            return False
        front = set()
        for ts in stamps:
            ids, teams, xy = players[int(ts)]
            me = xy[ids == t["player_id"]]
            if not len(me):
                continue
            mask = teams == opp_of(t["team_id"])
            d = np.hypot(*(xy[mask] - me[0]).T)
            ahead = (xy[mask][:, 0] - me[0][0]) * sign > 0
            front |= set(ids[mask][(d <= DRIBBLE_OPP_M) & ahead])
        if not front:
            return False
        ids, teams, xy = players[int(stamps[-1])]
        me = xy[ids == t["player_id"]]
        return bool(len(me)) and any(((xy[ids == o][0][0] - me[0][0]) * sign <= 0) for o in front if (ids == o).any())

    @staticmethod
    def dispossessed(t: dict, nxt: dict | None, ball: pd.DataFrame) -> bool:
        """The player lost the ball to an opponent at his feet (a tackle), with no kick: it is no pass. The ball
        goes straight to the opponent, slowly and only a short way."""
        if nxt is None or nxt["team_id"] == t["team_id"] or nxt["start"] - t["end"] > TACKLE_GAP_MS:
            return False
        fl = ball.loc[t["end"]:nxt["start"]].dropna(subset=["x"])
        return (math.hypot(nxt["x"] - t["end_x"], nxt["y"] - t["end_y"]) <= TACKLE_M
                and (fl.speed.max() if len(fl) else 0) <= CONTROL_SPEED)

    @staticmethod
    def clean(tracking: pd.DataFrame) -> pd.DataFrame:
        """Whole-millisecond times, one row per object and time, no player without a team."""
        t = tracking.copy()
        t["ts_ms"] = pd.to_numeric(t.ts_ms).round().astype("int64")
        t["object_id"] = t.object_id.astype(str)
        t["team_id"] = t.team_id.astype(object).where(t.team_id.notna(), None)
        t = t[(t.object_id == "ball") | t.team_id.notna()]
        return t.drop_duplicates(["ts_ms", "object_id"], keep="last")

    @staticmethod
    def joined(t: dict, nxt: dict, ball: pd.DataFrame) -> bool:
        """Can the ball have gone from this touch to the next? Same period, not too long, and no hole in the
        data in between (a replay was cut out): otherwise the touch is judged on its own."""
        if nxt["period"] != t["period"] or nxt["start"] - t["end"] > NEXT_TOUCH_MS:
            return False
        stamps = ball.loc[t["end"]:nxt["start"]].index.to_numpy()
        return len(stamps) < 2 or np.diff(stamps).max() <= TOUCH_HOLE_MS

    @staticmethod
    def detect(tracking: pd.DataFrame, home_id: str, keepers: set = frozenset(),
               clock_start: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
        """tracking (ts_ms, period, object_id, team_id, x, y[, z]) -> (events, freeze_frames) in the import format.
        clock_start: {period: (ts_ms, minute)} when the clip does not start at the period's kick-off."""
        tracking = PitchService.clean(tracking)
        ball = PitchService.ball_track(tracking)
        players = PitchService.player_frames(tracking)
        own = PitchService.owners(ball, players)
        tch = PitchService.with_kicks(PitchService.touches(own, ball, players), PitchService.kicks(ball, players, own))
        signs = PitchService.attack_sign(tracking, home_id)
        teams = sorted(t for t in tracking.team_id.dropna().unique())
        opp_of = (lambda team: next((t for t in teams if t != team), None))
        starts = {p: int(g.ts_ms.min()) for p, g in tracking.groupby("period")}
        events = []
        for i, t in enumerate(tch):
            sign = signs.get((t["period"], t["team_id"]), 1)
            nxt = tch[i + 1] if i + 1 < len(tch) and PitchService.joined(t, tch[i + 1], ball) else None
            cd = PitchService.carry_or_dribble(t, ball, players, opp_of, sign)
            if cd:
                events.append({**base(t, cd.pop("ts")), **cd, "end_x": t["end_x"], "end_y": t["end_y"]})
            if PitchService.dispossessed(t, nxt, ball):
                if cd and cd["type"] == "dribble":
                    events[-1]["outcome"] = "fail"           # he took the man on and lost the ball
                elif not cd:                                  # tackled while standing on the ball: no decision to judge
                    events.append({**base(t, t["end"]), "type": "dispossessed", "outcome": "fail", "x": t["end_x"],
                                   "y": t["end_y"], "end_x": nxt["x"], "end_y": nxt["y"]})
                continue
            ev = PitchService.between(t, nxt, ball, sign, keepers, tch[i + 1:i + 40])
            if ev["type"] == "pass" and nxt is None and ev["outcome"] == "fail" and PitchService.left_pitch(PitchService.flight(ball, t["end"], t["end"] + 4000)) is None:
                continue                                    # end of the clip, nothing to judge
            if (ev["type"] == "pass" and ev["outcome"] == "fail" and contested(t)) or t.get("crowded"):
                ev["type"] = "duel"     # a block or poke in a duel, or a first-time touch among opponents: not judged
            if ev.pop("into_own_goal", False) and events and events[-1]["team_id"] != t["team_id"]:
                # the ball went in off the keeper (or a defender): the goal is the shot before it
                events[-1].update(type="shot", outcome="goal", end_x=ev["end_x"], end_y=ev["end_y"])
            row = {**base(t, t["end"]), **ev, "x": t["end_x"], "y": t["end_y"]}
            if ev["type"] == "pass":
                fl = PitchService.flight(ball, t["end"], nxt["start"] if nxt else t["end"] + 4000)
                row["pass_type"], row["pass_height"] = PitchService.pass_kind(t["end_x"], t["end_y"], ev["end_x"], ev["end_y"], sign, fl.z.max())
            events.append(row)
        ev = pd.DataFrame(events)
        if ev.empty:
            return ev, pd.DataFrame(columns=["event_id", "player_id", "team_id", "x", "y"])
        ev = ev.sort_values("ts_ms").reset_index(drop=True)
        ev["event_id"] = [f"v_{i:05d}" for i in range(1, len(ev) + 1)]
        ev[["minute", "second"]] = [clock_of(ts, p, starts, clock_start) for ts, p in zip(ev.ts_ms, ev.period)]
        ev["play_pattern"] = [PitchService.restart_kind(e, ball) for e in ev.itertuples()]
        return ev, PitchService.freeze_frames(ev, players)

    @staticmethod
    def restart_kind(e, ball: pd.DataFrame) -> str:
        """How the ball came to the player: a set piece when it lay still before he played it (where it lay says
        which one), otherwise open_play. A hole in the tracking before the touch (no frames at all while the ball
        was out of play) counts as the ball lying still, but only for a restart taken on a line: mid-pitch the hole
        may be a replay cut. The scoring leaves out dribbles and shots where a set piece rules them out."""
        still = ball.loc[e.ts_ms - RESTART_STILL_MS:e.ts_ms - 120]
        earlier = ball.index[ball.index < e.ts_ms - RESTART_STILL_MS]
        hole = len(earlier) > 0 and (still.index.min() if len(still) else e.ts_ms) - earlier[-1] >= RESTART_STILL_MS
        if not hole and (len(still) < 3 or still.x.max() - still.x.min() > RESTART_STILL_M
                         or still.y.max() - still.y.min() > RESTART_STILL_M):
            return "open_play"
        x, y = e.x, e.y
        if min(x, PITCH_X - x) < CORNER_SPOT_M and min(y, PITCH_Y - y) < CORNER_SPOT_M:
            return "from_corner"
        if min(y, PITCH_Y - y) < TOUCHLINE_M:
            return "from_throw_in"
        if abs(x - PITCH_X / 2) < CENTRE_SPOT_M and abs(y - GOAL_Y) < CENTRE_SPOT_M:
            return "from_kick_off"
        if min(x, PITCH_X - x) < GOAL_AREA_X and abs(y - GOAL_Y) < GOAL_AREA_Y:
            return "from_goal_kick"                       # a goal kick, or the keeper with the ball in his hands
        return "open_play" if hole else "from_free_kick"

    @staticmethod
    def freeze_frames(ev: pd.DataFrame, players: dict) -> pd.DataFrame:
        """Everyone's position at the moment of each event (the frame nearest in time), with the way each one was
        running (vx, vy and facing, see motion)."""
        rows = []
        for e in ev.itertuples():
            ids, teams, xy = players[players.nearest(int(e.ts_ms))]
            run = PitchService.motion(players, int(e.ts_ms))
            rows += [(e.event_id, pid, team, round(x, 2), round(y, 2), *run.get(pid, (None, None, None)))
                     for pid, team, (x, y) in zip(ids, teams, xy)]
        return pd.DataFrame(rows, columns=["event_id", "player_id", "team_id", "x", "y", "vx", "vy", "facing_deg"])

    @staticmethod
    def draw_moment(decision: dict, positions: dict, home_id: str, home_name: str, away_name: str) -> bytes:
        """decision: the event and its options (marked with the MARKS flags, or faint in the analyst's copy);
        positions: the ball and the players. Returns PNG bytes: the part of the pitch where it happens, from above."""
        e = decision["event"]
        ball = (positions["ball"]["x"], positions["ball"]["y"])
        names = {p["player_id"]: p.get("name") for p in positions["players"]}
        spot_of = {p["player_id"]: (p["x"], p["y"]) for p in positions["players"]}
        marked = [([m for m in MARKS if o.get(m[0])], o) for o in decision["options"] if "target_x" in o]
        shown = [(hits, o) for hits, o in marked if hits or o.get("faint")]
        receivers = [spot_of[o["target_player_id"]] for _, o in shown if o.get("target_player_id") in spot_of]
        xs = [ball[0]] + [o["target_x"] for _, o in shown] + [r[0] for r in receivers]
        ys = [ball[1]] + [o["target_y"] for _, o in shown] + [r[1] for r in receivers]
        if decision.get("defence"):    # a goal picture: the defender and where he should have gone stay in view
            fix = decision["defence"]
            xs, ys = xs + [fix["from_x"], fix["to_x"]], ys + [fix["from_y"], fix["to_y"]]
        x0, x1, y0, y1 = zoom(xs, ys)   # the ball, where the marked options go and who they go to
        fig = Figure(figsize=(FIG_W, TITLE_H_IN + PITCH_H_IN + TEXT_H_IN), dpi=DPI, facecolor=BACKGROUND)
        total = TITLE_H_IN + PITCH_H_IN + TEXT_H_IN
        ax = fig.add_axes((0, TEXT_H_IN / total, 1, PITCH_H_IN / total))
        Pitch(pitch_type="custom", pitch_length=PITCH_X, pitch_width=PITCH_Y, pitch_color=GRASS, stripe=True,
              stripe_color=STRIPE, line_color=LINE_COLOR, linewidth=1.6, goal_type="box", pad_left=EDGE_M,
              pad_right=EDGE_M, pad_top=EDGE_M, pad_bottom=EDGE_M).draw(ax=ax)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        circle_m = PLAYER_PT / 72 * (x1 - x0) / FIG_W        # a player circle's diameter in metres at this zoom
        players = sorted(positions["players"], key=lambda p: p["player_id"] == e["player_id"])   # carrier on top
        true = [(p["x"], p["y"]) for p in players]
        spots = spread(true + [ball], circle_m * 1.05, fixed=len(true))[:-1]   # the ball stays put
        for (tx, ty), (x, y) in zip(true, spots):         # a moved circle keeps a dot and a line to its real spot
            if math.hypot(x - tx, y - ty) > circle_m * 0.1:
                ax.plot([tx, x], [ty, y], color=LINE_COLOR, lw=0.8, zorder=4)
                ax.scatter([tx], [ty], s=6, color=LINE_COLOR, zorder=4)
        drawn = {p["player_id"]: s for p, s in zip(players, spots)}   # where each circle is drawn
        labels, segments = [], []   # the names go on last, where they cover the least
        for hits, o in shown:       # under the players, so the numbers stay readable
            tip = (o["target_x"], o["target_y"])
            if not hits:            # the analyst's copy: every other option as a faint line, nothing more
                ax.plot([ball[0], tip[0]], [ball[1], tip[1]], color=LINE_COLOR, lw=1, ls=":", alpha=0.7, zorder=3)
                continue
            runner = spot_of.get(o.get("target_player_id"))    # a ball played into space ahead of him: his run
            runner = runner if runner and math.dist(runner, tip) >= RUN_MIN_GAIN_M else None
            if o.get("target_player_id") in drawn and not runner:   # to his feet: to his circle, even when moved
                tip = drawn[o["target_player_id"]]
            if runner:              # a pass into a run: a dashed ring round the runner and a white arrow along his run
                segments.append((runner, tip))
                colour = hits[0][1]
                ax.scatter([runner[0]], [runner[1]], s=(PLAYER_PT + 10) ** 2, facecolors="none", edgecolors=colour,
                           linewidths=2.5, linestyles="--", zorder=6)
                ax.annotate("", xy=tip, xytext=runner, zorder=7,
                            arrowprops=dict(arrowstyle="-|>,head_length=0.8,head_width=0.45", color=LINE_COLOR, lw=3,
                                            shrinkA=(PLAYER_PT + 10) / 2, shrinkB=PLAYER_PT / 2 + 1, mutation_scale=14,
                                            path_effects=[withStroke(linewidth=5, foreground="black")]))
                ax.annotate("run", ((runner[0] + tip[0]) / 2, (runner[1] + tip[1]) / 2), xytext=(0, -12),
                            textcoords="offset points", ha="center", fontsize=9, fontweight="bold", color=LINE_COLOR,
                            zorder=8, path_effects=[withStroke(linewidth=3, foreground="black")])
            dx, dy = tip[0] - ball[0], tip[1] - ball[1]
            n = math.hypot(dx, dy) or 1.0
            short = n < 2 * circle_m    # a very short pass: the head under his circle, never turned back
            for i, (_, colour, _, dashed) in enumerate(hits):   # side by side, and a ring round the target spot
                k = (i - (len(hits) - 1) / 2) * MARK_GAP * circle_m
                sx, sy = -dy / n * k, dx / n * k
                ax.annotate("", xy=(tip[0] + sx, tip[1] + sy), xytext=(ball[0] + sx, ball[1] + sy), zorder=3,
                            arrowprops=dict(arrowstyle="-|>,head_length=0.7,head_width=0.35", color=colour,
                                            lw=MARK_WIDTH, ls="--" if dashed else "-", shrinkA=0,
                                            shrinkB=0 if short else PLAYER_PT / 2 + 1, mutation_scale=14))
                ax.scatter([tip[0]], [tip[1]], s=(PLAYER_PT + 7 + 6 * i) ** 2, facecolors="none", edgecolors=colour,
                           linewidths=2, zorder=6)
            segments.append((ball, tip))
            labels.append((names.get(o.get("target_player_id")) or word(o).removeprefix("a ").capitalize(), tip,
                           hits[0][1]))
        m_per_pt = circle_m / PLAYER_PT
        boxes = []
        for name, tip, colour in labels:
            w, h = (len(name) * 9 * 0.6 + 8) * m_per_pt, 17 * m_per_pt    # 9 pt letters with the box's padding
            cx, cy = label_spot(tip, w, h, circle_m * 0.75, spots + [ball], circle_m / 2, segments, boxes,
                                (x0, x1, y0, y1))
            boxes.append((cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2))
            ax.text(cx, cy, name, ha="center", va="center", fontsize=9, color=LINE_COLOR, zorder=8,
                    bbox=dict(boxstyle="round,pad=0.25", fc="black", ec=colour, alpha=0.8))
        for p, (x, y) in zip(players, spots):
            actor = p["player_id"] == e["player_id"]
            ax.scatter([x], [y], s=PLAYER_PT ** 2, color=HOME if p["team_id"] == home_id else AWAY,
                       marker="D" if p.get("position") == "GK" else "o",     # the keepers are diamonds
                       edgecolors=LINE_COLOR, linewidths=3.5 if actor else 1, zorder=5)
            ax.text(x, y, str(p.get("shirt") or ""), color=LINE_COLOR, fontsize=8.5, fontweight="bold", ha="center",
                    va="center", zorder=5, clip_on=True)
        ax.scatter([ball[0]], [ball[1]], s=60, color=LINE_COLOR, edgecolors="black", linewidths=1.2, zorder=9)
        if decision.get("defence"):
            PitchService.draw_defence(ax, decision["defence"], drawn.get(decision["defence"]["player_id"]), circle_m,
                                      [*drawn.values(), ball])
        unseen = next((o for o in decision["options"] if o.get("is_decision1") and "target_x" not in o), None)
        if unseen:                  # Decision-1 chose the analyst's picture option that names no team-mate: no arrow
            ax.text(0.01, 0.015, textwrap.fill(f"Decision-1 chose what the analyst saw in the picture: {unseen['text']}",
                                               110), transform=ax.transAxes, fontsize=9.5, color=LINE_COLOR, zorder=10,
                    bbox=dict(boxstyle="round,pad=0.35", fc="black", ec=MARKS[3][1], alpha=0.85))
        fig.text(0.015, 1 - TITLE_H_IN / total / 2, f"Minute {e['minute']}, score {e.get('score_home')}-"
                 f"{e.get('score_away')}.  {e.get('player_name')} on the ball (thick white ring).  Red: {home_name} "
                 f"(attacks right), blue: {away_name}.  Keepers: diamonds.", color=LINE_COLOR, fontsize=10, va="center")
        low = fig.add_axes((0, 0, 1, TEXT_H_IN / total))
        low.set_axis_off()
        low.set_xlim(0, 1)
        low.set_ylim(0, 1)
        low.legend([Line2D([], [], color=c, lw=MARK_WIDTH, ls="--" if d else "-", marker=">", markevery=[-1])
                    for _, c, _, d in MARKS], [m[2] for m in MARKS], loc="upper center", ncol=len(MARKS),
                   frameon=False, labelcolor=LINE_COLOR, fontsize=10, handlelength=3)
        for side, (is_home, team, colour) in enumerate(((True, home_name, HOME), (False, away_name, AWAY))):
            squad = sorted((p for p in positions["players"] if (p["team_id"] == home_id) == is_home),
                           key=lambda p: (p.get("shirt") is None, p.get("shirt") or 0))
            left = 0.02 + side * 0.5
            low.scatter([left + 0.006], [0.7], s=80, color=colour, marker="s")
            low.text(left + 0.02, 0.7, team, color=LINE_COLOR, fontsize=10, va="center")
            for i, p in enumerate(squad):
                col, row = divmod(i, LEGEND_ROWS)
                low.text(left + col * 0.24, 0.58 - row * 0.095, f"{p.get('shirt') or '?':>2}  "
                         f"{p.get('name') or p['player_id']}", color=LINE_COLOR, fontsize=8.5, va="center")
        out = io.BytesIO()
        FigureCanvasAgg(fig).print_png(out)
        return out.getvalue()

    @staticmethod
    def draw_defence(ax, fix: dict, drawn_spot, circle_m: float, taken: list) -> None:
        """A goal picture: a dashed orange arrow from the defender's circle to where he should have gone, a ring
        there, a short label ("#4 cut out the pass") below, above, right or left of the ring, inside the picture where
        the fewest players and the ball (taken) sit under it, and a note on what the orange arrow means."""
        spot = (fix["to_x"], fix["to_y"])
        start = drawn_spot or (fix["from_x"], fix["from_y"])
        if math.dist(start, spot) > circle_m:     # already there (he only had to stay): just the ring
            ax.annotate("", xy=spot, xytext=start, zorder=7,
                        arrowprops=dict(arrowstyle="-|>,head_length=0.7,head_width=0.35", color=DEFENCE_COLOUR,
                                        lw=MARK_WIDTH + 0.8, ls="--", shrinkA=PLAYER_PT / 2 + 1, shrinkB=0, mutation_scale=14,
                                        path_effects=[withStroke(linewidth=MARK_WIDTH + 2, foreground="black")]))
        ax.scatter([spot[0]], [spot[1]], s=(PLAYER_PT * 0.8) ** 2, facecolors="none", edgecolors=DEFENCE_COLOUR,
                   linewidths=2, linestyles="--", zorder=7)
        late = f" ({fix['late_s']:.1f} s late)" if fix.get("late_s") else ""
        label = f"#{fix.get('shirt') or '?'} {DEFENCE_LABELS[fix['kind']]}{late}"
        m = circle_m / PLAYER_PT                        # metres per point
        w, h = len(label) * 9 * 0.55 * m, 14 * m        # the label's box in metres
        up = -1 if ax.yaxis_inverted() else 1
        places = [((0, -PLAYER_PT), "center", "top", (spot[0], spot[1] - up * (circle_m + h / 2))),
                  ((0, PLAYER_PT), "center", "bottom", (spot[0], spot[1] + up * (circle_m + h / 2))),
                  ((PLAYER_PT, 0), "left", "center", (spot[0] + circle_m + w / 2, spot[1])),
                  ((-PLAYER_PT, 0), "right", "center", (spot[0] - circle_m - w / 2, spot[1]))]
        under = lambda c: sum(abs(x - c[0]) < w / 2 + circle_m / 2 and abs(y - c[1]) < h / 2 + circle_m / 2   # noqa: E731
                              for x, y in taken)
        (x0, x1), (y0, y1) = sorted(ax.get_xlim()), sorted(ax.get_ylim())
        inside = lambda c: x0 + w / 2 <= c[0] <= x1 - w / 2 and y0 + h / 2 <= c[1] <= y1 - h / 2   # noqa: E731
        off, ha, va, c = min(places, key=lambda p: (not inside(p[3]), under(p[3])))
        box = dict(boxstyle="round,pad=0.25", fc="black", ec=DEFENCE_COLOUR, alpha=0.8)
        if inside(c):
            ax.annotate(label, spot, xytext=off, textcoords="offset points", ha=ha, va=va, fontsize=9,
                        color=LINE_COLOR, zorder=8, bbox=box)
        else:                       # in a corner every side runs off the picture: pushed back inside it
            ax.text(min(max(c[0], x0 + w / 2), x1 - w / 2), min(max(c[1], y0 + h / 2), y1 - h / 2), label,
                    ha="center", va="center", fontsize=9, color=LINE_COLOR, zorder=8, bbox=box)
        ax.text(0.99, 0.015, "Orange dashed arrow: where a defender should have gone to stop it",
                transform=ax.transAxes, ha="right", fontsize=9.5, color=LINE_COLOR, zorder=10,
                bbox=dict(boxstyle="round,pad=0.35", fc="black", ec=DEFENCE_COLOUR, alpha=0.85))

    # ---------- into 2D ----------
    def read_tracking(self, data: bytes, home_id: str, away_id: str) -> pd.DataFrame:
        """A tracking file (csv or csv.gz: ts_ms, period, object_id, team_id, x, y[, z]) -> positions."""
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        try:
            t = pd.read_csv(io.BytesIO(data), dtype={"team_id": "string", "object_id": "string"}, low_memory=False)
        except (ValueError, UnicodeDecodeError) as err:
            raise BadInput(f"the tracking file could not be read: {err}") from err
        missing = [c for c in TRACKING_COLS if c not in t]
        if missing:
            raise BadInput(f"missing columns in the tracking file: {', '.join(missing)}")
        teams = set(t.team_id.dropna())
        if teams != {home_id, away_id}:
            raise BadInput(f"team_id must be {home_id} and {away_id}, found: {', '.join(sorted(teams)) or 'none'}")
        if not t.object_id.eq("ball").any():
            raise BadInput("no ball rows (object_id = ball) in the tracking file")
        return self.orient(t[[c for c in [*TRACKING_COLS, "z"] if c in t]], home_id)

    def read_metrica(self, home_csv: bytes, away_csv: bytes, home_id: str, away_id: str, period: int,
                     start_minute: int, minutes: int) -> pd.DataFrame:
        """Metrica's own raw tracking files (one per team: Sample_Game_N_RawTrackingData_Home/Away_Team.csv) ->
        our positions for `minutes` from a match minute of one half (Metrica's clock runs on from the first
        half, so the second half is found by its own first frame). Player ids are TEAM_shirt; the ball comes
        from the home file. Metrica gives 0-1 coordinates with y down; ours are metres with y up."""
        rows = []
        for data, team, with_ball in ((home_csv, home_id, True), (away_csv, away_id, False)):
            try:
                shirts = pd.read_csv(io.BytesIO(data), nrows=1, skiprows=1, header=None).iloc[0]
                raw = pd.read_csv(io.BytesIO(data), skiprows=2)
            except (ValueError, UnicodeDecodeError) as err:
                raise BadInput(f"not a Metrica tracking file: {err}") from err
            if "Time [s]" not in raw or "Period" not in raw:
                raise BadInput("not a Metrica tracking file: no Time [s] / Period columns")
            raw = raw[raw.Period == period]
            if raw.empty:
                raise BadInput(f"no period {period} in the Metrica file")
            first = 45 * (period - 1)
            last = first + int(-(-(raw["Time [s]"].iat[-1] - raw["Time [s]"].iat[0]) // 60))   # rounded up
            if not first <= start_minute < last:
                raise BadInput(f"half {period} of this file runs from minute {first} to {last}: "
                               f"the start minute must be in it (match minute, 45 or later in the second half)")
            from_s = raw["Time [s]"].iat[0] + (start_minute - first) * 60
            raw = raw[raw["Time [s]"].between(from_s, from_s + minutes * 60)]
            ts = (raw["Time [s]"] * 1000).round().astype("int64")
            for i, col in enumerate(raw.columns):
                if not (col.startswith("Player") or (col == "Ball" and with_ball)):
                    continue
                oid = "ball" if col == "Ball" else f"{team}_{int(shirts[i]):02d}"
                rows.append(pd.DataFrame({"ts_ms": ts, "period": raw.Period, "object_id": oid,
                                          "team_id": None if col == "Ball" else team,
                                          "x": raw.iloc[:, i] * PITCH_X, "y": (1 - raw.iloc[:, i + 1]) * PITCH_Y}))
        if not rows:
            raise BadInput("no players in the Metrica files")
        t = pd.concat(rows).dropna(subset=["x", "y"]).sort_values(["ts_ms", "object_id"])
        # only the frames with the ball, like our own files: while it is out of play Metrica still follows the
        # players, and walking them back across the pitch would read as play (a goal then looks like a pass)
        t = t[t.ts_ms.isin(t.ts_ms[t.object_id == "ball"])]
        if t.empty or not t.object_id.eq("ball").any():
            raise BadInput("no positions in that time window")
        t["x"], t["y"] = t.x.round(2), t.y.round(2)
        t["team_id"] = t.team_id.astype("string")
        return self.orient(t.reset_index(drop=True), home_id)

    @staticmethod
    def orient(tracking: pd.DataFrame, home_id: str) -> pd.DataFrame:
        """Home team attacking +x in every period (the pitch is turned where it attacks the other way)."""
        return PitchService.home_to_right(tracking, home_id)

    # ---------- what the positions tell ----------
    def keepers(self, tracking: pd.DataFrame, home_id: str, known: set) -> set:
        return PitchService.keepers_of(tracking, home_id, set(known) | set(tracking.attrs.get("keepers", set())))

    def events(self, tracking: pd.DataFrame, home_id: str, keepers: set, period: int = 1,
               start_minute: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
        """On-ball events (pass, shot, dribble, carry, clearance ...) and the freeze frame of each one, with
        everyone's running direction. start_minute: the match minute of the clip's first frame."""
        clock = None
        if start_minute is not None and (tracking.period == period).any():
            clock = {period: (int(tracking[tracking.period == period].ts_ms.min()), start_minute)}
        ev, frames = PitchService.detect(tracking, home_id, keepers, clock)
        if ev.empty:
            raise BadInput("no ball touches found in the positions")
        return ev, frames

    def players(self, tracking: pd.DataFrame, names: dict, keepers: set, home_id: str,
                known: list[dict] = ()) -> list[dict]:
        """One row per player: name, position and top speed. What the file gives wins; the rest is read from
        the movement ("Team #n" names, position from the average spot, top speed from the running speeds)."""
        speed, role = PitchService.top_speeds(tracking), PitchService.positions(tracking, home_id, keepers)
        given = {p["player_id"]: p for p in known}
        out, count = [], {}
        pl = tracking[tracking.object_id != "ball"].drop_duplicates("object_id")
        for oid, team in zip(pl.object_id, pl.team_id):
            count[team] = count.get(team, 0) + 1
            row = {"player_id": oid, "team_id": team, "name": f"{names.get(team, team)} #{count[team]}",
                   "position": role.get(oid), "max_speed": speed.get(oid)}
            number = oid.rsplit("_", 1)[-1]
            if number.isdigit():                            # Metrica ids are TEAM_shirt
                row["shirt"] = int(number)
                row["name"] = f"{names.get(team, team)} #{int(number)}"
            row.update({k: v for k, v in given.get(oid, {}).items() if v is not None})
            out.append(row)
        return out

    # ---------- pictures and replay ----------
    def draw(self, event: dict, options: list[dict], frame: list[dict], home_id: str, home_name: str,
             away_name: str, defence: dict | None = None) -> bytes:
        """The moment from above as a PNG: everyone, the ball, the player's choice, the best and the safest
        good option as arrows. event: minute, score, player; frame: player_id, team_id, x, y, shirt. defence (goal
        pictures): where a defender should have gone (core/utils.py defence_fix), drawn as an orange arrow."""
        return PitchService.draw_moment({"event": event, "options": options} | ({"defence": defence} if defence else {}),
                                 {"ball": {"x": event["x"], "y": event["y"]}, "players": frame},
                                 home_id, home_name, away_name)

    @staticmethod
    def frames(tracking: pd.DataFrame, from_ms: int, to_ms: int, hz: int = REPLAY_HZ) -> list[dict]:
        """Positions between two times, hz frames a second, for the replay on the screen. The ball is in every
        frame: short gaps are filled in a line (ball_track), longer ones keep it where it was last seen (or first
        seen), so it never disappears while a player has it. It comes last, so it is drawn on top."""
        win = tracking[(tracking.ts_ms >= from_ms) & (tracking.ts_ms <= to_ms)]
        if win.empty:
            return []
        step = 1000 // hz
        start = int(win.ts_ms.min())
        win = win[(win.ts_ms - start) % step < 40]
        ball = PitchService.ball_track(tracking).loc[from_ms:to_ms, ["x", "y"]].ffill().bfill()
        out = []
        for ts, g in win[win.object_id != "ball"].groupby("ts_ms"):
            objs = [{"id": r.object_id, "team_id": None if pd.isna(r.team_id) else r.team_id,
                     "x": round(float(r.x), 2), "y": round(float(r.y), 2)} for r in g.itertuples() if pd.notna(r.x)]
            if ts in ball.index and pd.notna(ball.at[ts, "x"]):
                objs.append({"id": "ball", "team_id": None, "x": round(float(ball.at[ts, "x"]), 2),
                             "y": round(float(ball.at[ts, "y"]), 2)})
            out.append({"ts_ms": int(ts), "objects": objs})
        return out

pitch = PitchService()
