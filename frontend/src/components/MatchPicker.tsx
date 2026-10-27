import { ArrowRight, Loader2, Play } from "lucide-react"

import type { Match } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

type Props = { matches: Match[]; listed: boolean; onPick: (id: string) => void; onNew: () => void; busy: boolean }

const STATUS: Record<string, { text: string; variant: "good" | "fair" | "secondary" | "destructive" }> = {
  done: { text: "Analysed", variant: "good" },
  running: { text: "Finding critical moments…", variant: "fair" },
  loading: { text: "Preparing…", variant: "fair" },
  ready: { text: "Ready", variant: "secondary" },
  failed: { text: "Failed", variant: "destructive" },
}

// when the match was loaded: "27 Oct, 09:05"
const when = (m: Match) => m.created_at
  ? new Date(m.created_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""

// the clips start at 0-0, so the score is the goals in the clip
const goals = (m: Match) => (m.score?.home ?? 0) + (m.score?.away ?? 0)

// the first screen: open a match that is already there, or load a new one
export function MatchPicker({ matches, listed, onPick, onNew, busy }: Props) {
  return (
    <div className="animate-in fade-in duration-500 mx-auto max-w-5xl py-8 space-y-8">
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Choose a match</h1>
        <p className="text-muted-foreground">Open a match that is already analysed, or load a new 30-minute piece of the sample match.</p>
      </div>

      <div className="rounded-xl border-2 border-dashed border-pitch bg-pitch/5 px-6 py-5 flex flex-wrap items-center gap-4">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">New match</h2>
          <p className="text-sm text-muted-foreground">Loads a random 30-minute piece of the sample match and finds its critical moments (a few minutes).</p>
        </div>
        <Button className="ml-auto" onClick={onNew} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <Play />} Load sample match and find critical moments
        </Button>
      </div>

      {!listed && <p className="text-sm text-muted-foreground flex items-center gap-2"><Loader2 className="size-4 animate-spin" /> Reading the matches</p>}
      {matches.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Matches</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {matches.map((m) => {
              const s = STATUS[m.status] ?? { text: m.status, variant: "secondary" as const }
              return (
                <Card key={m.match_id} onClick={() => onPick(m.match_id)}
                  className="gap-3 p-5 cursor-pointer transition-all hover:border-pitch hover:shadow-md">
                  <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 font-semibold">
                    <span>{m.home_name}</span><span className="tabular-nums text-right">{m.score?.home ?? 0}</span>
                    <span>{m.away_name}</span><span className="tabular-nums text-right">{m.score?.away ?? 0}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">{when(m)}</p>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant={s.variant}>{s.text}</Badge>
                    {m.moments > 0 && <Badge variant="outline">{m.moments} critical moments</Badge>}
                    <Badge variant="outline">{goals(m)} {goals(m) === 1 ? "goal" : "goals"}</Badge>
                  </div>
                  <span className="mt-auto text-sm font-medium text-pitch flex items-center gap-1">Open <ArrowRight className="size-4" /></span>
                </Card>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
