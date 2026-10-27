import { useEffect, useState } from "react"
import { ChevronDown, ChevronRight, Image, Play } from "lucide-react"

import { api, clock, label, pct, preload, type Frame, type Goal, type GoalDecision, type Match } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Pick, Tag, Waiting } from "@/components/MomentCard"
import { Replay } from "@/components/Replay"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/prefs"

type Props = { match: Match; eventId: string }
const REPLAY_BEFORE_MS = 8000, REPLAY_AFTER_MS = 3000   // a decision's replay: 8 s before it, on to 3 s after the goal

// One goal and the decisions behind it: the Goal Analyst's story, then every decision with its picture and options
export function GoalCard({ match, eventId }: Props) {
  const [g, setG] = useState<Goal | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const fan = usePrefs().mode === "fan"

  useEffect(() => {
    let gone = false
    setG(null)
    api.goals(match.match_id, match.status).then(async (all) => {
      const found = all.find((x) => x.event_id === eventId) ?? null
      await Promise.all((found?.decisions ?? []).map((d) => preload(d.image_url)))   // every step's picture
      if (gone) return
      setG(found)
      setOpen(found?.analysis?.key_event_ids[0] ?? found?.decisions.find((d) => d.key)?.event_id ?? null)
    }).catch(() => { if (!gone) setG(null) })
    return () => { gone = true }
  }, [match.match_id, match.status, eventId])

  if (!g) return <Waiting text="Loading the goal" />

  const team = g.team_id === match.home_id ? match.home_name : match.away_name
  return (
    <Card className="animate-in fade-in duration-500 gap-4 py-5 min-w-0">
      <CardHeader className="px-5">
        <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
          <span className="font-mono tabular-nums">{clock(g)}</span>
          <span>Goal: {g.scorer_name ?? "?"}</span>
          <span className="text-muted-foreground text-sm font-normal">{team} · score {g.score}</span>
          {g.shot_speed_kmh != null && <span className="text-muted-foreground text-sm font-normal tabular-nums">Shot {g.shot_speed_kmh} km/h</span>}
          {g.source && <Badge variant="outline" className="ml-auto">{g.source === "stub" ? "Goal Analyst · local stand-in" : "Goal Analyst"}</Badge>}
        </CardTitle>
        <CardDescription className="text-base">{fan ? `How ${team} built this goal; the key moves are marked.` : `${g.decisions.length} decisions of ${team} built this goal; the key ones are marked.`}</CardDescription>
      </CardHeader>

      <CardContent className="px-5 space-y-5">
        <section className="space-y-2">
          {!!g.analysis?.opponent_errors?.length && (
            <div className="rounded-md border border-orange-500/40 bg-orange-500/5 px-3 py-2 text-sm space-y-1">
              <div className="text-xs font-semibold uppercase tracking-wide text-orange-500">Opponent mistakes</div>
              {g.analysis.opponent_errors.map((s, i) => <p key={i}>{s.text}</p>)}
            </div>
          )}
          <h3 className="font-semibold">How the goal was made</h3>
          {g.analysis ? g.analysis.sentences.map((s, i) => <p key={i} className={cn("leading-relaxed", fan ? "text-base" : "text-sm")}>{s.text}</p>)
            : <p className="text-sm text-muted-foreground">Press “Find critical moments”: the Goal Analyst then reads every decision behind this goal. Until then the key decisions are the ones that added the most value by the numbers.</p>}
        </section>

        <Separator />

        <ol className="space-y-2">
          {g.decisions.map((d) => (
            <Step key={d.event_id} d={d} goalMs={g.ts_ms} matchId={match.match_id} homeId={match.home_id} open={open === d.event_id}
              onToggle={() => setOpen(open === d.event_id ? null : d.event_id)} />
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

function Step({ d, goalMs, matchId, homeId, open, onToggle }:
  { d: GoalDecision; goalMs: number; matchId: string; homeId: string; open: boolean; onToggle: () => void }) {
  const [frames, setFrames] = useState<Frame[] | null>(null)
  const fan = usePrefs().mode === "fan"
  useEffect(() => { if (!open) setFrames(null) }, [open])
  const mine = d.options.find((o) => o.is_chosen)
  // the picture and the 3D replay mark only the player's choice (yellow, with the run when the ball went ahead of him)
  const shown = { ...d, options: mine ? [{ ...mine, is_best: false, is_safe_best: false, is_decision1: false }] : [] }
  const best = d.options.find((o) => o.is_best)
  const safe = d.options.find((o) => o.is_safe_best)
  const chance = (o?: typeof mine) => (fan || o?.p_success == null ? "" : `${pct(o.p_success)} chance it comes off`)
  const sorted = d.options.slice().sort((p, q) => (q.ev ?? 0) - (p.ev ?? 0))
  const added = d.delta_value == null ? null : `${d.delta_value >= 0 ? "+" : "−"}${pct(Math.abs(d.delta_value))}`
  return (
    <li className={cn("rounded-lg border", d.key && "border-pitch/60 bg-pitch/5")}>
      <button onClick={onToggle} className="w-full text-left px-3 py-2 flex flex-wrap items-center gap-2 cursor-pointer">
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        <span className="font-mono tabular-nums text-sm">{clock(d)}</span>
        <span className="font-medium">{d.player_name ?? "?"}</span>
        <span className="text-sm text-muted-foreground">{mine ? label(mine) : d.type}</span>
        {d.key && <Badge variant="good">Key decision</Badge>}
        {added && !fan && <span className="ml-auto text-xs text-muted-foreground tabular-nums">value added {added}</span>}
      </button>
      {d.note && !open && <p className="px-3 pb-2 -mt-1 text-sm text-muted-foreground">{d.note}</p>}
      {open && (
        <div className="animate-in fade-in slide-in-from-top-1 duration-300 px-3 pb-3 space-y-4">
          {d.note && <p className={cn("leading-relaxed", fan ? "text-base" : "text-sm")}>{d.note}</p>}
          {d.defence && (
            <div className="rounded-md border border-orange-500/40 bg-orange-500/5 px-3 py-2 text-sm">
              <div className="text-xs font-semibold uppercase tracking-wide text-orange-500 mb-1">What the defence could have done</div>
              {d.defence} <span className="text-muted-foreground">(the orange arrow in the picture{d.defence_by_decision1 ? "; Microsoft Decision-1 chose it from the defenders' options" : ""})</span>
            </div>
          )}
          {d.what_if && (
            <div className="rounded-md border border-poor/40 bg-poor/5 px-3 py-2 text-sm">
              <div className="text-xs font-semibold uppercase tracking-wide text-poor mb-1">Had he chosen otherwise</div>
              {d.what_if}
            </div>
          )}
          <div className="rounded-lg overflow-hidden bg-muted">
            {frames ? <Replay frames={frames} moment={shown} homeId={homeId} />
              : <img src={d.image_url} alt="The decision from above" className="w-full block" />}
          </div>
          {frames ? <Button variant="outline" size="sm" onClick={() => setFrames(null)}><Image /> Back to the picture</Button>
            : <Button size="sm" onClick={async () => setFrames(await api.replayRange(matchId, d.ts_ms - REPLAY_BEFORE_MS, goalMs + REPLAY_AFTER_MS))}><Play /> Play the decision in 3D</Button>}
          <div className="grid gap-3 sm:grid-cols-3">
            <Pick title={fan ? "What he did" : "The player's choice"} colour="bg-yellow-400" o={mine} chance={chance(mine)} note="" />
            <Pick title={fan ? "The big chance" : "Biggest chance"} sub={fan ? undefined : "by the numbers"} colour="bg-fuchsia-500" o={best} chance={chance(best)} note="" />
            <Pick title={fan ? "The safe ball" : "Safest good option"} sub={fan ? undefined : "by the numbers"} colour="bg-cyan-400" o={safe} chance={chance(safe)} note=""
              empty={fan ? "None was on" : "None: no option was both likely to come off and worth playing"} />
          </div>
          {!fan && <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Option</TableHead>
                <TableHead className="text-right">Chance it comes off</TableHead>
                <TableHead className="text-right">Goal chance if it works</TableHead>
                <TableHead className="text-right">Danger if lost</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((o) => {
                const shot = o.option_type === "shot"
                return (
                  <TableRow key={o.option_id} className={cn(o.is_chosen && "bg-yellow-400/10")}>
                    <TableCell className="whitespace-normal">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={cn(o.is_chosen && "font-semibold")}>{label(o)}</span>
                        {o.is_chosen && <Tag>chosen</Tag>}
                        {o.is_best && <Tag>biggest chance</Tag>}
                        {o.is_safe_best && <Tag>safest</Tag>}
                        {o.into_run && <Tag>into the run</Tag>}
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{shot ? `${pct(o.p_success)} (xG)` : pct(o.p_success)}</TableCell>
                    <TableCell className="text-right tabular-nums">{shot ? "—" : pct(o.value_if_success)}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(o.risk_if_fail)}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>}
        </div>
      )}
    </li>
  )
}
