"""ScoringService: scores every on-ball decision of a match. For each decision it builds the options the
player had (with chance of success, goal chance if it works and counter-attack risk if it fails), marks the
player's choice, the best and the safest good option, and gives the decision an importance."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.core.utils import (
    CROSS_ACCURACY,
    CROSS_BALL_SPEED,
    CROSS_WAIT_S,
    REACH_PACE,
    REACH_TURN_S,
    RUN_BACK_SPEED,
    RUN_MIN_SPEED,
    RUN_MIN_GAIN_M,
    RUN_SPACE_M,
    CLEAR_LENGTH_M,
    CLEAR_PRESSURE,
    CLEAR_ZONE_X,
    COUNTER_EVEN,
    COUNTER_RANGE,
    COUNTER_W,
    COUNTER_ZONE,
    CROSS_DROP_M,
    CROSS_ZONE,
    DECISION_TYPES,
    GOAL_Y,
    HALFWAY_X,
    HEIGHT_DEFAULT,
    KIND_GROUPS,
    KNOCKDOWN_M,
    LINE,
    LONG_ACCURACY,
    MAX_PASS_M,
    OFFSIDE_M,
    PC_CUT_SIGMA,
    PC_DT,
    PC_GRID_M,
    PC_LAMBDA,
    PC_MAX_S,
    PC_MAX_SPEED,
    PC_REACH_M,
    PC_REACT_S,
    PC_SIGMA,
    PASS_KINDS,
    PASS_ONLY,
    PITCH_X,
    PITCH_Y,
    SAFE_P,
    SET_PIECES,
    SHOT_RANGE_M,
    SHOT_TAKEN,
    SHOT_VALUE_CAP,
    SKILL_DEFAULT,
    TAKEN_FAR_M,
    SPEED_DEFAULT,
    STRENGTH_DEFAULT,
    WIDE,
    WIND_PUSH,
    clamp,
    closest_on_segment,
    dist,
    execution,
    flight_time,
    goal_distance,
    in_box,
    pass_direction,
    pass_lane,
    lead_s,
    pass_speed,
    played_with_head,
    seg_point_dist,
    skilled,
    good_edge,
    xg,
    xt,
)
from src.schemas.scoring import Moment, MomentPlayer, ScoredDecision, ScoredOption


class ScoringService:
    _surface = (None, None)      # (moment, control surface) of the last moment: one surface per moment

    @staticmethod
    def arrival(m: Moment, pts):
        """Spearman (2018): seconds every player (the ball carrier left out) needs to reach each point: he keeps
        running his way for PC_REACT_S, then runs straight there at PC_MAX_SPEED. -> (points x players, mate mask)"""
        team = [p for p in m.players if not p.is_actor]
        pos = np.array([p.xy for p in team], dtype=float)
        vel = np.array([(p.vx or 0.0, p.vy or 0.0) for p in team], dtype=float)
        start = pos + vel * PC_REACT_S
        far = np.linalg.norm(pts[:, None, :] - start[None, :, :], axis=2)
        return PC_REACT_S + far / PC_MAX_SPEED, np.array([p.mate for p in team])

    @staticmethod
    def pitch_control(m: Moment, pts, lofted=False):
        """Spearman (2018) pitch control: for a ball played from the carrier to each point (along the ground, or
        lofted: then it gets there after its flight time), the chance the team on the ball gets it under control
        there first (the rest is the other team's). A player is there by time t with a logistic chance around his
        arrival time and then controls the ball at rate PC_LAMBDA."""
        tau, mate = ScoringService.arrival(m, pts)
        length = np.linalg.norm(pts - np.array(m.ball), axis=1)
        ball_t = np.array([flight_time(d) if lofted else d / pass_speed(d) for d in length])
        k = math.pi / math.sqrt(3) / PC_SIGMA
        t = np.maximum(ball_t, tau.min(axis=1) - 3 * PC_SIGMA)          # nobody is there earlier than this
        att, left = np.zeros(len(pts)), np.ones(len(pts))
        for _ in range(int(PC_MAX_S / PC_DT)):
            there = 1 / (1 + np.exp(-k * (t[:, None] - tau)))
            rate = there.sum(axis=1)
            taken = left * (1 - np.exp(-PC_LAMBDA * PC_DT * rate))      # exact step, never more than is left
            att += taken * there[:, mate].sum(axis=1) / np.maximum(rate, 1e-9)
            left -= taken
            t = t + PC_DT
            if left.max() < 0.01:
                break
        return att / np.maximum(1 - left, 1e-9)

    @staticmethod
    def control(m: Moment):
        """The pitch control surface of a moment on a PC_GRID_M grid: (xs, ys, share of the team on the ball)."""
        if ScoringService._surface[0] is m:
            return ScoringService._surface[1]
        xs = np.arange(PC_GRID_M / 2, PITCH_X, PC_GRID_M)
        ys = np.arange(PC_GRID_M / 2, PITCH_Y, PC_GRID_M)
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        att = ScoringService.pitch_control(m, np.column_stack([gx.ravel(), gy.ravel()])).reshape(gx.shape)
        ScoringService._surface = (m, (xs, ys, att))
        return ScoringService._surface[1]

    @staticmethod
    def ours_at(m: Moment, spot) -> float:
        """Pitch control of the team on the ball at a spot (the grid cell it falls in)."""
        xs, ys, att = ScoringService.control(m)
        i = int(clamp(spot[0] // PC_GRID_M, 0, len(xs) - 1))
        j = int(clamp(spot[1] // PC_GRID_M, 0, len(ys) - 1))
        return float(att[i, j])

    @staticmethod
    def cut_out(m: Moment, b, tgt) -> float:
        """Chance an opponent gets a foot to the pass on its way: he must get within PC_REACH_M of a point of its
        path before the ball does; one already standing that close needs no reaction time."""
        lane = pass_lane(b, tgt)
        opp = [p for p in m.players if not p.mate]
        if not lane or not opp:
            return 0.0
        pts = np.array(lane)
        pos = np.array([p.xy for p in opp], dtype=float)
        gap = np.maximum(0.0, np.linalg.norm(pts[:, None, :] - pos[None, :, :], axis=2) - PC_REACH_M)
        tau = PC_REACT_S * np.minimum(1.0, gap / PC_REACH_M) + gap / PC_MAX_SPEED
        ball_t = np.linalg.norm(pts - np.array(b), axis=1) / pass_speed(dist(b, tgt))   # the whole pass is hit as hard
        there = 1 / (1 + np.exp(-math.pi / math.sqrt(3) / PC_CUT_SIGMA * (ball_t[:, None] - tau)))
        return float(1 - np.prod(1 - there.max(axis=0)))

    @staticmethod
    def p_ground(m: Moment, b, tgt, pressure) -> float:
        """Chance a ground pass from b to tgt comes off (Spearman pitch control): nobody cuts it out on the way,
        the team keeps it at the spot, and it is played well enough (less under pressure or blind)."""
        return (ScoringService.ours_at(m, tgt) * (1 - ScoringService.cut_out(m, b, tgt))
                * execution(b, tgt, pressure, m.facing))

    @staticmethod
    def p_air(m: Moment, mate: MomentPlayer, spot, accuracy) -> float:
        """Chance a lofted ball (a cross, a long ball) to spot comes off: it lands where meant (accuracy), the team
        gets there first while it is in the air (pitch control, nothing cuts it out on the way) and the team-mate
        wins the header against the nearest opponent (height, strength, who is closer); wind pushes it off."""
        ours = float(ScoringService.pitch_control(m, np.array([spot], dtype=float), lofted=True)[0])
        duel = clamp(1 + 0.1 * ScoringService.aerial_duel(m, mate, spot), 0.6, 1.3)
        return clamp(accuracy * ours * duel, 0.0, 1.0) * ScoringService.wind_factor(m, dist(m.ball, spot))

    @staticmethod
    def lost_at(m: Moment, spot):
        """Danger handed to the opponent if the ball is lost at spot: the spot's xT for them times their counter.
        The counter is the mean of two factors, each 0.6x to 2x: how much of the space between the spot and our
        goal they control (pitch control, from where everyone stands and runs) and how many of their players are
        on our side of the ball against ours there (keepers left out). Capped at 0.35."""
        zone = xt(PITCH_X - spot[0], PITCH_Y - spot[1])
        if not any(not p.mate for p in m.players):
            return round(min(0.35, zone), 4)
        xs, ys, att = ScoringService.control(m)
        depth, width = COUNTER_ZONE
        cells = att[(xs >= spot[0] - depth) & (xs <= spot[0] + PC_GRID_M)][:, np.abs(ys - spot[1]) <= width]
        theirs = 1 - (float(cells.mean()) if cells.size else ScoringService.ours_at(m, spot))
        lo, hi = COUNTER_RANGE
        space = lo * (hi / lo) ** theirs
        behind = sum(1 for p in m.players if p.mate and not p.is_keeper and not p.is_actor and p.xy[0] < spot[0])
        runners = sum(1 for p in m.players if not p.mate and not p.is_keeper and p.xy[0] < spot[0])
        count = clamp(math.exp(COUNTER_W * (runners - behind + COUNTER_EVEN)), lo, hi)
        return round(min(0.35, zone * math.sqrt(space * count)), 4)

    @staticmethod
    def build_moment(e, frame, players: dict, home_id: str, prev=None, wind_speed=0.0) -> Moment:
        """Event row + the freeze frame of that moment -> Moment, turned so the team on the ball attacks +x."""
        away = e.team_id != home_id
        turn = (lambda x, y: (PITCH_X - x, PITCH_Y - y)) if away else (lambda x, y: (x, y))

        def attr(pid, key, default):
            v = players.get(pid, {}).get(key)
            return default if v is None else v

        def line_of(pid):
            pos = attr(pid, "role", None) or attr(pid, "position", None)
            return LINE.get(pos, "mid")

        actor = frame[frame.player_id == e.player_id]
        facing = None
        if "facing_deg" in frame and len(actor) and actor.facing_deg.notna().iat[0]:
            facing = float(actor.facing_deg.iat[0])
            facing = (facing + 180) % 360 if away else facing
        end_x = e.end_x if e.end_x == e.end_x else e.x          # NaN check without pandas
        end_y = e.end_y if e.end_y == e.end_y else e.y
        pattern = getattr(e, "play_pattern", None) or "open_play"
        pattern = pattern if isinstance(pattern, str) else "open_play"
        return Moment(
            event_id=e.event_id, ball=turn(e.x, e.y), end=turn(end_x, end_y), chosen_type=e.type,
            pass_type=e.pass_type if isinstance(getattr(e, "pass_type", None), str) else None,
            outcome=str(e.outcome), recipient_id=getattr(e, "recipient_id", None) if isinstance(
                getattr(e, "recipient_id", None), str) else None,
            open_play=pattern not in SET_PIECES or pattern == "from_free_kick", pattern=pattern,
            header=played_with_head(e, prev), facing=facing,
            technique=attr(e.player_id, "technique", SKILL_DEFAULT), carrier_line=line_of(e.player_id),
            wind_speed=wind_speed,
            players=[MomentPlayer(
                player_id=r.player_id, xy=turn(r.x, r.y), mate=r.team_id == e.team_id,
                is_keeper=bool(getattr(r, "is_keeper", False)) or line_of(r.player_id) == "gk",
                is_actor=r.player_id == e.player_id,
                technique=attr(r.player_id, "technique", SKILL_DEFAULT),
                defending=attr(r.player_id, "defending", SKILL_DEFAULT),
                max_speed=attr(r.player_id, "max_speed", SPEED_DEFAULT),
                height_cm=attr(r.player_id, "height_cm", HEIGHT_DEFAULT),
                strength=attr(r.player_id, "strength", STRENGTH_DEFAULT),
                line=line_of(r.player_id), role=attr(r.player_id, "role", "") or "",
                vx=ScoringService.speed_part(getattr(r, "vx", None), away),
                vy=ScoringService.speed_part(getattr(r, "vy", None), away))
                for r in frame.itertuples()])

    @staticmethod
    def speed_part(v, away: bool) -> float | None:
        """One velocity component of a frame row in the attacking team's frame (None when not recorded)."""
        if v is None or v != v:
            return None
        return -float(v) if away else float(v)

    @staticmethod
    def aerial_duel(m: Moment, mate: MomentPlayer, spot):
        """The team-mate's edge over the opponent contesting a ball that drops at spot: taller, stronger and
        closer players win more headers; a keeper uses his hands in his own box. (No dice in the generator.)"""
        rival = min((p for p in m.players if not p.mate), key=lambda p: dist(p.xy, spot))

        def reach(p):
            return p.height_cm + 12 * p.strength + (30 if p.is_keeper and in_box(spot) else 0)
        gap = dist(rival.xy, spot) - dist(mate.xy, spot)
        return (reach(mate) - reach(rival)) / 10 + 0.2 * clamp(gap, -5, 5)

    @staticmethod
    def wind_factor(m: Moment, length):
        drift = WIND_PUSH * m.wind_speed * flight_time(length)
        return clamp(1 - 0.03 * drift, 0.75, 1.0)

    @staticmethod
    # ---------- options ----------
    def option(kind, tgt, ps, value, risk, target_id=None, offside=False, direction=None,
               into_run=False, shot_chance=None, into_space=False) -> ScoredOption:
        ps = round(0.0 if offside else ps, 4)
        return ScoredOption(option_type=kind, direction=direction, target_player_id=target_id,
                            target_x=round(tgt[0], 1), target_y=round(tgt[1], 1), p_success=ps,
                            value_if_success=round(value, 4), risk_if_fail=round(risk, 4),
                            ev=round(ps * value - (1 - ps) * risk, 4),
                            offside=offside, into_run=into_run, shot_chance=shot_chance,
                            into_space=into_space)

    @staticmethod
    def reach_s(mate: MomentPlayer, spot) -> float:
        """Seconds a team-mate needs to get to a spot: running at REACH_PACE of his top speed, plus up to
        REACH_TURN_S when he is running the other way."""
        d = dist(mate.xy, spot)
        turn = 0.0
        if d > 0.1 and mate.vx is not None and mate.vy is not None and math.hypot(mate.vx, mate.vy) > 0.5:
            cos = (mate.vx * (spot[0] - mate.xy[0]) + mate.vy * (spot[1] - mate.xy[1])) / (math.hypot(mate.vx, mate.vy) * d)
            turn = REACH_TURN_S * (1 - cos) / 2
        return d / (REACH_PACE * mate.max_speed) + turn

    @staticmethod
    def first_there(m: Moment, mate: MomentPlayer, spot) -> bool:
        """True when no other team-mate (the keeper and the ball carrier left out) gets to the spot sooner: a ball
        played into space is his only then, so two team-mates standing together do not both get it."""
        mine = ScoringService.reach_s(mate, spot)
        return all(ScoringService.reach_s(p, spot) >= mine for p in m.players
                   if p.mate and not p.is_actor and not p.is_keeper and p is not mate)

    @staticmethod
    def run_spot(mate: MomentPlayer, b):
        """Where a running team-mate meets a pass from b, or None when he is not running."""
        if mate.vx is None or mate.vy is None or math.hypot(mate.vx, mate.vy) < RUN_MIN_SPEED:
            return None
        lead = lead_s(b, mate.xy, mate.vx, mate.vy)
        spot = (clamp(mate.xy[0] + mate.vx * lead, 0.5, PITCH_X - 0.5),
                clamp(mate.xy[1] + mate.vy * lead, 0.5, PITCH_Y - 0.5))
        return spot if dist(spot, mate.xy) >= RUN_MIN_GAIN_M else None

    @staticmethod
    def space_spot(mate: MomentPlayer, b, run):
        """A ball into the space RUN_SPACE_M beyond where his run meets the pass, or None when he cannot sprint
        onto it by the time the ball gets there (or just after)."""
        speed = math.hypot(mate.vx, mate.vy)
        spot = (clamp(run[0] + mate.vx / speed * RUN_SPACE_M, 0.5, PITCH_X - 0.5),
                clamp(run[1] + mate.vy / speed * RUN_SPACE_M, 0.5, PITCH_Y - 0.5))
        d = dist(b, spot)
        if dist(spot, run) < RUN_MIN_GAIN_M or ScoringService.reach_s(mate, spot) > d / pass_speed(d) + CROSS_WAIT_S:
            return None
        return spot

    @staticmethod
    def pass_option(m: Moment, b, mate: MomentPlayer, tgt, opp_xy, keeper, pressure, line, wide_final_third,
                    into_run=False, into_space=False):
        """A pass to tgt (where the team-mate is, or where his run takes him). Offside is judged where he stands.
        Within shot range the pass also carries the chance of a first-time shot from tgt (angle, distance, who is
        in the way, the keeper, the pressure there); it is worth at least that chance times SHOT_TAKEN (he may not
        get the shot off), capped at SHOT_VALUE_CAP."""
        ps = ScoringService.p_ground(m, b, tgt, pressure)
        if m.header:
            ps *= 0.6
        ps = skilled(ps, m.technique)
        offside = m.open_play and mate.xy[0] > line + OFFSIDE_M
        cutter = min(opp_xy, key=lambda o: seg_point_dist(o, b, tgt))
        risk = ScoringService.lost_at(m, closest_on_segment(cutter, b, tgt))
        kind = "ground_cross" if wide_final_third and in_box(tgt) and not m.header else "pass"
        shot = None
        if goal_distance(tgt) < SHOT_RANGE_M:
            there = max(0.0, 1 - min(dist(o, tgt) for o in opp_xy) / 5)
            shot = xg(tgt[0], tgt[1], there, False, [o for o in opp_xy if o != keeper], keeper)[0]
        value = max(xt(*tgt), min(SHOT_TAKEN * (shot or 0.0), SHOT_VALUE_CAP))
        return ScoringService.option(kind, tgt, ps, value, risk, mate.player_id, offside=offside,
                                     direction="throw_in" if m.pattern == "from_throw_in" else pass_direction(b, tgt, line),
                                     into_run=into_run, shot_chance=shot, into_space=into_space)

    @staticmethod
    def lofted_options(m: Moment, b, opp_xy, keeper, line, pressure):
        """Crosses into the box and long balls over the press."""
        wide_final_third = b[0] > CROSS_ZONE[0] and abs(b[1] - GOAL_Y) > CROSS_ZONE[1]
        crossing = (wide_final_third and m.pattern == "open_play") or m.pattern in ("from_corner", "from_free_kick")
        long_passer = m.carrier_line in ("gk", "def") or (m.carrier_line == "mid" and pressure > 0.3)
        blockers = [p.xy for p in m.players if not p.mate and not p.is_keeper]
        out = []
        for mate in (p for p in m.players if p.mate and not p.is_actor and not p.is_keeper):
            offside = m.open_play and mate.xy[0] > line + OFFSIDE_M
            runner = mate.line == "fwd" or mate.role == "AM"
            # into the box: to the team-mate; to a runner: in front of him (fixed 8.5 m, not a dice roll), only
            # when he is not running back, gets there before the ball (or just after) and no team-mate is sooner
            spot = mate.xy if in_box(mate.xy) else (PITCH_X - CROSS_DROP_M, clamp(mate.xy[1], 24, 44))
            his = spot == mate.xy or ((mate.vx or 0.0) >= -RUN_BACK_SPEED
                                      and ScoringService.reach_s(mate, spot) <= dist(b, spot) / CROSS_BALL_SPEED + CROSS_WAIT_S
                                      and ScoringService.first_there(m, mate, spot))
            if crossing and his and (in_box(mate.xy) or (runner and mate.xy[0] > PITCH_X - 30)):
                chance = xg(spot[0], spot[1], 0.3, header=True, blockers=blockers, keeper=keeper)[0]
                ps = clamp(skilled(ScoringService.p_air(m, mate, spot, CROSS_ACCURACY), m.technique), 0.04, 0.7)
                out.append(ScoringService.option("cross", spot, ps, max(xt(*spot), chance), ScoringService.lost_at(m, spot),
                                  mate.player_id, offside))
            if (long_passer and b[0] < 55 and m.pattern not in ("from_corner", "from_throw_in")
                    and (mate.line == "fwd" or mate.role in WIDE) and dist(b, mate.xy) > 28):
                ps = clamp(skilled(ScoringService.p_air(m, mate, mate.xy, LONG_ACCURACY), m.technique), 0.08, 0.85)
                out.append(ScoringService.option("long_ball", mate.xy, ps, xt(*mate.xy), ScoringService.lost_at(m, mate.xy),
                                  mate.player_id, offside))
        return out

    @staticmethod
    def options_for(m: Moment) -> list[ScoredOption]:
        """Every option of the ball carrier: passes (ground crosses included), crosses, long balls, shot,
        dribbles. A ball played with the head allows only knock-downs and a headed shot."""
        b = m.ball
        opp = [p for p in m.players if not p.mate]
        if not opp:
            return []
        opp_xy = [p.xy for p in opp]
        keeper = next((p.xy for p in opp if p.is_keeper), None)
        pressure = max(0.0, 1 - min(dist(o, b) for o in opp_xy) / 5)
        xs = sorted((o[0] for o in opp_xy), reverse=True)
        line = max(xs[1] if len(xs) > 1 else xs[0], b[0], HALFWAY_X)   # second-last defender or the ball
        wide_final_third = b[0] > CROSS_ZONE[0] and abs(b[1] - GOAL_Y) > CROSS_ZONE[1]
        opts = []
        if m.pattern == "from_penalty":
            return [ScoringService.option("shot", (PITCH_X, GOAL_Y), 0.76, 1.0, 0.01)]
        reach = KNOCKDOWN_M if m.header else MAX_PASS_M
        for mate in (p for p in m.players if p.mate and not p.is_actor):
            if dist(b, mate.xy) > reach or m.pattern == "from_corner":
                continue
            opts.append(ScoringService.pass_option(m, b, mate, mate.xy, opp_xy, keeper, pressure, line, wide_final_third))
            run = ScoringService.run_spot(mate, b)       # the same pass played into his run
            if run and not m.header and dist(b, run) <= reach and ScoringService.first_there(m, mate, run):
                opts.append(ScoringService.pass_option(m, b, mate, run, opp_xy, keeper, pressure, line, wide_final_third,
                                                       into_run=True))
                space = ScoringService.space_spot(mate, b, run)      # or further on, into the space he sprints onto
                if space and dist(b, space) <= reach and ScoringService.first_there(m, mate, space):
                    opts.append(ScoringService.pass_option(m, b, mate, space, opp_xy, keeper, pressure, line,
                                                           wide_final_third, into_run=True, into_space=True))
        if not m.header:
            opts += ScoringService.lofted_options(m, b, opp_xy, keeper, line, pressure)
        if m.pattern not in PASS_ONLY and goal_distance(b) < SHOT_RANGE_M:
            blockers = [p.xy for p in opp if not p.is_keeper]
            g = xg(b[0], b[1], pressure, m.header, blockers, keeper)[0]
            if m.pattern == "from_free_kick":
                g = round(g * 0.6, 4)
            opts.append(ScoringService.option("shot", (PITCH_X, GOAL_Y), g, 1.0, 0.01))
        if (m.pattern not in PASS_ONLY and m.pattern != "from_free_kick" and m.carrier_line != "gk"
                and not m.header):
            here_risk = ScoringService.lost_at(m, b)
            edge, rival = 0.0, None
            carrier = next((p for p in m.players if p.is_actor), None)
            if pressure > 0.3:
                rival = min(opp, key=lambda p: dist(p.xy, b))
                if carrier:
                    edge = carrier.technique - rival.defending + 0.1 * (carrier.max_speed - rival.max_speed)
            kind = "dribble" if pressure > 0.3 else "carry"
            for dy in (-7, 0, 7):
                tgt = (min(b[0] + 8, PITCH_X - 1), clamp(b[1] + dy, 1, PITCH_Y - 1))
                crowd = sum(1 for o in opp_xy if dist(o, tgt) < 6)
                ps = 0.82 - 0.55 * pressure - 0.09 * crowd - (0.45 if in_box(tgt) else 0) + 0.15 * edge
                opts.append(ScoringService.option(kind, tgt, clamp(ps, 0.08, 0.9), xt(*tgt), here_risk))
        opts += ScoringService.defensive_options(m, b, opp_xy, pressure)
        same = ScoringService.matching(m, opts)
        if opts and (not same or min(dist((o.target_x, o.target_y), m.end) for o in same) > TAKEN_FAR_M):
            opts.append(ScoringService.taken(m, b, opp, keeper, pressure))
        return opts

    @staticmethod
    def defensive_options(m: Moment, b, opp_xy, pressure) -> list[ScoredOption]:
        """Under pressure: hold the ball and shield it; in the own third also clear it upfield or into touch."""
        if m.pattern != "open_play" or m.carrier_line == "gk":
            return []
        out = []
        here_risk = ScoringService.lost_at(m, b)
        if pressure > 0.3 and not m.header:
            ps = clamp(skilled(clamp(0.85 - 0.6 * pressure, 0.2, 0.9), m.technique), 0.15, 0.92)
            out.append(ScoringService.option("hold", b, ps, xt(*b), here_risk))
        if b[0] < CLEAR_ZONE_X and pressure >= CLEAR_PRESSURE:
            side = 6.0 if b[1] < GOAL_Y else PITCH_Y - 6.0              # towards his own touchline
            far = (min(b[0] + CLEAR_LENGTH_M, PITCH_X - 20), side)
            crowd = sum(1 for o in opp_xy if dist(o, b) < 2.5)
            ps = clamp(0.92 - 0.25 * pressure - 0.1 * crowd - (0.15 if m.header else 0), 0.4, 0.95)
            # upfield the ball is a fifty-fifty: half the threat of the spot, and the opponent may win it back there
            value = 0.5 * xt(*far) - 0.5 * min(0.35, xt(PITCH_X - far[0], PITCH_Y - far[1]))
            out.append(ScoringService.option("clearance", far, ps, value, here_risk))
            touch = (clamp(b[0] + 12, 1, PITCH_X - 1), 0.0 if b[1] < GOAL_Y else PITCH_Y)
            throw = min(0.35, xt(PITCH_X - touch[0], PITCH_Y - touch[1]))   # their throw-in there
            out.append(ScoringService.option("clear_out", touch, clamp(ps + 0.05, 0.45, 0.97), -0.5 * throw, here_risk))
        return out

    @staticmethod
    def taken(m: Moment, b, opp, keeper, pressure) -> ScoredOption:
        """The action the player took when no option stands for it (a shot from far out, a pass beyond the
        usual range, a header carry): scored with the same formulas, so its regret is still fair."""
        kind = ScoringService.chosen_kind(m)
        if kind == "shot":
            g = xg(b[0], b[1], pressure, m.header, [p.xy for p in opp if not p.is_keeper], keeper)[0]
            return ScoringService.option("shot", (PITCH_X, GOAL_Y), g, 1.0, 0.01)
        tgt = (clamp(m.end[0], 0, PITCH_X), clamp(m.end[1], 0, PITCH_Y))
        if kind == "clearance":
            return ScoringService.option("clearance", tgt, 0.8, 0.5 * xt(*tgt), ScoringService.lost_at(m, b))
        if kind in ("dribble", "carry"):
            ps = clamp(0.82 - 0.55 * pressure - (0.45 if in_box(tgt) else 0), 0.08, 0.9)
            return ScoringService.option(kind, tgt, ps, xt(*tgt), ScoringService.lost_at(m, b))
        mates = [p for p in m.players if p.mate and not p.is_actor]
        if kind in ("cross", "long_ball") and mates:            # in the air: nothing cuts it out on the way
            mate = next((p for p in mates if p.player_id == m.recipient_id), None) or min(mates, key=lambda p: dist(p.xy, tgt))
            ps = ScoringService.p_air(m, mate, tgt, CROSS_ACCURACY if kind == "cross" else LONG_ACCURACY)
        else:
            ps = ScoringService.p_ground(m, b, tgt, pressure)
        ps = skilled(ps, m.technique)
        return ScoringService.option(kind, tgt, ps, xt(*tgt), ScoringService.lost_at(m, tgt), m.recipient_id)

    @staticmethod
    # ---------- judging the real choice ----------
    def chosen_kind(m: Moment) -> str:
        """The option type of what the player did: a pass row marked as a cross or long ball is that option."""
        if m.chosen_type == "pass":
            return PASS_KINDS.get(m.pass_type or "", "pass")
        return m.chosen_type

    @staticmethod
    def matching(m: Moment, opts) -> list:
        """Options that stand for the player's action: same kind (else a related one, a low cross for a pass)
        and the known receiver when it has one."""
        kind = ScoringService.chosen_kind(m)
        for kinds in ({kind}, KIND_GROUPS.get(kind, {kind})):
            same = [o for o in opts if o.option_type in kinds]
            if m.recipient_id and kind != "shot":
                same = ([o for o in same if o.target_player_id == m.recipient_id]
                        or [o for o in same if o.target_player_id is None])
            if same:
                return same
        return []

    @staticmethod
    def pick_chosen(m: Moment, opts):
        """The option the player actually took: the one of his kind (and receiver) closest to where the ball went."""
        return min(ScoringService.matching(m, opts) or opts, key=lambda o: dist((o.target_x, o.target_y), m.end))

    @staticmethod
    def delta_value(m: Moment) -> float:
        """Value of where the ball ended up minus the value of where it started (as in the generator)."""
        if m.chosen_type == "shot":
            return round((1.0 if m.outcome == "goal" else 0.0) - xt(*m.ball), 4)
        after = xt(*m.end) if m.outcome == "success" else -xt(PITCH_X - m.end[0], PITCH_Y - m.end[1])
        return round(after - xt(*m.ball), 4)

    @staticmethod
    def judge(m: Moment, opts: list[ScoredOption]) -> ScoredDecision:
        chosen = ScoringService.pick_chosen(m, opts)
        best = max(opts, key=lambda o: o.ev)
        safe = [o for o in opts if o.p_success >= SAFE_P and o.ev >= 0]   # likely to come off and worth playing
        safe_best = max(safe, key=lambda o: o.ev) if safe else None
        spread = best.ev - min(o.ev for o in opts)
        for o in opts:
            o.is_chosen, o.is_best, o.is_safe_best = o is chosen, o is best, o is safe_best
        return ScoredDecision(
            event_id=m.event_id, options=opts, chosen_ev=chosen.ev, best_ev=best.ev,
            safe_best_ev=safe_best.ev if safe_best else None, regret=round(best.ev - chosen.ev, 4),
            regret_rel=round((best.ev - chosen.ev) / spread, 3) if spread > 1e-4 else 0.0,
            delta_value=ScoringService.delta_value(m))

    def score(self, events: pd.DataFrame, frames: pd.DataFrame, players: dict, home_id: str,
              wind_speed: float = 0.0) -> pd.DataFrame:
        """events (with score_home / score_away) + freeze frames -> the same events with options (list of
        dicts, option_id like v_00012_o03), chosen_ev, best_ev, safe_best_ev, regret, regret_rel,
        delta_value and importance. Rows that are no decision, or have no frame, keep empty scores."""
        by_event = {k: g for k, g in frames.groupby("event_id")}
        out, prev = [], None
        for e in events.itertuples():
            row = e._asdict()
            row.pop("Index", None)
            frame = by_event.get(e.event_id)
            if e.type in DECISION_TYPES and frame is not None:
                m = ScoringService.build_moment(e, frame, players, home_id, prev=prev, wind_speed=wind_speed)
                opts = ScoringService.options_for(m)
                if opts:
                    dec = ScoringService.judge(m, opts)
                    row.update(dec.model_dump(include={"chosen_ev", "best_ev", "safe_best_ev", "regret",
                                                       "regret_rel", "delta_value"}))
                    row["options"] = [{"option_id": f"{e.event_id}_o{i:02d}",
                                       **self.on_pitch(o.model_dump(), e.team_id != home_id)}
                                      for i, o in enumerate(dec.options, 1)]
                    row["importance"] = self.importance(row)
            out.append(row)
            prev = e
        return pd.DataFrame(out)

    @staticmethod
    def on_pitch(o: dict, away: bool) -> dict:
        """Option targets are worked out with the team on the ball attacking +x; stored like every other
        position (home attacks +x), so the away team's targets are turned back."""
        if away:
            o["target_x"], o["target_y"] = round(PITCH_X - o["target_x"], 1), round(PITCH_Y - o["target_y"], 1)
        return o

    @staticmethod
    def score_state(events: pd.DataFrame, home_id: str) -> pd.DataFrame:
        """The score before each event, from the goals among the events."""
        goal = events.outcome.eq("goal")
        home = (goal & events.team_id.eq(home_id)).cumsum().shift(fill_value=0)
        away = (goal & ~events.team_id.eq(home_id)).cumsum().shift(fill_value=0)
        return events.assign(score_home=home.astype(int), score_away=away.astype(int))

    @staticmethod
    def importance(row: dict) -> float:
        """How much one decision mattered: the value it changed, and the regret of a mistake or the edge of a good
        decision (whichever is bigger), weighted up in a close game and after the 60th minute."""
        gap = abs(row["score_home"] - row["score_away"])
        w_score = 1.5 if gap == 0 else 1.2 if gap == 1 else 0.7
        w_time = 1 + max(0, row["minute"] - 60) / 30
        evs = [o["ev"] for o in row["options"]]
        spread = max(evs) - min(evs)
        edge = good_edge(row)
        good = 4 * edge + (0.45 * edge / spread if spread > 1e-4 else 0.0)   # edge/spread rarely nears 1, regret_rel does
        return round(abs(row["delta_value"]) * w_score * w_time + max(4 * row["regret"] + 0.3 * row["regret_rel"], good), 4)


scoring = ScoringService()
