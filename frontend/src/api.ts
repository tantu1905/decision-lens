// The backend's API (/api/v1) and the shapes it answers with (backend/src/schemas/views.py).
const API = "/api/v1"

export type Sentence = { text: string; event_ids: string[] }
export type Score = { home: number; away: number }
export type Match = {
  match_id: string; home_id: string; away_id: string; home_name: string; away_name: string
  status: string; step: string | null; progress: number; message: string | null
  decisions: number; moments: number; score: Score; summary: { parts: Sentence[] } | null
  created_at: string | null
}
export type Option = {
  option_id: string; option_type: string; direction: string | null; target_name: string | null; text: string | null
  into_run: boolean; shot_chance: number | null; target_x: number | null; target_y: number | null
  p_success: number | null; value_if_success: number | null; risk_if_fail: number | null; ev: number | null
  is_chosen: boolean; is_best: boolean; is_safe_best: boolean; is_decision1: boolean
}
export type Analysis = {
  phase: string; zone: string; situation: Sentence[]; options: { option_id: string; note: string }[]
  missed: Sentence[]; best_option_id: string; safest_option_id: string
}
export type Decision1 = { source: "decision1" | "stub"; option_id: string; probability: number; probabilities: Record<string, number> }
export type Coach = { same_choice: boolean; score: number | null; sentences: Sentence[] }
export type Moment = {
  event_id: string; rank: number; kind: string; minute: number; second: number; team_id: string; player_id: string
  player_name: string | null; ts_ms: number; x: number; y: number; score: string; reason: string; status: string
  image_url: string | null; options: Option[]; chosen_option_id: string | null; analysis: Analysis | null
  decision1: Decision1 | null; coach: Coach | null; source: string; error: string | null
}
export type GoalDecision = {
  event_id: string; minute: number; second: number; player_id: string | null; player_name: string | null
  type: string; outcome: string | null; delta_value: number | null; chosen_ev: number | null; best_ev: number | null
  regret: number | null; ts_ms: number; x: number; y: number; key: boolean; note: string | null; what_if: string | null; defence: string | null; defence_by_decision1?: boolean; image_url: string; options: Option[]
}
export type Goal = {
  event_id: string; minute: number; second: number; team_id: string; scorer_id: string | null; scorer_name: string | null
  ts_ms: number; score: string; decisions: GoalDecision[]
  analysis: { key_event_ids: string[]; sentences: Sentence[]; notes: Sentence[]; what_if: Sentence[]; defence?: Sentence[]; opponent_errors?: Sentence[] } | null
  source: string | null
  shot_speed_kmh: number | null
}
// what the 3D replay needs of a decision: a critical moment, or a decision behind a goal
export type OnBall = { x: number; y: number; ts_ms: number; player_id: string | null; player_name: string | null; options: Option[] }
export type PlayerCard = { player_id: string; name: string; team_id: string; position: string | null; moments: number; avg_score: number | null; share: number | null
  passes: number; pass_m: number | null; pass_pct: number | null; top_speed_kmh: number | null; distance_km: number | null }
export type FanPost = { minute: number; handle: string; team_id: string | null; text: string; mood: "joy" | "anger" | "worry" | "praise" | "banter"; event_ids?: string[] }
export type FanFeed = { posts: FanPost[]; source: string | null }
export type RhythmMinute = {
  minute: number; possession_home: number | null; possession_away: number | null
  pressure_home: number | null; pressure_away: number | null; turnovers: number; decisions: number
}
export type Rhythm = {
  home_id: string; away_id: string; home_name: string; away_name: string; minutes: RhythmMinute[]
  goals: { minute: number; second: number; team_id: string }[]; spells: string[]
}
export type Frame = { ts_ms: number; objects: { id: string; team_id: string | null; x: number; y: number; shirt: number | null; position: string | null }[] }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, init)
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => null)
    throw new Error(typeof detail === "string" ? detail : r.status === 404 ? "This endpoint is not on the backend yet." : `Request failed (${r.status})`)
  }
  return r.json()
}

// read once per match and status: the loading screen reads these first, the page then shows them at once
const kept = new Map<string, Promise<unknown>>()
function keep<T>(path: string, status: string): Promise<T> {
  const key = `${path}|${status}`
  if (!kept.has(key)) kept.set(key, call<T>(path).catch((e) => { kept.delete(key); throw e }))
  return kept.get(key) as Promise<T>
}

// a picture fetched before the card that shows it opens, so the card appears whole
export const preload = (src?: string | null) => !src ? Promise.resolve()
  : new Promise<void>((done) => { const i = new window.Image(); i.onload = i.onerror = () => done(); i.src = src })

export const api = {
  matches: () => call<Match[]>("/matches"),
  match: (id: string, status?: string) => status ? keep<Match>(`/matches/${id}`, status) : call<Match>(`/matches/${id}`),
  moments: (id: string, status: string) => keep<Moment[]>(`/matches/${id}/moments`, status),
  moment: (id: string, eventId: string) => call<Moment>(`/matches/${id}/moments/${eventId}`),
  report: (id: string, status: string) => keep<PlayerCard[]>(`/matches/${id}/report`, status),
  goals: (id: string, status: string) => keep<Goal[]>(`/matches/${id}/goals`, status),
  rhythm: (id: string, status: string) => keep<Rhythm>(`/matches/${id}/rhythm`, status),
  replay: (id: string, eventId: string) => call<Frame[]>(`/matches/${id}/replay?event_id=${eventId}`),
  replayRange: (id: string, fromMs: number, toMs: number) => call<Frame[]>(`/matches/${id}/replay?from_ms=${fromMs}&to_ms=${toMs}`),
  fanFeed: (id: string, status: string) => keep<FanFeed>(`/matches/${id}/fan-feed`, status),
  analyseSample: () => call<Match>("/matches/sample/analyse", { method: "POST" }),
}

// ---- words for the screen ----
export const TYPES: Record<string, string> = {
  pass: "pass", ground_cross: "low cross", cross: "cross", long_ball: "long ball", shot: "shot", dribble: "dribble",
  carry: "carry", hold: "keep the ball", clearance: "clearance upfield", clear_out: "clearance into touch",
}
export const DIRS: Record<string, string> = { through: "through ball", forward: "forward pass", side: "sideways pass", back: "back pass", throw_in: "throw-in" }
export const KINDS: Record<string, string> = {
  missed_chance: "Missed chance", costly_mistake: "Costly mistake", good_decision: "Good decision",
  goal_build_up: "Goal build-up", defensive_moment: "Defending",
}
export const LEVELS = [
  { key: "good", title: "Good decisions", one: "Good decision", min: 7 },
  { key: "fair", title: "Fair decisions", one: "Fair decision", min: 4 },
  { key: "poor", title: "Poor decisions", one: "Poor decision", min: 0 },
] as const
export type Level = (typeof LEVELS)[number]
export const level = (score: number | null | undefined): Level | null =>
  score == null ? null : LEVELS.find((l) => score >= l.min) ?? null
// the Critical agent's kind is picked before the decision is scored: once there is a score, a kind that judges the
// decision gives way to the score's level, so a 4.0 never reads "Good decision"
const JUDGING = ["missed_chance", "costly_mistake", "good_decision"]
export const kindText = (kind: string, score: number | null | undefined) =>
  score != null && JUDGING.includes(kind) ? level(score)!.one : KINDS[kind] ?? kind

export const clock = (m: { minute: number; second: number }) => `${m.minute}:${String(m.second).padStart(2, "0")}`
export const pct = (v: number | null | undefined) => {   // small chances keep one decimal, so 0.4% does not read as 0%
  if (v == null) return "—"
  const p = 100 * Math.max(0, v)
  return p > 0 && p < 10 ? `${p.toFixed(1)}%` : `${Math.round(p)}%`
}
export const label = (o: Option) =>
  (o.option_type === "from_picture" ? o.text ?? "" : o.option_type === "pass" && o.direction ? DIRS[o.direction] : TYPES[o.option_type] ?? o.option_type)
  + (o.target_name && o.option_type !== "from_picture" ? ` to ${o.target_name}` : "")   // the analyst's sentence names him
