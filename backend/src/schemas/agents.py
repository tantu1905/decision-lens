"""The agents' answers (structured output of the Foundry agents and the local stand-ins)."""
from typing import Literal

from pydantic import BaseModel, Field


class Sentence(BaseModel):
    text: str
    event_ids: list[str] = Field(default_factory=list, description="the events this sentence rests on")


class MissedOption(Sentence):
    shirt: int | None = Field(default=None, description="shirt number of the team-mate the ball goes to; empty for a "
                              "shot or when it goes to no one player")
    into_run: bool = Field(default=False, description="true when the ball goes into the space ahead of that "
                           "team-mate's run, not to his feet")
    shot: bool = Field(default=False, description="true for a shot at goal (then shirt stays empty)")
    carry: bool = Field(default=False, description="true when the player keeps the ball and runs with it (a dribble "
                        "or a carry; then shirt stays empty)")
    clearance: bool = Field(default=False, description="true for a clearance or a long kick upfield to no one player "
                            "(then shirt stays empty)")


class ScoutPick(BaseModel):
    event_id: str
    reason: Sentence


class ScoutPicks(BaseModel):
    picks: list[ScoutPick]


class CriticalPick(BaseModel):
    event_id: str
    rank: int
    kind: Literal["missed_chance", "costly_mistake", "good_decision", "goal_build_up", "defensive_moment"]
    reason: Sentence


class CriticalPicks(BaseModel):
    picks: list[CriticalPick]


class OptionNote(BaseModel):
    option_id: str
    note: str = Field(description="one sentence on why this option is good or risky here")


class PositionAnalysis(BaseModel):
    """The GPT position analyst: what the picture shows, in football words."""
    phase: Literal["attack", "defence", "transition"]
    zone: str = Field(description="where the ball is, for example own box, middle third, final third, box")
    situation: list[Sentence] = Field(description="2-4 sentences: where the player is, who presses, where the space is")
    shortlist: list[str] = Field(default_factory=list, description="up to 5 option ids, besides the player's choice, "
                                 "that Decision-1 should weigh")
    options: list[OptionNote]
    missed: list[MissedOption] = Field(default_factory=list, description="options the picture shows but the code did "
                                   "not list, one sentence each, at most 3, no numbers")
    best_option_id: str = Field(description="the option id you judge raises the team's chance of scoring the most, "
                                "weighed against how likely it comes off")
    safest_option_id: str = Field(description="the option id you judge the safest good option: likely to come off "
                                  "and still worth playing")


class CoachReport(BaseModel):
    """The coach: the player's choice against Decision-1's."""
    same_choice: bool
    score: float = Field(ge=0, le=10, description="the player's decision out of 10, judged on its quality, not on how it turned out")
    sentences: list[Sentence] = Field(description="3-5 sentences: why it was right, or what the other choice would have brought")


class MatchSummary(BaseModel):
    parts: list[Sentence] = Field(description="4-8 sentences: the story of the match through its decisions")


class DefenceAnalysis(BaseModel):
    """The Defence Analyst: at one decision behind a goal, what the defence faced and which defenders' actions
    Decision-1 should weigh."""
    situation: list[Sentence] = Field(description="1-2 sentences: where the danger was and what the defence left open")
    shortlist: list[str] = Field(description="2-4 option ids of defence actions, the most sensible first")


class GoalAnalysis(BaseModel):
    """The Goal Analyst: the decisions that made one goal, and what another choice would have cost."""
    key_event_ids: list[str] = Field(description="the 1-3 decisions of the chain that made the goal, most important first")
    sentences: list[Sentence] = Field(description="3-5 sentences: how the goal was built and which decisions made it")
    notes: list[Sentence] = Field(default_factory=list, description="one sentence per decision of the chain, in "
                                  "order: what the player did and what it gave the attack; event_ids is that decision")
    what_if: list[Sentence] = Field(description="one sentence per key decision: had the player chosen another "
                                    "option, how the goal would have been lost; event_ids is that decision")
    defence: list[Sentence] = Field(default_factory=list, description="one sentence per decision with a Defence line: "
                                    "what that defender could have done to stop it; event_ids is that decision")
    opponent_errors: list[Sentence] = Field(default_factory=list, description="1-2 sentences on the conceding team's "
                                            "mistakes that led to the goal, such as how it lost the ball")


class FanPost(BaseModel):
    """One made-up fan's short reaction during the match."""
    minute: int
    handle: str = Field(description="a made-up fan handle, never a real person or account")
    team_id: str | None = Field(default=None, description="the team this fan supports, as its id; empty if neutral")
    text: str = Field(description="one or two short sentences, social-media style")
    mood: Literal["joy", "anger", "worry", "praise", "banter"]
    event_ids: list[str] = Field(default=[], description="the events the post reacts to, as given; never in the text")


class FanFeed(BaseModel):
    """The Fan Feed agent: fans of both sides reacting through the match."""
    posts: list[FanPost] = Field(description="10-15 posts in minute order, from both sides")
