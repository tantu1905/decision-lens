"""The critical-moment flow, from the scored decisions to the match story:
1. the decisions (but those behind a goal) are cut into stretches of 50; one Scout agent per stretch picks up to 10 (in parallel),
2. the candidates are cut into stretches of 30; one Critical Moment agent per stretch (in parallel) ranks its share
   of the moments that shaped the match (20-25 in 15 minutes, 50-60 in 90),
3. every moment, in parallel: picture (PitchService, saved by AzureBlobService) -> its options and numbers
   (scored by ScoringService) -> GPT Position Analyst -> Microsoft Decision-1 -> Coach,
4. alongside, one Goal Analyst per goal (no Decision-1) reads every decision behind it, names the ones that made it
   and what another choice would have cost; those decisions are never critical moments,
5. the Match Storyteller writes the story, then the Fan Feed agent made-up fans' posts through the match,
6. the player report cards: each player's average decision score (code only, no agent).
Agents run through AzureFoundryService; when it is not set up, or a call fails, the local stand-in answers
for that step and the run goes on. Every sentence goes through the fabrication check (core/utils.py check)."""
import asyncio
import math
import re
from pathlib import Path

from fastapi import BackgroundTasks

from src.core.settings import settings
from src.core.telemetry import emit_telemetry_event, emit_telemetry_exception, latency_tracker
from src.core.utils import (
    BadInput,
    COACH_BASE_RANGE,
    CONTROL_SHARE,
    CRITICAL_CHUNK,
    DEFENCE_SHORTLIST_MAX,
    FAN_POSTS_MAX,
    KINDS,
    LABELS,
    PHASE_BREAK_MS,
    RHYTHM_WINDOW_MIN,
    SAME_CHOICE_SCORE,
    SCORE_MIN,
    SCOUT_CHUNK,
    SCOUT_PICKS,
    NotFound,
    analyst_list,
    apart,
    ask_stub,
    base_score,
    best,
    build_defence_request,
    build_request,
    check,
    chosen,
    critical_range,
    defence_fix,
    defence_options,
    describe,
    describe_defence,
    goal_chain,
    goal_chains,
    good_edge,
    KEY_DECISIONS,
    key_decisions,
    lost_before,
    moment_options,
    name_of,
    phase_of,
    phases,
    picture_options,
    pitch_place,
    rushed,
    positions_table,
    scored_twin,
    situation,
    under_pressure)
from src.db.crud import event, match, moment, player
from src.schemas.agents import (
    CoachReport,
    DefenceAnalysis,
    CriticalPicks,
    FanFeed,
    GoalAnalysis,
    MatchSummary,
    MissedOption,
    PositionAnalysis,
    ScoutPicks,
    Sentence,
)
from src.schemas.views import (ChainDecision, FanFeedView, FlowStarted, GoalView, MatchView, MomentView, OptionView,
                               PlayerCard, RhythmGoal, RhythmMinute, RhythmView)
from src.services.azure_blob_service import matchFilesBlob
from src.services.azure_foundry_service import foundry
from src.services.pitch_service import pitch
from src.logic import stand_in
from src.logic.match import load_metrica, must_be_ready

PROMPTS = Path(__file__).parent / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / "common.md").read_text(encoding="utf-8") + "\n" + (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


# ---------- starting and reading ----------
def start(match_id: str, tasks: BackgroundTasks) -> FlowStarted:
    if must_be_ready(match_id).status == "running":   # a second run would delete the moments the first is writing
        raise BadInput(f"match {match_id} is already being analysed: wait until it is done")
    match.update(match_id, status="running", step="scouts", progress=0.0, message=None)
    tasks.add_task(run_sync, match_id)
    return FlowStarted(match_id=match_id, status="running")


def run_sync(match_id: str) -> None:
    asyncio.run(run(match_id))


def load_and_run(tasks: BackgroundTasks) -> MatchView:
    """A new piece of the sample match, and the agents on it as soon as it is prepared (the background jobs run in
    the order they were added)."""
    view = load_metrica(tasks)
    tasks.add_task(run_when_ready, view.match_id)
    return view


def run_when_ready(match_id: str) -> None:
    if match.read(match_id).status == "ready":    # a failed preparation keeps its reason on the match
        match.update(match_id, status="running", step="scouts", progress=0.0, message=None)
        run_sync(match_id)


def moments(match_id: str) -> list[MomentView]:
    must_be_ready(match_id)
    m = match.read(match_id)
    players = {p["player_id"]: p for p in player.read_all(match_id)}
    names = {pid: name_of(p) for pid, p in players.items()}
    rows = moment.read_all(match_id)
    events = {e["event_id"]: e for e in event.read_all(match_id, [r["event_id"] for r in rows])}
    return [moment_view(match_id, r, events[r["event_id"]], names, m.home_id, shirts(players)) for r in rows]


def one_moment(match_id: str, event_id: str) -> MomentView:
    """Only this moment's rows: a remote database answers each query over the network."""
    m = must_be_ready(match_id)
    r = moment.read(match_id, event_id)
    if r is None:
        raise NotFound(f"no critical moment {event_id}")
    players = {p["player_id"]: p for p in player.read_all(match_id)}
    names = {pid: name_of(p) for pid, p in players.items()}
    return moment_view(match_id, r, event.read(match_id, event_id), names, m.home_id, shirts(players))


def moment_image(match_id: str, event_id: str) -> bytes:
    r = moment.read(match_id, event_id)
    if r is None or not r["image_file"]:
        raise NotFound(f"no picture for {event_id}")
    return matchFilesBlob.get_blob(r["image_file"])


# ---------- the run ----------
async def run(match_id: str) -> None:
    try:
        m = match.read(match_id)
        ctx = context(m)
        emit_telemetry_event("flow.started", match_id=match_id, decisions=len(ctx["decisions"]), source=ctx["source"])
        with latency_tracker("flow.critical_moments", match_id=match_id):
            picks = await critical(ctx, await scouts(ctx))
        moment.delete(match_id)
        moment.create(match_id, [{"event_id": p.event_id, "rank": p.rank, "kind": p.kind, "reason": p.reason.text,
                                       "status": "waiting", "source": ctx["source"]} for p in picks.picks])
        match.update(match_id, step="moments", progress=0.3)
        with latency_tracker("flow.moments", match_id=match_id, moments=len(picks.picks)):
            goal_reports, _ = await asyncio.gather(goal_analysts(ctx),
                                                   asyncio.gather(*(one(ctx, p.event_id) for p in picks.picks)))
        match.update(match_id, step="summary", progress=0.9)
        story = await summary(ctx)
        feed, feed_src = await fan_feed(ctx, story)
        match.update(match_id, status="done", step="done", progress=1.0,
                     summary=story.model_dump() | {"goals": goal_reports,
                                                   "fan_feed": feed.model_dump() | {"source": feed_src}},
                     message=f"{len(picks.picks)} critical moments")
        matchFilesBlob.delete_blobs_by_prefix(decision_images(match_id))   # drawn with the old defence picks
        emit_telemetry_event("flow.done", match_id=match_id, moments=len(picks.picks))
    except Exception as err:                    # noqa: BLE001  (the run ends with its reason on the match)
        emit_telemetry_exception("flow.failed", err, match_id=match_id)
        match.update(match_id, status="failed", step=None, message=str(err)[:500] or type(err).__name__)


def context(m) -> dict:
    """Everything one run needs, read once: the decisions, names, goals and the limit on parallel calls."""
    events = event.read_all(m.match_id)
    decisions = [e for e in events if e["options"]]
    players = {p["player_id"]: p for p in player.read_all(m.match_id)}
    return {"m": m, "events": events, "decisions": decisions, "by_id": {e["event_id"]: e for e in decisions},
            "players": players, "names": {pid: name_of(p) for pid, p in players.items()},
            "chain": goal_chain(events), "range": critical_range(decisions), "phase": phases(events), "rushed": rushed(events), "limit": asyncio.Semaphore(settings.max_parallel),
            "source": "agent" if foundry.ready else "stub"}


# -- agents with a fallback --
async def ask(ctx: dict, name: str, text: str, shape, fallback, numbers_for, image: bytes | None = None,
              ids: list[str] = ()):
    """The agent's answer, checked; sentences that fail are sent back once, then dropped. Any failure:
    the stand-in's answer (fallback()). Returns (answer, source)."""
    if not foundry.ready:
        return fallback(), "stub"
    try:
        async with ctx["limit"]:
            out = await foundry.run(name, prompt(name), text, shape, image)
            fill_ids(out, ids)
            problems = check(sentences(out), numbers_for)
            if problems:
                out = await foundry.run(name, prompt(name), f"{text}\n\nYour last answer was:\n"
                                        f"{out.model_dump_json()}\n\nFix these problems:\n- " + "\n- ".join(problems),
                                        shape, image)
                fill_ids(out, ids)
        return drop_failing(out, numbers_for), "agent"
    except Exception as err:                # noqa: BLE001  (model, network or shape failure: stand-in)
        emit_telemetry_exception("agent.failed", err, agent=name, fallback="stub")
        return fallback(), "stub"

def numbers(ctx: dict, extra: dict | None = None):
    """numbers_for for verify: the percentages and the minute of each event, plus extra percentages."""
    def numbers_for(event_id):
        e = ctx["by_id"].get(event_id)
        if e is None:
            raise NotFound(event_id)
        pct = {100 * float(o[k]) for o in e["options"] for k in ("p_success", "value_if_success", "risk_if_fail")}
        return {"pct": pct | set((extra or {}).get(event_id, ())), "minutes": {e["minute"]}}
    return numbers_for

# -- 1. scouts --
async def scouts(ctx: dict) -> list[dict]:
    pool = [e for e in ctx["decisions"] if e["event_id"] not in ctx["chain"]]   # the Goal Analyst has those
    chunks = [pool[i:i + SCOUT_CHUNK] for i in range(0, len(pool), SCOUT_CHUNK)]

    async def one(chunk):
        ids = {e["event_id"] for e in chunk}
        text = "\n".join(line(ctx, e) for e in chunk)
        out, _ = await ask(ctx, "scout", story(ctx) + "\n\nYour stretch:\n" + text, ScoutPicks,
                                lambda: stand_in.scout(chunk, ctx["names"]), numbers(ctx))
        picks = [p for p in out.picks if p.event_id in ids][:SCOUT_PICKS]
        return picks or stand_in.scout(chunk, ctx["names"]).picks
    found = await asyncio.gather(*(one(c) for c in chunks))
    seen, out = set(), []
    for p in (p for group in found for p in group):
        if p.event_id not in seen:
            seen.add(p.event_id)
            out.append({**ctx["by_id"][p.event_id], "reason": p.reason})
    return out

# -- 2. the critical moments --
async def critical(ctx: dict, candidates: list[dict]) -> CriticalPicks:
    reasons = {c["event_id"]: c["reason"] for c in candidates}
    ids = set(reasons)
    lo, hi = ctx["range"]
    candidates = sorted(candidates, key=lambda c: c["ts_ms"])
    chunks = [candidates[i:i + CRITICAL_CHUNK] for i in range(0, len(candidates), CRITICAL_CHUNK)]

    async def one(chunk):              # one agent per stretch of candidates, asked for its share of the moments
        share = len(chunk) / len(candidates)
        few, most = max(1, round(lo * share)), max(1, round(hi * share))
        text = story(ctx) + (f"\n\nChoose and rank {few} to {most} moments, at least {max(1, few // 4)} of them "
                             f"good decisions.\n\nCandidates:\n") + "\n".join(
            f"{line(ctx, c)} | scout: {c['reason'].text}" for c in chunk)
        fallback = (lambda: stand_in.critical(chunk, reasons, ctx["chain"], ctx["names"], most))
        out, _ = await ask(ctx, "critical", text, CriticalPicks, fallback, numbers(ctx))
        mine = {c["event_id"] for c in chunk}
        return [p for p in out.picks if p.event_id in mine]
    found = [p for group in await asyncio.gather(*(one(c) for c in chunks)) for p in group]
    keep, seen, kept = [], set(), []      # one moment per attack phase, MOMENT_GAP_MS apart, none rushed
    for p in sorted(found, key=lambda p: p.rank):
        e = ctx["by_id"].get(p.event_id)
        if (p.event_id in ids and p.event_id not in seen | ctx["rushed"] | ctx["chain"] and p.kind in KINDS
                and apart(e, kept, ctx["phase"])):
            seen.add(p.event_id)
            keep.append(p)
            kept.append(e)
    if len(keep) < lo:          # too few: topped up by importance, candidates first, then any decision
        rest = [e for e in candidates if e["event_id"] not in seen]
        rest += sorted((e for e in ctx["decisions"] if e["event_id"] not in seen | ids | ctx["chain"]),
                       key=lambda e: e["importance"] or 0, reverse=True)
        fill = []
        for e in rest:
            if len(fill) == lo - len(keep):
                break
            if e["event_id"] not in seen | ctx["rushed"] and apart(e, kept + fill, ctx["phase"]):
                seen.add(e["event_id"])
                fill.append(e)
        keep += stand_in.critical(fill, reasons, ctx["chain"], ctx["names"], hi).picks
    keep = keep[:hi]
    for i, p in enumerate(keep, 1):
        p.rank = i
    return CriticalPicks(picks=keep)

# -- 3. one moment --
async def one(ctx: dict, event_id: str) -> None:
    mid = ctx["m"].match_id
    e = ctx["by_id"][event_id]
    try:
        moment.update(mid, event_id, status="running")
        # the analyst sees every option the code scored (only the player's choice marked in the picture), picks
        # the option that creates the biggest chance and the safest good one and builds the list Decision-1
        # weighs; then Decision-1 makes its own choice. The picture saved for the screen shows all the picks
        png = picture(ctx, e, e["options"], for_analyst=True)
        attacking, zone = phase_of(e, ctx["m"].home_id)
        analysis, src1 = await ask(ctx, "position", moment_text(ctx, e, e["options"]), PositionAnalysis,
                                        lambda: stand_in.position(e, moment_options(e), attacking, zone), numbers(ctx),
                                        png, [event_id])
        own_picks(analysis, e["options"])
        found = picture_options(e, analysis.missed, shirts(ctx["players"]))   # what the analyst saw in the picture
        opts, extra = analyst_list(e, [analysis.best_option_id, analysis.safest_option_id, *analysis.shortlist], found)
        opts += extra
        d1 = await decision1(ctx, e, opts, analysis, png)
        image_file = matchFilesBlob.upload_blob(picture(ctx, e, with_picks(e["options"] + extra, analysis, d1)),
                                                f"matches/{mid}/moments/{event_id}.png", "image/png")
        mine = next((o for o in e["options"] if o["is_chosen"]), None)
        pick = next(o for o in e["options"] + opts if o["option_id"] == d1["option_id"])
        d1_pct = {event_id: {100 * v for v in d1["probabilities"].values()}}
        base = base_score(e)
        coach, src2 = await ask(ctx, "coach", coach_text(ctx, e, opts, mine, pick, d1, analysis, base), CoachReport,
                                     lambda: stand_in.coach(e, mine, pick, ctx["names"].get(e["player_id"], "The player"), base),
                                     numbers(ctx, d1_pct), png, [event_id])
        if base is not None:                        # the coach weighs the picture, but not far from the numbers
            coach.score = min(max(coach.score, base - COACH_BASE_RANGE), base + COACH_BASE_RANGE)
        coach.score = max(coach.score, SCORE_MIN)
        coach.same_choice = bool(mine) and mine["option_id"] == pick["option_id"]
        if coach.same_choice:                       # Decision-1 has the last word
            coach.score = max(coach.score, SAME_CHOICE_SCORE)
        moment.update(mid, event_id, status="done", image_file=image_file, analysis=analysis.model_dump(),
                      decision1=d1, coach=coach.model_dump(),
                      source="agent" if "agent" in (src1, src2) else "stub")
    except Exception as err:                # noqa: BLE001  (only this moment fails)
        emit_telemetry_exception("moment.failed", err, match_id=mid, event_id=event_id)
        moment.update(mid, event_id, status="failed", error=str(err)[:500] or type(err).__name__)

async def decision1(ctx: dict, e: dict, opts: list[dict], analysis: PositionAnalysis, png: bytes) -> dict:
    labels = dict(zip(LABELS, opts))
    s = situation(e["team_id"], e["score_home"], e["score_away"], ctx["m"].home_id)
    state = f"{s['state']} {s['for']}-{s['against']}"
    source = "stub"
    probs = None
    if foundry.decision1_ready:
        body = build_request(e, labels, ctx["names"], team(ctx, e["team_id"]), state,
                             " ".join(x.text for x in analysis.situation), settings.decision1_deployment,
                             pitch_place(e, ctx["m"].home_id))
        try:
            async with ctx["limit"]:
                probs = await foundry.decision1(body)
            if not set(probs) & set(labels):
                raise ValueError(f"unexpected labels in the answer: {sorted(probs)}")
            source = "decision1"
        except Exception as err:            # noqa: BLE001
            emit_telemetry_exception("decision1.failed", err, event_id=e["event_id"], fallback="stub",
                                     reason=str(err)[:500])
            probs = None
    if probs is None:
        probs = ask_stub(labels, s["state"], e["minute"])
    top = max((k for k in probs if k in labels), key=probs.get)
    return {"source": source, "option_id": labels[top]["option_id"], "option_type": labels[top]["option_type"],
            "probability": round(probs[top], 4), "cannot_tell": round(probs.get("cannot_tell", 0.0), 4),
            "probabilities": {labels[k]["option_id"] if k in labels else k: round(v, 4) for k, v in probs.items()}}

# -- 4. the Goal Analyst, one per goal --
async def goal_analysts(ctx: dict) -> dict:
    """goal event_id -> {"analysis": GoalAnalysis, "source"}; the key decisions must be in that goal's chain."""

    async def one_goal(g, chain):
        ids = [e["event_id"] for e in chain]
        added = {e["event_id"]: {100 * e["delta_value"]} for e in chain if e["delta_value"] is not None}
        lost = lost_before(ctx["events"], chain)
        if lost:                                   # the expected value the conceding team gave up, told in its line
            added[lost["event_id"]] = {100 * (lost["regret"] or 0)}
        picks = await defence_picks(ctx, chain)
        fx = fixes(ctx, chain) | picks
        fallback = lambda: stand_in.goal(chain, ctx["names"], fx, lost)   # noqa: E731
        out, src = await ask(ctx, "goal", goal_text(ctx, g, chain, fx), GoalAnalysis, fallback,
                             numbers(ctx, added), ids=ids)
        out.key_event_ids = [i for i in dict.fromkeys(out.key_event_ids) if i in ids][:KEY_DECISIONS]
        out.notes = [s for s in out.notes if s.event_ids and s.event_ids[0] in ids]
        out.defence = [s for s in out.defence if s.event_ids and s.event_ids[0] in ids]
        if not out.key_event_ids:
            out, src = fallback(), "stub"
        return g["event_id"], {"analysis": out.model_dump(), "source": src, "defence": picks}
    return dict(await asyncio.gather(*(one_goal(g, c) for g, c in goal_chains(ctx["events"]) if c)))

def goal_text(ctx: dict, g: dict, chain: list[dict], fx: dict) -> str:
    """The goal and every decision behind it: where it was, the options with their numbers, the value the choice
    added and what a defender could have done (fx: Decision-1's choice at the key decisions, the code's elsewhere)."""
    parts = [f"{story(ctx)}\n\nGoal {g['event_id']} at {g['minute']}:{g['second']:02d} by "
             f"{ctx['names'].get(g['player_id'], '?')} of {team(ctx, g['team_id'])}. The decisions behind it, in order:"]
    lost = lost_before(ctx["events"], chain)
    if lost:
        c, b = chosen(lost) or {}, best(lost) or {}
        parts.append(f"\nBefore it, {team(ctx, lost['team_id'])} had the ball: {lost['event_id']} {lost['minute']}:"
                     f"{lost['second']:02d} {ctx['names'].get(lost['player_id'], '?')} chose {describe(c, ctx['names']) if c else '?'}"
                     f" (outcome {lost['outcome']}); his best option was {describe(b, ctx['names']) if b else '?'}; "
                     f"expected value given up {100 * (lost['regret'] or 0):.1f}%.")
    for e in chain:
        f = fx.get(e["event_id"])
        parts.append(f"\n{e['event_id']} {e['minute']}:{e['second']:02d} {ctx['names'].get(e['player_id'], '?')} "
                     f"({ctx['players'].get(e['player_id'], {}).get('position') or '?'}). {pitch_place(e, ctx['m'].home_id)} "
                     f"The value his choice added: {100 * (e['delta_value'] or 0):.1f}%; outcome {e['outcome']}.\n"
                     f"{option_lines(ctx, e['options'])}"
                     + (f"\nDefence: {ctx['names'].get(f['player_id'], '?')} could have {f['words']} "
                        f"({f'{f['late_s']:.1f} s late' if f['late_s'] else 'in time'})"
                        + (", Microsoft Decision-1's choice among the defence's options." if "decision1" in f else ".")
                        if f else ""))
    return "\n".join(parts)

async def defence_picks(ctx: dict, chain: list[dict]) -> dict:
    """event_id -> the defence action Decision-1 chose at that key decision of a goal (shaped like a defence_fix,
    with the Defence Analyst's words and Decision-1's answer): the code lists the defenders' options with their
    numbers, the Defence Analyst picks a few from them and the picture, Decision-1 chooses."""
    keepers = {pid for pid, p in ctx["players"].items() if p.get("position") == "GK"}

    async def one(e):
        opts = defence_options(e, keepers, ctx["m"].home_id)
        if not opts:
            return e["event_id"], None
        png = picture(ctx, e, [{**o, "is_best": False, "is_safe_best": False} for o in e["options"] if o["is_chosen"]])
        pct = {e["event_id"]: {100 * o[k] for o in opts for k in ("p_success", "value_if_success", "risk_if_fail")}}
        analysis, _ = await ask(ctx, "defence", defence_text(ctx, e, opts), DefenceAnalysis,
                                lambda: stand_in.defence(e, opts), numbers(ctx, pct), png, [e["event_id"]])
        by_id = {o["option_id"]: o for o in opts}
        short = ([by_id[i] for i in dict.fromkeys(analysis.shortlist) if i in by_id][:DEFENCE_SHORTLIST_MAX]
                 or opts[:DEFENCE_SHORTLIST_MAX])
        d1 = await decision1_defence(ctx, e, short, analysis)
        return e["event_id"], {**by_id[d1["option_id"]], "situation": [s.text for s in analysis.situation],
                               "decision1": d1}
    key = key_decisions(chain)
    return {k: v for k, v in await asyncio.gather(*(one(e) for e in chain if e["event_id"] in key)) if v}

def defence_text(ctx: dict, e: dict, opts: list[dict]) -> str:
    """One decision behind a goal and what the defenders nearest to it could have done, with the numbers."""
    m = ctx["m"]
    c = chosen(e)
    return (f"{story(ctx)}\n\n{e['event_id']} {e['minute']}:{e['second']:02d} {ctx['names'].get(e['player_id'], '?')} "
            f"of {team(ctx, e['team_id'])}: {pitch_place(e, m.home_id)} He chose: {describe(c, ctx['names']) if c else '?'} "
            f"The attack ended in a goal. What the defenders of "
            f"{team(ctx, m.away_id if e['team_id'] == m.home_id else m.home_id)} could have done:\n"
            + "\n".join(f"- {o['option_id']}: {describe_defence(o, ctx['names'])}" for o in opts))

async def decision1_defence(ctx: dict, e: dict, opts: list[dict], analysis: DefenceAnalysis) -> dict:
    """Decision-1 chooses the defence action, as decision1() does for the player on the ball."""
    labels = dict(zip(LABELS, opts))
    m = ctx["m"]
    defending = m.away_id if e["team_id"] == m.home_id else m.home_id
    s = situation(defending, e["score_home"], e["score_away"], m.home_id)
    source, probs = "stub", None
    if foundry.decision1_ready:
        body = build_defence_request(e, labels, ctx["names"], team(ctx, defending), f"{s['state']} {s['for']}-{s['against']}",
                                     " ".join(x.text for x in analysis.situation), settings.decision1_deployment,
                                     pitch_place(e, m.home_id))
        try:
            async with ctx["limit"]:
                probs = await foundry.decision1(body)
            if not set(probs) & set(labels):
                raise ValueError(f"unexpected labels in the answer: {sorted(probs)}")
            source = "decision1"
        except Exception as err:            # noqa: BLE001
            emit_telemetry_exception("decision1.failed", err, event_id=e["event_id"], fallback="stub",
                                     reason=str(err)[:500])
            probs = None
    if probs is None:
        probs = ask_stub(labels, s["state"], e["minute"])
    top = max((k for k in probs if k in labels), key=probs.get)
    return {"source": source, "option_id": labels[top]["option_id"], "probability": round(probs[top], 4)}

def fixes(ctx: dict, chain: list[dict]) -> dict:
    """event_id -> what one defender could have done against that decision (core/utils.py defence_fix)."""
    keepers = {pid for pid, p in ctx["players"].items() if p.get("position") == "GK"}
    return {e["event_id"]: f for e in chain if (f := defence_fix(e, keepers, ctx["m"].home_id))}

# -- 5. the story --
async def summary(ctx: dict) -> MatchSummary:
    rows = moment.read_all(ctx["m"].match_id)
    done = [r for r in rows if r["status"] == "done"]
    text = summary_text(ctx, done)
    out, _ = await ask(ctx, "summary", text, MatchSummary, lambda: stand_in.summary(done), numbers(ctx))
    return out

def summary_text(ctx: dict, done: list[dict]) -> str:
    spells = "\n".join(rhythm_of(ctx["m"], ctx["events"]).spells)
    return story(ctx) + f"\n\nRhythm (control vs chaos):\n{spells}\n\nCritical moments:\n" + "\n".join(
        f"{line(ctx, ctx["by_id"][r['event_id']])} | kind={r['kind']} | same as Decision-1: "
        f"{r['coach']['same_choice']} | coach: {' '.join(s['text'] for s in r['coach']['sentences'])}" for r in done)

# -- 6. the fan feed --
async def fan_feed(ctx: dict, told: MatchSummary) -> tuple[FanFeed, str]:
    """Made-up fans of both sides react through the match, from what the Storyteller was given and his story."""
    m = ctx["m"]
    done = [r for r in moment.read_all(m.match_id) if r["status"] == "done"]
    text = (f"{summary_text(ctx, done)}\n\nTeam ids: {m.home_id} = {m.home_name}, {m.away_id} = {m.away_name}.\n"
            f"The match story: {' '.join(s.text for s in told.parts)}")
    fallback = lambda: stand_in.fan_feed([{**ctx["by_id"][r["event_id"]], "kind": r["kind"]} for r in done],   # noqa: E731
                                         [e for e in ctx["events"] if e["outcome"] == "goal"], ctx["names"],
                                         m.home_id, m.away_id, m.home_name, m.away_name)
    out, src = await ask(ctx, "fan_feed", text, FanFeed, fallback, numbers(ctx))
    for p in out.posts:
        if p.team_id not in (m.home_id, m.away_id):
            p.team_id = None
        written = re.findall(r"\[event_ids?:([^\]]*)\]", p.text)       # ids the agent wrote into the post itself
        p.text = re.sub(r"\s*\[event_ids?:[^\]]*\]", "", p.text).strip()
        p.event_ids = [i for i in dict.fromkeys([*p.event_ids, *re.findall(r"[\w-]+", " ".join(written))])
                       if i in ctx["by_id"]]
    out.posts = sorted(out.posts, key=lambda p: p.minute)[:FAN_POSTS_MAX]
    if not out.posts:
        out, src = fallback(), "stub"
    return out, src

def read_fan_feed(match_id: str) -> FanFeedView:
    m = must_be_ready(match_id)
    s = m.summary or {}
    return FanFeedView(**s.get("fan_feed", {}))

# -- texts for the agents --
def team(ctx: dict, team_id: str) -> str:
    return ctx["m"].home_name if team_id == ctx["m"].home_id else ctx["m"].away_name

def story(ctx: dict) -> str:
    goals = [f"{e['minute']}' {team(ctx, e['team_id'])} ({ctx["names"].get(e['player_id'], '?')})"
             for e in ctx["events"] if e["outcome"] == "goal"]
    meta = ctx["m"].meta
    return (f"{ctx["m"].home_name} (home) v {ctx["m"].away_name}. The clip starts at minute {meta.get('start_minute', 0)} "
            f"with the score {meta.get('score_home', 0)}-{meta.get('score_away', 0)}. Goals in the clip: "
            f"{', '.join(goals) or 'none'}.")

def line(ctx: dict, e: dict) -> str:
    s = situation(e["team_id"], e["score_home"], e["score_away"], ctx["m"].home_id)
    c = chosen(e) or {}
    b = best(e) or {}
    return (f"{e['event_id']} {e['minute']}:{e['second']:02d} {e['team_id']} {ctx["names"].get(e['player_id'], '?')} "
            f"{s['state']} {s['for']}-{s['against']} chose={c.get('option_type')}"
            f"{'/' + c['direction'] if c.get('direction') else ''} best={b.get('option_type')}"
            f"{'/' + b['direction'] if b.get('direction') else ''} outcome={e['outcome']} "
            f"imp={e['importance']:.3f} regret={e['regret']:.3f} edge={good_edge(e):.3f}")

def option_lines(ctx: dict, opts: list[dict]) -> str:
    """The options by id; no best or safest tag, the analyst decides those."""
    return "\n".join(f"- {o['option_id']}: {describe(o, ctx["names"])}"
                     + (" [the player's choice]" if o["is_chosen"] else "") for o in opts)

def moment_text(ctx: dict, e: dict, opts: list[dict]) -> str:
    s = situation(e["team_id"], e["score_home"], e["score_away"], ctx["m"].home_id)
    return (f"Event {e['event_id']}, minute {e['minute']}:{e['second']:02d}. {ctx["names"].get(e['player_id'], '?')} "
            f"({ctx["players"].get(e['player_id'], {}).get('position') or '?'}) of {team(ctx, e['team_id'])} has the ball; "
            f"his team is {s['state']} {s['for']}-{s['against']}. {pitch_place(e, ctx['m'].home_id)}\n"
            f"Options:\n{option_lines(ctx, opts)}\n\n"
            f"{positions_table(e, shirts(ctx['players']), ctx['m'].home_id)}")


def coach_text(ctx: dict, e, opts, mine, pick, d1, analysis: PositionAnalysis, base: float | None = None) -> str:
    """base: the code's score of the player's decision from its numbers, a guide for the coach's own score."""
    return (f"{moment_text(ctx, e, opts)}\n\nThe player chose {mine['option_id'] if mine else 'something else'}. "
            f"The position analyst judged {analysis.best_option_id or 'none'} the option that creates the biggest "
            f"chance and {analysis.safest_option_id or 'none'} the safest good option. "
            f"Decision-1 chose {pick['option_id']} (probability {100 * d1['probability']:.0f}%).\n"
            f"Position analysis ({analysis.phase}, {analysis.zone}): {' '.join(s.text for s in analysis.situation)}\n"
            + "\n".join(f"- {n.option_id}: {n.note}" for n in analysis.options)
            + (f"\nThe code's base score of the player's decision: {base:.1f} out of 10." if base is not None else "")
            + ("\nThe player's pass went to a team-mate in an offside position." if mine and mine.get("offside") else ""))


# ---------- helpers ----------
def picture(ctx: dict, e: dict, opts: list[dict], for_analyst: bool = False, defence: dict | None = None) -> bytes:
    """The moment from above. for_analyst: only the player's choice marked, every other option a faint line (the
    analyst reads them in words). defence (goal pictures): where a defender should have gone."""
    if for_analyst:
        opts = [{**o, "is_best": False, "is_safe_best": False, "is_decision1": False, "faint": True} for o in opts]
    return pitch.draw({**e, "player_name": ctx["names"].get(e["player_id"])}, opts,
                      [{**f, "shirt": ctx["players"].get(f["player_id"], {}).get("shirt"),
                        "name": ctx["names"].get(f["player_id"])} for f in e["frame"]],
                      ctx["m"].home_id, ctx["m"].home_name, ctx["m"].away_name, defence)


def shirts(players: dict) -> dict:
    """player_id -> shirt number."""
    return {pid: p.get("shirt") for pid, p in players.items()}


def own_picks(analysis: PositionAnalysis, opts: list[dict]) -> None:
    """The analyst's picks must be listed options that count; otherwise the code's pick stands."""
    ids = {o["option_id"] for o in opts if not o.get("offside")}
    if analysis.best_option_id not in ids:
        analysis.best_option_id = next((o["option_id"] for o in opts if o["is_best"]), "")
    if analysis.safest_option_id not in ids:
        analysis.safest_option_id = next((o["option_id"] for o in opts if o["is_safe_best"]), "")


def with_picks(opts: list[dict], analysis: dict | PositionAnalysis | None, d1: dict | None) -> list[dict]:
    """Options with is_best and is_safe_best = the analyst's picks and is_decision1 = Decision-1's choice (the
    code's flags stay for a moment from before, made when the analyst picked neither)."""
    a = analysis.model_dump() if isinstance(analysis, PositionAnalysis) else analysis or {}
    if "best_option_id" not in a or "safest_option_id" not in a:
        return opts
    return [{**o, "is_best": o["option_id"] == a["best_option_id"],
             "is_safe_best": o["option_id"] == a["safest_option_id"],
             "is_decision1": bool(d1) and o["option_id"] == d1["option_id"]} for o in opts]


def sentences(out) -> list[Sentence]:
    if isinstance(out, (ScoutPicks, CriticalPicks)):
        return [p.reason for p in out.picks]
    if isinstance(out, PositionAnalysis):
        return out.situation + out.missed
    if isinstance(out, GoalAnalysis):
        return out.sentences + out.notes + out.what_if + out.defence + out.opponent_errors
    if isinstance(out, FanFeed):                    # no event behind a post: any percentage in it is made up
        return [Sentence(text=p.text) for p in out.posts]
    return out.sentences if isinstance(out, CoachReport) else out.parts


def fill_ids(out, ids) -> None:
    """Sentences about one moment rest on that moment, even when the agent left event_ids empty."""
    for s in sentences(out):
        if not s.event_ids:
            s.event_ids = list(ids)


def drop_failing(out, numbers_for):
    def ok(s):
        return not check([s], numbers_for)
    if isinstance(out, (ScoutPicks, CriticalPicks)):
        out.picks = [p for p in out.picks if ok(p.reason)]
    elif isinstance(out, PositionAnalysis):
        out.situation = [s for s in out.situation if ok(s)]
        out.missed = [s for s in out.missed if ok(s)]
    elif isinstance(out, CoachReport):
        out.sentences = [s for s in out.sentences if ok(s)]
    elif isinstance(out, GoalAnalysis):
        out.sentences, out.notes, out.what_if = ([s for s in out.sentences if ok(s)], [s for s in out.notes if ok(s)],
                                                 [s for s in out.what_if if ok(s)])
        out.defence, out.opponent_errors = [s for s in out.defence if ok(s)], [s for s in out.opponent_errors if ok(s)]
    elif isinstance(out, FanFeed):
        out.posts = [p for p in out.posts if ok(Sentence(text=p.text))]
    else:
        out.parts = [s for s in out.parts if ok(s)]
    return out


def option_view(o: dict, names: dict, said: dict | None = None) -> OptionView:
    return OptionView(**{k: o[k] for k in OptionView.model_fields if k in o and k not in ("target_name", "text")},
                      target_name=names.get(o.get("target_player_id")),
                      text=o.get("text") or (said or {}).get(o["option_id"]))


def moment_view(match_id: str, r: dict, e: dict, names: dict, home_id: str, shirt_of: dict) -> MomentView:
    s = situation(e["team_id"], e["score_home"], e["score_away"], home_id)
    missed = [MissedOption(**s) for s in (r["analysis"] or {}).get("missed", [])]
    found = picture_options(e, missed, shirt_of)
    twins = {o["option_id"]: scored_twin(e, o) for o in found}
    extra = [o for o in found if not twins[o["option_id"]]]
    said = {t["option_id"]: o["text"] for o in found if (t := twins[o["option_id"]])}   # the analyst's words stay
    opts = [option_view(o, names, said) for o in with_picks(e["options"] + extra, r["analysis"], r["decision1"])]
    return MomentView(event_id=e["event_id"], rank=r["rank"], kind=r["kind"], minute=e["minute"], second=e["second"],
                      team_id=e["team_id"], player_id=e["player_id"], player_name=names.get(e["player_id"]),
                      ts_ms=e["ts_ms"], x=e["x"], y=e["y"],
                      score=f"{e['score_home']}-{e['score_away']} ({s['state']})", reason=r["reason"],
                      status=r["status"], image_url=f"/api/v1/matches/{match_id}/moments/{e['event_id']}/image" if r["image_file"] else None,
                      options=opts, chosen_option_id=next((o.option_id for o in opts if o.is_chosen), None),
                      analysis=r["analysis"], decision1=r["decision1"], coach=r["coach"], source=r["source"],
                      error=r["error"])


# ---------- player report cards ----------
def cards(match_id: str) -> list[PlayerCard]:
    m = must_be_ready(match_id)
    players = {p["player_id"]: p for p in player.read_all(match_id)}
    distance = (m.meta or {}).get("stats", {}).get("distance_m", {})
    passes: dict[str, list] = {}
    for e in event.read_all(match_id):
        if e["type"] == "pass" and e["end_x"] is not None:
            passes.setdefault(e["player_id"], []).append((math.hypot(e["end_x"] - e["x"], e["end_y"] - e["y"]),
                                                          e["outcome"] == "success"))
    by_player: dict[str, list] = {}
    for r in moment.read_all(match_id):
        if r["status"] != "done":
            continue
        e = event.read(match_id, r["event_id"])
        by_player.setdefault(e["player_id"], []).append((e, r))
    out = []
    for pid, rows in by_player.items():
        p = players.get(pid, {})
        same = sum(1 for _, r in rows if (r["coach"] or {}).get("same_choice"))
        scores = [r["coach"]["score"] for _, r in rows if (r["coach"] or {}).get("score") is not None]
        ranked = sorted(rows, key=lambda x: x[0]["regret"] or 0)
        out.append(PlayerCard(player_id=pid, name=p.get("name", pid), team_id=p.get("team_id", ""),
                              position=p.get("position"), moments=len(rows),
                              avg_score=round(sum(scores) / len(scores), 1) if scores else None,
                              share=round(same / len(rows), 3) if rows else None,
                              best_event_id=ranked[0][0]["event_id"], worst_event_id=ranked[-1][0]["event_id"],
                              **pass_stats(passes.get(pid, [])),
                              top_speed_kmh=round(p["max_speed"] * 3.6, 1) if p.get("max_speed") else None,
                              distance_km=round(distance[pid] / 1000, 2) if pid in distance else None))
    return sorted(out, key=lambda c: (-c.moments, c.name))


def pass_stats(rows: list[tuple[float, bool]]) -> dict:
    """(length, reached a team-mate) of a player's passes -> count, average length (m) and completion (%)."""
    if not rows:
        return {"passes": 0}
    return {"passes": len(rows), "pass_m": round(sum(d for d, _ in rows) / len(rows), 1),
            "pass_pct": round(100 * sum(ok for _, ok in rows) / len(rows), 1)}


# ---------- the decisions behind each goal ----------
def goals(match_id: str) -> list[GoalView]:
    """Every goal with the decisions of its attack; the key ones are the Goal Analyst's, before the flow has run the
    KEY_DECISIONS that added the most value."""
    m = must_be_ready(match_id)
    names = {p["player_id"]: name_of(p) for p in player.read_all(match_id)}
    reports = (m.summary or {}).get("goals", {})
    shot = (m.meta or {}).get("stats", {}).get("shot_speed", {})
    out = []
    for g, chain in goal_chains(event.read_all(match_id)):
        report = reports.get(g["event_id"])
        a = report["analysis"] if report else {}
        key = set(a["key_event_ids"]) if report else key_decisions(chain)
        said = lambda part, eid: next((s["text"] for s in a.get(part, []) if eid in s["event_ids"]), None)   # noqa: E731
        home, away = g["score_home"] + (g["team_id"] == m.home_id), g["score_away"] + (g["team_id"] != m.home_id)
        out.append(GoalView(event_id=g["event_id"], minute=g["minute"], second=g["second"], ts_ms=g["ts_ms"],
                            team_id=g["team_id"],
                            scorer_id=g["player_id"], scorer_name=names.get(g["player_id"]), score=f"{home}-{away}",
                            decisions=[ChainDecision(
                                **{k: e[k] for k in ChainDecision.model_fields if k in e and k != "options"},
                                player_name=names.get(e["player_id"]), key=e["event_id"] in key,
                                note=said("notes", e["event_id"]), what_if=said("what_if", e["event_id"]),
                                defence=said("defence", e["event_id"]),
                                defence_by_decision1=e["event_id"] in ((report or {}).get("defence") or {}),
                                image_url=f"/api/v1/matches/{match_id}/decisions/{e['event_id']}/image",
                                options=[option_view(o, names) for o in e["options"]]) for e in chain],
                            analysis=report["analysis"] if report else None, source=report["source"] if report else None,
                            shot_speed_kmh=round(shot[g["event_id"]] * 3.6) if g["event_id"] in shot else None))
    return out


def decision_image(match_id: str, event_id: str) -> bytes:
    """One decision behind a goal from above, drawn when asked: the player's choice in yellow, with the receiver's
    run when the ball went ahead of him (no AI picks: the Goal Analyst reads the decisions in words), and an orange
    arrow to where the defender who could most easily have stopped it should have gone. Kept in the Blob after the
    first drawing; a new run of the agents clears them (the defence picks change)."""
    m = must_be_ready(match_id)
    name = decision_images(match_id) + f"{event_id}.png"
    try:
        return matchFilesBlob.get_blob(name)
    except NotFound:
        pass
    e = event.read(match_id, event_id)
    if e is None or not e["options"]:
        raise NotFound(f"no decision {event_id}")
    players = {p["player_id"]: p for p in player.read_all(match_id)}
    ctx = {"m": m, "players": players, "names": {pid: name_of(p) for pid, p in players.items()}}
    picks = {k: v for r in ((m.summary or {}).get("goals") or {}).values() for k, v in (r.get("defence") or {}).items()}
    fix = picks.get(event_id) or fixes(ctx, [e]).get(event_id)
    png = picture(ctx, e, [{**o, "is_best": False, "is_safe_best": False} for o in e["options"] if o["is_chosen"]],
                  defence=fix and {**fix, "shirt": players.get(fix["player_id"], {}).get("shirt")})
    matchFilesBlob.upload_blob(png, name, "image/png")
    return png


def decision_images(match_id: str) -> str:
    """The Blob folder of a match's goal decision pictures."""
    return f"matches/{match_id}/decisions/"


# ---------- control vs chaos, minute by minute ----------
def rhythm(match_id: str) -> RhythmView:
    m = must_be_ready(match_id)
    return rhythm_of(m, event.read_all(match_id))


def rhythm_of(m, events: list[dict]) -> RhythmView:
    """Per match minute of the clip, from the decisions: each team's share of the ball (the time from its touch to the
    next, a pause cut at PHASE_BREAK_MS), the share of its decisions made under pressure and the turnovers in open play."""
    decisions = [e for e in events if e["options"]]
    side = lambda e: "home" if e["team_id"] == m.home_id else "away"   # noqa: E731
    empty = lambda: {"time": {"home": 0, "away": 0}, "pressed": {"home": 0, "away": 0},   # noqa: E731
                     "decisions": {"home": 0, "away": 0}, "turnovers": 0}
    rows = {}
    for prev, e, nxt in zip([None] + decisions, decisions, decisions[1:] + [None]):
        r = rows.setdefault(e["minute"], empty())
        if nxt:
            r["time"][side(e)] += min(nxt["ts_ms"] - e["ts_ms"], PHASE_BREAK_MS)
        if prev and prev["team_id"] != e["team_id"] and e["ts_ms"] - prev["ts_ms"] <= PHASE_BREAK_MS:
            r["turnovers"] += 1
        r["decisions"][side(e)] += 1
        r["pressed"][side(e)] += under_pressure(e)
    share = lambda part, whole: round(part / whole, 3) if whole else None   # noqa: E731
    minutes = []
    for minute in range(min(rows, default=0), max(rows, default=-1) + 1):
        r = rows.get(minute) or empty()
        t, n, p = r["time"], r["decisions"], r["pressed"]
        minutes.append(RhythmMinute(minute=minute, possession_home=share(t["home"], t["home"] + t["away"]),
                                    possession_away=share(t["away"], t["home"] + t["away"]),
                                    pressure_home=share(p["home"], n["home"]), pressure_away=share(p["away"], n["away"]),
                                    turnovers=r["turnovers"], decisions=n["home"] + n["away"]))
    goals = [RhythmGoal(minute=e["minute"], second=e["second"], team_id=e["team_id"]) for e in events
             if e["outcome"] == "goal"]
    return RhythmView(home_id=m.home_id, away_id=m.away_id, home_name=m.home_name, away_name=m.away_name,
                      minutes=minutes, goals=goals, spells=spells(m, minutes))


def spells(m, minutes: list[RhythmMinute]) -> list[str]:
    """The RHYTHM_WINDOW_MIN minutes one team held the ball most, and those with the most turnovers, in words."""
    if not minutes:
        return []
    w = RHYTHM_WINDOW_MIN
    windows = [minutes[i:i + w] for i in range(max(1, len(minutes) - w + 1))]
    home = lambda win: sum(x.possession_home or 0 for x in win) / max(1, sum(x.possession_home is not None for x in win))   # noqa: E731
    span = lambda win: f"minutes {win[0].minute}-{win[-1].minute}"   # noqa: E731
    calm = max(windows, key=lambda win: abs(home(win) - 0.5))
    lead = home(calm) if home(calm) >= 0.5 else 1 - home(calm)
    out = [f"{span(calm)}: {m.home_name if home(calm) >= 0.5 else m.away_name} in control of the ball"
           if lead >= CONTROL_SHARE else f"{span(calm)}: neither team in control of the ball"]
    wild = max(windows, key=lambda win: sum(x.turnovers for x in win))
    if sum(x.turnovers for x in wild):
        out.append(f"{span(wild)}: chaotic, {sum(x.turnovers for x in wild)} turnovers")
    return out
