"""The whole flow on the synthetic sample (loaded on start), first with the stand-ins, then with a fake
Foundry whose answers include a made-up event and a made-up number."""
import time

from src.core.utils import (
    CRITICAL_MAX,
    CRITICAL_MIN,
    KEY_DECISIONS,
    LABELS,
    MOMENT_GAP_MS,
    SAME_CHOICE_SCORE,
    analyst_list,
    critical_range,
    ask_stub,
    build_request,
    foundry_root,
    picture_options,
    positions_table,
)
from src.core.settings import Settings
from src.logic.flow import with_picks
from src.schemas.agents import CriticalPick, CriticalPicks, FanFeed, FanPost, MissedOption, ScoutPick, ScoutPicks, Sentence
from src.services.azure_foundry_service import AzureFoundryService, choice_probabilities, decision1_url

API = "/api/v1/matches/SYN-0135"


def wait(client, status=("done", "failed")):
    for _ in range(300):
        m = client.get(API).json()
        if m["status"] in status:
            return m
        time.sleep(0.2)
    raise AssertionError("timed out")


def test_sample_is_loaded_and_scored(client):
    m = wait(client, ("ready", "done", "failed"))
    assert m["status"] in ("ready", "done") and m["decisions"] > 150 and m["score"] == {"home": 1, "away": 0}


def test_stub_flow_end_to_end(client):
    assert client.post(f"{API}/flow").json()["status"] == "running"
    m = wait(client)
    assert m["status"] == "done" and m["summary"]["parts"]
    moments = client.get(f"{API}/moments").json()
    assert CRITICAL_MIN <= len(moments) <= CRITICAL_MAX and all(x["status"] == "done" for x in moments)
    x = moments[0]
    assert x["decision1"]["source"] == "stub" and x["coach"]["sentences"] and x["analysis"]["options"]
    assert x["decision1"]["option_id"] in {o["option_id"] for o in x["options"]}
    assert all(0 <= y["coach"]["score"] <= 10 for y in moments)       # the player's decision out of 10
    assert all(y["coach"]["score"] >= SAME_CHOICE_SCORE for y in moments if y["coach"]["same_choice"])
    ts = sorted(60_000 * y["minute"] + 1000 * y["second"] for y in moments)
    assert all(b - a >= MOMENT_GAP_MS - 1000 for a, b in zip(ts, ts[1:]))   # spread over the match, one per attack
    img = client.get(x["image_url"])
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    cards = client.get(f"{API}/report").json()
    assert sum(c["moments"] for c in cards) == len(moments)
    assert client.get(f"{API}/replay?event_id={x['event_id']}").json()


def test_decisions_behind_each_goal(client):
    """After the flow the Goal Analyst's key decisions are in the sample goal's chain, each with a what-if, every
    decision has a note and a picture, and none of them is a critical moment."""
    wait(client)
    goals = client.get(f"{API}/goals").json()
    assert len(goals) == 1 and goals[0]["score"] == "1-0" and goals[0]["source"] == "stub"
    g = goals[0]
    ids = [d["event_id"] for d in g["decisions"]]
    key = g["analysis"]["key_event_ids"]
    assert ids and 1 <= len(key) <= KEY_DECISIONS and set(key) <= set(ids)
    assert {d["event_id"] for d in g["decisions"] if d["key"]} == set(key)
    assert {s["event_ids"][0] for s in g["analysis"]["what_if"]} == set(key)
    assert all(d["note"] and d["options"] for d in g["decisions"])
    assert all(d["what_if"] for d in g["decisions"] if d["key"])
    assert all(d["defence"] for d in g["decisions"]) and "opponent_errors" in g["analysis"]   # what a defender could have done
    assert all(d["defence_by_decision1"] for d in g["decisions"] if d["key"])     # Decision-1 chose the key ones
    assert not any(d["defence_by_decision1"] for d in g["decisions"] if not d["key"])
    assert client.get(g["decisions"][0]["image_url"]).content[:4] == b"\x89PNG"
    critical = {x["event_id"] for x in client.get(f"{API}/moments").json()}
    assert critical and not critical & set(ids)                        # the Goal Analyst's, not critical moments


def test_the_report_and_goals_carry_the_match_numbers(client):
    """Passes, top speed and distance on the report cards, and the goal's shot speed, all within football's range."""
    wait(client)
    cards = client.get(f"{API}/report").json()
    assert cards and any(c["passes"] for c in cards)
    for c in cards:
        assert c["top_speed_kmh"] is None or 15 <= c["top_speed_kmh"] <= 40
        assert c["distance_km"] is None or 0.3 <= c["distance_km"] <= 3.0       # 15 minutes of the match
        if c["passes"]:
            assert 0 <= c["pass_pct"] <= 100 and 0 < c["pass_m"] < 80
    assert 60 <= client.get(f"{API}/goals").json()[0]["shot_speed_kmh"] <= 140


def test_rhythm_minute_by_minute(client):
    """Every minute of the clip with each team's share of the ball, the goal as a marker and the spells in words."""
    wait(client, ("ready", "done", "failed"))
    r = client.get(f"{API}/rhythm").json()
    minutes = [x["minute"] for x in r["minutes"]]
    assert minutes == list(range(minutes[0], minutes[-1] + 1)) and len(minutes) >= 10
    assert all(abs(x["possession_home"] + x["possession_away"] - 1) < 0.01 for x in r["minutes"] if x["decisions"])
    assert all(0 <= x[k] <= 1 for x in r["minutes"] for k in ("pressure_home", "pressure_away") if x[k] is not None)
    assert sum(x["turnovers"] for x in r["minutes"]) > 0
    assert [g["team_id"] for g in r["goals"]] == [r["home_id"]] and r["goals"][0]["minute"] in minutes
    assert r["spells"] and any("turnovers" in s for s in r["spells"])


def test_agent_answers_are_checked(client, monkeypatch):
    """A scout names an event outside its stretch and writes a number that is not in the data: both are dropped."""
    monkeypatch.setattr(AzureFoundryService, "ready", property(lambda self: True))

    async def fake_run(self, name, instructions, text, shape, image=None):
        ids = [line.split()[0] for line in text.splitlines() if line.startswith("v_")]
        if shape is ScoutPicks:
            return ScoutPicks(picks=[ScoutPick(event_id="v_99999", reason=Sentence(text="made up", event_ids=["v_99999"])),
                                     ScoutPick(event_id=ids[0], reason=Sentence(text="A 97% chance.", event_ids=[ids[0]])),
                                     *[ScoutPick(event_id=i, reason=Sentence(text="Fine.", event_ids=[i])) for i in ids[1:4]]])
        if shape is CriticalPicks:
            return CriticalPicks(picks=[CriticalPick(event_id=i, rank=n, kind="good_decision",
                                                     reason=Sentence(text="Fine.", event_ids=[i]))
                                        for n, i in enumerate(ids, 1)])
        raise RuntimeError("no answer")           # position, coach, summary: the stand-ins answer
    monkeypatch.setattr(AzureFoundryService, "run", fake_run)
    client.post(f"{API}/flow")
    assert wait(client)["status"] == "done"
    moments = client.get(f"{API}/moments").json()
    ids = {x["event_id"] for x in moments}
    assert "v_99999" not in ids and CRITICAL_MIN <= len(moments) <= CRITICAL_MAX
    assert all("97%" not in x["reason"] for x in moments)


def test_decision1_address_and_answer():
    for given in ("https://x.services.ai.azure.com", "https://x.services.ai.azure.com/providers/microsoft/",
                  "https://x.services.ai.azure.com/api/projects/proj-default"):   # a project path gives a 400
        assert decision1_url(given) == "https://x.services.ai.azure.com/providers/microsoft/v1/systemone"
    assert choice_probabilities({"type": "choice", "choice": "A", "probabilities": {"A": 0.7, "B": 0.3}}) == {"A": 0.7, "B": 0.3}
    assert choice_probabilities({"type": "choice", "choice": "B", "confidence": 0.6}) == {"B": 0.6}


def test_picture_options_reach_decision1_without_numbers():
    e = {"event_id": "v_1", "minute": 70, "player_id": "p1", "team_id": "NRV",
         "frame": [{"player_id": "p1", "team_id": "NRV", "x": 50.0, "y": 30.0},
                   {"player_id": "p9", "team_id": "NRV", "x": 80.0, "y": 20.0}]}
    scored = [{"option_id": f"v_1_o0{i}", "option_type": "pass", "direction": "forward", "target_player_id": "p2",
               "p_success": 0.7, "value_if_success": 0.05, "risk_if_fail": 0.01, "ev": 0.03,
               "is_chosen": i == 1, "is_best": i == 2, "is_safe_best": False} for i in (1, 2)]
    extra = picture_options(e, [MissedOption(text="Through ball to the number 9 running behind the left back.", shirt=9),
                                MissedOption(text="Switch of play to the free winger on the right.")],
                            {"p1": 10, "p9": 9})
    labels = dict(zip(LABELS, scored + extra))
    body = build_request(e, labels, {"p1": "Ali", "p2": "Can", "p9": "Deniz"}, "NRV", "level 1-1", "He is pressed.",
                         "Decision-1")
    crit = body["questions"]["decision"]["criteria"]
    assert "seen in the picture" in crit["C"] and "%" not in crit["C"] and "Can" in crit["A"] and "Deniz" in crit["C"]
    assert (extra[0]["target_x"], extra[0]["target_y"]) == (80.0, 20.0) and "target_x" not in extra[1]
    probs = ask_stub(labels, "level", 70)
    assert set(labels) <= set(probs) and extra[0]["option_id"] == "v_1_p01"


def test_a_picture_option_into_a_run_goes_where_he_runs_and_the_analyst_gets_the_positions():
    e = {"event_id": "v_1", "player_id": "p1", "team_id": "NRV",
         "frame": [{"player_id": "p1", "team_id": "NRV", "x": 50.0, "y": 30.0, "vx": 0.0, "vy": 0.0},
                   {"player_id": "p9", "team_id": "NRV", "x": 80.0, "y": 20.0, "vx": 6.0, "vy": 0.0},
                   {"player_id": "q4", "team_id": "SHA", "x": 83.0, "y": 24.0, "vx": None, "vy": None}]}
    run, still = picture_options(e, [MissedOption(text="Ball behind for 9.", shirt=9, into_run=True),
                                     MissedOption(text="Short pass to 10.", shirt=10, into_run=True)],
                                 {"p1": 10, "p9": 9, "q4": 4})
    assert (run["target_x"], run["target_y"], run["into_run"]) == (91.0, 20.0, True)   # met by a 30 m pass after 1.8 s
    assert "target_x" not in still            # 10 is the player on the ball, not a team-mate
    table = positions_table(e, {"p1": 10, "p9": 9, "q4": 4}, "NRV")
    assert "red 9 (team-mate): x 80, y 20, 6.0 m/s forward, 32 m from the ball, nearest opponent 5.0 m" in table
    assert "blue 4 (opponent)" in table and "red 10 (on the ball)" in table


def test_a_carry_idea_ends_where_the_codes_carry_ends():
    e = {"event_id": "v_1", "player_id": "p1", "team_id": "NRV", "x": 50.0, "y": 30.0,
         "frame": [{"player_id": "p1", "team_id": "NRV", "x": 50.0, "y": 30.0}],
         "options": [{"option_type": "dribble", "target_x": 56.0, "target_y": 33.0, "ev": 0.02},
                     {"option_type": "carry", "target_x": 54.0, "target_y": 30.0, "ev": 0.01}]}
    [carry] = picture_options(e, [MissedOption(text="Carry it on.", carry=True)], {"p1": 10})
    assert (carry["target_x"], carry["target_y"]) == (56.0, 33.0)          # the code's best carry


def test_foundry_addresses_become_the_resource():
    for given in ("https://r.openai.azure.com/openai/v1", "https://r.openai.azure.com/openai/v1/", "https://r.openai.azure.com"):
        assert foundry_root(given) == "https://r.openai.azure.com"
    assert foundry_root("https://r.services.ai.azure.com/api/projects/proj-default") == "https://r.services.ai.azure.com"


def test_empty_env_lines_mean_local_database_and_folder():
    s = Settings(_env_file=None, db_connection_string="", local_storage_dir="  ")
    assert s.db_connection_string.startswith("sqlite:///") and s.local_storage_dir.endswith("storage")


def test_the_analyst_picks_the_chance_and_the_safest_and_decision1_its_own():
    opts = [{"option_id": "v_1_o01", "is_best": True, "is_safe_best": False},
            {"option_id": "v_1_o02", "is_best": False, "is_safe_best": True},
            {"option_id": "v_1_o03", "is_best": False, "is_safe_best": False}]
    shown = with_picks(opts, {"best_option_id": "v_1_o02", "safest_option_id": "v_1_o03"}, {"option_id": "v_1_o01"})
    assert [o["is_best"] for o in shown] == [False, True, False] and [o["is_safe_best"] for o in shown] == [False, False, True]
    assert [o["is_decision1"] for o in shown] == [True, False, False]
    assert with_picks(opts, None, None) == opts               # moments from before keep the code's flags


def test_the_analyst_builds_the_list_and_a_pass_the_code_scored_keeps_its_numbers():
    def o(i, mate=None, typ="pass", run=False, chosen=False):
        return {"option_id": f"v_1_o{i:02d}", "option_type": typ, "target_player_id": mate, "into_run": run,
                "p_success": 0.5 + i / 100, "ev": 0.01 * i, "is_chosen": chosen, "is_best": i == 9,
                "is_safe_best": i == 8}
    e = {"event_id": "v_1", "options": [o(1, "p2", chosen=True), *(o(i, f"p{i + 1}") for i in range(2, 10)),
                                         o(10, "p5", run=True), o(11, typ="dribble")]}
    found = [{"option_id": "v_1_p01", "option_type": "from_picture", "target_player_id": "p5", "into_run": True},
             {"option_id": "v_1_p02", "option_type": "from_picture", "target_player_id": "p20"}]
    scored, extra = analyst_list(e, ["v_1_o03", "", "v_1_o02", "v_1_o11", "v_1_o99"], found)
    assert [x["option_id"] for x in scored] == ["v_1_o01", "v_1_o02", "v_1_o03", "v_1_o10", "v_1_o11"]
    assert [x["option_id"] for x in extra] == ["v_1_p02"]          # p5 into his run is the code's o10, with numbers
    scored, _ = analyst_list(e, [], [])                              # no shortlist: the code's list
    assert {"v_1_o01", "v_1_o08", "v_1_o09"} <= {x["option_id"] for x in scored} and len(scored) == 6


def test_the_coach_says_when_the_pass_went_to_an_offside_player():
    from src.logic import stand_in
    e = {"event_id": "v_1"}
    mine = {"option_id": "v_1_o01", "option_type": "pass", "target_player_id": "H_9", "offside": True}
    d1 = {"option_id": "v_1_o02", "option_type": "pass", "target_player_id": "H_8"}
    assert any("offside" in s.text for s in stand_in.coach(e, mine, d1, "Ali", 2.0).sentences)


def test_the_keeper_is_told_apart(client):
    from src.core.utils import name_of, positions_table
    assert name_of({"name": "Kenji Kaya", "position": "GK"}) == "Kenji Kaya (GK)" and name_of({"name": "Omar"}) == "Omar"
    e = {"player_id": "p1", "team_id": "NRV",
         "frame": [{"player_id": "p1", "team_id": "NRV", "x": 50.0, "y": 30.0},
                   {"player_id": "gk", "team_id": "SHA", "x": 100.0, "y": 34.0, "position": "GK"}]}
    assert "goalkeeper, opponent" in positions_table(e, {"gk": 1}, "NRV")
    wait(client, ("ready", "done", "failed"))
    frame = client.get("/api/v1/matches/SYN-0135/replay").json()[0]["objects"]
    assert sum(1 for o in frame if o.get("position") == "GK") == 2     # one keeper a side in the sample match


def test_critical_moments_grow_with_the_match():
    """20-25 for a 15-minute clip (or shorter), 50-60 for 90 minutes, in between on a line."""
    clip = lambda minutes: [{"ts_ms": 0}, {"ts_ms": minutes * 60_000}]   # noqa: E731
    assert critical_range(clip(10)) == critical_range(clip(15)) == (CRITICAL_MIN, CRITICAL_MAX)
    assert critical_range(clip(90)) == (50, 60) and critical_range(clip(45)) == (32, 39)


def test_the_fans_post(client):
    """The fan feed comes from the stand-in: 10-15 made-up posts in minute order."""
    m = wait(client)
    feed = client.get(f"{API}/fan-feed").json()
    posts = feed["posts"]
    assert feed["source"] == "stub" and 10 <= len(posts) <= 15
    assert [p["minute"] for p in posts] == sorted(p["minute"] for p in posts)
    assert {p["team_id"] for p in posts} == {m["home_id"], m["away_id"]} and all(p["handle"] for p in posts)
    assert any(p["mood"] == "joy" and "GOAL" in p["text"] for p in posts)
    critical = {x["event_id"] for x in client.get(f"{API}/moments").json()}
    assert all(p["event_ids"] and "event_id" not in p["text"] for p in posts)
    assert any(set(p["event_ids"]) & critical for p in posts)         # these get a "See the moment" button


def test_ids_the_fan_feed_agent_writes_into_a_post_move_out_of_its_text(client, monkeypatch):
    m = wait(client)
    eid = client.get(f"{API}/moments").json()[0]["event_id"]
    monkeypatch.setattr(AzureFoundryService, "ready", property(lambda self: True))

    async def fake_run(self, name, instructions, text, shape, image=None):
        if name != "fan_feed":
            raise RuntimeError("no answer")       # every other agent: the stand-in answers
        return FanFeed(posts=[FanPost(minute=5, handle="fan_1", team_id=m["home_id"], mood="joy",
                                      text=f"What a pass! [event_ids: {eid}, v_nope]")])
    monkeypatch.setattr(AzureFoundryService, "run", fake_run)
    client.post(f"{API}/flow")
    wait(client)
    post = client.get(f"{API}/fan-feed").json()["posts"][0]
    assert post["text"] == "What a pass!" and post["event_ids"] == [eid]
