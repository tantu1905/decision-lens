import { useEffect, useRef } from "react"

import { TYPES, type Frame, type OnBall } from "@/api"

// The 3D replay (replay3d.js, three.js) owns this div: it builds the canvas and the controls itself. It is loaded
// the first time a moment is played, so the page itself stays small.
export function Replay({ frames, moment, homeId }: { frames: Frame[]; moment: OnBall; homeId: string }) {
  const div = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let r: typeof import("@/replay3d.js") | undefined, gone = false
    import("@/replay3d.js").then((m) => {
      if (gone || !div.current) return
      r = m
      m.play(div.current, frames, moment, homeId, (o) => o.target_name || TYPES[o.option_type] || o.option_type)
    })
    return () => { gone = true; r?.stop() }
  }, [frames, moment, homeId])
  return <div id="replay" ref={div} />
}
