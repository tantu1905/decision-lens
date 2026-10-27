from types import SimpleNamespace

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from src.core.utils import DEFENCE_OPTIONS_MAX, BadInput, defence_fix, defence_options, label_spot
from src.services.pitch_service import pitch
from src.services.pitch_service import PitchService


def track(rows):
    return pd.DataFrame(rows, columns=["ts_ms", "period", "object_id", "team_id", "x", "y"])


def test_top_speed_and_running_direction():
    rows = [(t, 1, "H_1", "H", 30 + 7 * t / 1000, 34.0) for t in range(0, 4000, 40)]
    rows += [(t, 1, "A_1", "A", 60.0, 34.0) for t in range(0, 4000, 40)]
    tr = track(rows)
    assert abs(PitchService.top_speeds(tr)["H_1"] - 7.0) < 0.1 and PitchService.top_speeds(tr)["A_1"] == 5.5
    mv = PitchService.motion(PitchService.player_frames(tr), 2000)
    assert mv["H_1"][2] in (0.0, 360.0) and mv["A_1"][2] is None


def test_positions_and_keepers():
    spots = {"H_gk": (5, 34), "H_cb": (30, 34), "H_lb": (28, 60), "H_cm": (50, 34), "H_dm": (45, 30), "H_st": (70, 34),
             "A_gk": (100, 34), "A_cb": (75, 34), "A_lb": (77, 8), "A_cm": (55, 34), "A_dm": (60, 38), "A_st": (35, 34)}
    tr = track([(0, 1, p, p[0], x, y) for p, (x, y) in spots.items()])
    assert PitchService.keepers_of(tr, "H", set()) == {"H_gk", "A_gk"}
    pos = PitchService.positions(tr, "H", {"H_gk", "A_gk"})
    assert pos["H_lb"] == "LB" and pos["A_lb"] == "LB" and pos["H_st"] == "ST" and pos["A_cb"] == "CB"


def test_tracking_file_is_checked():
    with pytest.raises(BadInput):
        pitch.read_tracking(b"ts_ms,period\n1,1\n", "H", "A")
    good = track([(0, 1, "ball", None, 50, 30), (0, 1, "H_1", "H", 40, 30), (0, 1, "A_1", "A", 60, 30)])
    with pytest.raises(BadInput):
        pitch.read_tracking(good.to_csv(index=False).encode(), "H", "X")
    assert len(pitch.read_tracking(good.to_csv(index=False).encode(), "H", "A")) == 3


def test_replay_frames():
    tr = track([(t, 1, o, None if o == "ball" else "H", 50, 30) for t in range(0, 2000, 40) for o in ("ball", "H_1")])
    out = pitch.frames(tr, 0, 1000)
    assert len(out) == 26 and {o["id"] for o in out[0]["objects"]} == {"ball", "H_1"}   # 25 a second, both ends


def test_speeds_never_run_across_a_hole_in_the_data():
    """Out of play the rows are gone while everyone walks on: a 20 m jump over the hole is no 40 m/s run."""
    rows = [(t, 2, o, None if o == "ball" else "H", 50 + t / 1000 + (20 if t >= 6000 else 0), 30)
            for t in range(0, 10000, 40) if not 3000 < t < 6000 for o in ("ball", "H_1")]
    frames = PitchService.player_frames(track(rows))
    for ts in (2900, 6000, 6120, 7000):
        assert abs(PitchService.motion(frames, ts)["H_1"][0] - 1.0) < 0.25


def test_read_metrica_second_half():
    """Metrica's clock runs on from the first half; the teams change ends; a substitute is NaN until he comes on."""
    def file(side, x):
        lines = [f",,,{side},,{side},,,", ",,,1,,14,,,", "Period,Frame,Time [s],Player1,,Player14,,Ball,"]
        for f in range(1, 3001):                             # 60 s of a first half, then 60 s of the second
            period, t = (1 if f <= 1500 else 2), f * 0.04
            px = x if period == 1 else 1 - x
            sub = "NaN,NaN" if period == 1 else f"{px},0.5"
            lines.append(f"{period},{f},{t:.2f},{px},0.5,{sub},0.5,0.5")
        return "\n".join(lines).encode()

    t = pitch.read_metrica(file("Home", 0.2), file("Away", 0.8), "H", "A", period=2, start_minute=45, minutes=1)
    assert set(t.period) == {2} and t.ts_ms.min() == 60040
    assert set(t.object_id) == {"ball", "H_01", "H_14", "A_01", "A_14"}
    assert t[t.team_id == "H"].x.mean() < t[t.team_id == "A"].x.mean()      # home attacks +x again


def test_a_hole_in_the_tracking_before_a_touch_on_the_line_is_a_throw_in():
    # the clip has no frames at all while the ball is out of play, so the ball cannot be seen lying still
    ts = list(range(0, 5000, 40)) + list(range(12000, 12120, 40))
    ball = pd.DataFrame({"x": [30.0 + i * 0.1 for i in range(len(ts))], "y": 1.0, "seen": True}, index=ts)
    e = SimpleNamespace(ts_ms=12200, x=36.0, y=0.5)
    assert PitchService.restart_kind(e, ball) == "from_throw_in"
    mid = SimpleNamespace(ts_ms=12200, x=50.0, y=34.0)          # a replay cut mid-pitch: nothing says the game stopped
    assert PitchService.restart_kind(mid, ball) == "open_play"
    assert PitchService.restart_kind(SimpleNamespace(ts_ms=100, x=36.0, y=0.5), ball) == "open_play"   # start of the clip


def test_a_name_goes_where_it_covers_no_player_and_no_arrow():
    """Above-right of the target is taken by a team-mate and the arrow comes in from the left: the name goes
    elsewhere, not over either."""
    tip, bounds = (50.0, 30.0), (0, 105, 0, 68)
    free = label_spot(tip, 6, 1.5, 1.5, [(55.0, 32.0)], 1.0, [], [], bounds)
    assert free != (tip[0] + 1.5 + 3, tip[1] + 1.5 + 0.75)
    cx, cy = label_spot(tip, 6, 1.5, 1.5, [(55.0, 32.0)], 1.0, [((30.0, 30.0), tip)], [], bounds)
    assert not (cx - 3 <= 40 <= cx + 3 and cy - 0.75 <= 30 <= cy + 0.75)     # not on the arrow


def goal_decision(option):
    """A home pass (home attacks +x) with one defender on its lane, one far away and the away keeper."""
    frame = [{"player_id": "H9", "team_id": "H", "x": 70.0, "y": 34.0, "shirt": 9, "name": "A"},
             {"player_id": "H7", "team_id": "H", "x": 90.0, "y": 34.0, "shirt": 7, "name": "B"},
             {"player_id": "A4", "team_id": "A", "x": 80.0, "y": 35.0, "shirt": 4, "name": "C"},
             {"player_id": "A2", "team_id": "A", "x": 60.0, "y": 10.0, "shirt": 2, "name": "D"},
             {"player_id": "A1", "team_id": "A", "x": 83.0, "y": 34.0, "shirt": 1, "name": "E", "position": "GK"}]
    e = {"event_id": "e1", "team_id": "H", "player_id": "H9", "x": 70.0, "y": 34.0, "minute": 10, "score_home": 0,
         "score_away": 0, "player_name": "A", "frame": frame}
    return e, [{"option_id": "o1", "is_chosen": True, **option}]


def test_a_defender_on_the_lane_cuts_out_the_pass_the_keeper_never_counts():
    e, opts = goal_decision({"option_type": "pass", "target_x": 90.0, "target_y": 34.0, "target_player_id": "H7"})
    fix = defence_fix({**e, "options": opts}, {"A1"}, "H")
    assert fix["player_id"] == "A4" and fix["kind"] == "cut" and fix["late_s"] == 0 and 72 <= fix["to_x"] <= 88
    e, opts = goal_decision({"option_type": "shot", "target_x": 105.0, "target_y": 34.0})
    fix = defence_fix({**e, "options": opts}, {"A1"}, "H")
    assert fix["kind"] == "block" and fix["to_x"] > e["x"] and fix["late_s"] > 0     # A4 stands 10 m away


def test_defence_options_carry_the_three_numbers_and_the_keeper_has_none():
    e, opts = goal_decision({"option_type": "pass", "target_x": 90.0, "target_y": 34.0, "target_player_id": "H7",
                             "value_if_success": 0.2})
    out = defence_options({**e, "options": opts}, {"A1"}, "H")
    assert 1 <= len(out) <= DEFENCE_OPTIONS_MAX and all(o["player_id"] != "A1" for o in out)
    assert [o["option_id"] for o in out] == [f"e1_d{i}" for i in range(1, len(out) + 1)]
    assert all(0 <= o["p_success"] <= 1 and o["value_if_success"] == 0.2 for o in out)
    assert [o["ev"] for o in out] == sorted((o["ev"] for o in out), reverse=True)
    assert out[0]["player_id"] == "A4" and out[0]["kind"] == "cut"            # A4 stands on the lane


def test_the_defence_arrow_is_drawn_only_on_goal_pictures():
    """A critical moment picture (no defence) is byte for byte what draw_moment drew before; the goal picture
    with the defender's arrow differs."""
    e, opts = goal_decision({"option_type": "pass", "target_x": 90.0, "target_y": 34.0, "target_player_id": "H7"})
    plain = PitchService.draw_moment({"event": e, "options": opts}, {"ball": {"x": 70.0, "y": 34.0},
                                     "players": e["frame"]}, "H", "Home", "Away")
    assert pitch.draw(e, opts, e["frame"], "H", "Home", "Away") == plain
    fix = defence_fix({**e, "options": opts}, {"A1"}, "H")
    assert pitch.draw(e, opts, e["frame"], "H", "Home", "Away", {**fix, "shirt": 4}) != plain


def test_the_defence_label_stays_inside_the_picture():
    """A defender on the goal line with players left of and below him: his label goes where it fits in the picture."""
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.set_xlim(60, 105)
    ax.set_ylim(10, 58)
    fix = {"player_id": "A3", "from_x": 100.0, "from_y": 28.0, "to_x": 103.5, "to_y": 34.0, "kind": "block",
           "late_s": 0.0, "shirt": 3}
    PitchService.draw_defence(ax, fix, None, 2.0, [(99.0, 34.0), (103.5, 30.0), (100.0, 28.0)])
    fig.canvas.draw()
    label = next(t for t in ax.texts if t.get_text().startswith("#3"))
    inner, outer = label.get_window_extent(), ax.get_window_extent()
    plt.close(fig)
    assert outer.x0 <= inner.x0 and inner.x1 <= outer.x1 and outer.y0 <= inner.y0 and inner.y1 <= outer.y1
