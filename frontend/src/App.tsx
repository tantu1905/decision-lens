import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { LayoutGrid, Loader2, Play } from "lucide-react"

import { api, type Match, type Moment } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MatchPicker } from "@/components/MatchPicker"
import { MomentList } from "@/components/MomentList"
import { GoalCard } from "@/components/GoalCard"
import { MomentCard } from "@/components/MomentCard"
import { SidePanel } from "@/components/SidePanel"
import { PrefsContext, recall, remember, type Mode } from "@/prefs"

const BUSY = ["loading", "running"]

export default function App() {
  const [matches, setMatches] = useState<Match[]>([])
  const [matchId, setMatchId] = useState<string | null>(null)
  const [match, setMatch] = useState<Match | null>(null)
  const [moments, setMoments] = useState<Moment[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [goal, setGoal] = useState<string | null>(null)        // a goal shown in the middle instead of a moment
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [listed, setListed] = useState(false)  // the match list has been read once
  const pending = useRef<string | null>(null)  // a match just loaded: "ready" only until its agents start
  const [tick, setTick] = useState(0)          // bumped to read the match again, also when its id did not change
  const [mode, setMode] = useState<Mode>(() => (recall("mode", "analyst") === "fan" ? "fan" : "analyst"))
  const [follow, setFollow] = useState(() => recall("follow", ""))   // "team:<id>", "player:<id>" or "" (see prefs.ts)

  const loadMatches = useCallback(async (pick?: string) => {
    try {
      const list = await api.matches()
      setMatches(list)
      setMatchId((cur) => pick ?? (cur && list.some((m) => m.match_id === cur) ? cur : null))   // no match chosen: the picker shows
      setTick((t) => t + 1)
      setError(null)
    } catch (e) { setError((e as Error).message) } finally { setListed(true) }
  }, [])

  useEffect(() => { loadMatches() }, [loadMatches])

  // the match and its moments; polled while the backend works on it
  useEffect(() => {
    if (!matchId) { setMatch(null); setMoments([]); return }
    let timer: number | undefined, gone = false
    const refresh = async () => {
      try {
        const m = await api.match(matchId)
        if (gone) return
        if (BUSY.includes(m.status) || (m.status === "ready" && pending.current === matchId)) {
          setMatch(m); setMoments([]); timer = window.setTimeout(refresh, 3000); return
        }
        // everything the page shows is read before the loading screen goes, so it all appears at once
        const [ms] = await Promise.all([
          m.moments ? api.moments(matchId, m.status).catch(() => []) : Promise.resolve([]),
          api.match(matchId, m.status).catch(() => null), api.goals(matchId, m.status).catch(() => null),
          api.rhythm(matchId, m.status).catch(() => null), api.fanFeed(matchId, m.status).catch(() => null),
          m.status === "done" ? api.report(matchId, m.status).catch(() => null) : null,
        ])
        if (gone) return
        if (pending.current === matchId) pending.current = null
        setMatch(m); setMoments(ms)
      } catch (e) { if (!gone) setError((e as Error).message) }
    }
    refresh()
    return () => { gone = true; window.clearTimeout(timer) }
  }, [matchId, tick])

  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); setError(null) } catch (e) { setError((e as Error).message) }
  }
  const analyse = () => act(async () => {     // a new random piece of the sample match (its own match), then the agents on it
    setLoading(true)
    try { const m = await api.analyseSample(); pending.current = m.match_id; setSelected(null); setGoal(null); await loadMatches(m.match_id) } finally { setLoading(false) }
  })
  const choose = (id: string) => { setMatchId(id); setSelected(null); setGoal(null) }
  const allMatches = () => { setMatchId(null); setSelected(null); setGoal(null); loadMatches() }
  const pickMoment = (id: string) => { setSelected(id); setGoal(null) }
  const pickGoal = (id: string) => { setGoal(id); setSelected(null) }
  const busy = loading || (match ? BUSY.includes(match.status) || (match.status === "ready" && pending.current === match.match_id) : false)
  const switching = !!matchId && match?.match_id !== matchId   // the chosen match is still being read
  const pickMode = (v: string) => { setMode(v as Mode); remember("mode", v) }
  const pickFollow = (v: string) => { const f = v === "none" ? "" : v; setFollow(f); remember("follow", f) }
  // who can be followed: the two teams, and the players of the critical moments grouped by team
  const teams = useMemo(() => !match ? [] : [{ id: match.home_id, name: match.home_name }, { id: match.away_id, name: match.away_name }].map((t) => ({
    ...t, players: [...new Map(moments.filter((m) => m.team_id === t.id).map((m) => [m.player_id, m.player_name ?? m.player_id])).entries()]
      .sort((p, q) => p[1].localeCompare(q[1])),
  })), [match, moments])
  const canFollow = teams.some((t) => follow === `team:${t.id}` || t.players.some(([id]) => follow === `player:${id}`))

  return (
    <PrefsContext.Provider value={{ mode, follow: canFollow ? follow : "" }}>
    <div className="min-h-screen flex flex-col">
      <header className="border-b bg-card">
        <div className="mx-auto max-w-[1600px] px-4 py-3 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="size-8 rounded-full bg-pitch grid place-items-center"><span className="size-3 rounded-full bg-white" /></span>
            <span className="text-lg font-semibold tracking-tight">Decision Lens</span>
          </div>
          <span className="hidden md:block text-muted-foreground text-sm">judges every on-ball decision by its quality, not its outcome</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Tabs value={mode} onValueChange={pickMode}>
              <TabsList>
                <TabsTrigger value="fan">Fan</TabsTrigger>
                <TabsTrigger value="analyst">Analyst</TabsTrigger>
              </TabsList>
            </Tabs>
            {match && (
              <Select value={canFollow ? follow : "none"} onValueChange={pickFollow}>
                <SelectTrigger className="min-w-40"><span className="text-muted-foreground">Follow</span><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Nobody</SelectItem>
                  {teams.map((t) => (
                    <SelectGroup key={t.id}>
                      <SelectLabel>{t.name}</SelectLabel>
                      <SelectItem value={`team:${t.id}`}>{t.name} (team)</SelectItem>
                      {t.players.map(([id, name]) => <SelectItem key={id} value={`player:${id}`}>{name}</SelectItem>)}
                    </SelectGroup>
                  ))}
                </SelectContent>
              </Select>
            )}
            {matchId && (
              <Button variant="outline" onClick={allMatches}><LayoutGrid /> All matches</Button>
            )}
            {matchId && matches.length > 0 && (
              <Select value={matchId ?? undefined} onValueChange={choose}>
                <SelectTrigger className="min-w-56"><SelectValue placeholder="Pick a match" /></SelectTrigger>
                <SelectContent>
                  {matches.map((m) => (
                    <SelectItem key={m.match_id} value={m.match_id}>{m.home_name} vs {m.away_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {matchId && <Button onClick={analyse} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" /> : <Play />} Load sample match and find critical moments
            </Button>}
          </div>
        </div>
        {match && !busy && !switching && (
          <div className="mx-auto max-w-[1600px] px-4 pb-3 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <Badge variant={match.status === "failed" ? "destructive" : match.status === "done" ? "good" : "secondary"} className="capitalize">{match.status}</Badge>
            {mode === "analyst" && <>
              <span>{match.decisions} decisions</span>
              <span>·</span>
              <span>{match.moments} critical moments</span>
            </>}
            {match.message && match.status !== "done" && <span>· {match.message}</span>}
          </div>
        )}
      </header>

      {error && (
        <div className="mx-auto w-full max-w-[1600px] px-4 pt-3">
          <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive flex justify-between gap-4">
            <span>{error}</span>
            <button className="underline cursor-pointer" onClick={() => setError(null)}>dismiss</button>
          </div>
        </div>
      )}

      <main className="mx-auto w-full max-w-[1600px] flex-1 p-4">
        {switching ? (
          <div key="switching" className="animate-in fade-in duration-500 h-[60vh] grid place-items-center text-center">
            <div className="space-y-4">
              <Loader2 className="size-10 animate-spin mx-auto text-pitch" />
              <p className="text-lg font-medium">Loading the match</p>
            </div>
          </div>
        ) : busy ? (
          <div key="busy" className="animate-in fade-in duration-500 h-[60vh] grid place-items-center text-center">
            <div className="space-y-4 w-72">
              <Loader2 className="size-10 animate-spin mx-auto text-pitch" />
              <p className="text-lg font-medium">{match?.status === "running" && !loading ? "Finding critical moments" : "Preparing the match"}</p>
              <Progress value={loading || !match ? 0 : 100 * match.progress} />
              {match?.step && !loading && <p className="text-sm text-muted-foreground capitalize">{match.step}</p>}
            </div>
          </div>
        ) : !matchId || !match ? (
          <MatchPicker key="picker" matches={matches} listed={listed} onPick={choose} onNew={analyse} busy={busy} />
        ) : (
          <div key="page" className="animate-in fade-in duration-500 grid gap-4 grid-cols-[minmax(0,1fr)] lg:grid-cols-[280px_minmax(0,1fr)_320px]">
            <MomentList moments={moments} selected={selected} onSelect={pickMoment} status={match.status} />
            {goal ? <GoalCard match={match} eventId={goal} />
              : <MomentCard matchId={match.match_id} homeId={match.home_id} eventId={selected} />}
            <SidePanel match={match} goal={goal} onGoal={pickGoal} moments={moments.map((m) => m.event_id)} onMoment={pickMoment} />
          </div>
        )}
      </main>

      <footer className="mx-auto w-full max-w-[1600px] px-4 py-4 text-xs text-muted-foreground">
        All data is synthetic. Agents run on Azure AI Foundry with the Microsoft Agent Framework; decisions are checked by Microsoft Decision-1.
      </footer>
    </div>
    </PrefsContext.Provider>
  )
}
