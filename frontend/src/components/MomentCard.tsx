import { useEffect, useState } from "react"
import { Image, Loader2, Play, Square } from "lucide-react"

import { api, clock, kindText, label, level, pct, preload, type Frame, type Moment, type Option } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Replay } from "@/components/Replay"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/prefs"

type Props = { matchId: string; homeId: string; eventId: string | null }

// the middle card while its data and picture are read
export function Waiting({ text }: { text: string }) {
  return (
    <Card className="animate-in fade-in duration-500 min-h-[60vh] grid justify-items-center content-start pt-24 text-center">
      <div className="space-y-4"><Loader2 className="size-10 animate-spin mx-auto text-pitch" /><p className="text-lg font-medium">{text}</p></div>
    </Card>
  )
}

export function MomentCard({ matchId, homeId, eventId }: Props) {
  const [x, setX] = useState<Moment | null>(null)
  const [frames, setFrames] = useState<Frame[] | null>(null)
  const [loading, setLoading] = useState(false)
  const fan = usePrefs().mode === "fan"   // the fan sees no numbers or tables: the picture, the verdict and the words

  useEffect(() => {
    setFrames(null)
    if (!eventId) { setX(null); return }
    let gone = false
    setLoading(true)
    api.moment(matchId, eventId).then(async (m) => { await preload(m.image_url); if (!gone) setX(m) })
      .finally(() => { if (!gone) setLoading(false) })
    return () => { gone = true }
  }, [matchId, eventId])

  if (!eventId) return (
    <Card className="animate-in fade-in duration-500 min-h-[60vh] grid place-items-center text-center">
      <CardContent className="text-muted-foreground">Pick a moment on the left to see the picture, the options and what the coach and Decision-1 say.</CardContent>
    </Card>
  )
  if (loading || !x) return <Waiting text="Loading the moment" />

  const opts = Object.fromEntries(x.options.map((o) => [o.option_id, o]))
  const mine = x.chosen_option_id ? opts[x.chosen_option_id] : undefined
  const best = x.options.find((o) => o.is_best)
  const safe = x.options.find((o) => o.is_safe_best)
  const d = x.decision1
  const d1 = d ? opts[d.option_id] : undefined
  const notes = Object.fromEntries((x.analysis?.options ?? []).map((n) => [n.option_id, n.note]))
  const said = (o?: Option) => (!o || o.option_type === "from_picture" ? "" : [o.text, notes[o.option_id]].filter(Boolean).join(" "))
  const share = (o?: Option) => (d && o ? d.probabilities[o.option_id] ?? null : null)
  const chance = (o?: Option) => (!o || fan || o.p_success == null ? "" : `${pct(o.p_success)} chance it comes off`)
  const c = x.coach, lv = level(c?.score)
  const sorted = x.options.slice().sort((p, q) => (q.ev ?? 0) - (p.ev ?? 0))

  const play = async () => setFrames(await api.replay(matchId, x.event_id))

  return (
    <Card className="animate-in fade-in duration-500 gap-4 py-5 min-w-0">
      <CardHeader className="px-5">
        <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
          <span className="font-mono tabular-nums">{clock(x)}</span>
          <span>{x.player_name}</span>
          <Badge variant="secondary">{kindText(x.kind, c?.score)}</Badge>
          <span className="text-muted-foreground text-sm font-normal">score {x.score}</span>
          {c?.score != null && lv && <Badge variant={lv.key} className="ml-auto text-sm px-2.5 py-1">{c.score.toFixed(1)} / 10 · {lv.title.split(" ")[0]} decision</Badge>}
        </CardTitle>
        <CardDescription className="text-base">{x.reason}</CardDescription>
      </CardHeader>

      <CardContent className="px-5 space-y-5">
        <div className="rounded-lg overflow-hidden bg-muted">
          {frames ? <Replay frames={frames} moment={x} homeId={homeId} />
            : x.image_url ? <img src={x.image_url} alt="The moment from above" className="w-full block" />
              : <div className="aspect-video grid place-items-center text-muted-foreground text-sm">{x.error ?? "Picture not ready yet"}</div>}
        </div>
        <div className="flex gap-2">
          {frames ? <Button variant="outline" size="sm" onClick={() => setFrames(null)}><Image /> Back to the picture</Button>
            : <Button size="sm" onClick={play}><Play /> Play the moment in 3D</Button>}
          {frames && <Button variant="ghost" size="sm" onClick={() => setFrames(null)}><Square /> Stop</Button>}
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Pick title={fan ? "What he did" : "The player's choice"} colour="bg-yellow-400" o={mine} chance={chance(mine)} note={said(mine)} />
          <Pick title={fan ? "The big chance" : "Biggest chance"} sub={fan ? undefined : "GPT analyst"} colour="bg-fuchsia-500" o={best} chance={chance(best)} note={said(best)} />
          <Pick title={fan ? "The safe ball" : "Safest good option"} sub={fan ? undefined : "GPT analyst"} colour="bg-cyan-400" o={safe} chance={chance(safe)} note={said(safe)}
            empty={fan ? "None was on" : "None: no option was both likely to come off and worth playing"} />
          <Pick title={fan ? "The AI's pick" : "Decision-1's choice"} sub={fan ? undefined : d?.source === "stub" ? "local stand-in" : "Microsoft Decision-1"} colour="bg-lime-400" o={d1} chance={chance(d1)} note={said(d1)} />
        </div>

        <Separator />

        <section className="space-y-2">
          <h3 className={cn("font-semibold flex items-center gap-2", fan && "text-lg")}>{fan ? "The coach says" : "Coach"}
            {c && <Badge variant={c.same_choice ? "good" : "poor"}>{c.same_choice ? (fan ? "Same as the AI" : "Same choice as Decision-1") : (fan ? "Not the AI's pick" : "Different from Decision-1")}</Badge>}
          </h3>
          {c ? c.sentences.map((s, i) => <p key={i} className={cn("leading-relaxed", fan ? "text-base" : "text-sm")}>{s.text}</p>)
            : <p className="text-sm text-muted-foreground">{x.error ?? "Not ready yet"}</p>}
        </section>

        {x.analysis && !fan && (
          <section className="space-y-2">
            <h3 className="font-semibold">Position <span className="text-muted-foreground font-normal text-sm">· {x.analysis.phase}, {x.analysis.zone}</span></h3>
            {x.analysis.situation.map((s, i) => <p key={i} className="text-sm leading-relaxed">{s.text}</p>)}
          </section>
        )}

        {!fan && <section className="space-y-2">
          <h3 className="font-semibold">Options</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Option</TableHead>
                <TableHead className="text-right">Chance it comes off</TableHead>
                <TableHead className="text-right">Goal chance if it works</TableHead>
                <TableHead className="text-right">Danger if lost</TableHead>
                <TableHead className="text-right">Decision-1's share</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((o) => {
                const shot = o.option_type === "shot"   // a shot that comes off is a goal: its chance is the xG
                return (
                  <TableRow key={o.option_id} className={cn(o.is_chosen && "bg-yellow-400/10")}>
                    <TableCell className="whitespace-normal">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={cn(o.is_chosen && "font-semibold")}>{label(o)}</span>
                        {o.is_chosen && <Tag>chosen</Tag>}
                        {o.is_best && <Tag>biggest chance</Tag>}
                        {o.is_safe_best && <Tag>safest</Tag>}
                        {d?.option_id === o.option_id && <Tag>Decision-1</Tag>}
                        {o.option_type === "from_picture" && <Tag>seen in the picture</Tag>}
                        {o.into_run && <Tag>into the run</Tag>}
                        {o.shot_chance != null && <Tag>shot from there {pct(o.shot_chance)}</Tag>}
                      </div>
                      {said(o) && <div className="text-xs text-muted-foreground mt-1">{said(o)}</div>}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{shot ? `${pct(o.p_success)} (xG)` : pct(o.p_success)}</TableCell>
                    <TableCell className="text-right tabular-nums">{shot ? "—" : pct(o.value_if_success)}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(o.risk_if_fail)}</TableCell>
                    <TableCell className="text-right tabular-nums">{share(o) == null ? "—" : pct(share(o))}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </section>}
      </CardContent>
    </Card>
  )
}

export function Tag({ children }: { children: React.ReactNode }) {
  return <Badge variant="outline" className="text-[11px] py-0 font-normal">{children}</Badge>
}

export function Pick({ title, sub, colour, o, chance, note, empty = "—" }:
  { title: string; sub?: string; colour: string; o?: Option; chance: string; note: string; empty?: string }) {
  return (
    <div className="rounded-lg border p-3 space-y-1">
      <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
        <span className={cn("size-2.5 rounded-full", colour)} />{title}
      </div>
      {sub && <div className="text-xs text-muted-foreground -mt-1">{sub}</div>}
      <div className="font-medium leading-snug">{o ? label(o) : empty}</div>
      {chance && <div className="text-sm text-muted-foreground">{chance}</div>}
      {note && <div className="text-xs text-muted-foreground border-t pt-1 mt-1">{note}</div>}
    </div>
  )
}
