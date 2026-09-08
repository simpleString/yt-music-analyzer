import { useEffect, useRef } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

import { useStateQuery } from "@/lib/api"
import { NoteLogo } from "@/components/LoadingNote"
import { Button } from "@/components/ui/button"

const NAV = [
  { to: "/", label: "Tracks", end: true },
  { to: "/artists", label: "Artists" },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/import", label: "Import" },
  { to: "/settings", label: "Settings" },
]

export function Layout() {
  const { data } = useStateQuery()
  const totals = data?.totals
  const headerRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const location = useLocation()
  // detail pages have a "← Back" in the header so it is reachable
  // from any scroll position
  const showBack = /^\/(artist|track)\//.test(location.pathname)

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
            <div className="relative flex flex-wrap items-center justify-center gap-x-2 gap-y-0.5">
              {showBack && (
                <Button
                  variant="outline"
                  size="sm"
                  className="absolute left-0 top-1/2 -translate-y-1/2"
                  onClick={() => navigate(-1)}
                >
                  <ArrowLeft className="size-3.5" />
                  Back
                </Button>
              )}
              <span className="inline-flex items-center gap-1.5">
                <NoteLogo size={36} animated={false} />
                <a
                  href="/"
                  className="text-lg font-bold no-underline"
                  style={{ color: "#ff0033" }}
                >
                  yt-music-analyzer!
                </a>
              </span>
              <span className="text-xs text-[#666666]">
                — music library
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
                tracks: {totals.tracks_total} · music: {totals.music_tracks} ·
                analyzed: {totals.analyzed}
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
