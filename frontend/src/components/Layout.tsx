import { useEffect, useRef } from "react"
import { NavLink, Outlet } from "react-router-dom"

import { useStateQuery } from "@/lib/api"

const NAV = [
  { to: "/", label: "Главная", end: true },
  { to: "/dashboard", label: "Дашборд" },
  { to: "/import", label: "Импорт" },
  { to: "/settings", label: "Настройки" },
]

export function Layout() {
  const { data } = useStateQuery()
  const totals = data?.totals
  const headerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = headerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      document.documentElement.style.setProperty(
        "--header-h",
        `${el.offsetHeight}px`
      )
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <div className="min-h-svh flex flex-col">
      <div className="w-full px-3 pt-2">
        <div
          ref={headerRef}
          className="sticky top-0 z-30 -mx-3 bg-background px-3"
        >
          <header className="w-full text-center">
            <div className="flex flex-wrap items-baseline justify-center gap-x-2 gap-y-0.5">
              <a
                href="/"
                className="text-lg font-bold no-underline"
                style={{ color: "#ff0033" }}
              >
                yt-music-analyzer!
              </a>
              <span className="text-xs text-[#666666]">
                — музыкальная библиотека
              </span>
            </div>
            <nav className="mt-0.5 flex flex-wrap items-center justify-center gap-0 text-sm">
              {NAV.map((item, i) => (
                <span key={item.to} className="flex items-center">
                  {i > 0 && <span className="px-1.5 text-[#999999]">|</span>}
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      isActive
                        ? "font-bold no-underline text-[#000000]"
                        : "text-[#0000cc] underline"
                    }
                  >
                    {item.label}
                  </NavLink>
                </span>
              ))}
            </nav>
            {totals && (
              <div className="mt-0.5 text-xs text-[#666666]">
                треков: {totals.tracks_total} · музыка: {totals.music_tracks} ·
                проанализировано: {totals.analyzed}
              </div>
            )}
            <hr className="mt-1.5 border-t border-[#cccccc] z-50" />
          </header>
        </div>

        <main className="w-full py-2.5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
