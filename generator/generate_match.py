"""Synthetic football match generator for Decision Lens.

Produces one fully synthetic match with:
  match_meta.json        teams, fictional squads and benches, decision profiles, alert thresholds
  events.csv             one row per action: passes, crosses, shots, set pieces, fouls, cards,
                         offsides, substitutions, goals
  freeze_frames.csv      positions + velocities of every player on the pitch at every event
  decision_options.csv   every option the ball carrier had, with model values
  critical_decisions.csv top decisions ranked by criticality, incl. the decisions behind each goal
  tracking.csv.gz        ball + players at 25 Hz while the ball is in play (gzip-compressed CSV)
  player_alerts.csv      overlay triggers: sprints, top speeds, distance milestones
  player_stats.csv       per-player passing, shooting, physical and decision summary
  with --metrica also the same match in Metrica Sports' raw format:
  SYN-xxxx_RawTrackingData_Home_Team.csv, ..._Away_Team.csv, SYN-xxxx_RawEventsData.csv

Players move continuously with speed and acceleration limits and cannot overlap, so velocities,
distances and sprints come from the movement itself. The ball rolls, flies, swerves, bounces and
drifts in the match wind. Duels depend on each player's height, strength, technique and defending,
and teams change their approach with the score and their pressing height. If xt_grid.json (made by learn_xt.py) sits next to
this script, expected threat is read from that learned grid.

If shape_table.json sits next to this script, players take their open-play
positions from that learned table and keep following the ball while it moves.

Usage: python3 generate_match.py --seed 7 --out ./output [--metrica]
"""
import argparse
import csv
import gzip
import json
import math
import os
import random

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_Y = PITCH_Y / 2
HALFWAY = PITCH_X / 2

# Home positions for a team attacking left -> right (x, y in metres). Each team picks one shape.
FORMATIONS = {
    "4-3-3": [("GK", 5, 34), ("RB", 25, 58), ("CB", 20, 42), ("CB", 20, 26), ("LB", 25, 10),
              ("CM", 42, 46), ("DM", 36, 34), ("CM", 42, 22),
              ("RW", 62, 60), ("ST", 68, 34), ("LW", 62, 8)],
    "4-4-2": [("GK", 5, 34), ("RB", 25, 58), ("CB", 20, 42), ("CB", 20, 26), ("LB", 25, 10),
              ("RM", 48, 60), ("CM", 40, 42), ("CM", 40, 26), ("LM", 48, 8),
              ("ST", 66, 41), ("ST", 66, 27)],
    "4-2-3-1": [("GK", 5, 34), ("RB", 25, 58), ("CB", 20, 42), ("CB", 20, 26), ("LB", 25, 10),
                ("DM", 36, 42), ("DM", 36, 26), ("RW", 58, 58), ("AM", 52, 34), ("LW", 58, 10),
                ("ST", 68, 34)],
}
# Shapes a team switches to after a red card, keyed by the number of outfield players left.
SHORT_HANDED = {
    9: ("4-4-1", [("RB", 24, 56), ("CB", 19, 42), ("CB", 19, 26), ("LB", 24, 12),
                  ("RM", 44, 58), ("CM", 38, 41), ("CM", 38, 27), ("LM", 44, 10), ("ST", 62, 34)]),
    8: ("4-3-1", [("RB", 23, 54), ("CB", 18, 41), ("CB", 18, 27), ("LB", 23, 14),
                  ("CM", 38, 48), ("DM", 34, 34), ("CM", 38, 20), ("ST", 60, 34)]),
}
LINE = {"GK": "gk", "RB": "def", "CB": "def", "LB": "def", "DM": "mid", "CM": "mid", "AM": "mid",
        "RM": "mid", "LM": "mid", "RW": "fwd", "ST": "fwd", "LW": "fwd"}
WIDE = {"RW", "LW", "RM", "LM"}
MAX_SPEED = {"gk": 6.5, "def": 8.6, "mid": 8.5, "fwd": 9.1}  # m/s
TAU_S = 3.0          # players close the gap to their target in about this many seconds
DRIFT = (0.95, 1.5)  # personal drift around the tactical target: (memory, step size in m)
JOG_MS = 1.8         # players never move slower than this while away from their target
RESPONSE_S = (0.5, 0.8)   # s a player takes to reach the speed and direction he wants (no snap stops or turns):
                          # (defending, attacking side)
IDLE = (4.0, 0.5)    # small restless wandering around the target: (time scale in s, size in m)
KEEPER_WALK = 1.0    # a keeper shuffles across his goal at walking pace
KEEPER_DRIFT = 0.2   # keepers wander this fraction of an outfield player's drift
P_PASS_BASE = 2.35   # intercept of the pass-completion model
# pass model: length, how much time defenders have to step into the lane, pressure on the passer,
# whether the passer can see the pass (body shape) and how tightly the receiver is marked
P_PASS_LEN = -0.055   # per metre of pass
P_PASS_LANE = 0.32    # per metre a defender would still be short of the ball's path (up to 6 m)
P_PASS_MARK = 0.22    # per metre between the receiver and his marker (up to 8 m)
P_PASS_PRESS = 0.6    # log-odds lost under full pressure
P_PASS_BLIND = 0.9    # log-odds lost for a pass straight behind the passer's back
LANE_REACH = 0.5      # a defender covers this much without moving (outstretched leg)
LANE_RUN = 3.5        # m/s a defender closes towards the lane once the ball is played
LANE_REACT = 0.25     # s before he reacts
TECH_PASS = 1.6      # log-odds added to a pass, cross or long ball per unit of technique above 0.5
SAFE_P = 0.7         # an option is "safe" from this chance of success; the safest good option is
                     # the highest-scoring safe one
CROSS_ZONE = (55, 8)   # crosses are offered beyond this x, at least this far from the middle of the pitch
FIRST_TOUCH_M = 4.0         # m at most a player in open play moves with the ball before he plays it
FIRST_TOUCH_MS = 2.5        # m/s he moves with it meanwhile
HOLD_S = 0.9                # typical seconds on the ball in open play (Metrica sample games: 1.3-1.6 s)
FIRST_TOUCH_AHEAD = 0.3     # how much of that move goes towards goal (the rest: away from the nearest opponent)
NET_DEPTH = 1.0             # m behind the goal line where a goal's ball comes to rest
BACK_DEEPEST = PITCH_X - 7   # attack-frame x: a back line drops no deeper than 7 m from its own goal
BUILD_UP_DEPTH = 14          # m from their own goal: the attacking back line stays at least this far out
CB_SPLIT = 1.7               # centre-backs spread this much wider than their home spot in the build-up
BACK_C = 45                  # defending back line (attack frame): 0.5 * ball x + this, before the press shift
ATT_GAP = 22                 # m the attacking back line stays behind the ball
FB_BEHIND = 10               # m behind the ball an attacking full-back gets to once the ball is past 30 m
FB_WIDE = 1.0                # and this far out compared with his home spot
MARK_GAP = 1.0               # m goal-side a centre-back marks a centre-forward who drops in front of the line
MISCONTROL = (3.0, 0.35)      # an opponent this close (m) to a pass's receiver nicks it off his first touch this often
WIDE_X = 80                  # attack-frame x up to which the flank bias applies
OUT_P = 0.3                 # share of other lost passes that run out for a throw-in
WIDE_LANE = 13.6             # m from the middle of the pitch where the flanks start (Metrica-style thirds of the width)
SHORT_PREF = 0.02            # choice bias against a ground pass, per 10 m beyond SHORT_FROM
SHORT_FROM = 20
WIDE_BIAS = 0.03             # choice bias for a pass out to the flank before the final third
LINE_SPACING = 10.5          # m between neighbours in a defending back line
ONSIDE_MARGIN = 4.0    # attackers try to stay this far behind the last defender (less = more offsides)
OFFSIDE_SEEN = 0.8     # how often the passer sees that the team-mate is offside (Metrica sample games: ~1 offside a match)
OFFSIDE_CLEAR_M = 1.0  # ...always, when he is this far beyond the line
RUN_BEHIND = 0.07      # chance a forward times a run in behind the defence at each decision
RUN_S = 2.5            # s a run in behind lasts, at RUN_PACE of his top speed
RUN_PACE = 0.8
RUN_TO_MAX_S = 5.0     # s more a player may need to get to a loose ball before it is simply his
WIDE_PAST_M = 3.0      # m past the goal line where a shot that misses ends
RECEIVE_M = 1.0        # m: a receiver farther than this from the ball when it arrives runs onto it
RUN_FROM_X = 40         # m: runs in behind start once the ball is this far up the pitch
RUN_CHECK_M = -1.0     # m past the last defender (before it: negative) at which a run with no ball for him is checked
RUN_DEPTH = (6, 14)    # m behind the last defender the run aims for
RUN_PASS_V = 4.0       # m/s towards goal: a team-mate this fast gets the ball played into his run...
RUN_PASS = 0.9         # ...which needs timing too
RUN_LEAD_MAX = 3.0     # s: aimed where he will be when the pass gets there, at most this late
# shot model (xG): distance, how wide the goal looks, how much of it defenders hide, where the keeper is
XG_BASE = -0.04        # intercept (log-odds); fitted to StatsBomb open-data zone averages
XG_DIST = -0.025       # per metre from the centre of the goal
XG_ANGLE = 1.895       # per unit of log(angle the goal mouth covers, radians)
XG_SHADOW = 1.0        # log-odds lost when defenders hide the whole goal mouth
XG_KEEPER = 1.64       # log-odds gained when the keeper is 4 m or more off the line to goal
XG_PRESSURE = 0.42     # log-odds lost under full pressure (an opponent right on the shooter)
XG_HEADER = 1.275      # log-odds lost for a header
BLOCK_REACH = 0.6      # m: a defender this close to the ball's path can block it
GOAL_POINTS = 15       # points across the goal mouth used to measure how much of it is hidden
# counter-attack danger: losing the ball is worse when few team-mates are goal-side of it
COUNTER_W = 0.3        # log-change of the danger per extra attacker or missing defender
COUNTER_EVEN = 3.0     # (runners - defenders behind the ball) at which the danger is the plain zone value
COUNTER_RANGE = (0.6, 2.0)
COUNTER_Q = (0.8, 1.2)  # how much one player counts in the counter, by quality
COUNTER_WIN = 0.3       # first-pass quality of the player who wins the ball: +-15% at most


def counter_weight(skill, max_speed):
    """How many 'average players' one player is worth in a counter-attack: skill (technique for
    the attackers, defending for us) and pace."""
    return clamp(1 + 0.8 * (skill - 0.5) + 0.08 * (max_speed - 8.5), *COUNTER_Q)
ACCEL, DECEL = (3.0, 2.5), (3.0, 2.5)  # m/s^2: how fast a player usually speeds up and slows down (defending, attacking)
ACCEL_MAX, DECEL_MAX = 4.0, 4.5  # m/s^2: all out, for the man going for the ball
BENCH_SIZE = 7
SUBS_PER_TEAM = 3
MAX_SUBS = 5          # planned changes plus injuries
FATIGUE = 0.07        # a player who has run about 10.5 km has lost this share of his top speed

# Fixed squads: every team keeps the same 18 players (and attributes) in every match.
LEAGUE_SEED = 2026
SQUAD_ROLES = ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "AM", "RW", "LW", "ST",
               "ST", "GK", "CB", "LB", "CM", "RW"]
# which squad positions can fill a formation slot, best first
FITS = {"GK": ["GK"], "RB": ["RB", "LB", "CB"], "LB": ["LB", "RB", "CB"], "CB": ["CB", "DM", "RB", "LB"],
        "DM": ["DM", "CM"], "CM": ["CM", "DM", "AM"], "AM": ["AM", "CM", "RW", "LW"],
        "RM": ["RW", "LW", "CM"], "LM": ["LW", "RW", "CM"], "RW": ["RW", "LW", "AM"],
        "LW": ["LW", "RW", "AM"], "ST": ["ST", "AM", "RW", "LW"]}

# ball physics
GRAVITY = 9.81
ROLL_KEEP = 0.45      # a ground pass arrives with this share of its starting speed (rolling friction)
AIR_KEEP = 0.75       # a lofted ball keeps this share of its horizontal speed in the air (drag)
BOUNCE = 0.45         # share of its vertical speed the ball keeps when it bounces
WIND_MAX = 7.0        # m/s; each match draws a wind up to this strength
WIND_PUSH = 0.22      # a lofted ball drifts with this share of the wind speed
PLAYER_RADIUS = 0.45  # players closer than twice this are pushed apart (bodies do not overlap)

# tactics: how high each team presses, and how the score changes a team's approach
PRESS_SHIFT = {"low": -3.0, "mid": 0.0, "high": 5.0}   # metres the defensive block moves up the pitch
SCORE_SHIFT = 3.0   # metres it moves up when chasing the game (down when protecting a lead)
CORNER_FROM_CROSS = 0.18  # share of failed crosses near the byline that go out for a corner
BYLINE_P = 1.0           # share of other failed passes ending this deep that roll out for a goal kick
BYLINE_X = 22            # m from the byline
GOAL_KICK_SHAPE_X = 45  # m: where the teams line up for a goal kick, as if the ball were there
GOAL_KICK_LONG = 0.05    # keepers usually kick a goal kick long (Metrica sample games: ~70% over 45 m)
HEAD_ON = 0.5            # a long ball that arrives is often headed on first time
CORNER_FROM_SHOT = 0.38   # share of parried or blocked shots that go out for a corner
SECOND_BALL_KEEP = 0.45   # share of headed clearances the attacking team wins back
FOUL_ON_TACKLE = (0.36, 0.18)   # chance a won tackle is a foul: outside / inside the defender's own box

# shots that miss: share of each ending (a goal is decided by xG first)
BOX_PASS = 0.8         # passes into the box are harder (crowd)
CLOSE_PASS = 0.75      # and harder still to a team-mate close to goal
CLOSE_RANGE = 11.0     # metres from the centre of the goal
MISTAKE_TEMP = 0.03    # mistakes favour the options that look next best
MISTAKE_DRIBBLE = 0.3   # a hard dribble is a less likely mistake than a playable-looking pass or shot
XGOT_SPREAD = 0.9      # how much the spot in the goal moves the chance of a shot on target (mean stays 1)
XGOT_MAX = 0.97
SHOT_ENDINGS = {"saved": 0.37, "off_target": 0.34, "post": 0.03}
SHOT_BLOCKED = (0.08, 0.9)   # weight of "blocked": base + this much times the share of the goal hidden
GOAL_HALF_WIDTH, CROSSBAR = 3.66, 2.44

# bodies: a hard collision can knock a player over, and rarely injure him
FALL_SPEED = 5.5        # m/s closing speed between two opponents that counts as a hard collision
FALL_CHANCE = 0.12      # chance a hard collision knocks one of them down (the weaker one, mostly)
INJURY_PER_FALL = 0.004
INJURY_PER_FOUL = 0.01
CONTACT_M = 1.3         # a defender this close to the dribbler can make his challenge

# shapes a manager switches to with ten outfield players: chasing the game, or protecting a lead
TACTICAL = {
    "push_forward": ("3-4-3", [("CB", 22, 46), ("CB", 20, 34), ("CB", 22, 22), ("RM", 46, 60), ("CM", 42, 41),
                               ("CM", 42, 27), ("LM", 46, 8), ("RW", 64, 56), ("ST", 70, 34), ("LW", 64, 12)]),
    "protect_lead": ("5-4-1", [("RB", 26, 60), ("CB", 18, 46), ("CB", 16, 34), ("CB", 18, 22), ("LB", 26, 8),
                               ("RM", 42, 56), ("CM", 36, 41), ("CM", 36, 27), ("LM", 42, 12), ("ST", 60, 34)]),
}
MANAGER_REACTS = 0.7    # chance the manager changes shape when the team's approach changes after 55'

# Decision profiles: temperature = how noisy the choice is, biases nudge option types
# (long_shot_bias only for shots from outside the box, cross_bias for wide players), mistake_rate = chance of
# deliberately picking one of the worst options (ground truth for testing the model).
PROFILES = {
    "safe_playmaker": {"temperature": 0.010, "shot_bias": 0.0005, "long_shot_bias": 0.044,
                       "dribble_bias": -0.01, "long_ball_bias": 0.002, "mistake_rate": 0.03},
    "selfish_striker": {"temperature": 0.020, "shot_bias": 0.0165, "long_shot_bias": 0.024,
                        "dribble_bias": 0.01, "long_ball_bias": -0.01, "mistake_rate": 0.10},
    "flair_winger": {"temperature": 0.025, "shot_bias": 0.0045, "long_shot_bias": 0.042,
                     "dribble_bias": 0.03, "cross_bias": 0.03, "long_ball_bias": -0.01, "mistake_rate": 0.08},
    "solid_defender": {"temperature": 0.012, "shot_bias": -0.0045, "long_shot_bias": 0.002,
                       "dribble_bias": -0.02, "cross_bias": 0.02, "long_ball_bias": 0.02,
                       "mistake_rate": 0.04},
    "keeper": {"temperature": 0.010, "shot_bias": -1.0, "long_shot_bias": 0.0,
               "dribble_bias": -1.0, "long_ball_bias": 0.02, "mistake_rate": 0.02},
}

# Overlay triggers for player identification (requirement 4.1 ii).
ALERTS = {"sprint_kmh": 25.2, "sprint_min_s": 1.0, "sprint_cooldown_s": 900, "top_speed_kmh": 32.0,
          "distance_milestone_km": 2.5}

# booked players tackle more carefully, so a second yellow is rarer than a first
CARDS = {"yellow_per_foul": 0.18, "second_yellow_per_foul": 0.04, "straight_red_per_foul": 0.005}

FIRST = ["Arda", "Leo", "Kenji", "Mateo", "Noah", "Emre", "Luca", "Omar", "Felix", "Iker", "Yusuf",
         "Theo", "Kaan", "Ravi", "Hugo", "Elias", "Bora", "Sami", "Jonas", "Milo", "Deniz", "Ilan"]
LAST = ["Vale", "Korhan", "Brandt", "Okoro", "Silva", "Tanaka", "Moreau", "Reyes", "Lindqvist", "Aydin",
        "Novak", "Haddad", "Costa", "Weber", "Yilmaz", "Dubois", "Kaya", "Ferro", "Nakamura", "Petrov",
        "Sahin", "Quinn"]

# seconds the ball is dead before each restart (Metrica sample games: the ball is out of play ~40% of the match)
STOPPAGE_S = {"from_kick_off": (5, 10), "from_throw_in": (12, 22), "from_goal_kick": (22, 35),
              "from_corner": (30, 45), "from_free_kick": (25, 50), "from_penalty": (60, 90)}

PASS_ONLY = {"from_throw_in", "from_goal_kick", "from_kick_off", "from_corner"}

XT_GRID = None
_grid_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xt_grid.json")
if os.path.exists(_grid_path):
    with open(_grid_path, encoding="utf-8") as _f:
        XT_GRID = json.load(_f)["grid"]

SHAPE = None   # learned team shapes (shape_table.json): where each slot stands for every ball position
_shape_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shape_table.json")
if os.path.exists(_shape_path):
    with open(_shape_path, encoding="utf-8") as _f:
        SHAPE = json.load(_f)
SHAPE_HOMES = {name: [(hx, hy) for _, hx, hy in slots] for name, slots in FORMATIONS.items()}
SHAPE_HOMES.update({name: [(5, 34)] + [(hx, hy) for _, hx, hy in slots]
                    for shapes in (SHORT_HANDED, TACTICAL) for name, slots in shapes.values()})
SHAPE_TAU_S = 6.0  # s over which a team's deviation from its learned average shape changes (Metrica sample games)
ATT_WIDTH = 1.2     # how much the side on the ball stretches its learned shape across the pitch
SHAPE_PACE = 0.82   # share of top speed players use to get back into a learned shape
SHAPE_WOBBLE = 0.7  # share of that deviation used as a target: the rest comes from players lagging their targets
RETARGET_S = 0.2   # s between target updates while the ball moves (learned shapes only)
REACT_S = 0.4      # s players lag behind the ball when they follow it
LEAD_M = 4.0       # m everyone aims ahead of the learned spot in the attacking direction: play moves that way and
                   # players read it (without it both teams trail their spots by about this much)


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def skilled(ps, technique):
    """A chance of success adjusted for the passer's technique (0.5 = average, no change)."""
    ps = clamp(ps, 0.001, 0.999)
    return round(sigmoid(math.log(ps / (1 - ps)) + TECH_PASS * (technique - 0.5)), 4)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def xt_formula(x, y):
    """Hand-written threat surface: the players' intuition, and the model's value until a grid is learned."""
    fx = (x / PITCH_X) ** 3
    centrality = 1 - abs(y - GOAL_Y) / GOAL_Y
    return 0.005 + 0.25 * fx * (0.35 + 0.65 * centrality ** 2)


def xt(x, y):
    if XT_GRID is None:
        return round(xt_formula(x, y), 4)
    cx = min(int(clamp(x, 0, PITCH_X - 1e-6) / PITCH_X * 16), 15)
    cy = min(int(clamp(y, 0, PITCH_Y - 1e-6) / PITCH_Y * 12), 11)
    return round(XT_GRID[cx][cy], 4)


def goal_distance(p):
    return math.hypot(PITCH_X - p[0], GOAL_Y - p[1])


def goal_angle(x, y):
    """Angle (radians) the 7.32 m goal mouth covers, seen from (x, y)."""
    a = math.atan2(7.32 * (PITCH_X - x), (PITCH_X - x) ** 2 + (GOAL_Y - y) ** 2 - (7.32 / 2) ** 2)
    return a if a > 0 else a + math.pi


def along(p, a, b):
    """How far along the segment a -> b the point p projects (0 at a, 1 at b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1.0)


def shadow(b, blockers):
    """Share of the goal mouth hidden from the ball by defenders standing in the way (0 to 1)."""
    hidden = 0
    for i in range(GOAL_POINTS):
        aim = (PITCH_X, GOAL_Y - GOAL_HALF_WIDTH + (i + 0.5) * 2 * GOAL_HALF_WIDTH / GOAL_POINTS)
        if any(0.03 < along(o, b, aim) < 1 and seg_point_dist(o, b, aim) < BLOCK_REACH for o in blockers):
            hidden += 1
    return hidden / GOAL_POINTS


def xg(x, y, pressure, header=False, blockers=(), keeper=None):
    """Chance a shot from (x, y) scores. Distance and the angle of the goal set the base; defenders in the
    way lower it, a keeper caught away from the line to goal raises it. Returns (xg, share hidden)."""
    d = goal_distance((x, y))
    hidden = shadow((x, y), blockers)
    keeper_off = 0.0
    if keeper is not None and along(keeper, (x, y), (PITCH_X, GOAL_Y)) > 0:
        keeper_off = clamp((seg_point_dist(keeper, (x, y), (PITCH_X, GOAL_Y)) - 1.0) / 3, 0, 1)
    z = (XG_BASE + XG_DIST * d + XG_ANGLE * math.log(max(goal_angle(x, y), 0.01)) - XG_SHADOW * hidden
         + XG_KEEPER * keeper_off - XG_PRESSURE * pressure - (XG_HEADER if header else 0))
    return round(min(0.95, sigmoid(z)), 4), round(hidden, 2)


def seg_point_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return dist(p, a)
    t = max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return dist(p, (ax + t * dx, ay + t * dy))


def closest_on_segment(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    if dx == dy == 0:
        return a
    t = max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return (ax + t * dx, ay + t * dy)


def pass_speed(length):
    """Typical speed of a ground pass (m/s): longer passes are struck harder."""
    return (28 + 1.3 * length) / 3.6


def lane_gap(origin, target, defenders):
    """How far the best-placed defender is still short of the ball's path when the ball passes him (m).
    A defender beside the passer has no time, one near the end of a slow pass has plenty;
    defenders behind the passer cannot cut the pass out. Negative: he gets there first."""
    length = dist(origin, target) or 1.0
    v = pass_speed(length)
    gap = 6.0
    for d in defenders:
        a = along(d, origin, target) * length  # metres from the passer
        if a <= 0 or a > length:
            continue
        t = a / v
        reach = LANE_REACH + LANE_RUN * max(0.0, t - LANE_REACT)
        gap = min(gap, seg_point_dist(d, origin, target) - reach)
    return max(-2.0, gap)


def blind(origin, target, facing):
    """0 when the pass goes where the passer faces, 1 when it goes straight behind him."""
    if facing is None:
        return 0.0
    ang = math.atan2(target[1] - origin[1], target[0] - origin[0]) - math.radians(facing)
    return (1 - math.cos(ang)) / 2


def p_pass(origin, target, defenders, pressure=0.0, facing=None):
    length = dist(origin, target)
    lane = lane_gap(origin, target, defenders)
    marker = min(dist(d, target) for d in defenders)
    z = (P_PASS_BASE + P_PASS_LEN * length + P_PASS_LANE * lane + P_PASS_MARK * min(marker, 8)
         - P_PASS_PRESS * pressure - P_PASS_BLIND * blind(origin, target, facing))
    return round(sigmoid(z), 4)


def p_cross(target, defenders):
    """Lofted ball into the box: lane blocking matters little, markers near the target matter a lot."""
    close = sum(1 for d in defenders if dist(d, target) < 3)
    marker = min(dist(d, target) for d in defenders)
    return round(clamp(0.26 + 0.05 * min(marker, 4) - 0.06 * close, 0.08, 0.5), 4)


def in_box(p):
    """Penalty box of the defending team, in the attacker's frame."""
    return p[0] > PITCH_X - 16.5 and abs(p[1] - GOAL_Y) < 20.16


def bend(a, b, f, curl):
    """Point at share f of the way from a to b, pushed sideways by curl * sin(pi f) (a swerving ball)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    side = curl * math.sin(math.pi * clamp(f, 0, 1))
    return (a[0] + dx * f - dy / length * side, a[1] + dy * f + dx / length * side)


def best_fit(players, role):
    """The squad player who fits a formation slot best (squad order breaks ties: regulars first)."""
    for pos in FITS[role]:
        for p in players:
            if p["position"] == pos:
                return p
    outfield = [p for p in players if p["position"] != "GK"] if role != "GK" else players
    return (outfield or players)[0]


def stance_of(urgency):
    return "push_forward" if urgency >= 0.5 else "protect_lead" if urgency <= -0.5 else "balanced"


def flight_time(length):
    """Seconds a lofted ball (cross, long ball, clearance) spends in the air."""
    return 0.7 + 0.035 * length


def to_af(pos, team_idx):
    """Mirror coordinates so the given team always attacks left -> right (attack frame)."""
    return pos if team_idx == 0 else (PITCH_X - pos[0], PITCH_Y - pos[1])


class Targets(dict):
    """player_id -> target spot. With learned shapes `ref` holds the ball spot (attack frame) and the attacking
    team the targets were set for, so advance() can keep moving them with the ball; `moved` holds that shift."""
    ref = None

    def __init__(self):
        super().__init__()
        self.moved = {}


class Match:
    def __init__(self, seed, hz=25):
        self.rng = random.Random(seed)
        self.seed = seed
        self.hz = hz
        self.dt = 1.0 / hz
        self.match_id = f"SYN-{seed:04d}"
        self.teams = [
            {"team_id": "NRV", "name": "Northbridge Rovers", "side": "home"},
            {"team_id": "SHA", "name": "Southhaven Athletic", "side": "away"},
        ]
        self.players = []
        self.bench = {0: [], 1: []}
        squads = self.squads()
        self.pos, self.vel, self.distance, self.top_speed, self.facing = {}, {}, {}, {}, {}
        self.sprints, self.last_sprint, self.sprint_run, self.offset, self.idle = {}, {}, {}, {}, {}
        self.top_alerted = set()
        self.pressing = set()   # the defender who goes to the ball in open play
        self.ball_trail = []    # recent ball spots, so players can follow the ball with a short delay
        self.wobble = {}        # team -> (learned shape deviation coefficients, time they were drawn)
        self.runs = {}          # forwards on a run in behind: player_id -> (until, target x, attacking team, last line)
        self.down_until, self.falls, self.injured = {}, {}, []
        self.formation = {t: self.rng.choice(sorted(FORMATIONS)) for t in (0, 1)}
        self.start_formation = dict(self.formation)
        self.formation_changes = []
        # the match wind (pushes lofted balls) and each team's pressing height
        self.wind_speed = round(self.rng.uniform(0, WIND_MAX), 1)
        self.wind_dir = round(self.rng.uniform(-180, 180))
        self.wind = (self.wind_speed * math.cos(math.radians(self.wind_dir)),
                     self.wind_speed * math.sin(math.radians(self.wind_dir)))
        self.press = {t: self.rng.choice(["low", "mid", "high"]) for t in (0, 1)}
        self.stance = {0: "balanced", 1: "balanced"}
        self.tactical_shifts = []
        for t_idx, team in enumerate(self.teams):
            free = list(squads[t_idx])
            for role, hx, hy in FORMATIONS[self.formation[t_idx]]:
                p = best_fit(free, role)
                free.remove(p)
                self.assign(p, role, (hx, hy))
                p["started"], p["on"], p["minute_on"] = True, True, 0
                self.players.append(p)
                self.init_state(p, to_af((hx * 0.48, hy), t_idx))
            self.bench[t_idx] = free
        self.by_id = {p["player_id"]: p for p in self.players}
        self.plan = {t: self.scout(t) for t in (0, 1)}
        self.tactical_shape = {0: False, 1: False}
        self.score = [0, 0]
        self.events, self.frames, self.options, self.alerts = [], [], [], []
        self.track_writer = None
        self.eid = 0
        self.clock = 0.0       # match clock in seconds (restarts at 45:00 in the second half)
        self.real_t = 0.0      # elapsed playing time, used for ts_ms
        self.period = 1
        self.possession_id = 0
        self.poss_team = None  # possession changes only when the other team gets the ball
        self.ball = (52.5, 34.0)
        self.ball_z = 0.0
        self.contacts = 0
        self.sub_plan = {t: sorted(self.rng.uniform(55, 85) for _ in range(SUBS_PER_TEAM)) for t in (0, 1)}
        self.subs_used = {0: 0, 1: 0}

    def squads(self):
        """Both teams' 18-man squads. They come from a fixed league seed, not the match seed,
        so names, positions and attributes stay the same from match to match."""
        r = random.Random(LEAGUE_SEED)
        names = r.sample([f"{f} {l}" for f in FIRST for l in LAST], 2 * len(SQUAD_ROLES))
        out = []
        for t_idx, team in enumerate(self.teams):
            squad = []
            for i, pos in enumerate(SQUAD_ROLES):
                line = LINE[pos]
                # physical and technical attributes (0-1 scales) decide one-on-one duels
                height = r.gauss(181, 5) + (6 if line == "gk" else 4 if pos == "CB" else 3 if pos == "ST" else
                                            -3 if pos in WIDE or pos == "AM" else 0)
                squad.append({
                    "player_id": f"{team['team_id']}_{i + 1:02d}", "team_id": team["team_id"], "team_idx": t_idx,
                    "name": names[t_idx * len(SQUAD_ROLES) + i], "position": pos, "shirt": i + 1,
                    "max_speed": MAX_SPEED[line] * r.uniform(0.93, 1.05), "height_cm": round(height),
                    "strength": round(clamp(r.gauss(0.55 + (0.1 if pos in ("CB", "ST") else 0), 0.15), 0.1, 1), 2),
                    "technique": round(clamp(r.gauss(0.5 + (0.15 if pos in WIDE or pos in ("AM", "CM") else
                                                            -0.1 if line == "def" else 0), 0.15), 0.1, 1), 2),
                    "defending": round(clamp(r.gauss(0.5 + (0.2 if line == "def" or pos == "DM" else
                                                            -0.15 if line == "fwd" else 0), 0.15), 0.1, 1), 2),
                    "started": False, "on": False, "yellow": 0, "minute_on": None, "minute_off": None})
            out.append(squad)
        return out

    @staticmethod
    def assign(p, role, home):
        """Give a squad player a slot in today's shape: role, line, home position and decision profile."""
        line = LINE[role]
        p["role"], p["line"], p["home"] = role, line, home
        p["profile"] = ("keeper" if role == "GK" else "solid_defender" if line == "def"
                        else "selfish_striker" if role == "ST" else "flair_winger" if role in WIDE
                        else "safe_playmaker")

    def init_state(self, p, pos):
        pid = p["player_id"]
        self.pos[pid] = pos
        self.vel[pid] = (0.0, 0.0)
        self.facing[pid] = 0.0
        self.distance[pid] = 0.0
        self.top_speed[pid] = 0.0
        self.sprints[pid] = 0
        self.last_sprint[pid] = -999.0
        self.sprint_run[pid] = 0.0
        self.offset[pid] = (0.0, 0.0)  # slow personal drift around tactical targets
        self.idle[pid] = (0.0, 0.0)    # small restless wandering, so nobody stands frozen on his spot
        self.down_until[pid] = -1.0    # a fallen player stays down until this time
        self.falls[pid] = 0

    def active(self, team_idx=None):
        return [p for p in self.players if p["on"] and (team_idx is None or p["team_idx"] == team_idx)]

    def pick(self, team_idx, roles, near=None):
        """First player on the pitch with one of `roles`, else the outfield player nearest `near`."""
        for role in roles:
            for p in self.active(team_idx):
                if p["role"] == role:
                    return p
        return self.nearest(team_idx, near or self.ball)

    # ---------- game state ----------
    def urgency(self, t):
        """How hard team t chases the game: >0 when behind, <0 when ahead, growing towards full time."""
        diff = self.score[1 - t] - self.score[t]
        return clamp(diff * (0.3 + 0.7 * min(self.clock, 5400) / 5400), -1.0, 1.0)

    def scout(self, t):
        """Game plan against this opponent: attack the flank of their weaker full-back, and cross more
        when our forwards are better in the air than their centre-backs."""
        opp = self.active(1 - t)
        backs = [p for p in opp if p["role"] in ("RB", "LB")]
        weak = min(backs, key=lambda p: p["defending"] + 0.05 * p["max_speed"])

        def reach(p):
            return p["height_cm"] + 12 * p["strength"]
        ours = max(reach(p) for p in self.active(t) if p["line"] == "fwd")
        cbs = [reach(p) for p in opp if p["role"] == "CB"]
        # their right-back defends our right-hand side (y < 34 in our attack frame), and vice versa
        return {"target_flank": "right" if weak["role"] == "RB" else "left", "weak_defender": weak["player_id"],
                "aerial_threat": ours > sum(cbs) / len(cbs) + 2}

    def update_stance(self):
        for t in (0, 1):
            stance = stance_of(self.urgency(t))
            if stance != self.stance[t]:
                self.stance[t] = stance
                leader = self.pick(t, ["DM", "CM", "AM", "ST"])
                spot = self.pos[leader["player_id"]]
                self.tactical_shifts.append({"minute": int(self.clock // 60), "team_id": self.teams[t]["team_id"],
                                             "stance": stance})
                self.record(leader, "tactical_shift", spot, spot, stance)
                # the manager may also change the shape (only with a full team of ten outfield players)
                outfield = [p for p in self.active(t) if p["line"] != "gk"]
                if len(outfield) != 10:
                    continue
                if stance in TACTICAL and self.clock >= 55 * 60 and self.rng.random() < MANAGER_REACTS:
                    self.reshape_to(t, *TACTICAL[stance], leader, "tactical")
                    self.tactical_shape[t] = True
                elif stance == "balanced" and self.tactical_shape[t]:
                    start = self.start_formation[t]
                    self.reshape_to(t, start, FORMATIONS[start][1:], leader, "tactical")
                    self.tactical_shape[t] = False

    # ---------- target positions ----------
    def learned_spot(self, p, ball_af, att):
        """p's learned open-play spot (attack frame of `att`) with the ball at ball_af in that frame."""
        t = p["team_idx"]
        name = self.formation[t]
        f = SHAPE["formations"][name]
        slot = f["slots"][SHAPE_HOMES[name].index(tuple(p["home"]))]
        bx, by = ball_af if t == att else (PITCH_X - ball_af[0], PITCH_Y - ball_af[1])
        gx, gy = SHAPE["grid_x"], SHAPE["grid_y"]
        fx = clamp(bx / (gx[1] - gx[0]), 0, len(gx) - 1.001)
        fy = clamp(by / (gy[1] - gy[0]), 0, len(gy) - 1.001)
        i, j = int(fx), int(fy)
        u, v = fx - i, fy - j
        phase = "att" if t == att else "def"
        g = SHAPE["teams"][f["team"]][phase]
        x, y = ((1 - u) * (1 - v) * g[i][j][slot][k] + u * (1 - v) * g[i + 1][j][slot][k]
                + (1 - u) * v * g[i][j + 1][slot][k] + u * v * g[i + 1][j + 1][slot][k] for k in (0, 1))
        # the whole team's current deviation from the average shape (pushed up, stretched, shifted ...)
        modes = SHAPE["teams"][f["team"]][phase + "_modes"]
        z, at = self.wobble.get(t, ([0.0] * len(modes), -1e9))   # kept across possession changes: no jumps
        if at != self.real_t:
            a = math.exp(-(self.real_t - at) / SHAPE_TAU_S)
            z = [a * c + math.sqrt(1 - a * a) * self.rng.gauss(0, 1) for c in z]
            self.wobble[t] = (z, self.real_t)
        n = len(modes[0]) // 2
        x += SHAPE_WOBBLE * sum(c * m[slot - 1] for c, m in zip(z, modes))
        y += SHAPE_WOBBLE * sum(c * m[n + slot - 1] for c, m in zip(z, modes))
        return (x, y) if t == att else (PITCH_X - x, PITCH_Y - y)

    def follow_ball(self, targets, ref, ball, dribbler, arrive):
        """Shift learned targets from where the ball was when they were set to where it is now (seen with a delay).
        Players with a job of their own (on or going to the ball, pressing, on a run) keep their target."""
        (rx, ry), att = ref
        now = to_af(ball, att)
        for pid in targets:
            p = self.by_id[pid]
            if (p["line"] == "gk" or pid == dribbler or pid in arrive or pid in self.pressing or pid in self.runs):
                continue
            ax, ay = self.learned_spot(p, now, att)
            bx, by = self.learned_spot(p, (rx, ry), att)
            sign = 1 if att == 0 else -1
            new = (sign * (ax - bx), sign * (ay - by))
            old = targets.moved.get(pid, (0.0, 0.0))
            tx, ty = targets[pid]
            targets[pid] = (clamp(tx + new[0] - old[0], 0, PITCH_X), clamp(ty + new[1] - old[1], 0, PITCH_Y))
            targets.moved[pid] = new

    def targets(self, ball, att, mode="open"):
        """Where every player wants to be, given the ball and the attacking team."""
        bx, by = to_af(ball, att)
        # defending back line, always goal-side; pressing teams and teams chasing the game hold it higher
        shift = PRESS_SHIFT[self.press[1 - att]] + SCORE_SHIFT * self.urgency(1 - att)
        back = clamp(max(0.5 * bx + BACK_C - shift, bx + 3), 58 - max(shift, 0), BACK_DEEPEST)
        push = 6 * self.urgency(att)   # the attacking side commits more players when chasing the game
        if mode == "kick_off":
            back = 62
        learned = {}
        if SHAPE and mode == "open":
            for p in self.active():
                if p["line"] != "gk":
                    lx, ly = self.learned_spot(p, (bx, by), att)
                    lx += LEAD_M
                    learned[p["player_id"]] = (lx + push / 2, ly) if p["team_idx"] == att else (lx - shift, ly)
            # the averaged table is narrower than any single moment (full-backs and wingers take turns to give the
            # width): the side on the ball spreads out to the width Metrica teams have in possession
            own = [pid for pid in learned if self.by_id[pid]["team_idx"] == att]
            mid_y = sum(learned[pid][1] for pid in own) / len(own)
            for pid in own:
                lx, ly = learned[pid]
                learned[pid] = (lx, clamp(mid_y + (ly - mid_y) * ATT_WIDTH, 1, PITCH_Y - 1))
            back = max(x for pid, (x, _) in learned.items() if self.by_id[pid]["team_idx"] != att)
        out = Targets()
        if learned:
            out.ref = ((bx, by), att)
        for p in self.active():
            hx, hy = p["home"]
            line = p["line"]
            spot = learned.get(p["player_id"])
            if p["team_idx"] == att:
                if line == "gk":
                    x, y = clamp(bx * 0.2, 4, 18), GOAL_Y
                elif line == "def" and spot:
                    x, y = spot
                elif line == "def":
                    # never deeper than the edge of the box; in the build-up the centre-backs split wide
                    x, y = clamp(max(bx - ATT_GAP + push, 0.6 * bx + 4), BUILD_UP_DEPTH, 58), hy * 0.85 + by * 0.15
                    if p["role"] == "CB" and bx < 35:
                        y = GOAL_Y + (hy - GOAL_Y) * CB_SPLIT + by * 0.1 - GOAL_Y * 0.1
                    elif p["role"] in ("RB", "LB") and bx > 30:   # full-backs push on and give the width
                        x, y = max(x, bx - FB_BEHIND), GOAL_Y + (hy - GOAL_Y) * FB_WIDE
                elif line == "mid":
                    # DM screens behind the ball, CMs find space ahead of it, the AM between the lines
                    ahead = {"DM": -5, "AM": 11}.get(p["role"], 6)
                    x, y = spot or (clamp(bx + ahead + push / 2, 22, back - 3), hy * 0.75 + by * 0.25)
                    if p["role"] in WIDE and not spot:   # wide midfielders hold the touchline
                        y = hy * 0.9 + by * 0.1
                    if bx > CROSS_ZONE[0] + 6 and abs(by - GOAL_Y) > CROSS_ZONE[1]:
                        if p["role"] in WIDE and (hy - GOAL_Y) * (by - GOAL_Y) < 0:   # far-post run
                            x, y = clamp(PITCH_X - 10, 38, back - 0.8), GOAL_Y - (by - GOAL_Y) * 0.3
                        elif p["role"] == "AM" or (p["role"] == "CM" and (hy - GOAL_Y) * (by - GOAL_Y) < 0):
                            x, y = clamp(PITCH_X - 13, 38, back - 0.8), GOAL_Y - (by - GOAL_Y) * 0.1  # penalty spot
                else:
                    wide = p["role"] in WIDE
                    x = spot[0] if spot else clamp(bx + 14, 38, back - 0.8)
                    run = self.runs.get(p["player_id"])
                    beyond = to_af(self.pos[p["player_id"]], att)[0] > back + 1   # caught offside: he checks his run
                    if run and (run[0] < self.real_t or run[2] != att or mode != "open" or beyond):
                        run = self.runs.pop(p["player_id"])   # over, or the ball changed hands
                        run = None
                    if (run is None and mode == "open" and not beyond and bx > RUN_FROM_X
                            and self.rng.random() < RUN_BEHIND):   # a run in behind, once the ball is far enough up
                        run = self.runs[p["player_id"]] = (self.real_t + RUN_S,
                                                           clamp(back + self.rng.uniform(*RUN_DEPTH), 38, PITCH_X - 6), att, back)
                    if run:
                        x = run[1]
                    y = spot[1] if spot else hy if wide else hy + (by - GOAL_Y) * 0.3
                    if bx > 66 and abs(by - GOAL_Y) > 12:
                        # ball out wide: striker attacks the near post, the far winger the far post
                        far_side = (hy - GOAL_Y) * (by - GOAL_Y) < 0
                        if not wide:
                            x, y = clamp(PITCH_X - 9, 38, back - 0.8), hy + (by - GOAL_Y) * 0.2
                        elif far_side:
                            x, y = clamp(PITCH_X - 8, 38, back - 0.8), GOAL_Y - (by - GOAL_Y) * 0.35
            else:
                own_y = PITCH_Y - hy
                if line == "gk":
                    x, y = PITCH_X - 2, GOAL_Y + (by - GOAL_Y) * 0.15
                elif spot:
                    x, y = spot
                elif line == "def":
                    x, y = back, own_y * 0.65 + by * 0.35
                elif line == "mid":
                    x, y = back - 13, own_y * 0.55 + by * 0.45
                else:
                    x, y = back - 27, own_y * 0.6 + by * 0.4
            if mode == "corner" and line != "gk" and not (p["team_idx"] == att and line == "def"):
                x, y = clamp(self.rng.gauss(96.5, 2.5), 89, 102.5), self.rng.gauss(GOAL_Y, 6)
            if mode == "kick_off":
                own_side = p["team_idx"] == att
                x = min(x, 51.5) if own_side else max(x, 53.5)
            ox, oy = self.offset[p["player_id"]]
            ox, oy = DRIFT[0] * ox + self.rng.gauss(0, DRIFT[1]), DRIFT[0] * oy + self.rng.gauss(0, DRIFT[1])
            self.offset[p["player_id"]] = (ox, oy)
            if line == "gk":
                ox, oy = KEEPER_DRIFT * ox, KEEPER_DRIFT * oy   # keepers stay close to their line
            if p["team_idx"] == att and line != "gk" and mode != "corner":
                x = min(x + ox, x if x > back else back - ONSIDE_MARGIN)   # attackers drift but try to stay onside
            else:
                x = x + ox
            # outfield players keep off the goal lines (only the keepers stand on them)
            x = clamp(x, 0.5, PITCH_X - 0.5) if line == "gk" else clamp(x, 2.5, PITCH_X - 2.5)
            y = clamp(y + oy, 0.5, PITCH_Y - 0.5)
            out[p["player_id"]] = to_af((x, y), att)
        # pressing: nearest outfield defender goes to the ball, second one covers
        b_af = (bx, by)
        defenders = sorted((p for p in self.active(1 - att) if p["line"] != "gk"),
                           key=lambda p: dist(to_af(self.pos[p["player_id"]], att), b_af))
        if mode == "open":
            out[defenders[0]["player_id"]] = to_af((bx + 1.2, by), att)
            self.pressing = {defenders[0]["player_id"]}
            if not learned:   # learned shapes already hold the cover (and drawing a defender out opens the line)
                out[defenders[1]["player_id"]] = to_af((min(bx + 6, PITCH_X - 5), by + (2 if by < GOAL_Y else -2)), att)
            if shift > 3 and bx < HALFWAY and not learned:   # a high press sends a third player at the ball
                out[defenders[2]["player_id"]] = to_af((bx + 4, by + (-5 if by < GOAL_Y else 5)), att)
            # the rest of the back line closes the gaps: evenly spaced, shifted towards the ball
            pressing = {d["player_id"] for d in defenders[:3]}
            line_up = sorted((p for p in self.active(1 - att) if p["line"] == "def" and p["player_id"] not in pressing),
                             key=lambda p: PITCH_Y - p["home"][1])
            centre = clamp(GOAL_Y * 0.6 + by * 0.4, 18, PITCH_Y - 18)
            for i, p in enumerate([] if learned else line_up):   # learned shapes space the line themselves
                ax, _ = to_af(out[p["player_id"]], att)
                y = centre + (i - (len(line_up) - 1) / 2) * LINE_SPACING + 0.5 * self.offset[p["player_id"]][1]
                out[p["player_id"]] = to_af((ax, clamp(y, 3, PITCH_Y - 3)), att)
            # a centre-back picks up each centre-forward who drops in front of the line: tight and goal-side
            for f in (p for p in self.active(att) if p["role"] == "ST"):
                fx, fy = to_af(out[f["player_id"]], att)
                cbs = [p for p in line_up if p["role"] == "CB" and p["player_id"] not in pressing]
                if cbs and fx > bx:
                    cb = min(cbs, key=lambda p: abs(to_af(out[p["player_id"]], att)[1] - fy))
                    pressing.add(cb["player_id"])
                    line_up.remove(cb)
                    out[cb["player_id"]] = to_af((min(fx + MARK_GAP, BACK_DEEPEST), fy), att)
        return out

    # ---------- movement ----------
    # ball paths: functions of time since the kick returning (x, y, z)
    def ground_path(self, a, b, v0):
        """A pass along the ground slows down as it rolls and may curl a little."""
        length = dist(a, b)
        v1 = ROLL_KEEP * v0
        total = 2 * length / (v0 + v1)
        curl = clamp(self.rng.gauss(0, 0.012 * length), -1.2, 1.2)

        def at(t):
            t = min(t, total)
            f = (v0 * t - (v0 - v1) / total * t * t / 2) / length if length > 1e-6 else 1.0
            return bend(a, b, f, curl) + (0.0,)
        return at, total

    def lofted_path(self, a, b, z0, z1, total, curl=0.0, bounce_at=None):
        """A ball in the air: gravity, drag on its horizontal speed and some swerve (spin).
        With bounce_at (0-1) it lands at that share of the way, bounces once and runs on to b."""
        land = 1.0 if bounce_at is None else bounce_at
        t_air = total   # time in the air before landing (or reaching b)
        zl = z1 if bounce_at is None else 0.0
        vz = (zl - z0 + GRAVITY * t_air * t_air / 2) / t_air
        k = 1 - AIR_KEEP
        norm = 1 - k / 2
        hop_t, hop_vz = 0.0, BOUNCE * (vz - GRAVITY * t_air)
        if bounce_at is not None:
            hop_vz = -hop_vz
            hop_t = (1 - land) * dist(a, b) / max(0.6 * AIR_KEEP * dist(a, b) * land / (t_air * norm), 1.0)

        def at(t):
            if t <= t_air:
                u = t / t_air
                f = land * (u - k * u * u / 2) / norm
                return bend(a, b, f, curl) + (max(0.0, z0 + vz * t - GRAVITY * t * t / 2),)
            tt = min(t - t_air, hop_t)
            f = land + (1 - land) * (tt / hop_t if hop_t else 1)
            return bend(a, b, f, curl) + (max(0.0, hop_vz * tt - GRAVITY * tt * tt / 2),)
        return at, t_air + hop_t

    def separate(self, ids, record=True):
        """Players cannot overlap: anyone closer than two body radii is pushed apart.
        A hard collision between opponents can knock one of them over."""
        ids = sorted(ids, key=lambda i: self.pos[i][0])
        gap = 2 * PLAYER_RADIUS
        for i, a in enumerate(ids):
            ax, ay = self.pos[a]
            for b in ids[i + 1:]:
                bx_, by_ = self.pos[b]
                if bx_ - ax >= gap:
                    break
                d = math.hypot(bx_ - ax, by_ - ay)
                if d < gap:
                    if d < 1e-6:
                        nx, ny, d = 0.0, 1.0, 0.0
                    else:
                        nx, ny = (bx_ - ax) / d, (by_ - ay) / d
                    push = (gap - d) / 2
                    ax, ay = ax - nx * push, ay - ny * push
                    self.pos[a] = ax, ay = clamp(ax, 0, PITCH_X), clamp(ay, 0, PITCH_Y)
                    self.pos[b] = (clamp(bx_ + nx * push, 0, PITCH_X), clamp(by_ + ny * push, 0, PITCH_Y))
                    self.contacts += 1
                    pa, pb = self.by_id[a], self.by_id[b]
                    if record and pa["team_idx"] != pb["team_idx"]:
                        va, vb = self.vel[a], self.vel[b]
                        closing = (va[0] - vb[0]) * nx + (va[1] - vb[1]) * ny
                        if closing > FALL_SPEED and self.rng.random() < FALL_CHANCE:
                            weaker = pa if self.rng.random() < 0.5 + (pb["strength"] - pa["strength"]) else pb
                            self.fall(weaker["player_id"])

    def fall(self, pid):
        if self.down_until[pid] > self.real_t:
            return
        self.down_until[pid] = self.real_t + self.rng.uniform(1.0, 2.5)
        self.vel[pid] = (0.0, 0.0)
        self.falls[pid] += 1
        if self.rng.random() < INJURY_PER_FALL and pid not in self.injured:
            self.injured.append(pid)

    def run_to(self, pid, spot, att):
        """The player who wins the ball runs to it (the ball waits at spot) instead of jumping there."""
        self.ball = spot
        d = dist(self.pos[pid], spot)
        if d > 0.5:
            tg = self.targets(spot, att)
            tg[pid] = spot
            self.advance(min(3.0, d / (0.8 * self.by_id[pid]["max_speed"])), tg, spot, arrive=(pid,))
            waited = 0.0
            while dist(self.pos[pid], spot) > 0.5 and waited < RUN_TO_MAX_S:   # still short of it: keep running
                self.advance(0.2, tg, spot, arrive=(pid,))
                waited += 0.2
        self.pos[pid] = spot

    def treat_injuries(self):
        """At a stoppage, injured players go off (if a substitute is left) or play on at reduced pace."""
        for pid in self.injured:
            p = self.by_id[pid]
            if not p["on"]:
                continue
            self.record(p, "injury", self.pos[pid], self.pos[pid], "injury")
            if self.substitute(p) is None:
                p["max_speed"] *= 0.8
        self.injured = []

    def advance(self, seconds, targets, ball_from, ball_to=None, dribbler=None, record=True, path=None, arrive=()):
        """Move everyone towards their targets for `seconds`, with limited speed, acceleration and braking.
        The ball follows `path` (a function of time), sticks to the dribbler, or stays at ball_from."""
        dt = self.dt
        steps = max(1, int(round(seconds / dt)))
        keep, kick = 1 - dt / IDLE[0], IDLE[1] * math.sqrt(2 * dt / IDLE[0])
        ref = getattr(targets, "ref", None)
        every, lag = max(1, round(RETARGET_S / dt)), max(1, round(REACT_S / dt))
        for s in range(1, steps + 1):
            if ref and path is None and s % every == 0:   # ball carried or held (on a pass they aim where it goes)
                self.follow_ball(targets, ref, (self.ball_trail or [self.ball])[-lag:][0], dribbler, arrive)
            for pid, (tx, ty) in targets.items():
                if self.down_until[pid] > self.real_t:   # on the ground
                    continue
                if pid != dribbler and pid not in arrive and self.by_id[pid]["line"] != "gk":
                    ix, iy = self.idle[pid]
                    self.idle[pid] = ix, iy = keep * ix + self.rng.gauss(0, kick), keep * iy + self.rng.gauss(0, kick)
                    tx, ty = tx + ix, ty + iy
                x, y = self.pos[pid]
                run = self.runs.get(pid)
                if run and pid not in arrive and to_af((x, y), run[2])[0] > run[3] + RUN_CHECK_M:
                    # past the last defender and the ball has not come: he checks his run and gets back onside
                    del self.runs[pid]
                    targets[pid] = tx, ty = to_af((run[3] - ONSIDE_MARGIN, to_af((tx, ty), run[2])[1]), run[2])
                dx, dy = tx - x, ty - y
                d = math.hypot(dx, dy)
                # tired legs: top speed drops as the distance covered grows
                vmax = self.by_id[pid]["max_speed"] * (1 - FATIGUE * min(self.distance[pid] / 10500, 1.2))
                keeper = self.by_id[pid]["line"] == "gk"
                speed = min(vmax, max(d / TAU_S, min(KEEPER_WALK if keeper else JOG_MS, d / dt)))
                running = pid in self.runs and self.runs[pid][0] > self.real_t
                if pid == dribbler or pid in arrive:   # the man on the ball (or going to it) gets there in time
                    speed = min(vmax, max(speed, d / ((steps - s + 1) * dt)))
                elif running and d > 1:                 # a run in behind
                    speed = RUN_PACE * vmax
                elif ref and pid not in self.pressing:  # getting back into shape: a hard run, not a sprint
                    speed = min(speed, SHAPE_PACE * vmax)
                wx, wy = (dx / d * speed, dy / d * speed) if d > 1e-6 else (0.0, 0.0)
                vx, vy = self.vel[pid]
                sharp = pid in self.pressing or pid == dribbler or pid in arrive or running   # all out
                easy = self.by_id[pid]["team_idx"] == self.poss_team   # with the ball the side is in less of a hurry
                resp = RESPONSE_S[easy]
                ax, ay = (wx - vx, wy - vy) if sharp else ((wx - vx) * dt / resp, (wy - vy) * dt / resp)
                a = math.hypot(ax, ay)
                limit = ((ACCEL_MAX if sharp else ACCEL[easy]) if math.hypot(wx, wy) > math.hypot(vx, vy)
                         else (DECEL_MAX if sharp else DECEL[easy])) * dt
                if a > limit:
                    ax, ay = ax / a * limit, ay / a * limit
                vx, vy = vx + ax, vy + ay
                nx, ny = x + vx * dt, y + vy * dt
                if not (0 <= nx <= PITCH_X and 0 <= ny <= PITCH_Y):   # nobody runs off the pitch
                    nx, ny = clamp(nx, 0, PITCH_X), clamp(ny, 0, PITCH_Y)
                    vx, vy = (nx - x) / dt, (ny - y) / dt
                self.vel[pid] = (vx, vy)
                if math.hypot(vx, vy) > 0.5:
                    self.facing[pid] = math.degrees(math.atan2(vy, vx))
                elif math.hypot(self.ball[0] - nx, self.ball[1] - ny) > 0.5:  # standing: turn towards the ball
                    self.facing[pid] = math.degrees(math.atan2(self.ball[1] - ny, self.ball[0] - nx))
                step = math.hypot(nx - x, ny - y)
                before = self.distance[pid]
                self.distance[pid] += step
                self.pos[pid] = (nx, ny)
                kmh = step / dt * 3.6
                if kmh > self.top_speed[pid]:
                    self.top_speed[pid] = kmh
                if record:
                    self.check_alerts(pid, kmh, before)
            self.separate(list(targets), record)
            if dribbler is not None:
                self.ball = self.pos[dribbler]
                self.ball_z = 0.0
            elif path is not None:
                bx_, by_, self.ball_z = path(s * dt)
                self.ball = (bx_, by_)
            self.ball_trail = self.ball_trail[-lag:] + [self.ball]
            self.clock += dt
            self.real_t += dt
            if record and self.track_writer is not None:
                ts = int(round(self.real_t * 1000))
                w = self.track_writer
                w.writerow((ts, self.period, "ball", "", round(self.ball[0], 2), round(self.ball[1], 2),
                            round(self.ball_z, 2), "", ""))
                for p in self.active():
                    pid = p["player_id"]
                    px, py = self.pos[pid]
                    w.writerow((ts, self.period, pid, p["team_id"], round(px, 2), round(py, 2), "",
                                round(self.facing[pid]), "down" if self.down_until[pid] > self.real_t else ""))

    def check_alerts(self, pid, kmh, dist_before):
        p = self.by_id[pid]
        ts = int(round(self.real_t * 1000))
        minute, second = divmod(int(self.clock), 60)
        base = {"ts_ms": ts, "period": self.period, "minute": minute, "second": second,
                "player_id": pid, "player_name": p["name"], "team_id": p["team_id"]}
        # a sprint = at least sprint_min_s above sprint_kmh; counted once per run
        self.sprint_run[pid] = self.sprint_run[pid] + self.dt if kmh >= ALERTS["sprint_kmh"] else 0.0
        if abs(self.sprint_run[pid] - ALERTS["sprint_min_s"]) < self.dt / 2:
            self.sprints[pid] += 1
            if self.real_t - self.last_sprint[pid] > ALERTS["sprint_cooldown_s"]:
                self.last_sprint[pid] = self.real_t
                self.alerts.append({**base, "alert_type": "sprint", "value": round(kmh, 1), "unit": "km/h",
                                    "text_en": f"{p['name']} sprinting at {kmh:.1f} km/h"})
        if kmh >= ALERTS["top_speed_kmh"] and pid not in self.top_alerted:
            self.top_alerted.add(pid)
            self.alerts.append({**base, "alert_type": "top_speed", "value": round(kmh, 1), "unit": "km/h",
                                "text_en": f"{p['name']} hits {kmh:.1f} km/h"})
        step_km = ALERTS["distance_milestone_km"] * 1000
        if int(self.distance[pid] // step_km) > int(dist_before // step_km):
            km = int(self.distance[pid] // step_km) * ALERTS["distance_milestone_km"]
            self.alerts.append({**base, "alert_type": "distance_milestone", "value": km, "unit": "km",
                                "text_en": f"{p['name']} has covered {km:g} km"})

    # ---------- options ----------
    def offside_line(self, t, ball_af):
        """Attack-frame x beyond which a receiver is offside: second-last defender or the ball."""
        xs = sorted((to_af(self.pos[p["player_id"]], t)[0] for p in self.active(1 - t)), reverse=True)
        return max(xs[1], ball_af[0], HALFWAY)

    def aerial_duel(self, mate, spot, t):
        """The opponent who contests a ball dropping at `spot` (attack frame), and mate's edge in that duel:
        taller, stronger and closer players win more headers; keepers can use their hands in their box."""
        spot_w = to_af(spot, t)
        rival = min(self.active(1 - t), key=lambda p: dist(self.pos[p["player_id"]], spot_w))

        def reach(p):
            return p["height_cm"] + 12 * p["strength"] + (30 if p["line"] == "gk" and in_box(spot) else 0)
        gap = dist(self.pos[rival["player_id"]], spot_w) - dist(self.pos[mate["player_id"]], spot_w)
        return rival, (reach(mate) - reach(rival)) / 10 + 0.2 * clamp(gap, -5, 5)

    def wind_factor(self, length):
        """Wind makes lofted balls harder to land on target."""
        drift = WIND_PUSH * self.wind_speed * flight_time(length)
        return clamp(1 - 0.03 * drift, 0.75, 1.0)

    def build_options(self, carrier, pattern, header_chance):
        t = carrier["team_idx"]
        b = to_af(self.ball, t)
        opp = [to_af(self.pos[p["player_id"]], t) for p in self.active(1 - t)]
        opp_out = [to_af(self.pos[p["player_id"]], t) for p in self.active(1 - t) if p["line"] != "gk"]
        keeper = next((to_af(self.pos[p["player_id"]], t) for p in self.active(1 - t) if p["line"] == "gk"), None)
        mates = [to_af(self.pos[p["player_id"]], t) for p in self.active(t) if p["line"] != "gk" and p is not carrier]
        nearest_opp = min(dist(o, b) for o in opp)
        pressure = max(0.0, 1 - nearest_opp / 5)
        here = xt(*b)
        facing = self.facing[carrier["player_id"]] + (180 if t == 1 else 0)  # attack frame

        def both(x, y):
            # (model's learned value, player's intuition): players read the game with the hand-written
            # surface, the analysis model judges them with the grid learned from their own play
            return xt(x, y), round(xt_formula(x, y), 4)

        opp_pl = [(to_af(self.pos[p["player_id"]], t), p) for p in self.active(1 - t) if p["line"] != "gk"]
        mate_pl = [(to_af(self.pos[p["player_id"]], t), p) for p in self.active(t)
                   if p["line"] != "gk" and p is not carrier]

        def lost_at(spot):
            # danger if the ball is lost at spot: the zone's value for the opponent, raised when they have
            # runners goal-side of the ball and few of our outfield players are behind it to defend;
            # each player counts by quality (fast, skilful runners and good, quick defenders count more)
            behind = sum(counter_weight(p["defending"], p["max_speed"]) for m, p in mate_pl if m[0] < spot[0])
            runners = sum(counter_weight(p["technique"], p["max_speed"]) for o, p in opp_pl if o[0] < spot[0])
            # whoever wins the ball plays the first pass of the counter
            winner = min(opp_pl, key=lambda op: dist(op[0], spot))[1]
            first = 1 + COUNTER_WIN * (winner["technique"] - 0.5)
            f = clamp(math.exp(COUNTER_W * (runners - behind + COUNTER_EVEN)), *COUNTER_RANGE) * first
            return tuple(round(min(0.35, v * f), 4) for v in both(PITCH_X - spot[0], PITCH_Y - spot[1]))

        turnover_risk = lost_at(b)
        line = self.offside_line(t, b)
        wide_final_third = b[0] > CROSS_ZONE[0] and abs(b[1] - GOAL_Y) > CROSS_ZONE[1]
        # a ball arriving in the air (after a cross) is played with the head, first time:
        # a headed shot or a short knock-down, no crossing and no dribbling
        aerial = self.rng.random() < header_chance
        opts = []

        def add(kind, mate, tgt, ps, value, risk, body="foot", offside=False, rival=None, clear=False):
            # value and risk are numbers, or (model, player) pairs from both();
            # the passer usually sees an offside team-mate (OFFSIDE_SEEN); the model always does
            value, p_value = value if isinstance(value, tuple) else (value, value)
            risk, p_risk = risk if isinstance(risk, tuple) else (risk, risk)
            true_ps = 0.0 if offside else ps
            seen_ps = 0.0 if offside and (clear or self.rng.random() < OFFSIDE_SEEN) else ps
            opts.append({"option_type": kind, "target_player_id": mate["player_id"] if mate else "",
                         "target": tgt, "p_success": true_ps, "value_if_success": value, "risk_if_fail": risk,
                         "body_part": body, "offside": offside,
                         "opponent_id": rival["player_id"] if rival else "",
                         "perceived_ev": seen_ps * p_value - (1 - seen_ps) * p_risk})

        if pattern == "from_penalty":
            add("shot", None, (PITCH_X, GOAL_Y), 0.76, 1.0, 0.01)
        else:
            set_piece = pattern != "open_play" and pattern != "from_keeper"
            for mate in self.active(t):
                if mate is carrier:
                    continue
                tgt = to_af(self.pos[mate["player_id"]], t)
                if dist(b, tgt) > (12 if aerial else 70):
                    continue
                offside = (not set_piece or pattern == "from_free_kick") and tgt[0] > line + 0.3
                clear = offside and tgt[0] > line + OFFSIDE_CLEAR_M
                if pattern != "from_corner" and dist(b, tgt) <= 55:
                    ps = p_pass(b, tgt, opp, pressure, facing)
                    if in_box(tgt):
                        ps = round(ps * BOX_PASS, 4)  # crowded box
                    if goal_distance(tgt) < CLOSE_RANGE:
                        ps = round(ps * CLOSE_PASS, 4)  # defenders mark tightest near goal
                    if aerial:
                        ps = round(ps * 0.6, 4)  # headed knock-down
                    ps = skilled(ps, carrier["technique"])
                    # if it fails, the ball is lost where the opponent nearest the passing lane cuts it out
                    cutter = min(opp, key=lambda o: seg_point_dist(o, b, tgt))
                    lost = closest_on_segment(cutter, b, tgt)
                    add("pass", mate, tgt, ps, both(*tgt), lost_at(lost),
                        "head" if aerial else "foot", offside, clear=clear)
                    vx, vy = self.vel[mate["player_id"]] if t == 0 else (-v for v in self.vel[mate["player_id"]])
                    if pattern == "open_play" and not aerial and vx >= RUN_PASS_V:   # the ball into his run
                        lead = 0.0
                        for _ in range(4):   # the meeting point moves with the time the pass takes
                            d = dist(b, (tgt[0] + vx * lead, tgt[1] + vy * lead))
                            lead = min(RUN_LEAD_MAX, d / pass_speed(d))
                        spot = (clamp(tgt[0] + vx * lead, 3, PITCH_X - 3), clamp(tgt[1] + vy * lead, 2, PITCH_Y - 2))
                        if dist(b, spot) <= 55:
                            ps = p_pass(b, spot, opp, pressure, facing) * RUN_PASS
                            if in_box(spot):
                                ps *= BOX_PASS
                            ps = skilled(round(ps, 4), carrier["technique"])
                            cutter = min(opp, key=lambda o: seg_point_dist(o, b, spot))
                            add("pass", mate, spot, ps, both(*spot), lost_at(closest_on_segment(cutter, b, spot)),
                                "foot", offside, clear=clear)
                crossing = (wide_final_third and pattern == "open_play") or pattern in ("from_corner", "from_free_kick")
                # a cross goes to a team-mate in the box, or into the space a forward is running towards
                attacking_run = mate["line"] == "fwd" or mate["role"] == "AM"
                if crossing and not aerial and (in_box(tgt) or (attacking_run and tgt[0] > PITCH_X - 30)):
                    spot = tgt if in_box(tgt) else (PITCH_X - self.rng.uniform(6, 11), clamp(tgt[1], 24, 44))
                    # a cross that arrives is worth the headed chance it creates, or the zone if more
                    chance = xg(spot[0], spot[1], 0.3, header=True, blockers=opp_out, keeper=keeper)[0]
                    value = tuple(max(v, chance) for v in both(*spot))
                    rival, edge = self.aerial_duel(mate, spot, t)
                    ps = (p_cross(spot, opp) + 0.05 * edge) * (1 if spot is tgt else 0.85) * self.wind_factor(dist(b, spot))
                    ps = skilled(clamp(ps, 0.05, 0.6), carrier["technique"])
                    add("cross", mate, spot, round(clamp(ps, 0.04, 0.7), 4), value,
                        lost_at(spot), offside=offside, rival=rival, clear=clear)
                long_passer = carrier["line"] in ("gk", "def") or (carrier["line"] == "mid" and pressure > 0.3)
                if long_passer and b[0] < 55 and pattern not in ("from_corner", "from_throw_in") \
                        and (mate["line"] == "fwd" or mate["role"] in WIDE) and dist(b, tgt) > 28:
                    # long ball over the press: an aerial duel at the other end, lost far from goal
                    rival, edge = self.aerial_duel(mate, tgt, t)
                    ps = (0.5 - 0.04 * sum(1 for o in opp if dist(o, tgt) < 5) + 0.05 * edge) * self.wind_factor(dist(b, tgt))
                    ps = skilled(clamp(ps, 0.2, 0.65), carrier["technique"])
                    add("long_ball", mate, tgt, round(clamp(ps, 0.15, 0.75), 4), both(*tgt),
                        lost_at(tgt), offside=offside, rival=rival, clear=clear)
            if pattern not in PASS_ONLY and goal_distance(b) < 32:
                header = aerial
                g, hidden = xg(b[0], b[1], pressure, header, opp_out, keeper)
                if pattern == "from_free_kick":
                    g = round(g * 0.6, 4)
                add("shot", None, (PITCH_X, GOAL_Y), g, 1.0, 0.01, "head" if header else "foot")
                opts[-1]["hidden"] = hidden
            if pattern not in PASS_ONLY and pattern != "from_free_kick" and carrier["line"] != "gk" and not aerial:
                # a dribble is a one-on-one duel: technique and pace against the nearest defender's defending
                rival, edge = None, 0.0
                if pressure > 0.3:
                    rival = self.nearest(1 - t, self.ball, outfield=False)
                    edge = carrier["technique"] - rival["defending"] + 0.1 * (carrier["max_speed"] - rival["max_speed"])
                for dy in (-7, 0, 7):
                    tgt = (min(b[0] + 8, PITCH_X - 1), clamp(b[1] + dy, 1, PITCH_Y - 1))
                    crowd = sum(1 for o in opp if dist(o, tgt) < 6)
                    ps = 0.82 - 0.55 * pressure - 0.09 * crowd - (0.45 if in_box(tgt) else 0) + 0.15 * edge
                    ps = round(clamp(ps, 0.08, 0.9), 4)
                    add("dribble" if pressure > 0.3 else "carry", None, tgt, ps, both(*tgt), turnover_risk,
                        rival=rival)
        for o in opts:
            o["ev"] = round(o["p_success"] * o["value_if_success"] - (1 - o["p_success"]) * o["risk_if_fail"], 4)
        return opts, pressure, here

    def choose(self, carrier, opts):
        prof = PROFILES[carrier["profile"]]
        best = max(opts, key=lambda o: o["ev"])
        ranked = sorted(opts, key=lambda o: o["ev"])
        worse = [o for o in ranked if best["ev"] - o["ev"] > 0.002]
        if worse and self.rng.random() < prof["mistake_rate"]:
            # a real player's mistake is a choice that also looks good in the moment (the square pass instead
            # of the shot, the safe ball instead of the through ball), not a near-hopeless dribble into a
            # defender or a 50-metre pass back from the six-yard box
            w = [o["p_success"] * math.exp(o["ev"] / MISTAKE_TEMP)
                 * (MISTAKE_DRIBBLE if o["option_type"] in ("dribble", "carry") else 1) for o in worse]
            if sum(w) > 0:
                return self.rng.choices(worse, weights=w)[0], True
        b = to_af(self.ball, carrier["team_idx"])
        u = self.urgency(carrier["team_idx"])   # chasing the game: more shots, crosses, long balls, dribbles
        scores = []
        for o in opts:
            if o["option_type"] == "shot":
                bias = prof["shot_bias"] + (prof["long_shot_bias"] if goal_distance(b) > 16.5 else 0) + 0.012 * u
            elif o["option_type"] in ("dribble", "carry"):
                bias = prof["dribble_bias"] + 0.008 * u
            elif o["option_type"] == "cross":
                bias = prof.get("cross_bias", 0.0) + 0.006 * u
            elif o["option_type"] == "long_ball":
                bias = prof.get("long_ball_bias", 0.0) + 0.006 * u
                if carrier["line"] == "gk" and b[0] < 7:
                    bias += GOAL_KICK_LONG
            else:
                bias = 0
            plan = self.plan[carrier["team_idx"]]
            tx, ty = o["target"]
            if o["option_type"] != "shot" and tx > 45 and (ty < GOAL_Y - 8 if plan["target_flank"] == "right"
                                                            else ty > GOAL_Y + 8):
                bias += 0.005   # the game plan: go at their weaker full-back
            if o["option_type"] == "pass":   # players like the short ball along the ground
                bias -= SHORT_PREF * max(0.0, dist(b, o["target"]) - SHORT_FROM) / 10
            if o["option_type"] == "pass" and abs(ty - GOAL_Y) > WIDE_LANE and tx < WIDE_X:
                bias += WIDE_BIAS   # teams build up through the flanks, where there is time on the ball
            if o["option_type"] == "cross" and plan["aerial_threat"]:
                bias += 0.008
            scores.append((o["perceived_ev"] + bias) / prof["temperature"])
        m = max(scores)
        w = [math.exp(s - m) for s in scores]
        return self.rng.choices(opts, weights=w)[0], False

    # ---------- recording ----------
    def record(self, player, etype, start, end, outcome, recipient="", pressure=0.0, extra=None):
        self.eid += 1
        event_id = f"e_{self.eid:05d}"
        minute, second = divmod(int(self.clock), 60)
        vx, vy = self.vel[player["player_id"]]
        row = {
            "event_id": event_id, "match_id": self.match_id, "period": self.period,
            "minute": minute, "second": second, "ts_ms": int(round(self.real_t * 1000)),
            "possession_id": self.possession_id, "team_id": player["team_id"], "player_id": player["player_id"],
            "player_name": player["name"], "type": etype, "play_pattern": "", "body_part": "",
            "x": round(start[0], 1), "y": round(start[1], 1), "end_x": round(end[0], 1), "end_y": round(end[1], 1),
            "outcome": outcome, "recipient_id": recipient, "under_pressure": pressure > 0.3,
            "actor_speed_kmh": round(math.hypot(vx, vy) * 3.6, 1),
            "score_home": self.score[0], "score_away": self.score[1],
        }
        if extra:
            row.update(extra)
        self.events.append(row)
        if dist(start, end) > 0.5:  # the player on the ball faces where they play it
            self.facing[player["player_id"]] = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
        for p in self.active():
            pid = p["player_id"]
            px, py = self.pos[pid]
            fvx, fvy = self.vel[pid]
            self.frames.append({"event_id": event_id, "player_id": pid, "team_id": p["team_id"],
                                "x": round(px, 1), "y": round(py, 1), "vx": round(fvx, 2), "vy": round(fvy, 2),
                                "facing_deg": round(self.facing[pid]),
                                "is_actor": p is player, "is_keeper": p["role"] == "GK"})
        return event_id

    def clear_and_recover(self, rival, spot, t, kind):
        """A defender heads a lofted ball away; whoever reaches the second ball first wins it."""
        r_af = to_af(spot, rival["team_idx"])
        reach = self.rng.uniform(12, 25) if kind == "cross" else self.rng.uniform(8, 18)
        loose_af = (clamp(r_af[0] + reach, 3, PITCH_X - 3), clamp(r_af[1] + self.rng.gauss(0, 8), 2, PITCH_Y - 2))
        loose = to_af(loose_af, rival["team_idx"])
        self.record(rival, "clearance", spot, loose, "success", extra={"body_part": "head"})
        return self.loose_ball(spot, loose, t, SECOND_BALL_KEEP, 2.2, flight_time(reach))

    def loose_ball(self, frm, spot, t, keep, z0=0.0, seconds=None):
        """The ball runs loose from frm to spot; the nearest player of the side that gets there first wins it."""
        winner = self.nearest(t if self.rng.random() < keep else 1 - t, spot)
        tg = self.targets(spot, t)
        tg[winner["player_id"]] = spot
        path, duration = self.lofted_path(frm, spot, z0, 0.0, seconds or max(0.5, flight_time(dist(frm, spot)) * 0.6))
        self.advance(duration, tg, frm, path=path)
        self.run_to(winner["player_id"], spot, winner["team_idx"])
        self.gain(winner["team_idx"])
        self.record(winner, "ball_recovery", spot, spot, "success")
        return winner

    def place_shot(self, base, shooter, t):
        """Spot (y, z) in the goal for a shot on target and its xGOT: the chance it scores given where it goes
        and where the keeper stands. `base` is the mean chance of an on-target shot from this chance (xG / chance
        of hitting the target); a corner far from the keeper scores more, a shot at the keeper less.
        Better finishers hit the corners a little more often."""
        r = self.rng
        keeper = next((p for p in self.active(1 - t) if p["line"] == "gk"), None)
        ky = to_af(self.pos[keeper["player_id"]], t)[1] if keeper else GOAL_Y
        ky = clamp(ky, GOAL_Y - GOAL_HALF_WIDTH, GOAL_Y + GOAL_HALF_WIDTH)
        skill = 1 - 0.4 * (shooter["technique"] - 0.5)
        y = GOAL_Y + r.uniform(-1, 1) * (GOAL_HALF_WIDTH - 0.15)
        z = 0.1 + r.random() ** 1.1 * (CROSSBAR - 0.2)
        # how hard the spot is to reach: sideways from the keeper and away from his waist height
        side = clamp(abs(y - ky) / (2 * GOAL_HALF_WIDTH), 0, 1)
        height = clamp(abs(z - 1.0) / 1.3, 0, 1)
        corner = clamp((0.7 * side ** skill + 0.3 * height ** skill) * 1.6, 0, 1)
        xgot = clamp(base * (1 - XGOT_SPREAD / 2 + XGOT_SPREAD * corner), 0.01, XGOT_MAX)
        return y, z, round(xgot, 4)

    def shot_end(self, outcome, start, t):
        """Where a shot ends (world frame) and at what height: in the net, at the keeper, wide or over,
        against the woodwork, or at the defender who blocks it."""
        r = self.rng
        if outcome == "goal":
            y, z = GOAL_Y + r.uniform(-3.4, 3.4), r.uniform(0.1, 2.3)
        elif outcome == "saved":
            y, z = GOAL_Y + r.uniform(-3.0, 3.0), r.uniform(0.2, 2.0)
        elif outcome == "post":
            if r.random() < 0.7:
                y, z = GOAL_Y + r.choice((-1, 1)) * GOAL_HALF_WIDTH, r.uniform(0.2, CROSSBAR)
            else:
                y, z = GOAL_Y + r.uniform(-3.5, 3.5), CROSSBAR
        elif outcome == "off_target":
            if r.random() < 0.6:   # wide
                y, z = GOAL_Y + r.choice((-1, 1)) * r.uniform(3.9, 9), r.uniform(0.1, 2.5)
            else:                  # over
                y, z = GOAL_Y + r.uniform(-3.6, 3.6), r.uniform(2.6, 5.0)
        else:   # blocked by the defender nearest the shot's path
            s_af = to_af(start, t)
            blocker = min((p for p in self.active(1 - t) if p["line"] != "gk"),
                          key=lambda p: seg_point_dist(to_af(self.pos[p["player_id"]], t), s_af, (PITCH_X, GOAL_Y)))
            spot = closest_on_segment(to_af(self.pos[blocker["player_id"]], t), s_af, (PITCH_X, GOAL_Y))
            return to_af(spot, t), r.uniform(0.2, 1.2)
        past = WIDE_PAST_M if outcome == "off_target" else 0.0   # a miss goes on past the line, it does not stop on it
        return to_af((PITCH_X + past, y), t), z

    def nearest(self, team_idx, point, outfield=True):
        pool = [p for p in self.active(team_idx) if not outfield or p["line"] != "gk"]
        return min(pool, key=lambda p: dist(self.pos[p["player_id"]], point))

    def gain(self, team_idx, force=False):
        """A new possession starts only when the other team gets the ball (or at a kick-off)."""
        if force or team_idx != self.poss_team:
            self.possession_id += 1
            self.poss_team = team_idx

    # ---------- discipline and substitutions ----------
    def book(self, offender, spot):
        """Possibly show a card after a foul; a red card removes the player."""
        r = self.rng.random()
        if r < CARDS["straight_red_per_foul"]:
            card = "red_card"
        elif r < CARDS["straight_red_per_foul"] + (CARDS["second_yellow_per_foul"] if offender["yellow"]
                                                   else CARDS["yellow_per_foul"]):
            offender["yellow"] += 1
            card = "red_card" if offender["yellow"] == 2 else "yellow_card"
        else:
            return
        self.record(offender, "card", spot, spot, card)
        if card == "red_card":
            offender["on"] = False
            offender["minute_off"] = int(self.clock // 60)
            self.reshape(offender, spot)

    def reshape(self, sent_off, spot):
        """After a red card the team drops into a shape for the players it has left."""
        t = sent_off["team_idx"]
        outfield = [p for p in self.active(t) if p["line"] != "gk"]
        if len(outfield) in SHORT_HANDED:
            self.reshape_to(t, *SHORT_HANDED[len(outfield)], sent_off, "red_card", spot)

    def reshape_to(self, t, name, slots, actor, reason, spot=None):
        """Move the outfield players into a new shape: each slot goes to the player whose old position is nearest."""
        free = [p for p in self.active(t) if p["line"] != "gk"]
        for role, hx, hy in sorted(slots, key=lambda s: s[1]):   # fill the back line first
            p = min(free, key=lambda p: dist(p["home"], (hx, hy)))
            free.remove(p)
            self.assign(p, role, (hx, hy))
        self.formation_changes.append({"minute": int(self.clock // 60), "team_id": self.teams[t]["team_id"],
                                       "from": self.formation[t], "to": name, "reason": reason})
        self.formation[t] = name
        spot = spot or self.pos[actor["player_id"]]
        self.record(actor, "formation_change", spot, spot, name)

    def make_subs(self):
        for t in (0, 1):
            while self.sub_plan[t] and self.clock / 60 >= self.sub_plan[t][0]:
                self.sub_plan[t].pop(0)
                tired = [p for p in self.active(t) if p["line"] in ("mid", "fwd")]
                if tired:
                    self.substitute(max(tired, key=lambda p: self.distance[p["player_id"]]))

    def substitute(self, off):
        """Bring on the bench player who fits the leaving player's slot best."""
        t = off["team_idx"]
        pool = [p for p in self.bench[t] if p["position"] != "GK"] if off["role"] != "GK" else self.bench[t]
        if not pool or self.subs_used[t] >= MAX_SUBS:
            return None
        new = best_fit(pool, off["role"])
        self.bench[t].remove(new)
        self.subs_used[t] += 1
        self.assign(new, off["role"], off["home"])
        new["on"], new["minute_on"] = True, int(self.clock // 60)
        touchline = to_af((HALFWAY, 0.5), t)
        self.init_state(new, touchline)
        self.players.append(new)
        self.by_id[new["player_id"]] = new
        self.record(off, "substitution", self.pos[off["player_id"]], touchline, "substitution", new["player_id"])
        off["on"] = False
        off["minute_off"] = int(self.clock // 60)
        return new

    # ---------- restarts ----------
    def set_restart(self, kind, team_idx, spot_af=None):
        """Place the ball for a restart; returns (carrier, play pattern, mode)."""
        self.treat_injuries()
        self.make_subs()
        self.update_stance()
        if kind == "from_kick_off":
            spot_af = (52.5, 34.0)
        elif kind == "from_goal_kick":
            spot_af = (6.0, 34.0)
        elif kind == "from_penalty":
            spot_af = (94.0, 34.0)
        spot = to_af(spot_af, team_idx)
        if kind == "from_kick_off":
            carrier = self.pick(team_idx, ["ST", "AM", "CM"], spot)
        elif kind == "from_goal_kick":
            carrier = self.pick(team_idx, ["GK"], spot)
        elif kind == "from_penalty":
            carrier = self.pick(team_idx, ["ST", "RW", "LW", "AM"], spot)
        elif kind == "from_corner":
            carrier = self.pick(team_idx, ["CM", "AM", "RM", "LM", "DM"], spot)
        else:
            carrier = self.nearest(team_idx, spot)
        mode = "corner" if kind == "from_corner" else "kick_off" if kind == "from_kick_off" else "set"
        # players reposition during the stoppage (not recorded as tracking)
        # at a goal kick both teams set up for the long kick, as if the ball were already further out
        shape = to_af((GOAL_KICK_SHAPE_X, GOAL_Y), team_idx) if kind == "from_goal_kick" else spot
        tg = self.targets(shape, team_idx, mode if mode != "set" else "open")
        tg[carrier["player_id"]] = spot
        self.advance(self.rng.uniform(*STOPPAGE_S[kind]), tg, spot, record=False)
        self.pos[carrier["player_id"]] = spot
        self.ball = spot
        self.ball_z = 0.0
        self.gain(team_idx, force=kind == "from_kick_off")
        return carrier, kind, mode

    # ---------- simulation ----------
    def simulate(self):
        halves = [(1, 0, 2700 + self.rng.uniform(60, 180)), (2, 2700, 5400 + self.rng.uniform(120, 300))]
        for period, start, half_end in halves:
            self.period, self.clock = period, start
            attacking = 0 if period == 1 else 1
            carrier, pattern, mode = self.set_restart("from_kick_off", attacking)
            header_chance = 0.0
            while self.clock < half_end:
                attacking = carrier["team_idx"]
                tg = self.targets(self.ball, attacking, mode)
                tg[carrier["player_id"]] = self.pos[carrier["player_id"]]
                hold = (self.rng.uniform(1.5, 3.0) if pattern != "open_play"
                        else clamp(self.rng.lognormvariate(math.log(HOLD_S), 0.6), 0.3, 4.0))
                if header_chance:
                    hold = self.rng.uniform(0.2, 0.5)  # the cross is met first time
                if pattern == "open_play" and not header_chance:
                    # in open play the player takes the ball with him while he looks up: a few metres forward,
                    # away from the nearest opponent (short of a carry, CARRY_MIN_M in the detector)
                    me = to_af(self.pos[carrier["player_id"]], attacking)
                    rival = to_af(self.pos[self.nearest(1 - attacking, self.pos[carrier["player_id"]])["player_id"]], attacking)
                    fx, fy, gap = FIRST_TOUCH_AHEAD, 0.0, dist(me, rival)
                    if 1e-6 < gap < 8:
                        fx, fy = fx + 0.8 * (me[0] - rival[0]) / gap, fy + 0.8 * (me[1] - rival[1]) / gap
                    norm = math.hypot(fx, fy) or 1.0
                    step = min(FIRST_TOUCH_M, FIRST_TOUCH_MS * hold)
                    tg[carrier["player_id"]] = to_af((clamp(me[0] + fx / norm * step, 3, PITCH_X - 3),
                                                      clamp(me[1] + fy / norm * step, 2, PITCH_Y - 2)), attacking)
                    self.advance(hold, tg, self.ball, dribbler=carrier["player_id"])
                else:
                    self.advance(hold, tg, self.ball, self.ball)
                self.ball = self.pos[carrier["player_id"]]
                mode = "open"
                opts, pressure, here = self.build_options(carrier, pattern, header_chance)
                if not opts:   # nobody close enough to head it to: he brings it down instead
                    opts, pressure, here = self.build_options(carrier, pattern, 0.0)
                chosen, mistake = self.choose(carrier, opts)
                best = max(opts, key=lambda o: o["ev"])
                worst = min(o["ev"] for o in opts)
                # the code's safest good option: the best score among options that usually come off
                safe = [o for o in opts if o["p_success"] >= SAFE_P]
                safe_best = max(safe, key=lambda o: o["ev"]) if safe else None
                t = attacking
                start_pt = self.ball
                end = to_af(chosen["target"], t)
                kind = chosen["option_type"]
                if kind in ("cross", "long_ball"):
                    # the wind carries a lofted ball off its intended spot
                    k = WIND_PUSH * flight_time(dist(start_pt, end)) * self.rng.uniform(0.6, 1.2)
                    end = (clamp(end[0] + self.wind[0] * k, 0.5, PITCH_X - 0.5),
                           clamp(end[1] + self.wind[1] * k, 0.5, PITCH_Y - 0.5))
                etype = "pass" if kind in ("cross", "long_ball") else kind
                success = self.rng.random() < chosen["p_success"]
                length = dist(start_pt, end)
                regret = round(best["ev"] - chosen["ev"], 4)
                spread = best["ev"] - worst
                extra = {"play_pattern": pattern, "body_part": chosen["body_part"],
                         "chosen_ev": chosen["ev"], "best_ev": best["ev"], "regret": regret,
                         "regret_rel": round((best["ev"] - chosen["ev"]) / spread, 3) if spread > 1e-4 else 0.0,
                         "injected_mistake": mistake, "opponent_id": chosen["opponent_id"],
                         "safe_best_ev": safe_best["ev"] if safe_best else ""}
                if etype == "pass":
                    speed = clamp(28 + 1.3 * length + self.rng.gauss(0, 6), 25, 105)
                    extra.update(pass_type={"cross": "cross", "long_ball": "long"}.get(kind, "ground"),
                                 pass_length_m=round(length, 1),
                                 pass_difficulty=round((1 - chosen["p_success"]) * 10, 1),
                                 ball_speed_kmh=round(speed, 1))
                    duration = length / (speed / 3.6)
                elif etype == "shot":
                    speed = clamp(100 - 0.8 * length + self.rng.gauss(0, 10), 45, 125)
                    if chosen["body_part"] == "head":
                        speed = clamp(speed * 0.55, 30, 75)
                    extra.update(ball_speed_kmh=round(speed, 1), xg=chosen["p_success"])
                    duration = length / (speed / 3.6)
                else:
                    duration = length / self.rng.uniform(5.0, 6.5)
                    extra.update(ball_speed_kmh=round(length / duration * 3.6, 1))
                if etype == "shot":
                    # a shot is blocked more often when defenders hide more of the goal
                    endings = dict(SHOT_ENDINGS, blocked=SHOT_BLOCKED[0] + SHOT_BLOCKED[1] * chosen.get("hidden", 0))
                    xgot = None
                    # the chance a shot is on target follows from xG and the usual mix of misses
                    w_all = sum(endings.values())
                    p_on = chosen["p_success"] + (1 - chosen["p_success"]) * endings["saved"] / w_all
                    if self.rng.random() > p_on:
                        misses = {k: v for k, v in endings.items() if k != "saved"}
                        outcome = self.rng.choices(list(misses), weights=list(misses.values()))[0]
                        end, shot_z = self.shot_end(outcome, start_pt, t)
                    else:
                        # on target: pick the spot in the goal; corners away from the keeper score more
                        gy, shot_z, xgot = self.place_shot(chosen["p_success"] / p_on, carrier, t)
                        outcome = "goal" if self.rng.random() < xgot else "saved"
                        end = to_af((PITCH_X, gy), t)
                    extra["xgot"] = xgot if xgot is not None else ""
                    extra["end_z"] = round(shot_z, 2)
                    duration = max(0.15, dist(start_pt, end) / (speed / 3.6))
                elif chosen["offside"]:
                    outcome = "offside"
                else:
                    outcome = "success" if success else "fail"
                # shots are judged now; other actions once we know where the ball ended up (below)
                extra["delta_value"] = round((1.0 if outcome == "goal" else 0.0) - here, 4)
                eid = self.record(carrier, etype, start_pt, end, outcome,
                                  chosen["target_player_id"] if etype == "pass" else "", pressure, extra)
                row = self.events[-1]
                if etype == "shot":
                    # expected assist: the completed pass that set up this shot carries the shot's xG
                    prev = next((e for e in reversed(self.events[:-1]) if e["type"] not in ("carry",)), None)
                    if (prev and prev["type"] == "pass" and prev["outcome"] == "success"
                            and prev["recipient_id"] == carrier["player_id"]):
                        prev["xa"] = row["xg"]
                for i, o in enumerate(opts):
                    o["option_id"] = f"{eid}_o{i:02d}"
                for key, o in (("chosen", chosen), ("best", best), ("safe_best", safe_best)):
                    # the three options a decision is judged by, with the parts of their score
                    row[key + "_option_id"] = o["option_id"] if o else ""
                    row[key + "_option_type"] = o["option_type"] if o else ""
                    for part in ("p_success", "value_if_success", "risk_if_fail"):
                        row[f"{key}_{part}"] = o[part] if o else ""
                for i, o in enumerate(opts):
                    tx, ty = to_af(o["target"], t)
                    self.options.append({
                        "event_id": eid, "option_id": f"{eid}_o{i:02d}", "option_type": o["option_type"],
                        "target_player_id": o["target_player_id"], "target_x": round(tx, 1),
                        "target_y": round(ty, 1), "p_success": o["p_success"],
                        "value_if_success": o["value_if_success"], "risk_if_fail": o["risk_if_fail"],
                        "difficulty": round((1 - o["p_success"]) * 10, 1),
                        "ev": o["ev"], "offside": o["offside"], "is_chosen": o is chosen, "is_best": o is best,
                        "is_safe_best": o is safe_best})

                # execute the action with continuous movement
                tg = self.targets(end, t)
                pattern, header_chance = "open_play", 0.0
                if etype == "pass":
                    receiver = self.by_id[chosen["target_player_id"]]
                    tg[receiver["player_id"]] = end
                    tg[carrier["player_id"]] = self.pos[carrier["player_id"]]
                    # lofted balls fly (some drop and bounce first), headers start at head height,
                    # ground passes roll and slow down
                    if kind in ("cross", "long_ball"):
                        bounce = 0.8 if kind == "long_ball" and self.rng.random() < 0.4 else None
                        curl = clamp(self.rng.gauss(0, 0.03 * length), -3, 3)
                        path, duration = self.lofted_path(start_pt, end, 0.0, 2.0, flight_time(length), curl, bounce)
                    elif chosen["body_part"] == "head":
                        path, duration = self.lofted_path(start_pt, end, 2.2, 0.0, max(0.4, duration))
                    else:
                        path, duration = self.ground_path(start_pt, end, speed / 3.6)
                    rival = self.by_id.get(chosen["opponent_id"]) if kind in ("cross", "long_ball") else None
                    if rival is not None and rival["on"] and outcome != "offside":
                        # aerial duel: both players attack the dropping ball; who gets there better placed
                        # (closer than planned) gains an edge on top of height and strength
                        tg[rival["player_id"]] = end
                        before = dist(self.pos[rival["player_id"]], end) - dist(self.pos[receiver["player_id"]], end)
                        self.advance(duration, tg, start_pt, path=path, arrive=(receiver["player_id"], rival["player_id"]))
                        after = dist(self.pos[rival["player_id"]], end) - dist(self.pos[receiver["player_id"]], end)
                        success = self.rng.random() < clamp(chosen["p_success"] + 0.02 * clamp(after - before, -4, 4), 0.03, 0.9)
                        row["outcome"] = outcome = "success" if success else "fail"
                    else:
                        self.advance(duration, tg, start_pt, path=path, arrive=(receiver["player_id"],))
                    end_af = to_af(end, t)
                    if outcome == "offside":
                        carrier, pattern, mode = self.set_restart("from_free_kick", 1 - t, to_af(end, 1 - t))
                    elif success:
                        if dist(self.pos[receiver["player_id"]], end) > RECEIVE_M:
                            self.run_to(receiver["player_id"], end, t)   # not there yet: he runs onto it, no jump
                        self.pos[receiver["player_id"]] = end
                        carrier = receiver
                        self.ball = end
                        if kind == "cross":
                            header_chance = 0.7
                        elif kind == "long_ball" and self.rng.random() < HEAD_ON:
                            header_chance = 1.0
                        else:
                            # a heavy first touch with an opponent right there: he nicks it away
                            rival = self.nearest(1 - t, end)
                            if dist(self.pos[rival["player_id"]], end) < MISCONTROL[0] and self.rng.random() < MISCONTROL[1]:
                                self.run_to(rival["player_id"], end, 1 - t)
                                self.gain(1 - t)
                                self.record(rival, "ball_recovery", end, end, "success")
                                carrier = rival
                    elif end_af[0] > 88 and self.rng.random() < CORNER_FROM_CROSS:
                        side = 0.3 if end_af[1] < GOAL_Y else PITCH_Y - 0.3
                        carrier, pattern, mode = self.set_restart("from_corner", t, (PITCH_X - 0.3, side))
                    elif kind != "cross" and end_af[0] > PITCH_X - BYLINE_X and self.rng.random() < BYLINE_P:
                        carrier, pattern, mode = self.set_restart("from_goal_kick", 1 - t)
                    elif self.rng.random() < OUT_P or end_af[1] < 2 or end_af[1] > PITCH_Y - 2:
                        side = 0.3 if end_af[1] < GOAL_Y else PITCH_Y - 0.3
                        spot_af = to_af((clamp(end_af[0], 1, PITCH_X - 1), side), t)
                        carrier, pattern, mode = self.set_restart("from_throw_in", 1 - t, to_af(spot_af, 1 - t))
                    elif kind in ("cross", "long_ball"):
                        # lofted ball: the defender who contested it wins it in the air where it comes down
                        rival = self.by_id.get(chosen["opponent_id"]) or self.nearest(1 - t, end, outfield=False)
                        if not rival["on"]:
                            rival = self.nearest(1 - t, end, outfield=False)
                        self.run_to(rival["player_id"], end, 1 - t)
                        if rival["line"] == "gk":   # the keeper claims it
                            self.ball = end
                            self.gain(1 - t)
                            self.record(rival, "interception", end, end, "success")
                            carrier, pattern = rival, "from_keeper"
                        else:
                            carrier = self.clear_and_recover(rival, end, t, kind)
                    else:
                        # ground pass: the opponent closest to the ball's path cuts it out on the way
                        winner = min(self.active(1 - t), key=lambda p: seg_point_dist(
                            self.pos[p["player_id"]], start_pt, end))
                        spot = closest_on_segment(self.pos[winner["player_id"]], start_pt, end)
                        self.run_to(winner["player_id"], spot, 1 - t)
                        self.gain(1 - t)
                        self.record(winner, "interception", spot, spot, "success")
                        carrier = winner
                elif etype in ("dribble", "carry"):
                    tg[carrier["player_id"]] = end
                    rival = self.by_id.get(chosen["opponent_id"])
                    if rival is not None and rival["on"]:
                        # the duel is played out: the defender chases the dribbler and the challenge happens
                        # when (and where) he gets close enough, decided by the odds plus who is quicker at
                        # that moment; without contact, the crowd around the ball still decides at the end
                        success, elapsed, cid, rid = None, 0.0, carrier["player_id"], rival["player_id"]
                        while elapsed < duration - 1e-9:
                            tg[rid] = self.pos[cid]
                            step = min(0.2, duration - elapsed)
                            self.advance(step, tg, start_pt, dribbler=cid)
                            elapsed += step
                            if dist(self.pos[rid], self.pos[cid]) < CONTACT_M:
                                edge = math.hypot(*self.vel[cid]) - math.hypot(*self.vel[rid])
                                success = self.rng.random() < clamp(chosen["p_success"] + 0.04 * edge, 0.03, 0.97)
                                if success and duration - elapsed > 1e-9:
                                    tg.pop(rid)   # beaten: the dribbler carries on
                                    self.advance(duration - elapsed, tg, start_pt, dribbler=cid)
                                break
                        if success is None:
                            success = self.rng.random() < chosen["p_success"]
                        row["outcome"] = outcome = "success" if success else "fail"
                    else:
                        self.advance(duration, tg, start_pt, dribbler=carrier["player_id"])
                    if success:
                        self.ball = self.pos[carrier["player_id"]]
                    else:
                        spot = self.pos[carrier["player_id"]]
                        tackler = self.by_id.get(chosen["opponent_id"]) or self.nearest(1 - t, spot)
                        box = in_box(to_af(spot, t))
                        # failed dribble ends in a foul; inside their own box defenders are far more careful
                        if self.rng.random() < FOUL_ON_TACKLE[1 if box else 0]:
                            self.record(tackler, "foul", spot, spot, "foul_committed")
                            if self.rng.random() < INJURY_PER_FOUL:
                                self.injured.append(carrier["player_id"])
                            self.book(tackler, spot)
                            kind_r = "from_penalty" if box else "from_free_kick"
                            carrier, pattern, mode = self.set_restart(kind_r, t, to_af(spot, t))
                        else:
                            self.gain(1 - t)
                            self.run_to(tackler["player_id"], spot, 1 - t)
                            self.record(tackler, "tackle", spot, spot, "success")
                            carrier = tackler
                else:  # shot
                    header = chosen["body_part"] == "head"
                    curl = 0.0 if header else clamp(self.rng.gauss(0, 0.03 * length), -2.5, 2.5)   # swerve
                    path, duration = self.lofted_path(start_pt, end, 2.2 if header else 0.1,
                                                      shot_z, duration / (1 - (1 - AIR_KEEP) / 2), curl)
                    self.advance(duration, tg, start_pt, path=path)
                    end_af = to_af(end, t)
                    if outcome == "goal":
                        self.score[t] += 1
                        # the ball ends in the net, a metre behind the line (tracking shows it crossing)
                        net = to_af((PITCH_X + NET_DEPTH, end_af[1]), t)
                        self.advance(0.3, tg, end, path=lambda s: (end[0] + (net[0] - end[0]) * min(1, s / 0.3),
                                                                   end[1], shot_z * max(0, 1 - s / 0.3)))
                        self.record(carrier, "goal", end, end, "goal")
                        self.advance(self.rng.uniform(35, 60), self.targets((52.5, 34.0), 1 - t, "kick_off"),
                                     (52.5, 34.0), record=False)
                        carrier, pattern, mode = self.set_restart("from_kick_off", 1 - t)
                    elif outcome == "off_target":
                        carrier, pattern, mode = self.set_restart("from_goal_kick", 1 - t)
                    elif outcome == "post":
                        # off the woodwork: the ball comes back into play and is a loose ball
                        rebound = to_af((PITCH_X - self.rng.uniform(4, 14), clamp(end_af[1] + self.rng.gauss(0, 8), 10, 58)), t)
                        carrier = self.loose_ball(end, rebound, t, 0.3, shot_z)
                    elif outcome == "saved" and self.rng.random() < clamp(0.8 - 0.006 * (speed - 60), 0.35, 0.9):
                        # the keeper holds it (harder the faster the shot)
                        keeper = self.pick(1 - t, ["GK"])
                        self.gain(1 - t)
                        self.ball = self.pos[keeper["player_id"]]
                        carrier, pattern = keeper, "from_keeper"
                    elif self.rng.random() < CORNER_FROM_SHOT:
                        side = 0.3 if to_af(start_pt, t)[1] < GOAL_Y else PITCH_Y - 0.3
                        carrier, pattern, mode = self.set_restart("from_corner", t, (PITCH_X - 0.3, side))
                    else:
                        # the keeper spills it or the block deflects it: a rebound for whoever gets there first
                        rebound = to_af((PITCH_X - self.rng.uniform(3, 12) if outcome == "saved" else end_af[0] - self.rng.uniform(2, 8),
                                         clamp(end_af[1] + self.rng.gauss(0, 7), 8, 60)), t)
                        carrier = self.loose_ball(end, rebound, t, 0.25 if outcome == "saved" else 0.2, shot_z)
                if etype != "shot":
                    # threat of the ball's new spot: ours if we kept it, the opponent's if we lost it
                    b_af = to_af(self.ball, t)
                    after = xt(*b_af) if carrier["team_idx"] == t else -xt(PITCH_X - b_af[0], PITCH_Y - b_af[1])
                    row["delta_value"] = round(after - here, 4)
        for p in self.active():
            p["minute_off"] = int(self.clock // 60)

    # ---------- criticality ----------
    def rank_critical(self, top_n=15):
        decisions = [e for e in self.events if "regret" in e]
        for e in decisions:
            gap = abs(e["score_home"] - e["score_away"])
            w_score = 1.5 if gap == 0 else 1.2 if gap == 1 else 0.7
            w_time = 1 + max(0, e["minute"] - 60) / 30
            e["criticality"] = round(abs(e["delta_value"]) * w_score * w_time + 4.0 * e["regret"]
                                     + 0.3 * e["regret_rel"], 4)
        picked = {e["event_id"]: e for e in sorted(decisions, key=lambda d: d["criticality"], reverse=True)[:top_n]}
        # the decisions behind each goal: the best build-up actions of the scoring attack, plus the
        # opponent's mistake if the attack began by winning the ball back. An attack runs back through
        # set pieces the scoring team won (a corner, a free kick) until the opponent last had the ball.
        on_ball = ("pass", "shot", "dribble", "carry", "interception", "tackle", "ball_recovery")
        for i, e in enumerate(self.events):
            if "regret" not in e or e["outcome"] != "goal":
                continue
            attack, j = [], i
            while j >= 0:
                x = self.events[j]
                if x["period"] != e["period"] or (x["team_id"] != e["team_id"] and x["type"] in on_ball):
                    break
                if x["team_id"] == e["team_id"] and "regret" in x:
                    attack.append(x)
                j -= 1
            for d in sorted(attack, key=lambda d: d["delta_value"], reverse=True)[:3]:
                d["goal_chain_of"], d["chain_role"] = e["event_id"], "build_up"
                picked.setdefault(d["event_id"], d)
            first = self.events[j + 1]
            if first["type"] in ("interception", "tackle", "ball_recovery") and j >= 0 and "regret" in self.events[j]:
                lost = self.events[j]
                lost["goal_chain_of"], lost["chain_role"] = e["event_id"], "turnover_conceded"
                picked.setdefault(lost["event_id"], lost)
        out = []
        for e in sorted(picked.values(), key=lambda d: d["criticality"], reverse=True):
            good = e["regret"] < 0.01 and e["regret_rel"] < 0.25
            positive = e["delta_value"] >= 0
            label = ("deserved" if good and positive else "unlucky" if good else
                     "lucky" if positive else "missed_opportunity")
            out.append({"event_id": e["event_id"], "minute": e["minute"], "second": e["second"],
                        "team_id": e["team_id"], "player_id": e["player_id"], "player_name": e["player_name"],
                        "type": e["type"], "pass_type": e.get("pass_type", ""), "play_pattern": e["play_pattern"],
                        "outcome": e["outcome"], "score_home": e["score_home"], "score_away": e["score_away"],
                        **{f"{k}_{part}": e[f"{k}_{part}"] for k in ("chosen", "best", "safe_best")
                           for part in ("option_id", "option_type", "p_success", "value_if_success", "risk_if_fail")},
                        "chosen_ev": e["chosen_ev"], "best_ev": e["best_ev"], "safe_best_ev": e["safe_best_ev"],
                        "regret": e["regret"], "regret_rel": e["regret_rel"], "delta_value": e["delta_value"],
                        "criticality": e["criticality"], "label": label, "goal_chain_of": e.get("goal_chain_of", ""),
                        "chain_role": e.get("chain_role", ""), "injected_mistake": e["injected_mistake"]})
        return out

    # ---------- per-player summary ----------
    def player_stats(self):
        rows = []
        for p in self.players:
            pid = p["player_id"]
            mine = [e for e in self.events if e["player_id"] == pid]
            passes = [e for e in mine if e["type"] == "pass"]
            shots = [e for e in mine if e["type"] == "shot"]
            decisions = [e for e in mine if "regret" in e]
            ok = [e for e in passes if e["outcome"] == "success"]
            cards = [e["outcome"] for e in mine if e["type"] == "card"]
            rows.append({
                "player_id": pid, "player_name": p["name"], "team_id": p["team_id"], "role": p["role"],
                "started": p["started"], "minute_on": p["minute_on"], "minute_off": p["minute_off"],
                "minutes_played": p["minute_off"] - p["minute_on"],
                "passes": len(passes), "pass_accuracy": round(len(ok) / len(passes), 3) if passes else "",
                "crosses": sum(1 for e in passes if e.get("pass_type") == "cross"),
                "avg_pass_length_m": round(sum(e["pass_length_m"] for e in passes) / len(passes), 1) if passes else "",
                "avg_pass_difficulty": round(sum(e["pass_difficulty"] for e in passes) / len(passes), 2) if passes else "",
                "offsides": sum(1 for e in self.events if e["recipient_id"] == pid and e["outcome"] == "offside"),
                "shots": len(shots), "xg": round(sum(e["xg"] for e in shots), 2),
                "xgot": round(sum(e["xgot"] for e in shots if e.get("xgot") not in (None, "")), 2),
                "goals": sum(1 for e in shots if e["outcome"] == "goal"),
                "xa": round(sum(e.get("xa") or 0 for e in passes), 2),
                "goals_prevented": (round(sum(e["xgot"] for e in self.events if e["type"] == "shot"
                                              and e.get("xgot") not in (None, "") and e["team_id"] != p["team_id"]
                                              and p["minute_on"] <= e["minute"] < p["minute_off"])
                                          - sum(1 for e in self.events if e["type"] == "shot" and e["outcome"] == "goal"
                                                and e["team_id"] != p["team_id"]
                                                and p["minute_on"] <= e["minute"] < p["minute_off"]), 2)
                                    if p["role"] == "GK" and p["minute_on"] is not None else ""),
                "max_shot_speed_kmh": max((e["ball_speed_kmh"] for e in shots), default=""),
                "duels_won": sum(1 for e in self.events if e.get("opponent_id") and e["outcome"] in ("success", "fail")
                                 and (e["player_id"] == pid) == (e["outcome"] == "success")
                                 and pid in (e["player_id"], e["opponent_id"])),
                "duels_lost": sum(1 for e in self.events if e.get("opponent_id") and e["outcome"] in ("success", "fail")
                                  and (e["player_id"] == pid) != (e["outcome"] == "success")
                                  and pid in (e["player_id"], e["opponent_id"])),
                "fouls": sum(1 for e in mine if e["type"] == "foul"),
                "yellow_cards": cards.count("yellow_card"), "red_cards": cards.count("red_card"),
                "falls": self.falls[pid],
                "distance_km": round(self.distance[pid] / 1000, 2),
                "top_speed_kmh": round(self.top_speed[pid], 1), "sprints": self.sprints[pid],
                "decisions": len(decisions),
                "avg_regret": round(sum(e["regret"] for e in decisions) / len(decisions), 4) if decisions else "",
                "injected_mistakes": sum(1 for e in decisions if e["injected_mistake"]),
            })
        return rows


def write_csv(path, rows, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


EVENT_FIELDS = ["event_id", "match_id", "period", "minute", "second", "ts_ms", "possession_id", "team_id",
                "player_id", "player_name", "type", "pass_type", "play_pattern", "body_part", "x", "y",
                "end_x", "end_y", "outcome", "recipient_id", "opponent_id", "under_pressure", "pass_length_m",
                "pass_difficulty", "ball_speed_kmh", "actor_speed_kmh", "xg", "xgot", "end_z", "xa", "score_home", "score_away",
                "chosen_ev", "best_ev", "safe_best_ev", "regret", "regret_rel", "delta_value", "injected_mistake"]

# ---------- Metrica format ----------
# The same match as Metrica Sports' public sample files: one raw tracking file per team and one events file.
# Like a real match file the frames run without a break at 25 Hz, the teams change ends at half time,
# the ball is NaN while it is out of play, a substitute is NaN until he comes on, coordinates are 0-1 with
# y down and players are only shirt numbers.
METRICA_SET_PIECE = {"from_corner": "CORNER KICK", "from_free_kick": "FREE KICK", "from_throw_in": "THROW IN",
                     "from_kick_off": "KICK OFF", "from_goal_kick": "GOAL KICK", "from_penalty": "PENALTY"}
METRICA_SHOT = {"goal": "ON TARGET-GOAL", "saved": "ON TARGET-SAVED", "off_target": "OFF TARGET-OUT",
                "post": "WOODWORK-OUT", "blocked": "BLOCKED"}
FRAME_MS = 40
DEAD_ROAM = 3.0   # m: how far players wander about during a 20 s stoppage
MISCONTROL_DUEL = 0.4   # share of heavy touches written as a ground duel
AERIAL_M = 5.0   # m: a team-mate and an opponent this close where a lofted ball comes down contest it in the air


def metrica_clock(tracking_rows):
    """{period: (first ts_ms, first frame)}: frames count on from one half to the next, with no half time."""
    first, last = {}, {}
    for period, ts in tracking_rows:
        first.setdefault(period, ts)
        last[period] = ts
    clock, frame = {}, 1
    for period in sorted(first):
        clock[period] = (first[period], frame)
        frame += (last[period] - first[period]) // FRAME_MS + 1
    return clock


def metrica_frame(clock, period, ts):
    start, frame = clock[period]
    return frame + max(0, round((ts - start) / FRAME_MS))


def write_metrica(out, prefix, tracking_path, meta, events):
    """tracking.csv.gz + match_meta.json + events -> {prefix}_RawTrackingData_Home_Team.csv,
    {prefix}_RawTrackingData_Away_Team.csv and {prefix}_RawEventsData.csv."""
    home_id = next(t["team_id"] for t in meta["teams"] if t["side"] == "home")
    shirt = {p["player_id"]: p["shirt"] for p in meta["players"]}
    frames = {}                                       # (period, ts) -> {object: (x, y)}
    with gzip.open(tracking_path, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            frames.setdefault((int(r["period"]), int(r["ts_ms"])), {})[r["object_id"]] = (float(r["x"]), float(r["y"]))
    keys = sorted(frames)
    clock = metrica_clock(keys)
    # the frames missing while the ball was out: players ease off, walk over on a gentle curve and settle,
    # the ball has no position
    rng = random.Random(meta["seed"])
    gk_ids = {p["player_id"] for p in meta["players"] if p["position"] == "GK"}
    rows = []
    for (period, ts), nxt in zip(keys, keys[1:] + [None]):
        rows.append((period, ts, frames[(period, ts)]))
        if nxt is None or nxt[0] != period or nxt[1] - ts <= FRAME_MS:
            continue
        a, b = frames[(period, ts)], frames[nxt]
        steps = (nxt[1] - ts) // FRAME_MS
        bow = {o: (rng.gauss(0, 2.0), rng.gauss(0, 2.0)) for o in a}
        # in a long stoppage players also walk about a little (Metrica sample games: ~8% of the time standing)
        roam = min(DEAD_ROAM, DEAD_ROAM * (nxt[1] - ts) / 20000)
        wob = {o: (rng.gauss(0, roam * (o not in gk_ids)), rng.gauss(0, roam * (o not in gk_ids)), rng.choice((2, 3, 4)))
               for o in a}
        for k in range(1, steps):
            w = k / steps
            e, arc = w * w * (3 - 2 * w), math.sin(math.pi * w)
            rows.append((period, ts + k * FRAME_MS,
                         {o: (a[o][0] + (b[o][0] - a[o][0]) * e + bow[o][0] * arc
                              + wob[o][0] * math.sin(wob[o][2] * math.pi * w),
                              a[o][1] + (b[o][1] - a[o][1]) * e + bow[o][1] * arc
                              + wob[o][1] * math.sin(wob[o][2] * math.pi * w))
                          for o in a if o in b and o != "ball"}))

    def spot(period, x, y):
        """Our metres (home attacks +x all match) -> Metrica 0-1, y down, home attacking +x in the first half."""
        if period == 2:
            x, y = PITCH_X - x, PITCH_Y - y
        return round(x / PITCH_X, 5), round(1 - y / PITCH_Y, 5)

    for side, team_id in (("Home", home_id), ("Away", next(t["team_id"] for t in meta["teams"] if t["side"] == "away"))):
        squad = [p["player_id"] for p in meta["players"] if p["team_id"] == team_id]
        squad.sort(key=lambda pid: (not next(p["started"] for p in meta["players"] if p["player_id"] == pid),
                                    shirt[pid]))
        with open(os.path.join(out, f"{prefix}_RawTrackingData_{side}_Team.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["", "", ""] + sum(([side, ""] for _ in squad), []) + ["", ""])
            w.writerow(["", "", ""] + sum(([shirt[pid], ""] for pid in squad), []) + ["", ""])
            w.writerow(["Period", "Frame", "Time [s]"] + sum(([f"Player{shirt[pid]}", ""] for pid in squad), [])
                       + ["Ball", ""])
            for period, ts, pos in rows:
                frame = metrica_frame(clock, period, ts)
                line = [period, frame, f"{frame * FRAME_MS / 1000:.2f}"]
                for oid in squad + ["ball"]:
                    line += list(spot(period, *pos[oid])) if oid in pos else ["NaN", "NaN"]
                w.writerow(line)

    def team_of(pid):
        return "Home" if pid.startswith(home_id + "_") else "Away"

    out_rows = []

    def add(e, team, kind, sub, start_ts, end_ts, frm, to, a, b):
        p = int(e["period"])
        sf, ef = metrica_frame(clock, p, start_ts), metrica_frame(clock, p, end_ts)
        sx, sy = spot(p, *a) if a else ("NaN", "NaN")
        ex, ey = spot(p, *b) if b else ("NaN", "NaN")
        out_rows.append([team, kind, sub, p, sf, f"{sf * FRAME_MS / 1000:.2f}", ef, f"{ef * FRAME_MS / 1000:.2f}",
                         f"Player{shirt[frm]}" if frm else "", f"Player{shirt[to]}" if to else "", sx, sy, ex, ey])

    def num(v):
        return float(v) if v not in ("", None) else None

    def nearby(period, ts, p1, p2):
        """True when the two players were within an aerial duel's reach of each other at that moment."""
        pos = frames.get((period, round(ts / FRAME_MS) * FRAME_MS), {})
        return p1 in pos and p2 in pos and math.dist(pos[p1], pos[p2]) < AERIAL_M

    def outside(spot):
        """A restart spot pushed just over the nearest line: where the ball went out."""
        x, y = spot
        gaps = {"x0": x, "x1": PITCH_X - x, "y0": y, "y1": PITCH_Y - y}
        side = min(gaps, key=gaps.get)
        return {"x0": (-0.5, y), "x1": (PITCH_X + 0.5, y), "y0": (x, -0.5), "y1": (x, PITCH_Y + 0.5)}[side]

    played = [e for e in events if e.get("player_id") in shirt and int(e["period"]) in clock
              and e["type"] in ("pass", "shot", "dribble", "clearance", "ball_recovery", "interception", "tackle", "foul")]
    after = {id(e): n for e, n in zip(played, played[1:] + [None])}
    before = {id(n): e for e, n in zip(played, played[1:])}
    keepers = {p["player_id"] for p in meta["players"] if p["position"] == "GK"}
    for i, e in enumerate(events):
        kind, pid, ts = e["type"], e.get("player_id"), int(e["ts_ms"])
        if not pid or pid not in shirt or int(e["period"]) not in clock:
            continue
        team = team_of(pid)
        other = "Away" if team == "Home" else "Home"
        p = int(e["period"])
        start = (num(e["x"]), num(e["y"])) if num(e.get("x")) is not None else None
        end = (num(e["end_x"]), num(e["end_y"])) if num(e.get("end_x")) is not None else start
        nxt = next((int(n["ts_ms"]) for n in events[i + 1:] if int(n["ts_ms"]) > ts), ts + 1000)
        length, speed = num(e.get("pass_length_m")), num(e.get("ball_speed_kmh"))
        end_ts = min(nxt, ts + round(1000 * length / (speed / 3.6))) if length and speed else nxt
        head = "HEAD-" if e.get("body_part") == "head" else ""
        then, prev = after.get(id(e)), before.get(id(e))
        restart = then is not None and then.get("play_pattern") in ("from_throw_in", "from_corner", "from_goal_kick")
        pattern = e.get("play_pattern")
        if pattern == "from_goal_kick" and kind == "pass":
            # Metrica: the keeper picks the ball up and the goal kick is a pass
            add(e, team, "RECOVERY", "", ts, ts, pid, None, start, start)
        elif pattern == "from_keeper" and prev is not None and prev["type"] == "shot" and prev["outcome"] == "saved":
            add(e, team, "RECOVERY", "SAVED", ts, ts, pid, None, start, start)
        elif pattern in METRICA_SET_PIECE and kind in ("pass", "shot"):
            add(e, team, "SET PIECE", METRICA_SET_PIECE[pattern], ts, ts, pid, None, None, None)
        if kind == "pass":
            parts = [w for w in ("HEAD" if head else "", "CROSS" if e.get("pass_type") == "cross" else "",
                                 "GOAL KICK" if pattern == "from_goal_kick" else "") if w]
            mate, rival = e.get("recipient_id") or None, e.get("opponent_id") or None
            if (e.get("pass_type") in ("cross", "long") and mate and rival and rival in shirt and rival not in keepers
                    and e["outcome"] != "offside" and nearby(p, end_ts, mate, rival)):
                won = e["outcome"] == "success"
                add(e, other if won else team, "CHALLENGE", "AERIAL-LOST", end_ts, end_ts, rival if won else mate,
                    None, end, end)
                add(e, team if won else other, "CHALLENGE", "AERIAL-WON", end_ts, end_ts, mate if won else rival,
                    None, end, end)
            if e["outcome"] == "success":
                add(e, team, "PASS", "-".join(parts), ts, end_ts, pid, mate, start, end)
            elif restart:
                add(e, team, "BALL OUT", "-".join(parts), ts, end_ts, pid, None, start, outside((num(then["x"]), num(then["y"]))))
            else:
                add(e, team, "BALL LOST", "OFFSIDE" if e["outcome"] == "offside" else "-".join(parts + ["INTERCEPTION"]),
                    ts, end_ts, pid, None, start, end)
        elif kind == "clearance":
            if then is not None and then["type"] == "ball_recovery" and team_of(then["player_id"]) == team:
                add(e, team, "PASS", "HEAD" if head else "CLEARANCE", ts, end_ts, pid, then["player_id"], start, end)
            else:   # Metrica calls a header away a header, and only a kick a clearance
                add(e, team, "BALL OUT" if restart else "BALL LOST", "HEAD" if head else "CLEARANCE", ts, end_ts, pid, None, start, end)
        elif kind == "shot":
            add(e, team, "SHOT", head + METRICA_SHOT.get(e["outcome"], "OFF TARGET"), ts, end_ts, pid, None, start, end)
        elif kind == "dribble":
            won = e["outcome"] == "success"
            rival = e.get("opponent_id") or None
            fouled = then is not None and then["type"] == "foul"
            if won:
                add(e, team, "CHALLENGE", "GROUND-WON", ts, ts, pid, None, start, start)
                if rival in shirt:
                    add(e, other, "CHALLENGE", "GROUND-LOST", ts, ts, rival, None, start, start)
            elif not fouled:   # a foul is written with the foul
                add(e, team, "CHALLENGE", "TACKLE-LOST", ts, ts, pid, None, start, start)
                add(e, team, "BALL LOST", "THEFT", ts, ts, pid, None, start, start)
        elif kind == "tackle":
            add(e, team, "CHALLENGE", "TACKLE-WON", ts, ts, pid, None, start, start)
            add(e, team, "RECOVERY", "THEFT", ts, ts, pid, None, start, start)
        elif kind in ("interception", "ball_recovery"):
            if (kind == "ball_recovery" and prev is not None and prev["type"] == "pass" and prev["outcome"] == "success"
                    and prev.get("recipient_id") in shirt and team_of(prev["recipient_id"]) != team):
                # a heavy touch: Metrica writes a duel only when the opponent actually challenged for it
                duel = rng.random() < MISCONTROL_DUEL
                if duel:
                    add(e, other, "CHALLENGE", "GROUND-LOST", ts, ts, prev["recipient_id"], None, start, start)
                add(e, other, "BALL LOST", "", ts, ts, prev["recipient_id"], None, start, start)
                if duel:
                    add(e, team, "CHALLENGE", "GROUND-WON", ts, ts, pid, None, start, start)
            if not (kind == "ball_recovery" and prev is not None and prev["type"] == "clearance"
                    and team_of(prev["player_id"]) == team):   # a headed clearance to a team-mate is a pass
                add(e, team, "RECOVERY", "INTERCEPTION" if kind == "interception" else "", ts, ts, pid, None, start, start)
        elif kind == "foul":
            victim = prev["player_id"] if prev is not None and prev["type"] == "dribble" else None
            duel = "TACKLE" if rng.random() < 0.5 else "GROUND"   # Metrica sample games: about half each
            add(e, team, "CHALLENGE", duel + "-FAULT-LOST", ts, ts, pid, None, start, start)
            if victim:
                add(e, other, "CHALLENGE", duel + "-FAULT-WON", ts, ts, victim, None, start, start)
            add(e, other, "FAULT RECEIVED", "", ts, ts, victim, None, start, start)
        elif kind == "card":
            add(e, team, "CARD", "RED" if "red" in e["outcome"] else "YELLOW", ts, ts, pid, None, None, None)
    with open(os.path.join(out, f"{prefix}_RawEventsData.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Team", "Type", "Subtype", "Period", "Start Frame", "Start Time [s]", "End Frame",
                    "End Time [s]", "From", "To", "Start X", "Start Y", "End X", "End Y"])
        w.writerows(out_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="output")
    ap.add_argument("--hz", type=int, default=25, help="movement and tracking frequency (frames per second)")
    ap.add_argument("--no-tracking", action="store_true", help="skip the tracking.csv.gz file")
    ap.add_argument("--metrica", action="store_true",
                    help="also write the match in Metrica Sports' raw format (two tracking files and one events file)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    m = Match(args.seed, hz=args.hz)
    track_file = None
    if not args.no_tracking:
        track_file = gzip.open(os.path.join(args.out, "tracking.csv.gz"), "wt", newline="", encoding="utf-8")
        m.track_writer = csv.writer(track_file)
        m.track_writer.writerow(("ts_ms", "period", "object_id", "team_id", "x", "y", "z", "facing_deg", "state"))
    m.simulate()
    if track_file:
        track_file.close()
    critical = m.rank_critical()
    write_csv(os.path.join(args.out, "events.csv"), m.events, EVENT_FIELDS)
    write_csv(os.path.join(args.out, "freeze_frames.csv"), m.frames)
    write_csv(os.path.join(args.out, "decision_options.csv"), m.options)
    write_csv(os.path.join(args.out, "critical_decisions.csv"), critical)
    write_csv(os.path.join(args.out, "player_alerts.csv"), m.alerts)
    write_csv(os.path.join(args.out, "player_stats.csv"), m.player_stats())
    meta = {"match_id": m.match_id, "synthetic": True, "seed": args.seed, "tracking_hz": args.hz,
            "pitch": {"length_m": PITCH_X, "width_m": PITCH_Y, "origin": "home team's left corner, home attacks +x"},
            "teams": m.teams, "final_score": {"home": m.score[0], "away": m.score[1]},
            "xt_source": "learned grid (xt_grid.json)" if XT_GRID else "hand-written formula",
            "alert_thresholds": ALERTS, "card_rates": CARDS,
            "formations": {m.teams[t]["team_id"]: m.start_formation[t] for t in (0, 1)},
            "formation_changes": m.formation_changes,
            "wind": {"speed_ms": m.wind_speed, "direction_deg": m.wind_dir},
            "press_height": {m.teams[t]["team_id"]: m.press[t] for t in (0, 1)},
            "tactical_shifts": m.tactical_shifts,
            "game_plans": {m.teams[t]["team_id"]: m.plan[t] for t in (0, 1)},
            "players": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in p.items()
                         if k not in ("home", "team_idx", "line", "on", "yellow")} for p in m.players],
            "unused_substitutes": {m.teams[t]["team_id"]: [{"player_id": p["player_id"], "name": p["name"],
                                                            "position": p["position"]} for p in m.bench[t]]
                                   for t in (0, 1)},
            "profiles": PROFILES}
    with open(os.path.join(args.out, "match_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    if args.metrica and not args.no_tracking:
        write_metrica(args.out, m.match_id, os.path.join(args.out, "tracking.csv.gz"), meta, m.events)
    print(f"{m.match_id}: {m.score[0]}-{m.score[1]}, {len(m.events)} events, "
          f"{len(m.options)} options, {len(critical)} critical decisions, {len(m.alerts)} alerts")


if __name__ == "__main__":
    main()
