"""What the routes take and return."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.schemas.agents import CoachReport, FanPost, GoalAnalysis, MatchSummary, PositionAnalysis


class MatchMeta(BaseModel):
    """What comes with an uploaded tracking file."""
    match_id: str
    home_id: str
    away_id: str
    home_name: str
    away_name: str
    period: int = 1
    start_minute: int = 0            # the match minute of the clip's first frame
    score_home: int = 0              # the score when the clip starts
    score_away: int = 0
    synthetic: bool = True
    keepers: list[str] = []
    players: list[dict] = []         # optional: player_id, name, position, shirt, max_speed, technique ...


class MatchView(BaseModel):
    match_id: str
    home_id: str
    away_id: str
    home_name: str
    away_name: str
    status: str
    step: str | None = None
    progress: float = 0.0
    message: str | None = None
    decisions: int = 0
    moments: int = 0
    score: dict = {}
    summary: MatchSummary | None = None
    created_at: datetime | None = None


class OptionView(BaseModel):
    option_id: str
    option_type: str                 # a scored option, or from_picture: seen by the analyst, no numbers
    direction: str | None = None
    target_name: str | None = None
    target_player_id: str | None = None
    text: str | None = None          # the analyst's sentence (from_picture, or his idea the code had scored)
    into_run: bool = False
    shot_chance: float | None = None # passes within shot range: xG of a first-time shot from where the ball arrives
    target_x: float | None = None    # where the ball goes (none for an option seen only in the picture)
    target_y: float | None = None
    p_success: float | None = None
    value_if_success: float | None = None
    risk_if_fail: float | None = None
    ev: float | None = None
    is_chosen: bool = False
    is_best: bool = False
    is_safe_best: bool = False
    is_decision1: bool = False


class Decision1View(BaseModel):
    source: Literal["decision1", "stub"]
    option_id: str
    option_type: str
    probability: float
    cannot_tell: float
    probabilities: dict[str, float]


class MomentView(BaseModel):
    event_id: str
    rank: int
    kind: str
    minute: int
    second: int
    team_id: str
    player_id: str
    player_name: str | None
    ts_ms: int                       # the replay stops here to show the options
    x: float                         # the ball at the decision
    y: float
    score: str
    reason: str
    status: str
    image_url: str | None = None
    options: list[OptionView] = []
    chosen_option_id: str | None = None
    analysis: PositionAnalysis | None = None
    decision1: Decision1View | None = None
    coach: CoachReport | None = None
    source: str = "agent"            # agent, or stub when the local stand-in answered
    error: str | None = None


class PlayerCard(BaseModel):
    player_id: str
    name: str
    team_id: str
    position: str | None
    moments: int
    avg_score: float | None          # the mean of its moments' decision scores, 0-10
    share: float | None
    best_event_id: str | None
    worst_event_id: str | None
    passes: int = 0
    pass_m: float | None = None      # average pass length, metres
    pass_pct: float | None = None    # share of passes that reached a team-mate, %
    top_speed_kmh: float | None = None
    distance_km: float | None = None # covered in the analysed clip


class ChainDecision(BaseModel):
    event_id: str
    minute: int
    second: int
    player_id: str | None
    player_name: str | None
    type: str
    outcome: str | None
    delta_value: float | None        # value of where the ball ended up minus where it started
    chosen_ev: float | None
    best_ev: float | None
    regret: float | None
    ts_ms: int                       # where the 3D replay stops, and where the ball was
    x: float
    y: float
    key: bool                        # one of the decisions that made the goal
    note: str | None = None          # the Goal Analyst on this decision
    what_if: str | None = None       # a key decision: how another choice would have lost the goal
    defence: str | None = None       # the Goal Analyst: what one defender could have done to stop it
    defence_by_decision1: bool = False   # that action is Decision-1's choice among the defence's options (key decisions)
    image_url: str
    options: list[OptionView]


class GoalView(BaseModel):
    event_id: str
    minute: int
    second: int
    team_id: str
    scorer_id: str | None
    scorer_name: str | None
    ts_ms: int                       # the decisions' replays run to here
    score: str                       # after the goal
    decisions: list[ChainDecision]
    analysis: GoalAnalysis | None = None   # the Goal Analyst's, after the flow has run
    shot_speed_kmh: float | None = None    # the ball just after the scorer's shot
    source: str | None = None



class RhythmMinute(BaseModel):
    """One match minute: who had the ball, how hard each team was pressed and how often the ball changed hands."""
    minute: int
    possession_home: float | None    # share of the minute's time on the ball (none: no touches in it)
    possession_away: float | None
    pressure_home: float | None      # share of the team's decisions with an opponent within PRESSURE_M of the ball
    pressure_away: float | None
    turnovers: int                   # the ball changed team in open play
    decisions: int


class RhythmGoal(BaseModel):
    minute: int
    second: int
    team_id: str


class RhythmView(BaseModel):
    home_id: str
    away_id: str
    home_name: str
    away_name: str
    minutes: list[RhythmMinute]
    goals: list[RhythmGoal]
    spells: list[str]                # the most controlled and the most chaotic spell, in words


class FlowStarted(BaseModel):
    match_id: str
    status: str


class FanFeedView(BaseModel):
    posts: list[FanPost] = []        # empty until the flow has run
    source: str | None = None        # agent, or stub when the local stand-in answered
