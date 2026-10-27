import { useEffect, useState } from "react"

import { Goal as GoalIcon } from "lucide-react"

import { api, clock, level, type Goal, type Match, type PlayerCard } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Rhythm } from "@/components/Rhythm"
import { FanFeed } from "@/components/FanFeed"
import { Fold } from "@/components/Fold"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"
import { followed, usePrefs } from "@/prefs"

type Props = { match: Match; goal: string | null; onGoal: (id: string) => void; moments: string[]; onMoment: (id: string) => void }

export function SidePanel({ match, goal, onGoal, moments, onMoment }: Props) {
  const [cards, setCards] = useState<PlayerCard[]>([])
  const [goals, setGoals] = useState<Goal[]>([])
  const { mode, follow } = usePrefs(), fan = mode === "fan"
  useEffect(() => {
    api.goals(match.match_id, match.status).then(setGoals).catch(() => setGoals([]))
  }, [match.match_id, match.status])
  useEffect(() => {
    if (match.status !== "done") { setCards([]); return }
    api.report(match.match_id, match.status).then(setCards).catch(() => setCards([]))
  }, [match.match_id, match.status])
  // the followed player's card (or his team's cards) pinned at the top
  const pinned = (c: PlayerCard) => followed(follow, { team_id: c.team_id, player_id: c.player_id })
  const shown = [...cards.filter(pinned), ...cards.filter((c) => !pinned(c))]

  return (
    <div className="space-y-4 self-start">
      <Fold title="Match story" description={`${match.home_name} ${match.score.home}-${match.score.away} ${match.away_name}`}
        body={cn("px-4 space-y-2 leading-relaxed", fan ? "text-base" : "text-sm")}>
          {match.summary ? match.summary.parts.map((s, i) => <p key={i}>{s.text}</p>)
            : <p className="text-muted-foreground">Run the critical moments to get the story.</p>}
      </Fold>
      {fan && <FanFeed matchId={match.match_id} status={match.status} moments={moments} onMoment={onMoment} />}
      <Fold title="Decisions behind the goals" description="Every goal traced back to the decisions that made it" body="px-2 space-y-1">
          {goals.length === 0 ? <p className="px-2 text-sm text-muted-foreground">No goals in this match.</p>
            : goals.map((g) => (
              <button key={g.event_id} onClick={() => onGoal(g.event_id)}
                className={cn("w-full text-left rounded-md px-2 py-2 hover:bg-muted cursor-pointer flex items-start gap-2", goal === g.event_id && "bg-muted")}>
                <GoalIcon className="size-4 mt-0.5 text-pitch shrink-0" />
                <span className="text-sm">
                  <span className="font-mono tabular-nums">{clock(g)}</span> {g.scorer_name ?? "?"} <span className="text-muted-foreground">· {g.score}</span>
                  <span className="block text-xs text-muted-foreground">
                    {fan ? "See how it was made" : <>{g.decisions.length} decisions, {g.decisions.filter((d) => d.key).length} key {g.analysis ? "" : "· run the analysis for the Goal Analyst"}</>}
                  </span>
                </span>
              </button>
            ))}
      </Fold>
      <Rhythm match={match} />
      <Fold title="Player report" open={false} body="px-2"
        description={fan ? "How well each player chose" : "Each player's average decision score (0-10), passing, top speed and distance in this clip"}>
          {cards.length === 0 ? <p className="px-2 text-sm text-muted-foreground">Ready when the analysis is done.</p> : fan ? (
            <ul className="space-y-1">
              {shown.map((c) => {
                const lv = level(c.avg_score)
                return (
                  <li key={c.player_id} className={cn("rounded-md px-2 py-1.5 flex items-center gap-2", pinned(c) && "bg-pitch/5 border-l-2 border-pitch")}>
                    <span className="min-w-0 flex-1 truncate">{c.name} <span className="text-muted-foreground text-sm">{c.position ?? ""}</span></span>
                    {lv && c.avg_score != null && <Badge variant={lv.key}>{c.avg_score.toFixed(1)} · {lv.title.split(" ")[0]}</Badge>}
                  </li>
                )
              })}
            </ul>
          ) : (
            <Table className="text-xs [&_th]:px-1.5 [&_td]:px-1.5">
              <TableHeader><TableRow><TableHead>Player</TableHead><TableHead className="text-right">Moments</TableHead><TableHead className="text-right">Avg score</TableHead>
                <TableHead className="text-right">Passes</TableHead></TableRow></TableHeader>
              <TableBody>
                {shown.map((c) => (
                  <TableRow key={c.player_id} className={cn(pinned(c) && "bg-pitch/5")}>
                    <TableCell className="whitespace-normal min-w-28">{c.name} <span className="text-muted-foreground">({c.position ?? "?"})</span>
                      <div className="text-[11px] text-muted-foreground tabular-nums">{c.pass_pct?.toFixed(0) ?? "–"}% passes · {c.pass_m?.toFixed(1) ?? "–"} m · {c.top_speed_kmh?.toFixed(1) ?? "–"} km/h · {c.distance_km?.toFixed(2) ?? "–"} km</div></TableCell>
                    <TableCell className="text-right tabular-nums">{c.moments}</TableCell>
                    <TableCell className="text-right tabular-nums">{c.avg_score?.toFixed(1) ?? "–"}</TableCell>
                    <TableCell className="text-right tabular-nums">{c.passes}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
      </Fold>
    </div>
  )
}
