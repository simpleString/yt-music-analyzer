import { useMemo, useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "react-router-dom"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts"

import { api } from "@/lib/api"
import { artistPath } from "@/lib/utils"
import { LoadingNote } from "@/components/LoadingNote"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableData,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const chartConfig = {
  listens: { label: "plays" },
}

type Preset = "all" | "7d" | "30d" | "month" | "year" | "custom"

const PRESET_LABELS: Record<Preset, string> = {
  all: "All time",
  "7d": "7 days",
  "30d": "30 days",
  month: "This month",
  year: "This year",
  custom: "Custom range",
}

function toIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function presetRange(preset: Preset): { from: string | null; to: string | null } {
  const today = new Date()
  switch (preset) {
    case "7d":
      return { from: toIso(new Date(Date.now() - 6 * 86400000)), to: toIso(today) }
    case "30d":
      return { from: toIso(new Date(Date.now() - 29 * 86400000)), to: toIso(today) }
    case "month":
      return {
        from: toIso(new Date(today.getFullYear(), today.getMonth(), 1)),
        to: toIso(today),
      }
    case "year":
      return {
        from: toIso(new Date(today.getFullYear(), 0, 1)),
        to: toIso(today),
      }
    default:
      return { from: null, to: null }
  }
}

export function Dashboard() {
  const navigate = useNavigate()
  const [preset, setPreset] = useState<Preset>("all")
  const [customFrom, setCustomFrom] = useState("")
  const [customTo, setCustomTo] = useState("")
  const [granularity, setGranularity] = useState<"month" | "week">("month")

  const range = useMemo(
    () =>
      preset === "custom"
        ? {
            from: customFrom || null,
            to: customTo || null,
          }
        : presetRange(preset),
    [preset, customFrom, customTo]
  )

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["dashboard", range.from, range.to, granularity],
    queryFn: () => api.dashboard({ ...range, granularity }),
    placeholderData: keepPreviousData,
  })

  const periodLabel =
    preset === "all"
      ? ""
      : preset === "custom"
        ? [range.from, range.to].filter(Boolean).join(" — ")
        : PRESET_LABELS[preset]

  if (isLoading)
    return (
      <div className="flex justify-center py-10">
        <LoadingNote />
      </div>
    )
  if (isError || !data) return <p>Failed to load data.</p>

  if (!data.totals.music_listens) {
    return (
      <div className="flex flex-col gap-3">
        <h1 className="text-lg font-bold text-black">Dashboard</h1>
        <Alert>
          <AlertDescription>
            No data{periodLabel && ` for the period (${periodLabel})`}. First
            import your history and run the music filter.
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const timeline = data.timeline.map(([m, v]) => ({ bucket: m, listens: v }))
  const hours = data.by_hour.map(([h, v]) => ({ hour: `${h}:00`, listens: v }))
  const weekdays = data.by_weekday.map(([d, v]) => ({ day: d, listens: v }))

  return (
      <div
      className={`flex flex-col gap-3 transition-opacity ${
        isFetching ? "pointer-events-none opacity-60" : ""
      }`}
    >
      <h1 className="text-lg font-bold text-black">Dashboard</h1>

      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={preset}
          onValueChange={(v) => setPreset(v as Preset)}
        >
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Period" />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(PRESET_LABELS) as Preset[]).map((p) => (
              <SelectItem key={p} value={p}>
                {PRESET_LABELS[p]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {preset === "custom" && (
          <>
            <Input
              type="date"
              className="w-40"
              value={customFrom}
              max={customTo || undefined}
              onChange={(e) => setCustomFrom(e.target.value)}
            />
            <span className="text-muted-foreground text-sm">—</span>
            <Input
              type="date"
              className="w-40"
              value={customTo}
              min={customFrom || undefined}
              onChange={(e) => setCustomTo(e.target.value)}
            />
          </>
        )}
        {periodLabel && (
          <span className="text-muted-foreground text-sm">
            Period: {periodLabel}
          </span>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Top artists</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Artist</TableHead>
                  <TableHead>plays</TableHead>
                  <TableHead>tracks</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.top_artists.map((a, i) => (
                  <TableRow
                    key={a.channel}
                    className="cursor-pointer"
                    onClick={() => navigate(artistPath(a.channel))}
                  >
                    <TableData className="text-muted-foreground tabular-nums">
                      {i + 1}
                    </TableData>
                    <TableData>
                      <span className="hover:underline">{a.channel}</span>
                    </TableData>
                    <TableData className="tabular-nums">{a.plays}</TableData>
                    <TableData className="tabular-nums">{a.tracks}</TableData>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Top tracks</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead>plays</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.top_tracks.map((t, i) => (
                  <TableRow
                    key={t.video_id}
                    className="cursor-pointer"
                    onClick={(e) => {
                      if (
                        e.target instanceof HTMLElement &&
                        e.target.closest("a")
                      )
                        return;
                      navigate(`/track/${t.video_id}`);
                    }}
                  >
                    <TableData className="text-muted-foreground tabular-nums">
                      {i + 1}
                    </TableData>
                    <TableData className="max-w-[22rem] truncate">
                      <span className="hover:underline">{t.title}</span>
                      <Link
                        to={artistPath(t.artist ?? t.channel)}
                        className="text-muted-foreground block truncate text-xs hover:underline"
                      >
                        {t.channel}
                      </Link>
                    </TableData>
                    <TableData className="tabular-nums">{t.plays}</TableData>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>
            Timeline {granularity === "month" ? "by month" : "by week"}
          </CardTitle>
          <div className="flex gap-1">
            <Button
              size="sm"
              variant={granularity === "week" ? "default" : "outline"}
              onClick={() => setGranularity("week")}
            >
              Weeks
            </Button>
            <Button
              size="sm"
              variant={granularity === "month" ? "default" : "outline"}
              onClick={() => setGranularity("month")}
            >
              Months
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <ChartContainer
            config={chartConfig}
            className="aspect-auto h-72 w-full"
          >
            <LineChart data={timeline}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="bucket"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={24}
              />
              <YAxis width={36} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Line
                dataKey="listens"
                type="linear"
                stroke="var(--chart-1)"
                fill="var(--chart-1)"
                fillOpacity={0.15}
                dot={false}
                strokeWidth={1}
              />
            </LineChart>
          </ChartContainer>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>By hour of day</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartContainer
              config={chartConfig}
              className="aspect-auto h-56 w-full"
            >
              <BarChart data={hours}>
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="hour"
                  tickLine={false}
                  axisLine={false}
                  tickMargin={8}
                  minTickGap={16}
                />
                <YAxis width={36} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="listens" fill="var(--chart-2)" />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>By day of week</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartContainer
              config={chartConfig}
              className="aspect-auto h-56 w-full"
            >
              <BarChart data={weekdays}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="day" tickLine={false} axisLine={false} />
                <YAxis width={36} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="listens" fill="var(--chart-4)" />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
