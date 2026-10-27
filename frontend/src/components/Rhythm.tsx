import { useEffect, useId, useState } from "react"

import { api, pct, type Match, type Rhythm as RhythmData, type RhythmMinute } from "@/api"
import { Fold } from "@/components/Fold"

// the team colours of the app (the replay and the pictures)
const HOME = "#d32f2f"
const AWAY = "#1565c0"
// the chart, in viewBox units: the share of the ball above, the turnovers below, one x axis (match minutes)
const W = 320, L = 4, R = 4
const TOP = 10, PH = 72, GAP = 10, BH = 28
const BASE = TOP + PH + GAP + BH, H = BASE + 16

export function Rhythm({ match }: { match: Match }) {
  const [data, setData] = useState<RhythmData | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const id = useId()
  useEffect(() => {
    api.rhythm(match.match_id, match.status).then(setData).catch(() => setData(null))
  }, [match.match_id, match.status])

  const ms = data?.minutes ?? []
  const first = ms[0]?.minute ?? 0, span = Math.max(1, ms.length)
  const band = (W - L - R) / span
  const x = (minute: number) => L + (minute - first) * band          // minute as a time: 17.5 = 17:30
  const y = (share: number) => TOP + (1 - share) * PH                 // the home team's share of the ball
  const mid = y(0.5)
  const pts = ms.filter((m) => m.possession_home != null).map((m) => [x(m.minute + 0.5), y(m.possession_home!)] as const)
  const line = pts.map(([a, b], i) => `${i ? "L" : "M"}${a},${b}`).join("")
  const area = pts.length ? `${line}L${pts[pts.length - 1][0]},${mid}L${pts[0][0]},${mid}Z` : ""
  const most = Math.max(1, ...ms.map((m) => m.turnovers))
  const bw = Math.min(24, band - 2)
  const ticks = ms.map((m) => m.minute).filter((m) => m % 5 === 0)
  const h = hover == null ? null : ms[hover]
  const hx = hover == null ? 0 : (x(ms[hover].minute + 0.5) / W) * 100

  return (
    <Fold title="Control vs chaos" description="Share of the ball each minute, and how often it changed hands" open={false} body="px-4 space-y-2">
        {!data || ms.length === 0 ? <p className="text-sm text-muted-foreground">Ready when the match is loaded.</p> : <>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <Key color={HOME}>{data.home_name} on the ball</Key>
            <Key color={AWAY}>{data.away_name} on the ball</Key>
            <Key color="var(--muted-foreground)">Turnovers</Key>
          </div>
          <div className="relative" onMouseLeave={() => setHover(null)}>
            <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block" role="img"
              aria-label={`Control vs chaos. ${data.spells.join(". ")}`}>
              <defs>
                <clipPath id={`${id}-up`}><rect x={0} y={TOP} width={W} height={mid - TOP} /></clipPath>
                <clipPath id={`${id}-down`}><rect x={0} y={mid} width={W} height={TOP + PH - mid} /></clipPath>
              </defs>
              {h && <rect x={x(h.minute)} y={TOP} width={band} height={BASE - TOP} fill="var(--muted)" />}
              <line x1={L} x2={W - R} y1={mid} y2={mid} stroke="var(--border)" />
              <line x1={L} x2={W - R} y1={BASE} y2={BASE} stroke="var(--border)" />
              <path d={area} fill={HOME} fillOpacity={0.16} clipPath={`url(#${id}-up)`} />
              <path d={area} fill={AWAY} fillOpacity={0.16} clipPath={`url(#${id}-down)`} />
              <path d={line} fill="none" stroke="var(--foreground)" strokeOpacity={0.6} strokeWidth={2}
                strokeLinejoin="round" strokeLinecap="round" />
              <text x={L + 2} y={TOP + 8} fontSize={8} fill="var(--muted-foreground)">100%</text>
              <text x={L + 2} y={mid - 3} fontSize={8} fill="var(--muted-foreground)">50%</text>
              {ms.map((m) => m.turnovers > 0 && (
                <path key={m.minute} d={bar(x(m.minute + 0.5) - bw / 2, bw, (m.turnovers / most) * BH)}
                  fill="var(--muted-foreground)" fillOpacity={0.6} />
              ))}
              {ticks.map((t) => (
                <text key={t} x={x(t)} y={H - 3} fontSize={8} textAnchor="middle" fill="var(--muted-foreground)"
                  className="tabular-nums">{t}'</text>
              ))}
              {data.goals.map((g, i) => {
                const gx = x(g.minute + g.second / 60), c = g.team_id === data.home_id ? HOME : AWAY
                return <g key={i}>
                  <line x1={gx} x2={gx} y1={TOP} y2={BASE} stroke={c} strokeWidth={1.5} />
                  <circle cx={gx} cy={TOP} r={4} fill={c} stroke="var(--card)" strokeWidth={2} />
                </g>
              })}
              {ms.map((m, i) => (
                <rect key={m.minute} x={x(m.minute)} y={0} width={band} height={H} fill="transparent"
                  onMouseEnter={() => setHover(i)} onClick={() => setHover(i)} />
              ))}
            </svg>
            {h && <Tip minute={h} data={data} style={hx < 50 ? { left: `calc(${hx}% + 12px)` } : { right: `calc(${100 - hx}% + 12px)` }} />}
          </div>
          {data.spells.length > 0 && (
            <ul className="text-xs text-muted-foreground space-y-0.5">
              {data.spells.map((s, i) => <li key={i}>{s[0].toUpperCase() + s.slice(1)}</li>)}
            </ul>
          )}
        </>}
    </Fold>
  )
}

// a column from the baseline with a rounded top (square at the baseline)
function bar(x0: number, w: number, h: number) {
  const r = Math.min(2, w / 2, h)
  return `M${x0},${BASE}V${BASE - h + r}Q${x0},${BASE - h} ${x0 + r},${BASE - h}H${x0 + w - r}Q${x0 + w},${BASE - h} ${x0 + w},${BASE - h + r}V${BASE}Z`
}

function Key({ color, children }: { color: string; children: React.ReactNode }) {
  return <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: color }} />{children}</span>
}

function Tip({ minute: m, data, style }: { minute: RhythmMinute; data: RhythmData; style: React.CSSProperties }) {
  const goals = data.goals.filter((g) => g.minute === m.minute)
  return (
    <div className="pointer-events-none absolute top-0 z-10 rounded-md border bg-popover px-2 py-1.5 text-xs text-popover-foreground shadow-md space-y-0.5 w-52 max-w-[60%]" style={style}>
      <div className="font-medium tabular-nums">Minute {m.minute}'</div>
      <Row color={HOME} name={data.home_name} ball={m.possession_home} pressed={m.pressure_home} />
      <Row color={AWAY} name={data.away_name} ball={m.possession_away} pressed={m.pressure_away} />
      <div className="text-muted-foreground">{m.turnovers} turnover{m.turnovers === 1 ? "" : "s"} · {m.decisions} decisions</div>
      {goals.map((g, i) => <div key={i}>Goal for {g.team_id === data.home_id ? data.home_name : data.away_name}</div>)}
    </div>
  )
}

function Row({ color, name, ball, pressed }: { color: string; name: string; ball: number | null; pressed: number | null }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="size-2 rounded-full" style={{ background: color }} />
      <span>{name}: <span className="tabular-nums">{pct(ball)}</span> of the ball, <span className="tabular-nums">{pct(pressed)}</span> under pressure</span>
    </div>
  )
}
