"""Constants and helpers shared by every layer. Change a threshold here, nowhere else.
Only the Python standard library is imported here."""
import json
import math
import random
import re
import statistics
from pathlib import Path

# ---- pitch (metres, the home team attacks +x) ----
PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_Y = PITCH_Y / 2
GOAL_HALF_WIDTH = 3.66
HALFWAY_X = PITCH_X / 2


# ---- errors (the app turns them into 404 / 400) ----
class NotFound(Exception):
    pass


class BadInput(Exception):
    pass


LIGHT_AGENTS = ("summary", "fan_feed")   # agents that only write text from finished results: FOUNDRY_LIGHT_MODEL

# ---- critical moments: scouts, then the Critical Moment agent ----
SCOUT_CHUNK = 50            # decisions one scout reads
SCOUT_PICKS = 10            # most candidates one scout returns
CRITICAL_CHUNK = 30         # candidates one Critical Moment agent reads
CRITICAL_MIN, CRITICAL_MAX = 20, 25   # critical moments of a 15-minute clip (or shorter)
CRITICAL_MIN_90, CRITICAL_MAX_90 = 50, 60   # and of a 90-minute match; in between on a straight line (critical_range)
KINDS = ("missed_chance", "costly_mistake", "good_decision", "goal_build_up", "defensive_moment")
MISTAKE_REGRET = 0.02
MOMENT_OPTIONS = 6          # options of one moment shown to GPT and Decision-1 (chosen, best, safest first)
TO_MATE = ("pass", "ground_cross", "cross", "long_ball")   # options that play the ball to a team-mate
MISSED_MAX = 3              # options the position analyst may add from the picture (no numbers)
RUN_WITH_BALL = ("dribble", "carry")
RUN_SHOW_P = 0.5           # running with the ball is among a moment's options when it comes off this often
REPLAY_HZ = 25
CLIP_BEFORE_MS, CLIP_AFTER_MS = 8000, 3000
METRICA_CLIP_MINUTES = 30  # a loaded Metrica match: this many minutes from a random start in one half
SAMPLE_MATCH_BLOB = "sample_match/"  # the Blob folder of the sample match (its two raw Metrica files)
# made-up names for a loaded Metrica match (its files have shirt numbers only), new on every load
TOWNS = ["Northbridge", "Southhaven", "Eastmoor", "Westfield", "Ashford", "Kingsport", "Redcliff", "Silverton",
         "Oakvale", "Riverside", "Stonebury", "Harbourne", "Elmstead", "Brightwater", "Highgate", "Lakemont"]
CLUBS = ["Rovers", "Athletic", "United", "City", "Wanderers", "Albion", "Town", "FC"]
FIRST = ["Arda", "Leo", "Kenji", "Mateo", "Noah", "Emre", "Luca", "Omar", "Felix", "Iker", "Yusuf", "Theo", "Kaan",
         "Ravi", "Hugo", "Elias", "Bora", "Sami", "Jonas", "Milo", "Deniz", "Ilan", "Tomas", "Adrian", "Nico", "Malik"]
LAST = ["Vale", "Korhan", "Brandt", "Okoro", "Silva", "Tanaka", "Moreau", "Reyes", "Lindqvist", "Aydin", "Novak",
        "Haddad", "Costa", "Weber", "Yilmaz", "Dubois", "Kaya", "Ferro", "Nakamura", "Petrov", "Sahin", "Quinn",
        "Varga", "Mensah", "Ortiz", "Holm"]


# ---- fan feed ----
FAN_POSTS_MAX = 15
FAN_HANDLES = ["terrace_voice", "north_stand_nick", "kitchen_pundit", "season_ticket_7", "flask_and_scarf",
               "late_bus_home", "row_z_regular", "halftime_pie", "away_end_echo", "sofa_gaffer"]   # made up

# ---- verify ----
_NUM = r"(\d{1,3}(?:[.,]\d{1,2})?)"
PERCENT = re.compile(rf"%\s?{_NUM}|{_NUM}\s?%|yüzde\s+{_NUM}|{_NUM}\s+(?:percent|per cent)", re.IGNORECASE)
MINUTE = re.compile(r"(\d{1,3})\.\s?dakika|minute\s+(\d{1,3})|(\d{1,3})(?:st|nd|rd|th)\s+minute", re.IGNORECASE)
# ---- scoring (copied from the generator so imported matches are scored the same way) ----
SAFE_P = 0.7
MAX_PASS_M = 55
TAKEN_FAR_M = 10.0          # the nearest option of the player's kind lies farther than this from where the ball went:
                            # what he did (a ball poked out of play, say) is scored as its own option
SHOT_RANGE_M = 32
SHOT_TAKEN = 0.6           # a pass into shooting range: share of times the receiver gets the shot off (controls it
                           # and shoots before a defender closes him down); the xG at the spot assumes he always does
SHOT_VALUE_CAP = 0.35      # most a pass is worth for the shot it sets up (like the cap on the danger of a loss)
SKILL_DEFAULT = 0.5
SPEED_DEFAULT = 8.5
HEIGHT_DEFAULT = 180
STRENGTH_DEFAULT = 0.5
CROSS_ZONE = (55, 8)
CROSS_DROP_M = 8.5         # a cross to a running team-mate lands this far from goal (generator: random 6-11 m)
KNOCKDOWN_M = 12
HEADER_TOUCH_S = 0.5
WIND_PUSH = 0.22
TECH_PASS = 1.6
XG_BASE, XG_DIST, XG_ANGLE, XG_SHADOW = -0.04, -0.025, 1.895, 1.0
XG_KEEPER, XG_PRESSURE, XG_HEADER = 1.64, 0.42, 1.275
BLOCK_REACH, GOAL_POINTS = 0.6, 15
COUNTER_RANGE = (0.6, 2.0)   # the opponent's counter makes the danger of a lost ball 0.6x to 2x the zone value
COUNTER_W, COUNTER_EVEN = 0.3, 3.0  # log-change per extra runner or missing defender; (runners - defenders) that is even
WIDE = {"RW", "LW", "RM", "LM"}
LINE = {"GK": "gk", "RB": "def", "CB": "def", "LB": "def", "DM": "mid", "CM": "mid", "AM": "mid",
        "RM": "mid", "LM": "mid", "RW": "fwd", "LW": "fwd", "ST": "fwd"}
DECISION_TYPES = ["pass", "shot", "dribble", "carry", "clearance"]
# defensive and new options
CLEAR_ZONE_X = 35.0          # in his own third a player may clear the ball
CLEAR_LENGTH_M = 45.0
CLEAR_PRESSURE = 0.2         # ...when an opponent is this close (pressure 0-1)
THROUGH_NEAR_M = 5.0         # a forward pass to a team-mate this near the opponents' last line (or past it) is a through ball
RUN_LEAD_MAX_S = 3.0         # a pass into a run is aimed where the team-mate will be when it gets there, at most this late
RUN_MIN_SPEED = 2.5          # m/s: slower than this is not a run
RUN_MIN_GAIN_M = 3.0         # the spot must be this far from where he stands, else it is the plain pass
RUN_SPACE_M = 8.0            # a ball into space: this much further along his run, when he can sprint onto it in time
REACH_PACE = 0.8             # a team-mate runs to a ball played into space at this share of his top speed
REACH_TURN_S = 0.8           # ...and loses up to this long turning round when he runs the other way
RUN_BACK_SPEED = 1.0         # m/s towards his own goal: a cross is not played in front of him
CROSS_BALL_SPEED = 20.0      # m/s of a cross in the air: a runner must reach its spot by then...
CROSS_WAIT_S = 0.5           # ...or this little later
FORWARD_M, BACK_M = 5.0, -5.0   # metres gained (lost) that make a pass forward (back); in between sideways
# Spearman (2018) pitch control: who gets to a ball played to a spot first, from positions and velocities
PC_REACT_S = 0.7             # a player keeps running his way this long before he reacts
PC_MAX_SPEED = 5.0           # m/s he then runs at, straight to the spot
PC_SIGMA = 0.45              # s: spread of a player's arrival time
PC_LAMBDA = 4.3              # 1/s: how quickly a player who is there brings the ball under control
PC_DT, PC_MAX_S = 0.04, 10.0  # integration step and longest wait after the ball arrives (s)
PC_REACH_M = 0.5             # a player can cut out a pass this far from where he gets to
PC_CUT_SIGMA = 0.225         # s: spread of the arrival time at a passing ball (sharper: it does not wait)
PC_GRID_M = 2.0              # the control surface of a moment is worked out on this grid
PC_LANE_STEP_M = 3.0         # a pass is checked for a cut-out at points this far apart along its path
PC_PRESS, PC_BLIND = 0.2, 0.15  # share of passes that go astray under full pressure / played blind
CROSS_ACCURACY, LONG_ACCURACY = 0.8, 0.9  # share of crosses / long balls that land where they were meant
COUNTER_ZONE = (30.0, 20.0)  # after a loss: the space this deep towards our goal and this wide either side


# ---- helpers ----
def clean(value):
    """pandas / numpy values -> plain JSON values (NaN becomes None, also inside lists and dicts: PostgreSQL's JSON
    has no NaN)."""
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def made_up_teams() -> tuple[str, str]:
    """Two different team names, at random."""
    home, away = random.sample(TOWNS, 2)
    return f"{home} {random.choice(CLUBS)}", f"{away} {random.choice(CLUBS)}"


def made_up_players(player_ids: list[str]) -> list[dict]:
    """A different name for every player, at random."""
    people = random.sample([f"{f} {l}" for f in FIRST for l in LAST], len(player_ids))
    return [{"player_id": p, "name": n} for p, n in zip(player_ids, people)]


def shirt_numbers(team: list[dict]) -> dict:
    """Shirt numbers from the positions: GK 1, RB 2, CB 3-4 (right one first), LB 5; with one striker CM 6-8-10
    (deepest first), right wing 7, left wing 11, ST 9; with two strikers ST 9 and 11, wings 7 and 10, CM 6-8.
    team: one team's players with player_id, role (PitchService.positions), minutes on the pitch, depth (towards
    the goal attacked) and right (towards his right touchline). The eleven who played longest get these numbers;
    anyone left over, and the substitutes, get the free ones, then 12 on."""
    team = sorted(team, key=lambda p: -p["minutes"])
    first = team[:11]
    two_up = sum(p["role"] == "ST" for p in first) >= 2
    slots = [("GK", [1], None), ("RB", [2], None), ("CB", [3, 4], "right"), ("LB", [5], None),
             ("ST", [9, 11] if two_up else [9], "depth"), (("RW", "RM"), [7], "depth"),
             (("LW", "LM"), [10] if two_up else [11], "depth"), ("CM", [6, 8] if two_up else [6, 8, 10], "depth")]
    out = {}
    for roles, numbers, order in slots:
        mine = [p for p in first if p["role"] in (roles if isinstance(roles, tuple) else (roles,))
                and p["player_id"] not in out]
        if order == "right":
            mine.sort(key=lambda p: -p["right"])
        elif order == "depth":
            mine.sort(key=lambda p: p["depth"])
        out.update({p["player_id"]: n for p, n in zip(mine, numbers)})
    free = [n for n in range(1, 12) if n not in out.values()] + list(range(12, 100))
    for p in team:
        if p["player_id"] not in out:
            out[p["player_id"]] = free.pop(0)
    return out


def name_metrica_players(tracking, roles: dict, home_id: str) -> list[dict]:
    """Made-up names for every player of a Metrica match read by PitchService.read_metrica (ids TEAM_shirt), and
    shirt numbers from their positions (roles: PitchService.positions)."""
    pl = tracking[tracking.object_id != "ball"]
    mean = pl.groupby("object_id").agg(team=("team_id", "first"), x=("x", "mean"), y=("y", "mean"),
                                       frames=("x", "size"))
    players = made_up_players(sorted(mean.index))
    shirts = {}
    for team_id, team in mean.groupby("team"):
        home = team_id == home_id                       # the home team attacks +x, its right touchline is y = 0
        shirts.update(shirt_numbers([{"player_id": pid, "role": roles.get(pid), "minutes": r.frames,
                                      "depth": r.x if home else PITCH_X - r.x,
                                      "right": -r.y if home else r.y} for pid, r in team.iterrows()]))
    return [{**p, "shirt": shirts[p["player_id"]]} for p in players]


def rows(df):
    return [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def situation(team_id, score_home, score_away, home_id):
    mine, theirs = (score_home, score_away) if team_id == home_id else (score_away, score_home)
    return {"state": "leading" if mine > theirs else "trailing" if mine < theirs else "level",
            "for": int(mine), "against": int(theirs)}


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def along(p, a, b):
    """How far along the segment a -> b the point p projects (0 at a, 1 at b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1.0)


def seg_point_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return dist(p, a)
    t = clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy), 0, 1)
    return dist(p, (a[0] + t * dx, a[1] + t * dy))


def closest_on_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return a
    t = clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy), 0, 1)
    return (a[0] + t * dx, a[1] + t * dy)


def in_box(p):
    """Penalty box of the defending team, in the attacker's frame."""
    return p[0] > PITCH_X - 16.5 and abs(p[1] - GOAL_Y) < 20.16


def goal_distance(p):
    return math.hypot(PITCH_X - p[0], GOAL_Y - p[1])


def flight_time(length):
    """Seconds a lofted ball spends in the air."""
    return 0.7 + 0.035 * length


def zone_of(x, y):
    """Pitch zone in the attacking team's frame."""
    if in_box((x, y)):
        return "box"
    if goal_distance((x, y)) < 25:
        return "edge_of_box"
    return "final_third" if x > 70 else "middle" if x > 52.5 else "own_half"


# ---- event detection from positions ----
CONTROL_M = 1.6            # ball this close to a player's feet counts as his
CONTROL_Z = 1.6            # ...and no higher than this (a ball overhead is still in flight)
CONTROL_SPEED = 9.0        # m/s; a faster ball is passing by, not under control
KICKOFF_GAP_MS = 10_000    # a shot, then this long a pause and a restart on the centre spot: it was a goal
# set pieces: the ball lay still this long (moving less than RESTART_STILL_M) before it was played; where it lay
# says which one (corner, throw-in, kick-off, goal kick, else a free kick)
RESTART_STILL_MS, RESTART_STILL_M = 2000, 0.4
CORNER_SPOT_M, TOUCHLINE_M, CENTRE_SPOT_M = 3.0, 1.5, 2.0
GOAL_AREA_X, GOAL_AREA_Y = 6.0, 10.0
KICKOFF_WINDOW_MS = 120_000  # ... as long as the restart comes within two minutes
KICKOFF_MAX_TOUCHES = 3    # ...with at most this many touches in between (the ball fetched from the net)
KICKOFF_SPOT_M = 2.0       # how near the centre spot the restart touch starts
KICKOFF_STILL_MS = 2_000   # ...after the ball has lain on the spot this long
FLICKER_MS = 400           # two touches of one player this close together are one touch
PASS_BY_MS = 200           # a touch this short in which the ball kept its line and pace is no touch...
PASS_BY_TURN_DEG = 15.0    # ...turning less than this
PASS_BY_SPEED_CHANGE = 2.0  # ...and changing speed by less than this many m/s
PASS_BY_MIN_SPEED = 3.0    # ...while rolling at least this fast
PASS_BY_LONG_MS = 1000     # a longer "touch" like that is no touch either when the ball left the player behind...
PASS_BY_GAIN_M = 2.0       # ...going this much further than he did
PASS_BY_DECEL = 4.0        # m/s per second a rolling ball may slow down beyond PASS_BY_SPEED_CHANGE in a longer one
MIN_TOUCH_MS = 40          # one frame at 25 fps: one-touch passes are this short
SMOOTH_MS = 200            # positions are smoothed over this long (jitter)
GAP_FILL_MS = 600          # the ball may vanish this long (hidden by players) and is drawn in a straight line
CARRY_MIN_M = 4.0          # a touch that moves the ball this far with the player is a carry
CARRY_START_M = 0.5        # a carry starts when the ball has moved this far from where the touch began
TACKLE_GAP_MS = 300        # the ball reaches an opponent this soon after a touch, slowly...
TACKLE_M = 3.0             # ...and this near: he took it off the player's feet (no pass)
DRIBBLE_OPP_M = 2.0        # an opponent this close during a carry makes it a take-on
SHOT_SPEED = 13.0          # m/s; a ball this fast towards goal is a shot, not a pass
SHOT_DETECT_RANGE_M = 35.0 # detection: shots start no further than this from goal
GOAL_MARGIN_M = 2.0        # a shot aimed this far wide of the posts still counts as a shot
SHOT_SPEED_NEAR = 7.0      # m/s; close to goal (a header, a tap-in) a slower ball is still a shot
SHOT_NEAR_M = 12.0         # ...within this distance of goal
WIDE_SHOT_Y = 20.16        # a fast ball over the goal line this near the centre (box width) is a shot off target
NEXT_TOUCH_MS = 15_000     # a touch this long after the last one is not where that ball went (a gap, a stoppage)
TOUCH_HOLE_MS = 3000       # ...or with a hole this long in the data between them (a cut replay)
SPEED_LOOK_MS = 500        # a shot's speed is read over the first half second of the flight
KICK_M = 1.5               # a sudden change of the ball's path this close to a player is his kick (one-touch)
KICK_TURN_DEG = 35.0       # ...a turn of at least this much
KICK_GAIN = 5.0            # ...or a speed-up of at least this many m/s
KICK_OUT_SPEED = 7.0       # ...and the ball leaves at least this fast
GOAL_LINE_SLACK_M = 0.5    # touches with the ball further behind a goal line are dead-ball touches
OFFSIDE_M = 0.0            # a receiver any distance beyond the second-last defender (or the ball) is offside
KICK_BACK_M, KICK_BACK_DEG = 3.0, 120.0  # a ball turned back this sharply was touched by the nearest player this close
KICK_RIVAL_M = 1.0         # a first-time touch with an opponent this much farther or nearer is a duel (who touched it?)
DUEL_MS = 400              # a touch this short that loses the ball is a block or a poke in a duel, not a chosen pass
KICK_GAP_MS = 600          # a kick this close to the same player's touch is part of that touch
KICK_LOOK_MS = 120         # speeds before and after the kick are measured over this long
AIM_MS = 400               # a shot's aim is read from the ball's path this long after the kick
LONG_PASS_M = 30.0
HIGH_BALL_Z = 2.0          # a pass that rises above this is lofted (when the ball height is known)
WIDE_Y = 13.84             # crosses come from outside the width of the penalty box
# player profile from tracking (Metrica): no player data in the file
PROFILE_WINDOW_MS = 400       # speeds and running directions are read over this long
PROFILE_SPEED_Q = 0.99        # top speed = this quantile of a player's speeds (a single spike is a bad position)
PROFILE_SPEED_CAP = (5.5, 10.5)   # m/s; outside this the clip was too short or the data wrong
PROFILE_MOVING = 1.5          # m/s; slower than this a player's facing is unknown
PROFILE_DEF_SHARE = 0.4       # the deepest 40% of a team's outfield players are the back line...
PROFILE_FWD_SHARE = 0.2       # ...the furthest forward 20% the attack, the rest midfield
PROFILE_WIDE_M = 10.0         # standing this far from the middle on average = a full-back or winger
DISTANCE_MAX_SPEED = 12.0     # m/s; a faster step between two frames is a bad position, not running


# ---- files and stored tables ----
FRAME_COLS = ["player_id", "team_id", "x", "y", "vx", "vy", "facing_deg"]


def positions_file(match_id):
    return f"matches/{match_id}/positions.csv.gz"


def match_score(meta, home_id, goal_teams):
    """The score now: the score at the clip's start plus the goals found in the clip (their team ids)."""
    home = goal_teams.count(home_id)
    return {"home": meta.get("score_home", 0) + home, "away": meta.get("score_away", 0) + len(goal_teams) - home}


# ---- fabrication check: every percentage and minute an agent writes must be in the event's data ----
def rounds_to(said: str, value: float) -> bool:
    """Is the number as written (34, 34.5 or 34,5) a rounding of the real value?"""
    said = said.replace(",", ".")
    places = len(said.split(".")[1]) if "." in said else 0
    return abs(float(said) - value) <= 0.5 * 10 ** -places + 1e-6


def check(sentences, numbers_for) -> list[str]:
    """numbers_for(event_id) -> {"pct": percentages in that event's data (0-100, not rounded),
    "minutes": its match minute}; a plain set means percentages only. Raises NotFound for an unknown id."""
    problems = []
    for s in sentences:
        pct, minutes = set(), set()
        for eid in s.event_ids:
            try:
                known = numbers_for(eid)
            except NotFound:
                problems.append(f"unknown event: {eid}")
                continue
            if isinstance(known, dict):
                pct |= known.get("pct", set())
                minutes |= known.get("minutes", set())
            else:
                pct |= known
        for groups in PERCENT.findall(s.text):
            said = next(g for g in groups if g)
            if not any(rounds_to(said, k) for k in pct):
                problems.append(f"percentage not in the data: {said}% ({s.text[:50]})")
        for groups in MINUTE.findall(s.text) if minutes else ():
            said = int(next(g for g in groups if g))
            if not any(said in (m, m + 1) for m in minutes):      # minute 72 (72:06) is also "the 73rd minute"
                problems.append(f"minute not in the data: {said} ({s.text[:50]})")
    return problems


# ---- options in words (agents, Decision-1, stand-ins) ----
WORDS = {"pass": "a pass", "ground_cross": "a low cross", "cross": "a cross", "long_ball": "a long ball",
         "shot": "a shot", "dribble": "a dribble", "carry": "a carry", "hold": "keeping the ball",
         "clearance": "a clearance upfield", "clear_out": "a clearance into touch"}


SAME_CHOICE_SCORE = 7.0      # a decision Decision-1 would have made too is at least a good one
SCORE_GAP_EV = 0.05          # expected value given up against the best option that brings the base score down to
                             # about 3.7 (5 points of goal chance: about a box-edge pass against a midfield one)
SCORE_MIN = 0.1              # the lowest decision score: even a clear mistake is not a flat 0.0
COACH_BASE_RANGE = 2.0       # the coach's score stays this close to the code's base score
GOOD_REGRET_REL = 0.1        # a choice this close to the best (share of the options' spread) can be a good decision


def base_score(e: dict) -> float | None:
    """The code's score of the player's decision out of 10, from how much expected value his option gives up
    against the best one he had: 10 when none was better, falling off smoothly (about 3.7 at SCORE_GAP_EV given
    up, 1.4 at twice that, 0.5 at three times) and never below SCORE_MIN, so bigger mistakes still score
    differently. A calm moment where every
    option is worth about the same scores high whatever he chose. None when the decision was not scored."""
    opts = e.get("options") or []
    mine = next((o for o in opts if o.get("is_chosen")), None)
    if mine is None or len(opts) < 2:
        return None
    gap = max(o["ev"] for o in opts) - mine["ev"]
    return max(round(10 * math.exp(-max(gap, 0) / SCORE_GAP_EV), 1), SCORE_MIN)


def good_edge(e: dict) -> float:
    """How much more expected value the player's option had than the middle of his options, when it was (about)
    the best one; 0 otherwise. A clever decision, where only one way was good, then matters as much as a mistake
    of the same size; in a calm moment every option is worth about the same and the edge stays small."""
    opts = e.get("options") or []
    mine = next((o for o in opts if o.get("is_chosen")), None)
    if mine is None or len(opts) < 2 or (e.get("regret_rel") or 0) > GOOD_REGRET_REL:
        return 0.0
    return round(max(mine["ev"] - statistics.median(o["ev"] for o in opts), 0.0), 4)


def word(o):
    if not o:
        return "another option"
    if o["option_type"] == "from_picture":
        return f"what the analyst saw in the picture ({o['text'].rstrip('.').lower()})"
    if o["option_type"] == "pass" and o.get("direction"):
        w = {"through": "a through ball", "forward": "a forward pass", "side": "a sideways pass",
             "back": "a back pass", "throw_in": "a throw-in"}[o["direction"]]
        return f"{w} into the space ahead of the run" if o.get("into_space") else f"{w} into the run" if o.get("into_run") else w
    return WORDS.get(o["option_type"], o["option_type"])


def chosen(e):
    return next((o for o in e["options"] if o["is_chosen"]), None)


def best(e):
    return next((o for o in e["options"] if o["is_best"]), None)


def kind_of(e, in_chain):
    """The kind of a critical moment from the code's numbers (used when the agent gives none)."""
    c = chosen(e) or {}
    if in_chain:
        return "goal_build_up"
    if c.get("option_type") in ("clearance", "clear_out", "hold"):
        return "defensive_moment"
    if (e["regret"] or 0) >= MISTAKE_REGRET:
        return "missed_chance" if (best(e) or {}).get("option_type") == "shot" else "costly_mistake"
    return "good_decision"


# ---- one critical moment ----
CHAIN_MS = 20_000          # decisions of the scoring team this long before a goal built it
KEY_DECISIONS = 3          # the decisions behind a goal that added the most value
PHASE_BREAK_MS = 5_000     # a pause this long between touches (the ball out, a foul) starts a new attack phase
MOMENT_GAP_MS = 15_000     # two critical moments are at least this far apart, and never in the same attack phase
DECIDE_MIN_MS = 1_500      # a touch this soon after winning the ball (a first-time clearance) left no time to decide


def moment_options(e):
    """The options shown to GPT and Decision-1: the player's choice, the best, the safest and, when it is likely
    to come off, the best way to run with the ball (it rarely scores high, so it would not be seen otherwise)
    first, then the next by score, in the order the code listed them (so the best is not always A)."""
    must = [o for o in e["options"] if o["is_chosen"] or o["is_best"] or o["is_safe_best"]]
    runs = [o for o in e["options"] if o["option_type"] in RUN_WITH_BALL and o["p_success"] >= RUN_SHOW_P]
    if runs and not any(o["option_type"] in RUN_WITH_BALL for o in must):
        must.append(max(runs, key=lambda o: o["ev"]))
    rest = sorted((o for o in e["options"] if o not in must), key=lambda o: o["ev"], reverse=True)
    keep = must + rest[:max(0, MOMENT_OPTIONS - len(must))]
    return [o for o in e["options"] if o in keep]


def analyst_list(e, picks, found) -> tuple[list[dict], list[dict]]:
    """What Decision-1 weighs, as the position analyst built it: the player's choice and the analyst's picks (the
    biggest chance, the safest and his shortlist, at most MOMENT_OPTIONS in all), plus what he saw in the
    picture; a picture option the code already scored goes with the code's numbers. With no shortlist (a
    stand-in) the code's list stands. Returns (scored options, picture options without numbers)."""
    by = {o["option_id"]: o for o in e["options"]}
    ids = [o["option_id"] for o in e["options"] if o["is_chosen"]] + [i for i in picks if i in by]
    ids = list(dict.fromkeys(ids))[:MOMENT_OPTIONS] if len(set(ids)) > 1 else [o["option_id"] for o in moment_options(e)]
    twins = [scored_twin(e, o) for o in found]
    keep = set(ids) | {t["option_id"] for t in twins if t}
    return [o for o in e["options"] if o["option_id"] in keep], [o for o, t in zip(found, twins) if not t]


def scored_twin(e, o):
    """The code's own pass for a picture option that names a team-mate (the same receiver, to his feet or into his
    run, the likeliest to come off when there are several), or None."""
    same = [s for s in e["options"] if o.get("target_player_id") and s.get("target_player_id") == o["target_player_id"]
            and s["option_type"] in TO_MATE and bool(s.get("into_run")) == bool(o.get("into_run"))]
    return max(same, key=lambda s: s["p_success"], default=None)


def picture_options(e, missed, shirt_of, most=MISSED_MAX) -> list[dict]:
    """The analyst's picture-only options as option rows (no numbers), ids like e_00012_p01. When the analyst named
    the team-mate by shirt number the option points at where he stands, so the picture can draw it."""
    mates = {shirt_of.get(f["player_id"]): f for f in e.get("frame") or []
             if f["team_id"] == e["team_id"] and f["player_id"] != e["player_id"]}
    ball = next(((f["x"], f["y"]) for f in e.get("frame") or [] if f["player_id"] == e["player_id"]), None)
    out = []
    for i, s in enumerate(missed[:most], 1):
        o = {"option_id": f"{e['event_id']}_p{i:02d}", "option_type": "from_picture", "text": s.text,
             "is_chosen": False, "is_best": False, "is_safe_best": False}
        if getattr(s, "carry", False) or getattr(s, "clearance", False):   # where the code's own one ends
            kinds = RUN_WITH_BALL if getattr(s, "carry", False) else ("clearance", "clear_out", "long_ball")
            own = max((c for c in e.get("options") or [] if c["option_type"] in kinds and c.get("target_x") is not None),
                      key=lambda c: c.get("ev") or 0, default=None)
            if own:
                o |= {"target_x": own["target_x"], "target_y": own["target_y"]}
        mate = mates.get(getattr(s, "shirt", None)) if getattr(s, "shirt", None) is not None else None
        if mate:
            o |= {"target_player_id": mate["player_id"], "target_x": mate["x"], "target_y": mate["y"]}
            spot = run_spot(mate, ball) if getattr(s, "into_run", False) and ball else None
            if spot:                # into his run: where he will be, as for the code's passes into a run
                o |= {"target_x": spot[0], "target_y": spot[1], "into_run": True}
        out.append(o)
    return out


def run_spot(f, ball):
    """Where a running player of a freeze frame meets a pass from ball, or None when he is not running."""
    vx, vy = f.get("vx"), f.get("vy")
    if vx is None or vy is None or vx != vx or vy != vy or math.hypot(vx, vy) < RUN_MIN_SPEED:
        return None
    lead = lead_s(ball, (f["x"], f["y"]), vx, vy)
    spot = (round(clamp(f["x"] + vx * lead, 0.5, PITCH_X - 0.5), 2),
            round(clamp(f["y"] + vy * lead, 0.5, PITCH_Y - 0.5), 2))
    return spot if dist(spot, (f["x"], f["y"])) >= RUN_MIN_GAIN_M else None


def name_of(p: dict) -> str:
    """A player's name as the agents, the pictures and the screen say it: the keeper is marked."""
    return p["name"] + (" (GK)" if p.get("position") == "GK" else "")


def positions_table(e, shirt_of, home_id) -> str:
    """Everyone on the pitch in numbers for the analyst: where he stands, how fast he moves and which way (in his
    own team's attacking direction) and how far the nearest opponent is."""
    frame = [f for f in e.get("frame") or [] if f.get("x") is not None]
    ball = next((f for f in frame if f["player_id"] == e["player_id"]), None)   # the player on the ball
    rows = []
    for f in sorted(frame, key=lambda f: (f["team_id"] != e["team_id"], shirt_of.get(f["player_id"]) or 0)):
        side = "blue" if f["team_id"] != home_id else "red"
        who = "on the ball" if f["player_id"] == e["player_id"] else (
            "team-mate" if f["team_id"] == e["team_id"] else "opponent")
        if f.get("position") == "GK":
            who = "goalkeeper, " + who
        near = min((dist((f["x"], f["y"]), (g["x"], g["y"])) for g in frame if g["team_id"] != f["team_id"]),
                   default=None)
        vx, vy = f.get("vx"), f.get("vy")
        move = "standing"
        if vx is not None and vy is not None and vx == vx and vy == vy and math.hypot(vx, vy) >= 1.0:
            ahead = vx if f["team_id"] == home_id else -vx      # towards the goal his team attacks
            way = "forward" if ahead > abs(vy) else "back" if -ahead > abs(vy) else "across"
            move = f"{math.hypot(vx, vy):.1f} m/s {way}"
        rows.append(f"- {side} {shirt_of.get(f['player_id']) or '?'} ({who}): x {f['x']:.0f}, y {f['y']:.0f}, {move}"
                    + (f", {dist((f['x'], f['y']), (ball['x'], ball['y'])):.0f} m from the ball" if who == "team-mate" and ball else "")
                    + (f", nearest opponent {near:.1f} m" if near is not None else ""))
    return (f"Positions (metres; the pitch is {PITCH_X:.0f} x {PITCH_Y:.0f}, x from the left goal line, y from the "
            "bottom touchline, as in the picture; forward = towards the goal that player's team attacks):\n"
            + "\n".join(rows))


def goal_attacked(e, home_id):
    """The middle of the goal the team on the ball attacks."""
    return (PITCH_X, GOAL_Y) if e["team_id"] == home_id else (0.0, GOAL_Y)


def phase_of(e, home_id):
    """(attacking, zone) of the ball carrier, in his team's attacking frame."""
    x, y = (e["x"], e["y"]) if e["team_id"] == home_id else (PITCH_X - e["x"], PITCH_Y - e["y"])
    return x > 40, zone_of(x, y)


def phases(events) -> dict:
    """event_id -> its attack phase: a new phase starts when the other team has the ball or play stops a while."""
    out, n, last = {}, 0, None
    for e in events:
        if last is not None and (e["team_id"] != last["team_id"] or e["ts_ms"] - last["ts_ms"] > PHASE_BREAK_MS):
            n += 1
        out[e["event_id"]], last = n, e
    return out


def rushed(events) -> set:
    """Decisions made so soon after the team won the ball that the player had no time to choose."""
    return {e["event_id"] for prev, e in zip(events, events[1:])
            if e["team_id"] != prev["team_id"] and e["ts_ms"] - prev["ts_ms"] < DECIDE_MIN_MS}


def critical_range(decisions) -> tuple[int, int]:
    """How many critical moments a clip gets, by its minutes of play: CRITICAL_MIN to CRITICAL_MAX for 15 minutes
    or less, CRITICAL_MIN_90 to CRITICAL_MAX_90 for 90, on a straight line between (and beyond)."""
    minutes = (decisions[-1]["ts_ms"] - decisions[0]["ts_ms"]) / 60_000 if decisions else 0
    t = (max(minutes, 15) - 15) / 75
    return (round(CRITICAL_MIN + t * (CRITICAL_MIN_90 - CRITICAL_MIN)),
            round(CRITICAL_MAX + t * (CRITICAL_MAX_90 - CRITICAL_MAX)))


def apart(e: dict, kept: list[dict], phase: dict) -> bool:
    """True when e is in another attack phase than every kept moment and at least MOMENT_GAP_MS from each."""
    return all(phase.get(e["event_id"]) != phase.get(k["event_id"]) and abs(e["ts_ms"] - k["ts_ms"]) >= MOMENT_GAP_MS
               for k in kept)


def goal_chains(events) -> list[tuple[dict, list[dict]]]:
    """(goal, its decisions in time order): the scoring team's decisions in the CHAIN_MS before the goal, back to
    the last touch of the other team."""
    out = []
    for i, g in enumerate(events):
        if g["outcome"] != "goal":
            continue
        chain = []
        for e in reversed(events[:i + 1]):
            if e["team_id"] != g["team_id"] or g["ts_ms"] - e["ts_ms"] > CHAIN_MS:
                break
            if e["options"]:
                chain.insert(0, e)
        out.append((g, chain))
    return out


def lost_before(events, chain: list[dict]) -> dict | None:
    """The conceding team's last decision before a goal's chain (it lost the ball), if it came within CHAIN_MS."""
    start = chain[0]
    return next((e for e in reversed(events) if e["ts_ms"] < start["ts_ms"] and e["options"]
                 and e["team_id"] != start["team_id"] and start["ts_ms"] - e["ts_ms"] <= CHAIN_MS), None)


# ---- what a defender could have done against one decision behind a goal ----
DEFENCE_REACT_S = 0.5       # s a defender needs before he moves when the ball is played
DEFENCE_SPEED = 6.5         # m/s a defender runs at to the spot
DEFENCE_REACH_M = 1.0       # he stops a ball passing this close to him (a stretched leg)
DEFENCE_SKIP_M = 2.0        # the first and last metres of a pass (off the foot, at the receiver) are not cut out
DEFENCE_STEP_M = 1.0        # a ground pass is checked at points this far apart along its path
DEFENCE_GOAL_SIDE_M = 1.5   # marking: this far from the receiver's spot towards the defenders' goal
DEFENCE_CLOSE_M = 2.0       # closing down: this far in front of the carrier towards the goal
DEFENCE_CLOSE_S = 1.0       # s the carrier takes to shoot, dribble or set off: the time to close him down
DEFENCE_WORDS = {"cut": "cut out the pass", "mark": "marked the receiver goal-side", "close": "closed him down",
                 "block": "blocked the shot"}
DEFENCE_LABELS = {"cut": "cut out the pass", "mark": "mark goal-side", "close": "close him down",
                  "block": "block the shot"}   # the same, on the picture
DEFENCE_ACTS = {"cut": "steps across and cuts out the pass", "mark": "marks the receiver goal-side",
                "close": "closes the player on the ball down", "block": "blocks the shot"}   # the options, for Decision-1


def defence_fix(e: dict, keepers: set, home_id: str) -> dict | None:
    """The one defender (keepers left out) who could most easily have stopped this decision of the scoring team,
    and where he should have gone: across a ground pass at the earliest point he reaches before the ball (cut);
    when no one could, or for any other ball to a team-mate, goal-side of the receiver (mark); in front of a carrier
    or shooter (close / block). late_s: how many seconds he would have been late (0: he could make it). None when
    the decision has no chosen option or no defender in the frame."""
    c = chosen(e)
    them = [f for f in e.get("frame") or [] if f["team_id"] != e["team_id"] and f["player_id"] not in keepers]
    if not c or not them:
        return None
    ball, goal = (e["x"], e["y"]), goal_attacked(e, home_id)
    run = lambda f, p: DEFENCE_REACT_S + max(dist((f["x"], f["y"]), p) - DEFENCE_REACH_M, 0) / DEFENCE_SPEED   # noqa: E731
    tip = (c["target_x"], c["target_y"]) if c.get("target_x") is not None else None
    length = dist(ball, tip) if tip else 0.0
    made = []
    if c["option_type"] in ("pass", "ground_cross") and tip:
        speed = pass_speed(length)
        for k in range(int(DEFENCE_SKIP_M / DEFENCE_STEP_M), int((length - DEFENCE_SKIP_M) / DEFENCE_STEP_M) + 1):
            p = (ball[0] + (tip[0] - ball[0]) * k * DEFENCE_STEP_M / length,
                 ball[1] + (tip[1] - ball[1]) * k * DEFENCE_STEP_M / length)
            made += [(k, run(f, p) - k * DEFENCE_STEP_M / speed, f, p) for f in them]
        made = [x for x in made if x[1] <= 0]
    if made:                    # the earliest point on the pass a defender reaches before the ball
        _, late, f, spot = min(made, key=lambda x: x[:2])
        kind = "cut"
    else:
        if c["option_type"] in TO_MATE and tip:
            n = dist(tip, goal) or 1.0
            spot = (tip[0] + (goal[0] - tip[0]) / n * DEFENCE_GOAL_SIDE_M,
                    tip[1] + (goal[1] - tip[1]) / n * DEFENCE_GOAL_SIDE_M)
            kind, ball_s = "mark", length / pass_speed(length) if c["option_type"] == "pass" else flight_time(length)
        else:
            n = dist(ball, goal) or 1.0
            spot = (ball[0] + (goal[0] - ball[0]) / n * DEFENCE_CLOSE_M,
                    ball[1] + (goal[1] - ball[1]) / n * DEFENCE_CLOSE_M)
            kind, ball_s = "block" if c["option_type"] == "shot" else "close", DEFENCE_CLOSE_S
        f = min(them, key=lambda f: run(f, spot))
        late = run(f, spot) - ball_s
    return {"player_id": f["player_id"], "from_x": f["x"], "from_y": f["y"], "to_x": round(spot[0], 2),
            "to_y": round(spot[1], 2), "kind": kind, "words": DEFENCE_WORDS[kind], "late_s": round(max(late, 0.0), 1)}


# ---- the defence's options at a goal's key decisions: the Defence Analyst picks a few, Decision-1 chooses ----
DEFENCE_NEAREST = 3         # the defenders nearest to the action who get options
DEFENCE_OPTIONS_MAX = 5     # defence options the Defence Analyst sees for one decision
DEFENCE_SHORTLIST_MAX = 4   # options the Defence Analyst passes on to Decision-1
DEFENCE_LATE_SPREAD_S = 0.3   # s: how fast the chance he gets there in time falls with how late he is (half at 0)
DEFENCE_QUESTION = ("Taking the score, the minute, where on the pitch the ball is and the defence analysis into "
                    "account, which action by a defender was the best way to stop this attack? Weigh the chance he "
                    "gets there in time, the chance of a goal it takes away and the danger he leaves behind if he is "
                    "too late. Answer cannot_tell if the information is not enough to decide.")


def defence_options(e: dict, keepers: set, home_id: str) -> list[dict]:
    """What the DEFENCE_NEAREST defenders (keepers left out) could have done against this decision of the scoring
    team, as options with the attack's three numbers: p_success (he gets there in time), value_if_success (the
    chance of a goal the attack loses: the value of the player's choice) and risk_if_fail (the chance of a goal he
    leaves open: the best option to the attacker nearest him), ev = p * value - (1 - p) * risk. The spots are
    defence_fix's: across a ground pass (cut), goal-side of the receiver (mark), in front of the carrier
    (close / block). The best DEFENCE_OPTIONS_MAX by ev, ids <event_id>_d<n>."""
    c = chosen(e)
    them = [f for f in e.get("frame") or [] if f["team_id"] != e["team_id"] and f["player_id"] not in keepers]
    if not c or not them:
        return []
    ball, goal = (e["x"], e["y"]), goal_attacked(e, home_id)
    run = lambda f, p: DEFENCE_REACT_S + max(dist((f["x"], f["y"]), p) - DEFENCE_REACH_M, 0) / DEFENCE_SPEED   # noqa: E731
    tip = (c["target_x"], c["target_y"]) if c.get("target_x") is not None else None
    length = dist(ball, tip) if tip else 0.0
    spots = []                  # (kind, spot or None for a cut, the seconds the ball gives him)
    if c["option_type"] in ("pass", "ground_cross") and tip and length > 2 * DEFENCE_SKIP_M:
        spots.append(("cut", None, None))
    if c["option_type"] in TO_MATE and tip:
        n = dist(tip, goal) or 1.0
        spots.append(("mark", (tip[0] + (goal[0] - tip[0]) / n * DEFENCE_GOAL_SIDE_M,
                               tip[1] + (goal[1] - tip[1]) / n * DEFENCE_GOAL_SIDE_M),
                      length / pass_speed(length) if c["option_type"] == "pass" else flight_time(length)))
    else:
        n = dist(ball, goal) or 1.0
        spots.append(("block" if c["option_type"] == "shot" else "close",
                      (ball[0] + (goal[0] - ball[0]) / n * DEFENCE_CLOSE_M, ball[1] + (goal[1] - ball[1]) / n * DEFENCE_CLOSE_M),
                      DEFENCE_CLOSE_S))
    attackers = [f for f in e["frame"] if f["team_id"] == e["team_id"] and f["player_id"] != e["player_id"]
                 and f["player_id"] != c.get("target_player_id")]
    value, out = float(c.get("value_if_success") or 0.0), []
    near = sorted(them, key=lambda f: dist((f["x"], f["y"]), tip or ball))[:DEFENCE_NEAREST]
    for f in near:
        free = min(attackers, key=lambda a: dist((a["x"], a["y"]), (f["x"], f["y"])), default=None)
        risk = max((float(o["value_if_success"]) for o in e["options"] if free
                    and o.get("target_player_id") == free["player_id"]), default=0.0)
        for kind, spot, ball_s in spots:
            if kind == "cut":       # the point on the pass he reaches with the most time to spare
                speed = pass_speed(length)
                points = [(ball[0] + (tip[0] - ball[0]) * k * DEFENCE_STEP_M / length,
                           ball[1] + (tip[1] - ball[1]) * k * DEFENCE_STEP_M / length, k * DEFENCE_STEP_M / speed)
                          for k in range(int(DEFENCE_SKIP_M / DEFENCE_STEP_M),
                                         int((length - DEFENCE_SKIP_M) / DEFENCE_STEP_M) + 1)]
                late, x, y = min((run(f, (x, y)) - t, x, y) for x, y, t in points)
                spot = (x, y)
            else:
                late = run(f, spot) - ball_s
            p = 1 / (1 + math.exp(late / DEFENCE_LATE_SPREAD_S))
            out.append({"player_id": f["player_id"], "from_x": f["x"], "from_y": f["y"], "to_x": round(spot[0], 2),
                        "to_y": round(spot[1], 2), "kind": kind, "words": DEFENCE_WORDS[kind],
                        "late_s": round(max(late, 0.0), 1), "option_type": "defence", "p_success": round(p, 3),
                        "value_if_success": round(value, 4), "risk_if_fail": round(risk, 4),
                        "ev": round(p * value - (1 - p) * risk, 4)})
    out = sorted(out, key=lambda o: -o["ev"])[:DEFENCE_OPTIONS_MAX]
    return [{"option_id": f"{e['event_id']}_d{i}", **o} for i, o in enumerate(out, 1)]


def describe_defence(o: dict, names: dict) -> str:
    """One defence option in words with its three numbers."""
    return (f"{names.get(o['player_id'], 'A defender')} {DEFENCE_ACTS[o['kind']]}. "
            f"Chance he gets there in time: {o['p_success']:.0%}. Chance of a goal it takes away: "
            f"{o['value_if_success']:.1%}. If he is too late, chance of a goal from the player he leaves: "
            f"{o['risk_if_fail']:.1%}.")


def build_defence_request(e: dict, labels: dict, names: dict, team_name: str, state: str, analysis_text: str,
                          deployment: str = "", place: str = "") -> dict:
    """Decision-1's request for the defence at one decision behind a goal: text only, like build_request."""
    criteria = {k: describe_defence(o, names) for k, o in labels.items()}
    criteria["cannot_tell"] = "The information is not enough to decide"
    text = (f"Football match, minute {e['minute']}. {team_name} is defending, {state}. "
            f"{names.get(e['player_id'], 'A player')} of the other team has the ball and plays it on; the attack ends "
            f"in a goal. {place} Defence analysis: {analysis_text}")
    return {"model": deployment, "state": text,
            "questions": {"decision": {"type": "choice", "instructions": DEFENCE_QUESTION, "criteria": criteria}}}


def goal_chain(events):
    """Event ids of every decision behind a goal."""
    return {e["event_id"] for _, chain in goal_chains(events) for e in chain}


def key_decisions(chain: list[dict]) -> set:
    """Event ids of the KEY_DECISIONS decisions of one goal's chain that added the most value (delta_value)."""
    return {e["event_id"] for e in sorted(chain, key=lambda e: -(e["delta_value"] or 0))[:KEY_DECISIONS]}


# ---- the rhythm of the match: control vs chaos, minute by minute ----
PRESSURE_M = 3.0           # an opponent this close to the ball puts the player on it under pressure
RHYTHM_WINDOW_MIN = 5      # the spells told to the Storyteller are this many minutes long
CONTROL_SHARE = 0.6        # a team with this share of the ball over a spell is in control of it


def under_pressure(e: dict) -> bool:
    """An opponent within PRESSURE_M of the ball in the decision's freeze frame."""
    return any(f["team_id"] != e["team_id"] and dist((f["x"], f["y"]), (e["x"], e["y"])) <= PRESSURE_M
               for f in e["frame"] or [])


# ---- Microsoft Decision-1: the request for one moment, and the stand-in used while it is not set up ----
LABELS = "ABCDEFGHI"       # 6 scored options + up to MISSED_MAX from the picture
QUESTION = ("Taking the score, the minute, where on the pitch the ball is and the position analysis into account, "
            "which option is the best "
            "choice for the team in this situation? Weigh the chance it comes off, what it brings if it works and "
            "the danger if it fails. Answer cannot_tell if the information is not enough to decide.")
TYPE_TEXT = {"pass": "Pass to", "ground_cross": "Low cross to", "cross": "Cross towards", "long_ball": "Long ball to",
             "shot": "Shoot at goal", "dribble": "Dribble past the defender", "carry": "Carry the ball forward",
             "hold": "Keep the ball and shield it", "clearance": "Clear the ball upfield",
             "clear_out": "Clear the ball into touch"}
DIRECTION_TEXT = {"through": "through ball", "forward": "forward pass", "side": "sideways pass", "back": "back pass",
                  "throw_in": "throw-in"}


def describe(o: dict, names: dict) -> str:
    """One option in words with its three numbers; a from_picture option has only the analyst's sentence."""
    if o["option_type"] == "from_picture":
        to = f"the ball goes to {names[o['target_player_id']]}; " if o.get("target_player_id") in names else ""
        return f"{o['text']} ({to}seen in the picture by the position analyst; the code has no numbers for it)"
    p = float(o["p_success"])
    if o["option_type"] == "shot":
        return (f"Shoot at goal. Chance it scores: {p:.0%}. If it does not, chance the opponent scores from the "
                f"turnover: {float(o['risk_if_fail']):.1%}.")
    if o.get("offside"):
        return (f"{TYPE_TEXT.get(o['option_type'], o['option_type'])} {names.get(o.get('target_player_id'), '')}".strip()
                + ". He is offside, so the pass cannot count: the other team gets a free kick.")
    head = TYPE_TEXT.get(o["option_type"], o["option_type"])
    if o.get("direction") and o["option_type"] == "pass":
        head = f"{DIRECTION_TEXT[o['direction']].capitalize()} to"
    if o.get("into_space"):
        head = head.replace(" to", " into the space ahead of")
    elif o.get("into_run"):
        head = head.replace(" to", " into the run of")
    if o.get("target_player_id"):
        head += f" {names.get(o['target_player_id'], o['target_player_id'])}"
    shot = ("" if o.get("shot_chance") is None else
            f" From where the ball arrives a first-time shot would score with {float(o['shot_chance']):.0%} chance.")
    return (f"{head}. Chance it comes off: {p:.0%}. If it works, chance the attack ends in a goal: "
            f"{max(0.0, float(o['value_if_success'])):.1%}.{shot} If it fails, chance the opponent scores from the "
            f"turnover: {float(o['risk_if_fail']):.1%}.")


def pitch_place(e: dict, home_id: str) -> str:
    """Where the ball is for the team on it, and what that means for risk (Decision-1 and the analyst read it)."""
    x, y = (e["x"], e["y"]) if e["team_id"] == home_id else (PITCH_X - e["x"], PITCH_Y - e["y"])
    if x < 35:
        return (f"The ball is in his team's defensive third, {x:.0f} m from their own goal: losing it here can "
                "give the other team a chance at once, so safety matters most.")
    if x <= 70:
        return "The ball is in the middle third: keeping it and moving the team forward both matter."
    return (f"The ball is in the attacking third, {goal_distance((x, y)):.0f} m from the other team's goal: here a "
            "riskier option that can lead to a goal is often worth it, and losing the ball costs less.")


def build_request(e: dict, labels: dict, names: dict, team_name: str, state: str, analysis_text: str,
                  deployment: str = "", place: str = "") -> dict:
    """Decision-1 reads text and JSON only, so the picture reaches it through the analyst's words."""
    criteria = {k: describe(o, names) for k, o in labels.items()}
    criteria["cannot_tell"] = "The information is not enough to decide"
    text = (f"Football match, minute {e['minute']}. {team_name} is {state}. {names.get(e['player_id'], 'A player')} "
            f"has the ball and has {len(labels)} options. {place} Position analysis: {analysis_text}")
    return {"model": deployment, "state": text,
            "questions": {"decision": {"type": "choice", "instructions": QUESTION, "criteria": criteria}}}


def ask_stub(labels: dict, state: str, minute: int) -> dict[str, float]:
    """Stand-in for Decision-1: weighs each option's score against its chance of success, valuing that chance
    more when leading late. For building and testing only; these are not the model's numbers."""
    late = min(int(minute), 90) / 90
    weight = {"leading": 1 + 1.5 * late, "level": 1.0, "trailing": max(0.3, 1 - 0.7 * late)}.get(state, 1.0)
    scored = {k: o for k, o in labels.items() if o["option_type"] != "from_picture"}
    evs = {k: float(o["ev"]) for k, o in scored.items()}
    low, span = min(evs.values()), (max(evs.values()) - min(evs.values())) or 1.0
    utility = {k: (evs[k] - low) / span + weight * float(o["p_success"]) for k, o in scored.items()}
    middle = sum(utility.values()) / len(utility)            # a picture option without numbers sits in the middle
    utility |= {k: middle for k in labels if k not in scored}
    first, second = sorted(utility.values(), reverse=True)[:2] if len(utility) > 1 else (1, 0)
    unsure = 0.5 if first - second < 0.02 else 0.1
    exp = {k: math.exp((u - first) / 0.15) for k, u in utility.items()}
    total = sum(exp.values())
    probs = {k: (1 - unsure) * v / total for k, v in exp.items()}
    probs["cannot_tell"] = unsure
    return probs


# ---- logging: what goes into a log line (no prompts, agent answers or file contents) ----
APPLICATION_LOGGER_NAME = "ApplicationLogger"
SENSITIVE_CONTENT_FRAGMENTS = {"body", "content", "image", "message", "payload", "prompt", "request_text",
                               "response_text", "api_key", "token", "secret"}


def sanitize_log_value(key, value):
    normalized_key = re.sub(r"[^a-z0-9]+", "_", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key.strip()).lower()).strip("_")
    if any(fragment in normalized_key for fragment in SENSITIVE_CONTENT_FRAGMENTS):
        return "[redacted]"
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, set)):
        return json.dumps({"item_count": len(value)}, sort_keys=True)
    if isinstance(value, dict):
        return json.dumps({"field_count": len(value)}, sort_keys=True)
    return str(value)


def sanitize_log_attributes(attributes, extra_attributes=None):
    out = {}
    for source in (attributes, extra_attributes or {}):
        for key, value in source.items():
            if value is None or not key.strip():
                continue
            out[key.strip()] = sanitize_log_value(key.strip(), value)
    return out


def format_log_attributes(attributes):
    return " ".join(f"{key}={value}" for key, value in attributes.items())


def build_log_extra(event_name, properties):
    return {"workflow_event_name": event_name, **properties}


# ---- helpers of ScoringService that need only the standard library ----


def goal_angle(x, y):
    """Angle (radians) the 7.32 m goal mouth covers, seen from (x, y)."""
    if x >= PITCH_X:                                  # on or behind the goal line: only between the posts
        return math.pi if abs(y - GOAL_Y) < GOAL_HALF_WIDTH else 0.0
    a = math.atan2(7.32 * (PITCH_X - x), (PITCH_X - x) ** 2 + (GOAL_Y - y) ** 2 - (7.32 / 2) ** 2)
    return a if a >= 0 else a + math.pi


def shadow(b, blockers):
    """Share of the goal mouth hidden from the ball by defenders in the way (0 to 1)."""
    hidden = 0
    for i in range(GOAL_POINTS):
        aim = (PITCH_X, GOAL_Y - GOAL_HALF_WIDTH + (i + 0.5) * 2 * GOAL_HALF_WIDTH / GOAL_POINTS)
        if any(0.03 < along(o, b, aim) < 1 and seg_point_dist(o, b, aim) < BLOCK_REACH for o in blockers):
            hidden += 1
    return hidden / GOAL_POINTS


def xg(x, y, pressure, header=False, blockers=(), keeper=None):
    """Returns (xg, share of the goal hidden)."""
    d = goal_distance((x, y))
    hidden = shadow((x, y), blockers)
    keeper_off = 0.0
    if keeper is not None and along(keeper, (x, y), (PITCH_X, GOAL_Y)) > 0:
        keeper_off = clamp((seg_point_dist(keeper, (x, y), (PITCH_X, GOAL_Y)) - 1.0) / 3, 0, 1)
    z = (XG_BASE + XG_DIST * d + XG_ANGLE * math.log(max(goal_angle(x, y), 0.01)) - XG_SHADOW * hidden
         + XG_KEEPER * keeper_off - XG_PRESSURE * pressure - (XG_HEADER if header else 0))
    return round(min(0.95, sigmoid(z)), 4), round(hidden, 2)


PASS_ONLY = {"from_throw_in", "from_goal_kick", "from_kick_off", "from_corner"}
SET_PIECES = {"from_throw_in", "from_goal_kick", "from_kick_off", "from_corner", "from_free_kick"}
PASS_KINDS = {"cross": "cross", "long": "long_ball", "long_ball": "long_ball"}
KIND_GROUPS = {"pass": {"pass", "ground_cross"}, "cross": {"cross", "ground_cross"},
               "dribble": {"dribble", "carry", "hold"}, "carry": {"dribble", "carry", "hold"},
               "clearance": {"clearance", "clear_out", "long_ball"}}


# ---------- building the moment ----------
def played_with_head(e, prev) -> bool:
    """Is this touch a header? The file's body_part first, then the ball's height, then the time rule."""
    part = getattr(e, "body_part", None)
    if isinstance(part, str) and part in ("head", "foot"):
        return part == "head"
    if prev is None or prev.type != "pass" or getattr(prev, "recipient_id", None) != e.player_id:
        return False                                     # not the receiver of a pass
    arrived = prev.ts_ms + 1000 * flight_time(dist((prev.x, prev.y), (prev.end_x, prev.end_y)))
    first_time = (e.ts_ms - arrived) / 1000 <= HEADER_TOUCH_S     # a high ball he controlled first was not headed
    height = getattr(prev, "pass_height", None)
    if isinstance(height, str) and height:
        return height == "high" and in_box((e.x, e.y)) and first_time
    return getattr(prev, "pass_type", None) == "cross" and first_time


# ---------- the generator's chance models ----------
def skilled(ps, technique):
    """A chance of success adjusted for the passer's technique (0.5 = average, no change)."""
    ps = clamp(ps, 0.001, 0.999)
    return round(sigmoid(math.log(ps / (1 - ps)) + TECH_PASS * (technique - 0.5)), 4)


def blind(origin, target, facing):
    if facing is None:
        return 0.0
    ang = math.atan2(target[1] - origin[1], target[0] - origin[0]) - math.radians(facing)
    return (1 - math.cos(ang)) / 2


def pass_speed(length):
    """m/s of a ground pass of this length: longer passes are hit harder (as in the generator)."""
    return (28 + 1.3 * length) / 3.6


def lead_s(ball, xy, vx, vy):
    """Seconds until a ground pass from ball reaches a player running from xy at (vx, vy): where they meet."""
    t = 0.0
    for _ in range(4):   # the meeting point moves with t; a few rounds settle it
        d = dist(ball, (xy[0] + vx * t, xy[1] + vy * t))
        t = min(RUN_LEAD_MAX_S, d / pass_speed(d))
    return t


def pass_lane(origin, target):
    """Points along a pass where it can be cut out: every PC_LANE_STEP_M, the last few metres left out."""
    length = dist(origin, target)
    n = int((length - PC_LANE_STEP_M) // PC_LANE_STEP_M)
    return [(origin[0] + (target[0] - origin[0]) * k * PC_LANE_STEP_M / length,
             origin[1] + (target[1] - origin[1]) * k * PC_LANE_STEP_M / length) for k in range(1, n + 1)]


def execution(origin, target, pressure, facing):
    """Share of passes played well enough to reach the spot: less under pressure and when played blind."""
    return 1 - PC_PRESS * pressure - PC_BLIND * blind(origin, target, facing)


def pass_direction(b, tgt, line) -> str:
    """through: forward to a team-mate at or near the opponents' last line; else by the metres gained."""
    gain = tgt[0] - b[0]
    if gain > FORWARD_M and tgt[0] >= line - THROUGH_NEAR_M:
        return "through"
    return "forward" if gain > FORWARD_M else "back" if gain < BACK_M else "side"


# ---- helpers of PitchService that need only the standard library ----


def smooth_window(step: float) -> int:
    """Frames in SMOOTH_MS, odd so the window is centred."""
    w = int(round(SMOOTH_MS / step))
    return w + 1 if w % 2 == 0 else w


def behind_goal_line(x) -> bool:
    """The ball is past a goal line: dead until the corner or goal kick, which is taken on the pitch."""
    return x < -GOAL_LINE_SLACK_M or x > PITCH_X + GOAL_LINE_SLACK_M


def goal_x(sign):
    return PITCH_X if sign > 0 else 0.0


def aimed_at_goal(x0, y0, x1, y1, sign) -> bool:
    """Does the line from (x0, y0) through (x1, y1) cross the goal line near the posts?"""
    gx = goal_x(sign)
    if (x1 - x0) * sign <= 0:
        return False
    t = (gx - x0) / (x1 - x0)
    y_at_line = y0 + t * (y1 - y0)
    return abs(y_at_line - GOAL_Y) <= GOAL_HALF_WIDTH + GOAL_MARGIN_M


def contested(t: dict) -> bool:
    """A touch of DUEL_MS or less that loses the ball: a block, a deflection or a poke in a duel. The player had no
    time to choose, so it is not judged as a pass (measured: 2 real passes in 300 such touches are lost)."""
    return t["end"] - t["start"] <= DUEL_MS


# ---------- all together ----------
def clock(ts, period, starts) -> tuple[int, int]:
    """Match clock from the time since the period started (second half starts at 45:00)."""
    secs = (ts - starts[period]) / 1000 + (45 * 60 if period == 2 else 0)
    return int(secs // 60), int(secs % 60)


def clock_of(ts, period, starts, clock_start):
    if clock_start and period in clock_start:
        t0, minute = clock_start[period]
        secs = (ts - t0) / 1000 + minute * 60
        return int(secs // 60), int(secs % 60)
    return clock(ts, period, starts)


def base(t: dict, ts: int) -> dict:
    return {"ts_ms": int(ts), "period": t["period"], "team_id": t["team_id"], "player_id": t["player_id"],
            "pass_type": None, "pass_height": None, "recipient_id": None}
# ---- the moment picture (drawn with mplsoccer) ----
FIG_W, PITCH_H_IN, TEXT_H_IN, TITLE_H_IN = 11.0, 11.0 * PITCH_Y / PITCH_X, 2.1, 0.45   # inches
DPI = 100
LEGEND_ROWS = 6            # players per column in the picture's list of shirt numbers
GRASS, STRIPE, BACKGROUND, LINE_COLOR = "#3b8f40", "#368538", "#1e4d22", "#ffffff"
HOME, AWAY = "#d32f2f", "#1565c0"
# the four marked options: (flag, colour, label, dashed), told apart by colour and dashes
MARKS = [("is_chosen", "#ffeb3b", "Player's choice", False), ("is_best", "#ff40ff", "Biggest chance (AI)", False),
         ("is_safe_best", "#00e5ff", "Safest option (AI)", True), ("is_decision1", "#76ff03", "Decision-1's choice", False)]
DEFENCE_COLOUR = "#ff9100"  # goal pictures: the arrow of where a defender should have gone
MARK_WIDTH = 2.4           # points: a marked option's line
MARK_GAP = 0.35            # share of a player circle between the lines of one option that carries several marks
PLAYER_PT = 20             # points: a player circle's diameter
ZOOM_PAD_M = 9             # metres shown around the ball and the marked targets
ZOOM_MIN_M = 55            # the picture shows at least this much of the pitch's length
EDGE_M = 3                 # metres of grass outside the lines


def zoom(xs: list[float], ys: list[float]) -> tuple[float, float, float, float]:
    """(x0, x1, y0, y1): the part of the pitch the picture shows, the ball and the marked targets with
    ZOOM_PAD_M round them, in the shape of the pitch so every picture has the same size."""
    x0, x1, y0, y1 = min(xs) - ZOOM_PAD_M, max(xs) + ZOOM_PAD_M, min(ys) - ZOOM_PAD_M, max(ys) + ZOOM_PAD_M
    w = min(max(x1 - x0, (y1 - y0) * PITCH_X / PITCH_Y, ZOOM_MIN_M), PITCH_X + 2 * EDGE_M)
    h = w * PITCH_Y / PITCH_X
    cx = clamp((x0 + x1) / 2, w / 2 - EDGE_M, PITCH_X + EDGE_M - w / 2)
    cy = clamp((y0 + y1) / 2, h / 2 - EDGE_M, PITCH_Y + EDGE_M - h / 2)
    return cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2


def label_spot(tip, w, h, gap, circles, radius, segments, boxes, bounds):
    """Centre of a w x h name box next to tip (all in metres) that covers the fewest player circles, arrows and
    other boxes and stays inside bounds (x0, x1, y0, y1); the eight sides are tried, above-right first."""
    def inside(x, y, b):
        return b[0] <= x <= b[1] and b[2] <= y <= b[3]

    def cost(cx, cy):
        b = (cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2)
        grown = (b[0] - radius, b[1] + radius, b[2] - radius, b[3] + radius)
        c = 10 * sum(inside(x, y, grown) for x, y in circles)
        c += 5 * sum(any(inside(a[0] + (z[0] - a[0]) * k / 20, a[1] + (z[1] - a[1]) * k / 20, b) for k in range(21))
                     for a, z in segments)
        c += 10 * sum(b[0] < o[1] and o[0] < b[1] and b[2] < o[3] and o[2] < b[3] for o in boxes)
        return c + (100 if not (bounds[0] <= b[0] and b[1] <= bounds[1] and bounds[2] <= b[2] and b[3] <= bounds[3])
                    else 0)
    sides = [(1, 1), (1, 0), (0, 1), (-1, 1), (1, -1), (-1, 0), (0, -1), (-1, -1)]
    spots = [(tip[0] + sx * (gap + w / 2), tip[1] + sy * (gap + h / 2)) for sx, sy in sides]
    return min(spots, key=lambda s: cost(*s))   # min keeps the first of equal ones


def spread(points: list[tuple[float, float]], gap: float, fixed: int | None = None, rounds: int = 12) -> list[list[float]]:
    """Spots moved apart until no two are closer than gap (players standing on top of each other show as
    two circles side by side). fixed: the index that stays put (the ball)."""
    out = [list(p) for p in points]
    for _ in range(rounds):
        moved = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                dx, dy = out[j][0] - out[i][0], out[j][1] - out[i][1]
                d = math.hypot(dx, dy)
                if d >= gap:
                    continue
                if d < 1e-6:
                    dx, dy, d = 1.0, 0.0, 1.0
                push = (gap - d) / d
                wi, wj = (0.0, 1.0) if i == fixed else (1.0, 0.0) if j == fixed else (0.5, 0.5)
                out[i][0] -= dx * push * wi
                out[i][1] -= dy * push * wi
                out[j][0] += dx * push * wj
                out[j][1] += dy * push * wj
                moved = True
        if not moved:
            break
    return out


TRACKING_COLS = ["ts_ms", "period", "object_id", "team_id", "x", "y"]


# ---- helpers of AzureFoundryService that need only the standard library ----


def foundry_root(endpoint: str) -> str:
    """Any address Foundry shows for a resource (.../openai/v1, .../api/projects/<name>, the bare resource) -> the
    bare resource address the Agent Framework client wants (it adds /openai/v1 itself)."""
    base = endpoint.rstrip("/")
    if "/api/projects/" in base:
        base = base.split("/api/projects/")[0]
    return base.removesuffix("/openai/v1").removesuffix("/openai")


def decision1_url(endpoint: str) -> str:
    """The resource address (https://<name>.services.ai.azure.com), also as the playground or the project page shows
    it (/providers/microsoft..., /api/projects/<project>, /openai/v1) -> the systemone route at the resource root.
    Under a project path Azure answers 400 "Missing required query parameter: api-version"."""
    base = endpoint.strip().rstrip("/").removesuffix("/v1/systemone").removesuffix("/providers/microsoft")
    return f"{foundry_root(base)}/providers/microsoft/v1/systemone"


def choice_probabilities(answer: dict) -> dict[str, float]:
    """A choice answer: the chosen option and, when given, a probability for every option. Microsoft's page
    does not name the field, so the usual names are tried; with none of them the choice gets its confidence."""
    for key in ("probabilities", "distribution", "scores", "options"):
        if isinstance(answer.get(key), dict):
            return {k: float(v) for k, v in answer[key].items()}
    return {answer["choice"]: float(answer.get("confidence", 1.0))}


# ---- expected threat: the learned grid (generator/learn_xt.py) ----
XT_GRID = json.loads((Path(__file__).with_name("xt_grid.json")).read_text(encoding="utf-8"))["grid"]


def xt(x, y):
    cx = min(int(clamp(x, 0, PITCH_X - 1e-6) / PITCH_X * 16), 15)
    cy = min(int(clamp(y, 0, PITCH_Y - 1e-6) / PITCH_Y * 12), 11)
    return round(XT_GRID[cx][cy], 4)
