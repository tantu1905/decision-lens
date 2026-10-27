import { clock, kindText, LEVELS, level, type Moment } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Fold } from "@/components/Fold"
import { cn } from "@/lib/utils"
import { followed, usePrefs } from "@/prefs"

type Props = { moments: Moment[]; selected: string | null; onSelect: (id: string) => void; status: string }

export function MomentList({ moments, selected, onSelect, status }: Props) {
  const { follow } = usePrefs()
  const groups = [...LEVELS.map((l) => ({ key: l.key as string, title: l.title })), { key: "none", title: "Not scored yet" }]
  // the followed team's or player's moments come first, in their own group; the others are dimmed
  const mine = moments.filter((m) => followed(follow, m))
  if (mine.length) groups.unshift({ key: "follow", title: follow.startsWith("team:") ? "Your team" : "Your player" })
  const groupOf = (m: Moment) => (mine.includes(m) ? "follow" : level(m.coach?.score)?.key ?? "none")
  return (
    // one card per group, each opens and closes on its title; the column scrolls on its own on a wide screen
    <div className="space-y-4 self-start lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
      {moments.length === 0 && (
        <Fold title="Critical moments" body="px-2">
          {status === "running" ? <div className="space-y-2 px-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
            : <p className="px-2 text-sm text-muted-foreground">No critical moments yet.</p>}
        </Fold>
      )}
      {groups.map(({ key, title }) => {
        const these = moments.filter((m) => groupOf(m) === key)
        if (!these.length) return null
        return (
          <Fold key={key} body="px-2"
            title={<><span className={cn("size-2 rounded-full", key === "good" && "bg-good", key === "fair" && "bg-fair", key === "poor" && "bg-poor", key === "none" && "bg-muted-foreground/40", key === "follow" && "bg-pitch")} />{title}</>}
            side={<span className="text-muted-foreground text-sm font-normal">{these.length}</span>}>
              {these.map((m) => {
                const s = m.coach?.score
                return (
                  <button
                    key={m.event_id}
                    onClick={() => onSelect(m.event_id)}
                    className={cn("w-full text-left rounded-md px-2 py-2 flex items-center gap-3 cursor-pointer hover:bg-accent transition-colors",
                      key === "follow" && "bg-pitch/5 border-l-2 border-pitch", mine.length > 0 && key !== "follow" && "opacity-50 hover:opacity-100",
                      selected === m.event_id && "bg-accent ring-1 ring-ring/40 opacity-100")}
                  >
                    <span className="font-mono text-sm tabular-nums w-11 text-muted-foreground">{clock(m)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{m.player_name ?? "—"}</span>
                      <span className="block truncate text-xs text-muted-foreground">{kindText(m.kind, s)}</span>
                    </span>
                    {s == null ? <Badge variant="outline" className="capitalize">{m.status}</Badge>
                      : <Badge variant={level(s)!.key}>{s.toFixed(1)}</Badge>}
                  </button>
                )
              })}
          </Fold>
        )
      })}
    </div>
  )
}
