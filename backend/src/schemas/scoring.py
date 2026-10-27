"""Scoring input and output (ScoringService): the moment it scores and the options it finds."""
from pydantic import BaseModel


class MomentPlayer(BaseModel):
    player_id: str
    xy: tuple[float, float]          # turned to the attacking team's frame
    mate: bool                       # same team as the ball carrier
    is_keeper: bool = False
    is_actor: bool = False
    technique: float = 0.5
    defending: float = 0.5
    max_speed: float = 8.5
    height_cm: float = 180
    strength: float = 0.5
    line: str = "mid"                # gk, def, mid, fwd
    role: str = ""
    vx: float | None = None          # the way he is running, m/s, in the same frame as xy
    vy: float | None = None


class Moment(BaseModel):
    """Input of scoring: one decision, the team on the ball playing towards +x."""
    event_id: str
    ball: tuple[float, float]
    end: tuple[float, float]
    chosen_type: str
    pass_type: str | None = None     # cross / long: which kind of pass option the player took
    outcome: str
    recipient_id: str | None = None
    open_play: bool = True
    pattern: str = "open_play"
    header: bool = False
    facing: float | None = None
    technique: float = 0.5
    carrier_line: str = "mid"
    wind_speed: float = 0.0
    players: list[MomentPlayer]


class ScoredOption(BaseModel):
    option_type: str                 # pass, ground_cross, cross, long_ball, shot, dribble, carry, hold, clearance
    direction: str | None = None     # passes: through, forward, side, back, throw_in
    target_player_id: str | None = None
    target_x: float
    target_y: float
    p_success: float                 # chance it comes off
    value_if_success: float          # chance the attack ends in a goal if it works (xT / xG)
    risk_if_fail: float              # chance the opponent scores from the turnover
    ev: float
    offside: bool = False
    into_run: bool = False           # a pass played where the team-mate will be, not where he is
    into_space: bool = False         # ...further ahead, into the space he has to sprint onto
    shot_chance: float | None = None # passes within shot range: xG of a first-time shot from where the ball arrives
    is_chosen: bool = False
    is_best: bool = False
    is_safe_best: bool = False


class ScoredDecision(BaseModel):
    event_id: str
    options: list[ScoredOption]
    chosen_ev: float
    best_ev: float
    safe_best_ev: float | None
    regret: float
    regret_rel: float
    delta_value: float
