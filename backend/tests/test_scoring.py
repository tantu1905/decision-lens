from src.schemas.scoring import Moment, MomentPlayer
from src.core.utils import SHOT_TAKEN, SHOT_VALUE_CAP, describe, pass_direction
from src.services.scoring_service import ScoringService


def moment(ball, mates, opps, chosen="pass", end=None, line="def"):
    players = [MomentPlayer(player_id="me", xy=ball, mate=True, is_actor=True, line=line)]
    players += [MomentPlayer(player_id=f"m{i}", xy=xy, mate=True) for i, xy in enumerate(mates)]
    players += [MomentPlayer(player_id=f"o{i}", xy=xy, mate=False) for i, xy in enumerate(opps)]
    players.append(MomentPlayer(player_id="ok", xy=(103, 34), mate=False, is_keeper=True, line="gk"))
    return Moment(event_id="e1", ball=ball, end=end or ball, chosen_type=chosen, outcome="success",
                  carrier_line=line, players=players)


def test_defender_under_pressure_can_hold_or_clear():
    m = moment((15, 30), [(30, 50), (40, 20)], [(16.5, 30.5), (25, 34)], chosen="clearance", end=(60, 6))
    kinds = {o.option_type for o in ScoringService.options_for(m)}
    assert {"hold", "clearance", "clear_out"} <= kinds
    d = ScoringService.judge(m, ScoringService.options_for(m))
    assert next(o for o in d.options if o.is_chosen).option_type == "clearance"


def test_no_clearance_in_the_opponents_half():
    m = moment((70, 34), [(80, 20)], [(71, 34.5), (90, 34)], line="mid")
    assert not {"clearance", "clear_out"} & {o.option_type for o in ScoringService.options_for(m)}


def test_pass_directions():
    assert pass_direction((50, 34), (70, 30), line=72) == "through"
    assert pass_direction((50, 34), (60, 30), line=80) == "forward"
    assert pass_direction((50, 34), (52, 50), line=80) == "side"
    assert pass_direction((50, 34), (35, 30), line=80) == "back"


def test_away_targets_are_stored_on_the_pitch():
    o = ScoringService.on_pitch({"target_x": 100.0, "target_y": 10.0}, away=True)
    assert (o["target_x"], o["target_y"]) == (5.0, 58.0)


def test_pass_into_the_run_of_a_moving_team_mate():
    m = moment((50, 34), [(62, 30)], [(70, 40), (85, 34)], line="mid")
    still = [o for o in ScoringService.options_for(m) if o.target_player_id == "m0"]
    assert len(still) == 1 and not still[0].into_run
    runner = m.model_copy(update={"players": [p.model_copy(update={"vx": 5.0, "vy": 0.0}) if p.player_id == "m0" else p
                                               for p in m.players]})
    runs = [o for o in ScoringService.options_for(runner) if o.target_player_id == "m0"]
    assert [o.into_run for o in runs] == [False, True] and runs[1].target_x == 68.5   # met by a 12 m pass after 1.3 s
    assert runs[1].direction in ("forward", "through") and runs[1].p_success > 0


def test_pass_chance_comes_from_pitch_control():
    free = moment((50, 34), [(62, 30)], [(80, 50), (85, 34)], line="mid")
    marked = moment((50, 34), [(62, 30)], [(63, 31), (85, 34)], line="mid")
    cut = moment((50, 34), [(62, 30)], [(56, 32.5), (85, 34)], line="mid")
    p = {k: next(o.p_success for o in ScoringService.options_for(m) if o.target_player_id == "m0")
         for k, m in (("free", free), ("marked", marked), ("cut", cut))}
    assert p["free"] > 0.9 and p["marked"] < p["free"] - 0.3 and p["cut"] < p["free"] - 0.3


def test_losing_the_ball_is_worse_when_they_own_the_space_behind_it():
    covered = moment((60, 34), [(40, 30), (40, 40), (45, 34)], [(62, 34)], line="mid")
    open_ = moment((60, 34), [(75, 30)], [(62, 34), (50, 25), (50, 45)], line="mid")
    assert ScoringService.lost_at(open_, (60, 34)) > 1.5 * ScoringService.lost_at(covered, (60, 34))


def test_a_long_ball_the_player_played_flies_over_the_defenders():
    m = moment((20, 34), [(75, 40)], [(30, 36), (45, 38), (60, 39), (85, 34)], end=(75, 40))
    m = m.model_copy(update={"pass_type": "long", "recipient_id": "m0"})
    chosen = ScoringService.judge(m, ScoringService.options_for(m)).options
    taken = next(o for o in chosen if o.is_chosen)
    assert taken.option_type == "long_ball" and taken.p_success > 0.3


def test_base_score_of_a_decision():
    from src.core.utils import base_score
    opts = [{"ev": v, "is_chosen": v == 0.04} for v in (0.05, 0.04, 0.01, 0.0, -0.01)]
    assert base_score({"options": opts}) == 8.2 and base_score({"options": []}) is None   # 0.01 given up
    calm = [{"ev": v, "is_chosen": v == 0.003} for v in (0.006, 0.005, 0.004, 0.003, 0.002)]
    assert base_score({"options": calm}) == 9.4                 # every option about the same: a fine choice
    bad = [{"ev": v, "is_chosen": v == 0.01} for v in (0.28, 0.1, 0.01)]
    assert base_score({"options": bad}) == 0.1                  # a back pass instead of a 30% shot: the lowest score
    worse = [{"ev": v, "is_chosen": v == 0.0} for v in (0.06, 0.0)]
    assert base_score({"options": worse}) == 3.0                # a smaller mistake scores differently, not 0


def test_attack_phases_and_spacing():
    from src.core.utils import apart, phases, rushed
    ev = [{"event_id": "a", "team_id": "H", "ts_ms": 0}, {"event_id": "b", "team_id": "H", "ts_ms": 3000},
          {"event_id": "c", "team_id": "A", "ts_ms": 4000}, {"event_id": "d", "team_id": "A", "ts_ms": 40_000}]
    ph = phases(ev)
    assert ph["a"] == ph["b"] != ph["c"] != ph["d"]
    assert not apart(ev[1], [ev[0]], ph) and not apart(ev[2], [ev[0]], ph) and apart(ev[3], [ev[0]], ph)
    assert rushed(ev) == {"c"}                    # cleared 1 s after the other team's touch


def test_a_pass_far_from_every_option_is_scored_as_itself():
    # a ball poked over the byline with no team-mate near: the nearest pass option is 30 m away, so what the
    # player did is scored as its own option instead of being read as a back pass
    m = moment((102.9, 55), [(75, 48), (71, 46)], [(101, 56), (90, 50)], end=(105.2, 55.1))
    m = m.model_copy(update={"outcome": "fail"})
    d = ScoringService.judge(m, ScoringService.options_for(m))
    c = next(o for o in d.options if o.is_chosen)
    assert c.option_type == "pass" and c.target_player_id is None and c.target_x == 105.0 and c.p_success < 0.5


def test_a_pass_carries_the_shot_chance_from_where_it_arrives():
    m = moment((80, 34), [(94, 34), (94, 6), (30, 34)], [(96, 50), (96, 20)], line="mid")
    by = {o.target_player_id: o for o in ScoringService.options_for(m) if o.option_type in ("pass", "ground_cross") and not o.into_run}
    central, wide, back = by["m0"], by["m1"], by["m2"]
    assert central.shot_chance > wide.shot_chance > 0 and back.shot_chance is None
    assert central.value_if_success >= min(SHOT_TAKEN * central.shot_chance, SHOT_VALUE_CAP)   # he may not get it off
    assert "shot" in describe(central.model_dump(), {"m0": "Kane"}) and "shot" not in describe(back.model_dump(), {"m2": "Dier"})


def test_a_throw_in_is_called_a_throw_in():
    m = moment((36, 0.5), [(45, 10), (30, 8)], [(50, 20), (70, 34)], line="mid").model_copy(update={"pattern": "from_throw_in"})
    opts = ScoringService.options_for(m)
    assert opts and all(o.direction == "throw_in" for o in opts if o.option_type == "pass")
    assert describe(opts[0].model_dump(), {"m0": "Kane", "m1": "Dier"}).startswith("Throw-in to ")
