import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { TrendingDown, TrendingUp } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/lib/api";
import { languageLabel } from "@/lib/track";
import { artistPath, cn, tracksPath } from "@/lib/utils";
import { LoadingNote } from "@/components/LoadingNote";
import { TrackRow, TrackTable } from "@/components/TrackTable";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const chartConfig = {
  listens: { label: "plays" },
  happy: { label: "Happy" },
  sad: { label: "Sad" },
  relaxed: { label: "Relaxed" },
  party: { label: "Party" },
}

const MOOD_LINES = [
  { key: "happy", label: "Happy", color: "var(--chart-2)" },
  { key: "sad", label: "Sad", color: "var(--chart-3)" },
  { key: "relaxed", label: "Relaxed", color: "var(--chart-4)" },
  { key: "party", label: "Party", color: "var(--chart-5)" },
] as const;
type MoodKey = (typeof MOOD_LINES)[number]["key"];

const CTX_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem_11rem] items-center gap-1.5 px-1.5"

const DISC_ARTIST_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_5.5rem] items-center gap-1.5 px-1.5"

const DISC_TRACK_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem] items-center gap-1.5 px-1.5";

const MOOD_LABELS: Record<string, string> = {
  happy: "Happy",
  sad: "Sad",
  relaxed: "Relaxed",
  aggressive: "Aggressive",
  electronic: "Electronic",
  acoustic: "Acoustic",
  party: "Party",
  epic: "Epic",
  dark: "Dark",
  romantic: "Romantic",
  atmospheric: "Atmospheric",
};

const PIE_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

type Preset = "all" | "7d" | "30d" | "month" | "year" | "custom";

const PRESET_LABELS: Record<Preset, string> = {
  all: "All time",
  "7d": "7 days",
  "30d": "30 days",
  month: "This month",
  year: "This year",
  custom: "Custom range",
};

function toIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function presetRange(preset: Preset): {
  from: string | null;
  to: string | null;
} {
  const today = new Date();
  switch (preset) {
    case "7d":
      return {
        from: toIso(new Date(Date.now() - 6 * 86400000)),
        to: toIso(today),
      };
    case "30d":
      return {
        from: toIso(new Date(Date.now() - 29 * 86400000)),
        to: toIso(today),
      };
    case "month":
      return {
        from: toIso(new Date(today.getFullYear(), today.getMonth(), 1)),
        to: toIso(today),
      };
    case "year":
      return {
        from: toIso(new Date(today.getFullYear(), 0, 1)),
        to: toIso(today),
      };
    default:
      return { from: null, to: null };
  }
}

function pct(part: number, total: number): number {
  return total > 0 ? Math.round((part / total) * 100) : 0;
}

function fmtNum(n: number): string {
  return n.toLocaleString("en-US")
}

function Delta({ value, prev }: { value: number; prev: number | null }) {
  if (prev == null || prev === 0 || value === prev) return null;
  const p = Math.round(((value - prev) / prev) * 100);
  if (!Number.isFinite(p)) return null;
  const up = p > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-medium",
        up ? "text-emerald-600" : "text-red-600",
      )}
      title={`previous period: ${fmtNum(prev)}`}
    >
      {up ? (
        <TrendingUp className="size-3" />
      ) : (
        <TrendingDown className="size-3" />
      )}
      {Math.abs(p)}%
    </span>
  );
}

function KpiStat({
  title,
  value,
  prev,
}: {
  title: string;
  value: number;
  prev: number | null;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-muted-foreground text-xs">{title}</span>
      <span className="text-sm font-bold tabular-nums">{fmtNum(value)}</span>
      <Delta value={value} prev={prev} />
    </div>
  );
}

function FeatureRow({
  label,
  value,
  max,
  display,
}: {
  label: string;
  value: number;
  max: number;
  display: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-muted-foreground w-28 shrink-0 text-sm">
        {label}
      </span>
      <Progress value={(value / max) * 100} className="h-2" />
      <span className="w-14 shrink-0 text-right text-sm font-medium tabular-nums">
        {display}
      </span>
    </div>
  );
}

export function Dashboard() {
  const navigate = useNavigate();
  const [preset, setPreset] = useState<Preset>("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [granularity, setGranularity] = useState<"month" | "week">("month")
  const [activeMood, setActiveMood] = useState<MoodKey | null>(null);
  const [ctxLimit, setCtxLimit] = useState(8)
  const [discArtistsLimit, setDiscArtistsLimit] = useState(8)
  const [discTracksLimit, setDiscTracksLimit] = useState(8);

  const range = useMemo(
    () =>
      preset === "custom"
        ? {
            from: customFrom || null,
            to: customTo || null,
          }
        : presetRange(preset),
    [preset, customFrom, customTo],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["dashboard", range.from, range.to, granularity],
    queryFn: () => api.dashboard({ ...range, granularity }),
    placeholderData: keepPreviousData,
  });

  const { data: ctx } = useQuery({
    queryKey: ["context-recs", ctxLimit, range.from, range.to],
    queryFn: () => api.contextRecs(ctxLimit, range.from, range.to),
    placeholderData: keepPreviousData,
    staleTime: 10 * 60 * 1000,
  })

  const { data: disc } = useQuery({
    queryKey: [
      "discoveries",
      discArtistsLimit,
      discTracksLimit,
      range.from,
      range.to,
    ],
    queryFn: () =>
      api.discoveries(discArtistsLimit, discTracksLimit, range.from, range.to),
    placeholderData: keepPreviousData,
  });

  const periodLabel =
    preset === "all"
      ? ""
      : preset === "custom"
        ? [range.from, range.to].filter(Boolean).join(" — ")
        : PRESET_LABELS[preset];

  // period controls stay visible in every state (loading / error / empty),
  // so an interval without data can always be changed
  const header = (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 className="text-lg font-bold text-black">Dashboard</h1>
      <Select value={preset} onValueChange={(v) => setPreset(v as Preset)}>
        <SelectTrigger className="w-40">
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
            className="w-36"
            value={customFrom}
            max={customTo || undefined}
            onChange={(e) => setCustomFrom(e.target.value)}
          />
          <span className="text-muted-foreground text-sm">—</span>
          <Input
            type="date"
            className="w-36"
            value={customTo}
            min={customFrom || undefined}
            onChange={(e) => setCustomTo(e.target.value)}
          />
        </>
      )}
    </div>
  );

  if (isLoading)
    return (
      <div className="flex flex-col gap-3">
        {header}
        <div className="flex justify-center py-10">
          <LoadingNote />
        </div>
      </div>
    );
  if (isError || !data)
    return (
      <div className="flex flex-col gap-3">
        {header}
        <Alert>
          <AlertDescription>Failed to load data.</AlertDescription>
        </Alert>
      </div>
    );

  if (!data.totals.music_listens) {
    return (
      <div className="flex flex-col gap-3">
        {header}
        <Alert>
          <AlertDescription>
            {preset === "all" ? (
              <>
                No data yet. First import your history and run the music
                filter.
              </>
            ) : (
              <>
                No listens in this period
                {periodLabel && ` (${periodLabel})`} — pick another interval
                or switch to all time.
              </>
            )}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const timeline = data.timeline.map(([m, v]) => ({ bucket: m, listens: v }));
  const hours = data.by_hour.map(([h, v]) => ({ hour: `${h}:00`, listens: v }));
  const weekdays = data.by_weekday.map(([d, v]) => ({ day: d, listens: v }));
  const trend = data.mood_trend.map(([b, v]) => ({
    bucket: b,
    happy: v.happy,
    sad: v.sad,
    relaxed: v.relaxed,
    party: v.party,
  }));
  const moodRadar = Object.entries(data.mood_profile).map(([m, v]) => ({
    mood: MOOD_LABELS[m] ?? m,
    value: v,
  }));
  const genres = data.genre_distribution.map((g) => ({
    name: g.name,
    listens: g.listens,
  }));
  const keys = data.by_key.map(([k, v]) => ({ name: k, listens: v }));
  const languages = data.language_distribution.map(([code, listens]) => ({
    code,
    name: languageLabel(code),
    listens,
  }));
  const vocalPie = [
    { name: "Vocal", value: data.vocal_split.vocal },
    { name: "Instrumental", value: data.vocal_split.instrumental },
  ];

  const discoveryLabel =
    preset === "all" ? "last 30 days" : periodLabel || "period";
  const { kpi } = data;
  const { avg_features: avg, vocal_split: vocal } = data;

  const WEEKDAY_NAMES = [
    "Mondays",
    "Tuesdays",
    "Wednesdays",
    "Thursdays",
    "Fridays",
    "Saturdays",
    "Sundays",
  ];

  return (
    <div className="flex flex-col gap-3">
      {header}
      <div
        className={`flex flex-col gap-3 transition-opacity ${
          isFetching ? "pointer-events-none opacity-60" : ""
        }`}
      >
        <div className=" flex flex-wrap items-center gap-x-5 gap-y-1">
          <KpiStat
            title="Plays"
            value={kpi.listens.value}
            prev={kpi.listens.prev}
          />
          <KpiStat
            title="Hours"
            value={kpi.hours.value}
            prev={kpi.hours.prev}
          />
          <KpiStat
            title="Artists"
            value={kpi.artists.value}
            prev={kpi.artists.prev}
          />
          <KpiStat
            title="Tracks"
            value={kpi.tracks.value}
            prev={kpi.tracks.prev}
          />
        </div>

      {ctx && ctx.items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>For now</CardTitle>
            <CardDescription>
              tracks you usually play around {String(ctx.hour).padStart(2, "0")}
              :00 on {WEEKDAY_NAMES[ctx.weekday] ?? "this day"} ·{" "}
              {periodLabel || "all time"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <TrackTable
              grid={CTX_GRID}
              extraHead={<span className="text-right">reason</span>}
            >
              {ctx.items.map((it, i) => (
                <TrackRow
                  key={it.track.video_id}
                  videoId={it.track.video_id}
                  title={it.track.title}
                  channel={it.track.channel}
                  artist={it.track.artist}
                  plays={it.plays}
                  info={it.info}
                  index={i}
                  grid={CTX_GRID}
                  extra={
                    <span className="flex items-center justify-end gap-1 overflow-hidden">
                      {it.reason.split(", ").map((r) => {
                        // color by reason type: hour pattern, weekday
                        // pattern, or the generic fallback
                        const color = r.startsWith("often at")
                          ? "var(--chart-1)"
                          : r.startsWith("on ")
                            ? "var(--chart-4)"
                            : "";
                        return (
                          <Badge
                            key={r}
                            variant={color ? "default" : "secondary"}
                            className="max-w-[11rem] px-1.5 py-0 text-xs font-normal"
                            style={
                              color ? { backgroundColor: color } : undefined
                            }
                          >
                            <span className="truncate">{r}</span>
                          </Badge>
                        );
                      })}
                    </span>
                  }
                />
              ))}
            </TrackTable>
            {ctx.items.length < ctx.total && (
              <div className="mt-2 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCtxLimit((l) => l + 8)}
                >
                  Show more ({fmtNum(ctx.total - ctx.items.length)} left)
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Discoveries</CardTitle>
          <CardDescription>
            Artists and tracks heard for the first time ({discoveryLabel})
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div>
            <p className="mb-2 text-sm">
              <span className="font-bold">
                {fmtNum(disc?.new_artists_total ?? 0)}
              </span>{" "}
              <span className="text-muted-foreground">new artists</span>
            </p>
            <div className="border border-[#999999]">
              <div
                className={cn(
                  DISC_ARTIST_GRID,
                  "h-12 border-b border-[#999999] bg-[#eeeeee] text-xs font-bold whitespace-nowrap text-black"
                )}
              >
                <span>#</span>
                <span />
                <span>Artist</span>
                <span className="text-right">plays</span>
              </div>
              {(disc?.top_new_artists ?? []).map((a, i) => (
                <div
                  key={a.name}
                  className={cn(
                    DISC_ARTIST_GRID,
                    "h-12 cursor-pointer border-b border-[#e0e0e0] hover:bg-[#ffffcc]"
                  )}
                  onClick={() => navigate(artistPath(a.name))}
                >
                  <span className="text-muted-foreground tabular-nums">
                    {i + 1}
                  </span>
                  {a.top_video_id ? (
                    <img
                      src={`https://i.ytimg.com/vi/${a.top_video_id}/default.jpg`}
                      alt=""
                      loading="lazy"
                      className="h-10 w-10 border border-[#999999] object-cover"
                    />
                  ) : (
                    <span className="block h-10 w-10 border border-[#e0e0e0] bg-[#eeeeee]" />
                  )}
                  <span className="truncate text-sm" title={a.name}>
                    {a.name}
                  </span>
                  <span className="text-right text-sm tabular-nums">
                    {fmtNum(a.plays)}
                  </span>
                </div>
              ))}
              {disc && disc.top_new_artists.length === 0 && (
                <p className="text-muted-foreground px-2 py-3 text-center text-xs">
                  No new artists in this period.
                </p>
              )}
            </div>
            {disc && discArtistsLimit < Math.min(50, disc.new_artists_total) && (
              <div className="mt-2 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setDiscArtistsLimit((l) => l + 8)}
                >
                  Show more artists (
                  {fmtNum(
                    Math.min(disc.new_artists_total, 50) -
                      disc.top_new_artists.length
                  )}{" "}
                  left)
                </Button>
              </div>
            )}
          </div>

          <div className="mt-4">
            <p className="mb-2 text-sm">
              <span className="font-bold">
                {fmtNum(disc?.new_tracks_total ?? 0)}
              </span>{" "}
              <span className="text-muted-foreground">new tracks</span>
            </p>
            <TrackTable grid={DISC_TRACK_GRID}>
              {(disc?.top_new_tracks ?? []).map((t, i) => (
                <TrackRow
                  key={t.video_id}
                  videoId={t.video_id}
                  title={t.title}
                  channel={t.channel}
                  artist={t.artist}
                  plays={t.plays}
                  info={t.info}
                  index={i}
                  grid={DISC_TRACK_GRID}
                />
              ))}
              {disc && disc.top_new_tracks.length === 0 && (
                <p className="text-muted-foreground px-2 py-3 text-center text-xs">
                  No new tracks in this period.
                </p>
              )}
            </TrackTable>
            {disc && discTracksLimit < Math.min(50, disc.new_tracks_total) && (
              <div className="mt-2 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setDiscTracksLimit((l) => l + 8)}
                >
                  Show more tracks (
                  {fmtNum(
                    Math.min(disc.new_tracks_total, 50) -
                      disc.top_new_tracks.length
                  )}{" "}
                  left)
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Timeline</CardTitle>
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

      <Card>
        <CardHeader>
          <CardTitle>Mood over time</CardTitle>
          <CardDescription>
            Average Essentia moods of analyzed listens,{" "}
            {granularity === "month" ? "by month" : "by week"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ChartContainer
            config={chartConfig}
            className="aspect-auto h-56 w-full"
          >
            <LineChart data={trend}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="bucket"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={24}
              />
              <YAxis domain={[0, 1]} width={32} />
              <ChartTooltip content={<ChartTooltipContent />} />
              {MOOD_LINES.map((m) => (
                <Line
                  key={m.key}
                  dataKey={m.key}
                  type="linear"
                  stroke={m.color}
                  dot={false}
                  strokeWidth={1.5}
                  strokeOpacity={
                    activeMood === null || activeMood === m.key ? 1 : 0.15
                  }
                />
              ))}
            </LineChart>
          </ChartContainer>
          <div className="flex items-center justify-center gap-4 pt-3">
            {MOOD_LINES.map((m) => {
              const dimmed = activeMood !== null && activeMood !== m.key;
              return (
                <button
                  key={m.key}
                  type="button"
                  onClick={() =>
                    setActiveMood(activeMood === m.key ? null : m.key)
                  }
                  title={
                    activeMood === m.key
                      ? "show all moods"
                      : "highlight this mood"
                  }
                  className={cn(
                    "flex cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-xs text-foreground",
                    dimmed ? "opacity-40" : "",
                  )}
                >
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                    style={{ backgroundColor: m.color }}
                  />
                  {m.label}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Mood profile</CardTitle>
            <CardDescription>
              Average mood of analyzed listens ({Math.round(avg.coverage * 100)}
              % coverage)
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ChartContainer
              config={{ value: { label: "mood" } }}
              className="mx-auto aspect-square max-h-72 w-full max-w-sm"
            >
              <RadarChart data={moodRadar} outerRadius="75%">
                <PolarGrid />
                <PolarAngleAxis dataKey="mood" tick={{ fontSize: 10 }} />
                <PolarRadiusAxis tick={false} axisLine={false} />
                <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                <Radar
                  dataKey="value"
                  stroke="var(--chart-1)"
                  fill="var(--chart-1)"
                  fillOpacity={0.3}
                />
              </RadarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Average sound</CardTitle>
            <CardDescription>
              Weighted by plays ({Math.round(avg.coverage * 100)}% coverage)
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col justify-center gap-3">
            {avg.tempo != null && (
              <FeatureRow
                label="Tempo"
                value={Math.min(avg.tempo, 180)}
                max={180}
                display={`${Math.round(avg.tempo)} BPM`}
              />
            )}
            {avg.energy != null && (
              <FeatureRow
                label="Energy"
                value={avg.energy}
                max={1}
                display={`${Math.round(avg.energy * 100)}%`}
              />
            )}
            {avg.danceability != null && (
              <FeatureRow
                label="Danceability"
                value={avg.danceability}
                max={1}
                display={`${Math.round(avg.danceability * 100)}%`}
              />
            )}
            {avg.acousticness != null && (
              <FeatureRow
                label="Acousticness"
                value={avg.acousticness}
                max={1}
                display={`${Math.round(avg.acousticness * 100)}%`}
              />
            )}
            {avg.brightness != null && (
              <FeatureRow
                label="Brightness"
                value={avg.brightness}
                max={1}
                display={`${Math.round(avg.brightness * 100)}%`}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Genres by plays</CardTitle>
            <CardDescription>
              Top {genres.length}, Essentia tags (
              {Math.round(data.genre_coverage * 100)}% coverage) — click to
              filter tracks
            </CardDescription>
          </CardHeader>
          <CardContent>
            {genres.length === 0 ? (
              <p className="text-muted-foreground py-8 text-center text-sm">
                No analyzed tracks in this period.
              </p>
            ) : (
              <ChartContainer
                config={chartConfig}
                className="aspect-auto h-72 w-full"
              >
                <BarChart
                  data={genres}
                  layout="vertical"
                  margin={{ right: 16 }}
                >
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={200}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 11 }}
                  />
                  <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                  <Bar
                    dataKey="listens"
                    fill="var(--chart-1)"
                    radius={[0, 3, 3, 0]}
                    className="cursor-pointer"
                    onClick={(d: { payload?: { name?: string } }) =>
                      d?.payload?.name &&
                      navigate(tracksPath({ genre: d.payload.name }))
                    }
                  />
                </BarChart>
              </ChartContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Keys</CardTitle>
            <CardDescription>
              Most common keys of analyzed listens — click to filter tracks
            </CardDescription>
          </CardHeader>
          <CardContent>
            {keys.length === 0 ? (
              <p className="text-muted-foreground py-8 text-center text-sm">
                No analyzed tracks in this period.
              </p>
            ) : (
              <ChartContainer
                config={chartConfig}
                className="aspect-auto h-72 w-full"
              >
                <BarChart data={keys} layout="vertical" margin={{ right: 16 }}>
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={80}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 11 }}
                  />
                  <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                  <Bar
                    dataKey="listens"
                    fill="var(--chart-2)"
                    radius={[0, 3, 3, 0]}
                    className="cursor-pointer"
                    onClick={(d: { payload?: { name?: string } }) =>
                      d?.payload?.name &&
                      navigate(tracksPath({ key: d.payload.name }))
                    }
                  />
                </BarChart>
              </ChartContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Vocal vs instrumental</CardTitle>
            <CardDescription>
              {Math.round(vocal.coverage * 100)}% of listens whisper-checked
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center gap-2">
              <ChartContainer
                config={chartConfig}
                className="aspect-square max-h-52 w-full max-w-[13rem]"
              >
                <PieChart>
                  <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                  <Pie
                    data={vocalPie}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={45}
                    outerRadius={72}
                    paddingAngle={2}
                    strokeWidth={0}
                    className="cursor-pointer"
                    onClick={(d: { payload?: { name?: string } }) =>
                      d?.payload?.name === "Instrumental" &&
                      navigate(tracksPath({ instrumental: "1" }))
                    }
                  >
                    <Cell fill="var(--chart-1)" />
                    <Cell fill="var(--chart-4)" />
                  </Pie>
                </PieChart>
              </ChartContainer>
              <div className="text-muted-foreground flex gap-4 text-xs">
                <span>
                  Vocal{" "}
                  <b className="text-foreground tabular-nums">
                    {pct(vocal.vocal, vocal.vocal + vocal.instrumental)}%
                  </b>
                </span>
                <button
                  className="hover:text-foreground cursor-pointer"
                  onClick={() => navigate(tracksPath({ instrumental: "1" }))}
                >
                  Instrumental{" "}
                  <b className="text-foreground tabular-nums">
                    {pct(vocal.instrumental, vocal.vocal + vocal.instrumental)}%
                  </b>
                </button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Languages</CardTitle>
            <CardDescription>
              By plays of tracks with lyrics — click to filter tracks
            </CardDescription>
          </CardHeader>
          <CardContent>
            {languages.length === 0 ? (
              <p className="text-muted-foreground py-8 text-center text-sm">
                No lyrics in this period.
              </p>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <ChartContainer
                  config={chartConfig}
                  className="aspect-square max-h-52 w-full max-w-[13rem]"
                >
                  <PieChart>
                    <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                    <Pie
                      data={languages}
                      dataKey="listens"
                      nameKey="name"
                      innerRadius={45}
                      outerRadius={72}
                      paddingAngle={2}
                      strokeWidth={0}
                      className="cursor-pointer"
                      onClick={(d: { payload?: { code?: string } }) =>
                        d?.payload?.code &&
                        navigate(tracksPath({ language: d.payload.code }))
                      }
                    >
                      {languages.map((_, i) => (
                        <Cell
                          key={i}
                          fill={PIE_COLORS[i % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                  </PieChart>
                </ChartContainer>
                <div className="flex flex-wrap justify-center gap-x-3 gap-y-1">
                  {languages.map((l, i) => (
                    <button
                      key={l.code}
                      className="text-muted-foreground hover:text-foreground flex cursor-pointer items-center gap-1 text-xs"
                      onClick={() => navigate(tracksPath({ language: l.code }))}
                    >
                      <span
                        className="size-2 shrink-0 rounded-[2px]"
                        style={{
                          backgroundColor: PIE_COLORS[i % PIE_COLORS.length],
                        }}
                      />
                      {l.name}{" "}
                      <b className="text-foreground tabular-nums">
                        {pct(
                          l.listens,
                          languages.reduce((s, x) => s + x.listens, 0),
                        )}
                        %
                      </b>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

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
    </div>
  );
}
