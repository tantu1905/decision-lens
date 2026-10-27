// The viewer's preferences, set in the header (App.tsx) and read anywhere with usePrefs():
// - mode: "analyst" shows every number and table, "fan" only the pictures, the scores' Good/Fair/Poor and the stories
// - follow: the team or player the viewer follows, "team:<team_id>" or "player:<player_id>", or "" for nobody
import { createContext, useContext } from "react"

export type Mode = "fan" | "analyst"
export type Prefs = { mode: Mode; follow: string }

export const PrefsContext = createContext<Prefs>({ mode: "analyst", follow: "" })
export const usePrefs = () => useContext(PrefsContext)

// is this moment (or player card) the followed team's or player's
export const followed = (follow: string, x: { team_id: string; player_id: string }) =>
  follow !== "" && (follow === `team:${x.team_id}` || follow === `player:${x.player_id}`)

// localStorage may be missing or blocked (private window): then the preferences just are not remembered
export const recall = (key: string, fallback: string) => {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}
export const remember = (key: string, value: string) => {
  try { localStorage.setItem(key, value) } catch { /* not remembered */ }
}
