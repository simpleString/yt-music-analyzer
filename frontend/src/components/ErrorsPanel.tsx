import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"

import { api } from "@/lib/api"
import { artistPath } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function ErrorsPanel() {
  const { data: errors } = useQuery({
    queryKey: ["processing-errors"],
    queryFn: api.errors,
    refetchInterval: 15_000,
  })

  if (!errors || errors.length === 0) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Processing errors</CardTitle>
        <CardDescription>
          Current per-track failures (audio download/analysis, lyrics lookup).
          Rows disappear once the stage succeeds; unavailable videos are
          retried in 30 days or via "Retry failed videos".
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="border border-[#999999]">
          <div className="grid h-9 grid-cols-[4.25rem_minmax(0,1fr)_5rem_minmax(0,2fr)_9rem] items-center gap-1.5 border-b border-[#999999] bg-[#eeeeee] px-1.5 text-xs font-bold whitespace-nowrap text-black">
            <span />
            <span>Track</span>
            <span>Stage</span>
            <span>Error</span>
            <span>Date</span>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {errors.map((e) => (
              <div
                key={`${e.video_id}:${e.stage}`}
                className="grid grid-cols-[4.25rem_minmax(0,1fr)_5rem_minmax(0,2fr)_9rem] items-center gap-1.5 border-b border-[#e0e0e0] px-1.5 py-1 text-sm hover:bg-[#ffffcc]"
              >
                <img
                  src={`https://i.ytimg.com/vi/${e.video_id}/default.jpg`}
                  alt=""
                  loading="lazy"
                  className="h-9 w-16 border border-[#999999] object-cover"
                />
                <span className="min-w-0">
                  <Link
                    to={`/track/${e.video_id}`}
                    className="block truncate hover:underline"
                    title={e.title}
                  >
                    {e.title}
                  </Link>
                  <Link
                    to={artistPath(e.artist)}
                    className="text-muted-foreground block truncate text-xs hover:underline"
                  >
                    {e.artist}
                  </Link>
                </span>
                <span>
                  <Badge variant="outline" className="font-normal uppercase">
                    {e.stage}
                  </Badge>
                </span>
                <span
                  className="text-muted-foreground truncate text-xs"
                  title={e.error}
                >
                  {e.error}
                </span>
                <span className="text-muted-foreground text-xs tabular-nums">
                  {new Date(e.created_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
