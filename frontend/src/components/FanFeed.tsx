import { useEffect, useState } from "react"

import { Angry, Eye, Frown, PartyPopper, Smile, ThumbsUp, type LucideIcon } from "lucide-react"

import { api, type FanPost, type Match } from "@/api"
import { Button } from "@/components/ui/button"
import { Fold } from "@/components/Fold"

// the team colours of the pictures and the 3D replay (home red, away blue)
const HOME = "#d32f2f", AWAY = "#1565c0"
const MOODS: Record<FanPost["mood"], { icon: LucideIcon; label: string }> = {
  joy: { icon: PartyPopper, label: "Joy" }, anger: { icon: Angry, label: "Anger" }, worry: { icon: Frown, label: "Worry" },
  praise: { icon: ThumbsUp, label: "Praise" }, banter: { icon: Smile, label: "Banter" },
}

// Made-up fans of both sides reacting through the match (written by the Fan Feed agent after the match story).
// status: the match's, so the feed is read again when a run is done; a post about a critical moment (moments: their
// event ids) gets a button that opens that moment.
type Props = { matchId: string; status?: string; moments: string[]; onMoment: (eventId: string) => void }
export function FanFeed({ matchId, status, moments, onMoment }: Props) {
  const [posts, setPosts] = useState<FanPost[]>([])
  const [match, setMatch] = useState<Match | null>(null)
  useEffect(() => {
    let gone = false
    api.fanFeed(matchId, status ?? "").then((f) => { if (!gone) setPosts(f.posts) }).catch(() => { if (!gone) setPosts([]) })
    api.match(matchId, status).then((m) => { if (!gone) setMatch(m) }).catch(() => { if (!gone) setMatch(null) })
    return () => { gone = true }
  }, [matchId, status])

  const team = (id: string | null) =>
    !match || !id ? null : id === match.home_id ? { name: match.home_name, colour: HOME } : { name: match.away_name, colour: AWAY }

  return (
    <Fold title="Fan feed" description="Made-up fans of both sides react as the match goes on" body="px-4">
        {posts.length === 0 ? <p className="text-sm text-muted-foreground">Run the critical moments to hear from the fans.</p> : (
          <ul className="space-y-2 max-h-[28rem] overflow-y-auto pr-1">
            {posts.map((p, i) => {
              const t = team(p.team_id)
              const { icon: Icon, label } = MOODS[p.mood] ?? MOODS.banter
              const moment = p.event_ids?.find((id) => moments.includes(id))
              return (
                <li key={i} className="rounded-md border bg-card p-2 text-sm border-l-4" style={{ borderLeftColor: t?.colour ?? "var(--border)" }}>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground truncate">{p.handle}</span>
                    {t && <span className="truncate">· {t.name}</span>}
                    <span className="ml-auto font-mono tabular-nums">{p.minute}'</span>
                    <span title={label} aria-label={label}><Icon className="size-3.5 shrink-0" /></span>
                  </div>
                  <p className="mt-1 leading-snug">{p.text}</p>
                  {moment && <Button variant="ghost" size="sm" className="mt-1 h-7 px-2 text-xs" onClick={() => onMoment(moment)}>
                    <Eye /> See the moment</Button>}
                </li>
              )
            })}
          </ul>
        )}
    </Fold>
  )
}
