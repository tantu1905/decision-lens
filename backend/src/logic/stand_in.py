"""Local stand-ins for the agents, used while Foundry is not set up (and when one agent call fails). They
follow the same shapes as the agents' answers and use only the code's numbers, so the screen and the tests
work without Azure. Every answer they give is marked source=stub."""
from src.core.utils import (
    DEFENCE_SHORTLIST_MAX,
    FAN_HANDLES,
    FAN_POSTS_MAX,
    SAME_CHOICE_SCORE,
    SCOUT_PICKS,
    best,
    chosen,
    key_decisions,
    kind_of,
    word)
from src.schemas.agents import (
    CoachReport,
    CriticalPick,
    CriticalPicks,
    DefenceAnalysis,
    FanFeed,
    FanPost,
    GoalAnalysis,
    MatchSummary,
    OptionNote,
    PositionAnalysis,
    ScoutPick,
    ScoutPicks,
    Sentence,
)

def reason(e: dict, names: dict) -> Sentence:
    return Sentence(text=f"{names.get(e['player_id'], 'The player')} chose {word(chosen(e))} where {word(best(e))} "
                         "was best.", event_ids=[e["event_id"]])


def scout(decisions: list[dict], names: dict) -> ScoutPicks:
    top = sorted(decisions, key=lambda e: e["importance"] or 0, reverse=True)[:SCOUT_PICKS]
    return ScoutPicks(picks=[ScoutPick(event_id=e["event_id"], reason=reason(e, names)) for e in top])


def critical(candidates: list[dict], reasons: dict, chain: set, names: dict, most: int) -> CriticalPicks:
    """The most important candidates (at most `most`), in match order."""
    top = sorted(candidates, key=lambda e: e["importance"] or 0, reverse=True)[:most]
    top = sorted(top, key=lambda e: e["ts_ms"])
    return CriticalPicks(picks=[CriticalPick(event_id=e["event_id"], rank=i, kind=kind_of(e, e["event_id"] in chain),
                                             reason=reasons.get(e["event_id"]) or reason(e, names))
                                for i, e in enumerate(top, 1)])


def position(e: dict, opts: list[dict], attacking: bool, zone: str) -> PositionAnalysis:
    eid = [e["event_id"]]
    return PositionAnalysis(
        phase="attack" if attacking else "defence", zone=zone.replace("_", " "),
        situation=[Sentence(text=f"The ball is in the {zone.replace('_', ' ')} and his team is "
                                 f"{'attacking' if attacking else 'defending'}.", event_ids=eid)],
        shortlist=[o["option_id"] for o in opts if not o["is_chosen"]],
        options=[OptionNote(option_id=o["option_id"], note=f"{word(o).capitalize()}: the code rates it "
                            f"{'safe' if o['p_success'] >= 0.7 else 'risky'}.") for o in opts],
        best_option_id=next((o["option_id"] for o in opts if o["is_best"]), ""),
        safest_option_id=next((o["option_id"] for o in opts if o["is_safe_best"]), ""))


def coach(e: dict, player_pick: dict | None, d1_pick: dict, name: str, base: float | None = None) -> CoachReport:
    eid = [e["event_id"]]
    same = bool(player_pick) and player_pick["option_id"] == d1_pick["option_id"]
    if same:
        text = [f"{name} chose {word(player_pick)}, the same as Decision-1.",
                "Given the score and the minute it was the right balance of risk and reward."]
    else:
        text = [f"{name} chose {word(player_pick)}, Decision-1 would have chosen {word(d1_pick)}.",
                f"{word(d1_pick).capitalize()} weighed the chance and the danger better at this score and minute."]
    score = max(base if base is not None else 8.0, SAME_CHOICE_SCORE) if same else base if base is not None else 5.0
    if player_pick and player_pick.get("offside"):
        text.append("The team-mate was offside, so the pass could not count: the other team gets a free kick.")
    return CoachReport(same_choice=same, score=score, sentences=[Sentence(text=t, event_ids=eid) for t in text])


def summary(moments: list[dict]) -> MatchSummary:
    same = [m for m in moments if (m.get("coach") or {}).get("same_choice")]
    ids = [m["event_id"] for m in moments]
    return MatchSummary(parts=[Sentence(text=f"In {len(moments)} critical moments the players made the same choice as "
                                             f"Decision-1 {len(same)} times.", event_ids=ids)])


def goal(chain: list[dict], names: dict, fixes: dict | None = None, lost: dict | None = None) -> GoalAnalysis:
    """The decisions that added the most value, and for each the safest other option, which would have kept the
    ball but not made the goal; what the code's defender could have done (fixes: event_id -> defence_fix) and how
    the conceding team lost the ball (lost: its last decision before the chain)."""
    key = [e for e in sorted(chain, key=lambda e: -(e["delta_value"] or 0)) if e["event_id"] in key_decisions(chain)]
    name = lambda e: names.get(e["player_id"], "The player")   # noqa: E731
    said = [Sentence(text=f"{name(e)}'s choice of {word(chosen(e))} moved the attack closer to the goal than any "
                          "other decision in it.", event_ids=[e["event_id"]]) for e in key[:1]]
    said += [Sentence(text=f"{name(e)} then added {word(chosen(e))}.", event_ids=[e["event_id"]]) for e in key[1:]]
    what_if = []
    for e in key:
        rest = [o for o in e["options"] if not o["is_chosen"]]
        alt = max(rest, key=lambda o: o["p_success"]) if rest else None
        what_if.append(Sentence(text=f"Had {name(e)} chosen {word(alt)} instead, the team would have kept the ball "
                                     "but the defence would have had time to recover, and the goal would not have come.",
                                event_ids=[e["event_id"]]))
    notes = [Sentence(text=f"{name(e)} chose {word(chosen(e))}.", event_ids=[e["event_id"]]) for e in chain]
    defence = [Sentence(text=f"{names.get(f['player_id'], 'A defender')} could have {f['words']}"
                             + (f", but he would have been {f['late_s']:.1f} s late." if f["late_s"] else " in time."),
                        event_ids=[e["event_id"]]) for e in chain if (f := (fixes or {}).get(e["event_id"]))]
    errors = [Sentence(text=f"{name(lost)} chose {word(chosen(lost))}"
                            + (f" where {word(best(lost))} was better" if (lost["regret"] or 0) > 0 else "")
                            + ", and the attack that led to the goal started from there.",
                       event_ids=[lost["event_id"]])] if lost else []
    return GoalAnalysis(key_event_ids=[e["event_id"] for e in key], sentences=said, notes=notes, what_if=what_if,
                        defence=defence, opponent_errors=errors)


def defence(e: dict, opts: list[dict]) -> DefenceAnalysis:
    """The defence options by the code's own order (expected value)."""
    return DefenceAnalysis(situation=[Sentence(text="The defence had to stop the ball reaching the danger zone.",
                                               event_ids=[e["event_id"]])],
                           shortlist=[o["option_id"] for o in opts[:DEFENCE_SHORTLIST_MAX]])


FAN_LINES = {"good_decision": ("praise", "What a decision from {name}! That is how you play it."),
             "costly_mistake": ("anger", "{name}, what was that? We gave it away there."),
             "missed_chance": ("worry", "{name} had to do better with that one. Nervous times."),
             "goal_build_up": ("joy", "Lovely move, {name} keeps it flowing!"),
             "defensive_moment": ("praise", "Big moment at the back from {name}. Calm heads.")}


def fan_feed(moments: list[dict], goals: list[dict], names: dict, home_id: str, away_id: str, home_name: str,
             away_name: str) -> FanFeed:
    """Made-up fans react to each goal (both sides) and to the most important critical moments, in minute order."""
    posts = []
    for g in goals:
        team, other, other_id = ((home_name, away_name, away_id) if g["team_id"] == home_id
                                 else (away_name, home_name, home_id))
        posts.append(FanPost(minute=g["minute"], handle="", team_id=g["team_id"], mood="joy",
                             text=f"GOAL! {names.get(g['player_id'], 'Someone')} scores for {team}! Get in!",
                             event_ids=[g["event_id"]]))
        posts.append(FanPost(minute=g["minute"], handle="", team_id=other_id, mood="worry",
                             text=f"{other} need a response now. Wake up!", event_ids=[g["event_id"]]))
    room = max(0, FAN_POSTS_MAX - len(posts))
    for e in sorted(moments, key=lambda e: e["importance"] or 0, reverse=True)[:room]:
        mood, text = FAN_LINES.get(e["kind"], ("banter", "{name} on the ball. Here we go."))
        posts.append(FanPost(minute=e["minute"], handle="", team_id=e["team_id"], mood=mood,
                             text=text.format(name=names.get(e["player_id"], "The player")), event_ids=[e["event_id"]]))
    posts.sort(key=lambda p: p.minute)
    for i, p in enumerate(posts):
        p.handle = FAN_HANDLES[i % len(FAN_HANDLES)]
    return FanFeed(posts=posts)
