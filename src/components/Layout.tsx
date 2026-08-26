import { NavLink, Outlet } from "react-router-dom"

import { useStateQuery } from "@/lib/api"
import { cn } from "@/lib/utils"

const NAV = [
  { to: "/", label: "Главная", end: true },
  { to: "/dashboard", label: "Дашборд" },
  { to: "/moods", label: "Настроения" },
  { to: "/recommendations", label: "Рекомендации" },
  { to: "/import", label: "Импорт" },
]

export function Layout() {
  const { data } = useStateQuery()
  const totals = data?.totals

  return (
    <div className="min-h-svh">
      <header className="bg-background/95 sticky top-0 z-40 w-full border-b backdrop-blur">
        <div className="flex w-full flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3">
          <span className="text-sm font-bold tracking-tight">
            yt-music-analyzer
          </span>
          <nav className="flex items-center gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-sm transition-colors",
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          {totals && (
            <span className="text-muted-foreground ml-auto text-xs">
              треков: {totals.tracks_total} · музыка: {totals.music_tracks} ·
              проанализировано: {totals.analyzed}
            </span>
          )}
        </div>
      </header>
      <main className="w-full px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
