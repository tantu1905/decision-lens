import { useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type Props = { title: ReactNode; side?: ReactNode; description?: ReactNode; open?: boolean; body?: string; children: ReactNode }

// a card that opens and closes on its title, so the long panels need less scrolling
export function Fold({ title, side, description, open = true, body, children }: Props) {
  const [shown, setShown] = useState(open)
  return (
    <Card className="gap-0 py-4">
      <CardHeader className="px-4 cursor-pointer select-none" onClick={() => setShown(!shown)}>
        <CardTitle className="flex items-center gap-2">
          <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform duration-300", !shown && "-rotate-90")} />
          <span className="flex-1 flex items-center gap-2">{title}</span>{side}
        </CardTitle>
        {description && <Slide shown={shown}><CardDescription className="pl-6">{description}</CardDescription></Slide>}
      </CardHeader>
      <Slide shown={shown}><CardContent className={cn("pt-3", body)}>{children}</CardContent></Slide>
    </Card>
  )
}

// grows to its content's height and shrinks back to nothing, so opening and closing slides instead of jumping
function Slide({ shown, children }: { shown: boolean; children: ReactNode }) {
  return (
    <div className={cn("grid transition-[grid-template-rows,opacity] duration-300 ease-out", shown ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
      <div className="overflow-hidden min-h-0">{children}</div>
    </div>
  )
}
