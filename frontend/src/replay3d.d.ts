import type { Frame, OnBall, Option } from "./api"

export function stop(): void
export function play(div: HTMLElement, frames: Frame[], x: OnBall, home: string, name: (o: Option) => string): Promise<void>
