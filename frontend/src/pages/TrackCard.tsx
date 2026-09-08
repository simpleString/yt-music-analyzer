import { useEffect, useState, type ReactNode } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import {
  Cell,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
} from "recharts";

import { api, type YtmSimilarTrack } from "@/lib/api";
import { techTooltip } from "@/lib/track";
import { artistPath, cn } from "@/lib/utils";
import { LoadingNote } from "@/components/LoadingNote";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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

const MOOD_LABELS: [string, string][] = [
  ["mood_happy", "Happy"],
  ["mood_sad", "Sad"],
  ["mood_relaxed", "Calm"],
  ["mood_aggressive", "Aggressive"],
  ["mood_electronic", "Electronic"],
  ["mood_acoustic", "Acoustic"],
  ["mood_party", "Party"],
  ["mood_epic", "Epic"],
  ["mood_dark", "Dark"],
  ["mood_romantic", "Romantic"],
  ["mood_atmospheric", "Atmospheric"],
];

const FEATURE_LABELS: [string, string][] = [
  ["energy", "Energy"],
  ["danceability", "Danceability"],
  ["acousticness", "Acousticness"],
  ["brightness", "Brightness"],
  ["dynamics", "Dynamics"],
  ["percussive", "Percussion"],
];

const PIE_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

const MATCH_COLORS: Record<string, string> = {
  "by timbre": "var(--chart-1)",
  "by rhythm": "var(--chart-2)",
  "by harmony": "var(--chart-3)",
  "by character": "var(--chart-4)",
  "by instruments": "var(--chart-5)",
  "by genre": "var(--chart-1)",
  "by lyrics": "var(--chart-3)",
  "by themes": "var(--chart-2)",
  essentia: "var(--chart-4)",
};

type SimilarItem = {
  track: { video_id: string; title: string; channel: string; artist?: string };
  distance: number;
  match?: string;
  tempo?: number | null;
};

function fmtDuration(sec: number | null): string {
  if (!sec) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <span>
      <span className="text-muted-foreground">{label}: </span>
      <span className="font-medium">{value}</span>
    </span>
  );
}

function RadarBlock({
  data,
  color,
}: {
  data: { axis: string; value: number }[];
  color: string;
}) {
  return (
    <ChartContainer
      config={{ value: { label: "value" } }}
      className="aspect-auto h-48 w-full"
    >
      <RadarChart data={data}>
        <PolarGrid />
        <PolarAngleAxis dataKey="axis" />
        <ChartTooltip content={<ChartTooltipContent />} />
        <Radar
          dataKey="value"
          stroke={color}
          fill={color}
          fillOpacity={0.35}
        />
      </RadarChart>
    </ChartContainer>
  );
}

function DonutBlock({
  data,
  unit,
  legendCols = 1,
}: {
  data: { name: string; value: number }[];
  unit: string;
  legendCols?: 1 | 2;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div className="flex flex-col items-center gap-2 sm:flex-row sm:items-center sm:gap-4">
      <div className="relative shrink-0">
        <ChartContainer
          config={{ value: { label: "weight" } }}
          className="aspect-auto h-40 w-40"
        >
          <PieChart>
            <ChartTooltip content={<ChartTooltipContent />} />
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius="55%"
              outerRadius="85%"
              paddingAngle={2}
            >
              {data.map((g, i) => (
                <Cell key={g.name} fill={PIE_COLORS[i % PIE_COLORS.length]} />
              ))}
            </Pie>
          </PieChart>
        </ChartContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold text-black">{data.length}</span>
          <span className="text-muted-foreground text-xs">{unit}</span>
        </div>
      </div>
      <ul
        className={`grid flex-1 gap-x-6 gap-y-1 ${legendCols === 2 ? "sm:grid-cols-2" : ""}`}
      >
        {data.map((g, i) => (
          <li key={g.name} className="flex items-center gap-1.5 text-xs">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 border border-[#666666]"
              style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
            />
            <span className="min-w-0 flex-1 truncate">{g.name}</span>
            <span className="tabular-nums">
              {Math.round((g.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SimilarRow({
  item,
  index,
  maxD,
  showMatch,
  onOpen,
}: {
  item: SimilarItem;
  index: number;
  maxD: number;
  showMatch: boolean;
  onOpen: () => void;
}) {
  // skewed scale: everything in recommendations is already
  // "similar", so worst of the top >= 50%, best -> 100%
  const sim = maxD > 0 ? 0.5 + 0.5 * (1 - item.distance / maxD) : 1;
  const pct = Math.round(sim * 100);
  const hue = 45 + (142 - 45) * ((sim - 0.5) * 2);
  const extras: string[] = [];
  if (item.tempo != null) extras.push(`BPM: ${Math.round(item.tempo)}`);
  extras.push(`distance: ${item.distance.toFixed(3)} (lower = more similar)`);
  if (showMatch && item.match) extras.push(`match: ${item.match}`);
  return (
    <li
      className="hover:bg-[#ffffcc] flex cursor-pointer items-center gap-1.5 border-b border-[#e0e0e0] px-1 py-1 last:border-b-0"
      title={techTooltip(item.track, extras)}
      onClick={(e) => {
        if (e.target instanceof HTMLElement && e.target.closest("a")) return;
        onOpen();
      }}
    >
      <span className="text-muted-foreground w-5 shrink-0 text-right text-xs tabular-nums">
        {index + 1}
      </span>
      <a
        href={`https://www.youtube.com/watch?v=${item.track.video_id}`}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0"
      >
        <img
          src={`https://i.ytimg.com/vi/${item.track.video_id}/mqdefault.jpg`}
          alt=""
          loading="lazy"
          className="h-8 w-[52px] shrink-0 border border-[#999999] object-cover"
        />
      </a>
      <span className="min-w-0 flex-1">
        <a
          href={`https://www.youtube.com/watch?v=${item.track.video_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="block truncate text-sm hover:underline max-w-fit"
          title={item.track.title}
        >
          {item.track.title}
        </a>
        <Link
          to={artistPath(item.track.artist ?? item.track.channel)}
          className="text-muted-foreground block truncate text-xs hover:underline max-w-fit"
        >
          {item.track.channel}
        </Link>
      </span>
      {showMatch && item.match ? (
        <Badge
          variant="outline"
          className="shrink-0 text-xs"
          style={{
            borderColor: MATCH_COLORS[item.match] ?? "var(--chart-5)",
            color: MATCH_COLORS[item.match] ?? "var(--chart-5)",
          }}
        >
          {item.match}
        </Badge>
      ) : null}
      <span className="w-8 shrink-0 text-right text-xs tabular-nums">
        {pct}%
      </span>
      <span className="h-2.5 w-24 shrink-0 border border-[#999999] bg-[#eeeeee]">
        <span
          className="block h-full"
          style={{ width: `${pct}%`, background: `hsl(${hue} 70% 45%)` }}
        />
      </span>
      <span
        className="text-muted-foreground w-10 shrink-0 text-right text-xs tabular-nums"
        title="distance (lower = more similar)"
      >
        {item.distance.toFixed(3)}
      </span>
    </li>
  );
}

const YTM_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem_4rem_3.5rem_4.5rem] items-center gap-1.5 px-1.5";

function YtmRow({
  item,
  index,
  onOpen,
  hasHistory,
}: {
  item: YtmSimilarTrack;
  index: number;
  onOpen: () => void;
  hasHistory: boolean | undefined;
}) {
  const info = item.in_history ? (item.info ?? null) : null;
  const extras: string[] = [];
  if (info) {
    if (info.genre) extras.push(`genre: ${info.genre}`);
    extras.push(
      `first: ${info.first_listen ?? "—"} · last: ${info.last_listen ?? "—"}`,
    );
  }
  const tooltip = info
    ? techTooltip(
        {
          tempo: info.tempo,
          energy: info.energy,
          danceability: info.danceability,
          acousticness: info.acousticness,
          language: info.language,
        },
        extras,
      )
    : "";
  return (
    <div
      className={cn(
        YTM_GRID,
        "h-12 min-w-[62rem] hover:bg-[#ffffcc] border-b border-[#e0e0e0]",
        hasHistory ? "cursor-pointer" : "",
      )}
      title={tooltip || undefined}
      onClick={(e) => {
        if (e.target instanceof HTMLElement && e.target.closest("a")) return;
        onOpen();
      }}
    >
      <span className="text-muted-foreground tabular-nums">{index + 1}</span>
      <a
        href={`https://www.youtube.com/watch?v=${item.video_id}`}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0"
      >
        <img
          src={`https://i.ytimg.com/vi/${item.video_id}/mqdefault.jpg`}
          alt=""
          loading="lazy"
          className="h-10 w-[71px] shrink-0 border border-[#999999] object-cover"
        />
      </a>
      <span className="min-w-0">
        <a
          href={`https://www.youtube.com/watch?v=${item.video_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="block truncate text-sm hover:underline max-w-fit"
          title={item.title}
        >
          {item.title}
        </a>
        {item.artist ? (
          <Link
            to={artistPath(item.artist)}
            className="text-muted-foreground block truncate text-xs hover:underline max-w-fit"
          >
            {item.artist}
          </Link>
        ) : (
          <span className="text-muted-foreground block truncate text-xs">
            {"\u00a0"}
          </span>
        )}
      </span>
      <span className="flex min-w-0 flex-col items-start gap-0.5 overflow-hidden">
        {info?.cluster ? (
          <Badge variant="outline" className="max-w-full">
            <span className="truncate">{info.cluster}</span>
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
        {(info?.genre || info?.language) && (
          <Badge variant="secondary" className="max-w-full font-normal">
            <span className="truncate">
              {[info?.genre, info?.language].filter(Boolean).join(" · ")}
            </span>
          </Badge>
        )}
      </span>
      <span className="text-right text-sm tabular-nums">
        {info?.tempo != null ? Math.round(info.tempo) : "—"}
      </span>
      <span className="text-muted-foreground text-right text-sm tabular-nums">
        {info?.energy != null ? info.energy.toFixed(2) : "—"}
      </span>
      <span className="text-muted-foreground text-right text-sm tabular-nums">
        {info?.danceability != null ? info.danceability.toFixed(2) : "—"}
      </span>
      <span className="text-muted-foreground text-right text-sm tabular-nums">
        {info?.acousticness != null ? info.acousticness.toFixed(2) : "—"}
      </span>
      <span className="text-right text-sm tabular-nums">
        {info ? info.play_count : "—"}
      </span>
      <span
        className="text-right text-sm tabular-nums"
        title={
          info?.match != null
            ? "audio similarity to this track (essentia tags)"
            : undefined
        }
      >
        {info?.match != null ? `${info.match}%` : "—"}
      </span>
      <span
        className="text-muted-foreground text-right text-sm tabular-nums"
        title="essentia distance to this track (lower = more similar)"
      >
        {info?.match != null ? ((100 - info.match) / 100).toFixed(3) : "—"}
      </span>
      <span className="text-center text-xs">
        {item.in_history ? (
          <span
            className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-green-600 text-[11px] font-bold text-white"
            title="In your history"
          >
            ✓
          </span>
        ) : (
          ""
        )}
      </span>
      <span className="text-muted-foreground text-right text-sm tabular-nums">
        {fmtDuration(info?.duration ?? item.duration)}
      </span>
    </div>
  );
}

function YtmTable({
  items,
  onOpen,
}: {
  items: YtmSimilarTrack[];
  onOpen: (item: YtmSimilarTrack) => void;
}) {
  return (
    <div className="overflow-x-auto border border-[#999999]">
      <div>
        <div
          className={cn(
            YTM_GRID,
            "h-12 min-w-[62rem] border-b border-[#999999] bg-[#eeeeee] text-xs font-bold text-black whitespace-nowrap",
          )}
        >
          <span>#</span>
          <span />
          <span>Track</span>
          <span>Mood</span>
          <span className="text-right">BPM</span>
          <span className="text-right">energy</span>
          <span className="text-right">dance.</span>
          <span className="text-right">acoust.</span>
          <span className="text-right">plays</span>
          <span className="text-right">match</span>
          <span className="text-right">dist.</span>
          <span className="text-center">hist.</span>
          <span className="text-right">length</span>
        </div>
        <div>
          {items.map((s, i) => (
            <YtmRow
              key={`${s.video_id}-${i}`}
              item={s}
              index={i}
              onOpen={() => onOpen(s)}
              hasHistory={s.in_history}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function TrackCard() {
  const { videoId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showLyrics, setShowLyrics] = useState(false);
  // on-demand analysis of an un-analyzed track
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState("");

  // remember the last opened track: the tracks list scrolls back to it
  // on browser Back
  useEffect(() => {
    if (videoId) sessionStorage.setItem("tracks-open-track", videoId);
  }, [videoId]);

  const {
    data: t,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["track", videoId],
    queryFn: () => api.trackDetail(videoId!),
    enabled: !!videoId,
  });

  const { data: lyrics } = useQuery({
    queryKey: ["lyrics", videoId],
    queryFn: () => api.trackLyrics(videoId!),
    enabled: !!videoId && !!t?.has_lyrics,
  });

  const { data: recs } = useQuery({
    queryKey: ["recommendations", videoId],
    queryFn: () => api.recommendations(videoId!),
    enabled: !!videoId,
  });

  const { data: ytmData } = useQuery({
    queryKey: ["youtube-similar", videoId],
    queryFn: () => api.youtubeSimilar(videoId!),
    enabled: !!videoId,
    staleTime: 5 * 60 * 1000,
  });
  const ytmItems = ytmData?.enabled ? ytmData.similar : [];
  const [ytmShown, setYtmShown] = useState(10);
  useEffect(() => setYtmShown(10), [videoId]);
  const ytmVisible = ytmItems.slice(0, ytmShown);

  const essentiaQuery = useInfiniteQuery({
    queryKey: ["essentia-recommendations", videoId],
    queryFn: ({ pageParam = 0 }) =>
      api.recommendationsEssentia(videoId!, pageParam, 10),
    initialPageParam: 0,
    enabled: !!videoId,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.similar.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });

  const similarQuery = useInfiniteQuery({
    queryKey: ["similar-recommendations", videoId],
    queryFn: ({ pageParam = 0 }) =>
      api.recommendationsSimilar(videoId!, pageParam, 10),
    initialPageParam: 0,
    enabled: !!videoId,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.similar.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });

  const essentiaItems =
    essentiaQuery.data?.pages.flatMap((p) => p.similar) ?? [];
  const essentiaTotal = essentiaQuery.data?.pages[0]?.total ?? 0;
  const similarItems = similarQuery.data?.pages.flatMap((p) => p.similar) ?? [];
  const similarTotal = similarQuery.data?.pages[0]?.total ?? 0;
  const similarMaxD = similarItems.length
    ? Math.max(...similarItems.map((x) => x.distance))
    : 0;
  const essentiaMaxD = essentiaItems.length
    ? Math.max(...essentiaItems.map((x) => x.distance))
    : 0;

  const analyzeOne = useMutation({
    mutationFn: () => api.analyzeTrack(videoId!),
    onSuccess: () => {
      setAnalyzeError("");
      setAnalyzing(true);
    },
    onError: (e) => {
      setAnalyzing(false);
      setAnalyzeError(e.message);
    },
  });

  const { data: analyzeStatus } = useQuery({
    queryKey: ["analyze-status", videoId],
    queryFn: () => api.analyzeStatus(videoId!),
    enabled: !!videoId && analyzing,
    refetchInterval: 3000,
  });

  useEffect(() => {
    if (!analyzing) return;
    if (analyzeStatus?.status === "done") {
      setAnalyzing(false);
      // fresh features + ytm meta/similar + recommendations everywhere
      queryClient.invalidateQueries();
    } else if (analyzeStatus?.status === "error") {
      setAnalyzing(false);
      setAnalyzeError(analyzeStatus.detail || "analysis failed");
    }
  }, [analyzing, analyzeStatus, queryClient]);

  if (isLoading)
    return (
      <div className="flex justify-center py-10">
        <LoadingNote />
      </div>
    );
  if (isError || !t)
    return (
      <div className="flex flex-col gap-4">
        <Alert variant="destructive">
          <AlertDescription>Track not found.</AlertDescription>
        </Alert>
        <Button
          variant="outline"
          className="w-fit"
          onClick={() => navigate(-1)}
        >
          Back
        </Button>
      </div>
    );

  const moodData = MOOD_LABELS.map(([key, label]) => ({
    axis: label,
    value: (t as unknown as Record<string, number | null>)[key] ?? 0,
  }));
  const featureData = FEATURE_LABELS.map(([key, label]) => ({
    axis: label,
    value: (t as unknown as Record<string, number | null>)[key] ?? 0,
  }));
  const genreData = t.genre_scores.map((g) => ({
    name: g.name,
    value: Math.max(g.score, 0.0001),
  }));
  const instrumentData = t.instrument_scores.map((g) => ({
    name: g.name,
    value: Math.max(g.score, 0.0001),
  }));
  const hasFeatures = t.energy != null || t.tempo != null;

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <Card>
        <CardContent className="flex items-start gap-3">
          <a
            href={`https://www.youtube.com/watch?v=${t.video_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0"
          >
            <img
              src={`https://i.ytimg.com/vi/${t.video_id}/mqdefault.jpg`}
              alt=""
              className="h-[70px] w-auto border border-[#999999]"
              loading="lazy"
            />
          </a>
          <div className="flex min-w-0 flex-1 flex-col justify-center gap-1 overflow-hidden">
            <div className="flex flex-col min-w-0 items-baseline">
              <a
                href={`https://www.youtube.com/watch?v=${t.video_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 min-w-0 flex-1 truncate text-base font-bold"
              >
                {t.title}
              </a>
              <span className="text-muted-foreground min-w-0 shrink-[2] truncate text-xs">
                <Link
                  to={artistPath(t.artist ?? t.channel)}
                  className="hover:underline"
                >
                  {t.channel}
                </Link>
              </span>
            </div>
            <div className="grid grid-cols-2 items-center gap-1">
              <div className="flex flex-wrap gap-1 items-center">
                {t.cluster_name && (
                  <Badge variant="secondary" className="px-1.5 py-0 text-xs">
                    {t.cluster_name}
                  </Badge>
                )}
                {t.topic && (
                  <Badge variant="outline" className="px-1.5 py-0 text-xs">
                    {t.topic}
                  </Badge>
                )}
                {t.language && (
                  <Badge variant="outline" className="px-1.5 py-0 text-xs">
                    {t.language}
                  </Badge>
                )}
                {t.ytm?.album && (
                  <Badge variant="outline" className="px-1.5 py-0 text-xs">
                    {t.ytm.album}
                    {t.ytm.year ? ` · ${t.ytm.year}` : ""}
                  </Badge>
                )}
                {t.sentiment != null && (
                  <Badge variant="outline" className="px-1.5 py-0 text-xs">
                    sentiment: {t.sentiment > 0 ? "+" : ""}
                    {t.sentiment}
                  </Badge>
                )}
              </div>

              <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-sm sm:grid-cols-3">
                <div className="flex flex-col sm:border-l sm:border-[#e0e0e0] sm:pl-4">
                  <Stat label="plays" value={t.play_count} />
                  <Stat label="key" value={t.key || "—"} />
                </div>
                <div className="flex flex-col sm:border-l sm:border-[#e0e0e0] sm:pl-4">
                  <Stat label="duration" value={fmtDuration(t.duration)} />
                  <Stat label="first listen" value={t.first_listen ?? "—"} />
                </div>
                <div className="flex flex-col sm:border-l sm:border-[#e0e0e0] sm:pl-4">
                  <Stat label="BPM" value={t.tempo ?? "—"} />
                  <Stat label="last listen" value={t.last_listen ?? "—"} />
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Charts: radars on the left, tag donuts on the right;
          both cards stretch to the same height */}
      {hasFeatures ? (
        <div className="grid gap-3 md:grid-cols-2">
          <Card className="flex flex-col">
            <CardHeader className="p-4 pb-2">
              <CardTitle>Moods &amp; Features</CardTitle>
            </CardHeader>
            <CardContent className="grid flex-1 content-start gap-3 p-4 pt-0 sm:grid-cols-2">
              <RadarBlock data={moodData} color="var(--chart-1)" />
              <RadarBlock data={featureData} color="var(--chart-2)" />
            </CardContent>
          </Card>
          {(genreData.length > 0 || instrumentData.length > 0) && (
            <Card className="flex flex-col">
              <CardHeader className="p-4 pb-2">
                <CardTitle>Genres &amp; Instruments</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col content-start gap-3 p-4 pt-0">
                {genreData.length > 0 && (
                  <DonutBlock data={genreData} unit="genres" />
                )}
                {instrumentData.length > 0 && (
                  <DonutBlock
                    data={instrumentData}
                    unit="instruments"
                    legendCols={2}
                  />
                )}
              </CardContent>
            </Card>
          )}
        </div>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Not analyzed yet</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <p className="text-muted-foreground text-sm">
              This track has no audio analysis. Analyze it right here, or use
              the batch "Audio analysis" job on the import page.
            </p>
            {analyzing ? (
              <LoadingNote size="sm" />
            ) : (
              <Button
                size="sm"
                className="w-fit"
                disabled={analyzeOne.isPending}
                onClick={() => analyzeOne.mutate()}
              >
                Analyze this track
              </Button>
            )}
            {analyzeError && (
              <Alert variant="destructive">
                <AlertDescription>{analyzeError}</AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}

      {/* Lyrics */}
      {t.has_lyrics && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              Lyrics
              {lyrics?.source === "whisper" && (
                <Badge variant="outline" className="text-xs">
                  whisper draft
                </Badge>
              )}
            </CardTitle>
            <button
              type="button"
              aria-label={showLyrics ? "Collapse" : "Expand"}
              onClick={() => setShowLyrics((v) => !v)}
              className="text-muted-foreground hover:text-foreground flex h-6 w-6 items-center justify-center"
            >
              <ChevronDown
                className={`h-4 w-4 transition-transform ${showLyrics ? "rotate-180" : ""}`}
              />
            </button>
          </CardHeader>
          {showLyrics && lyrics && (
            <CardContent>
              <pre className="max-h-96 overflow-y-auto font-sans text-sm whitespace-pre-wrap">
                {lyrics.text}
              </pre>
            </CardContent>
          )}
        </Card>
      )}

      {/* Similar tracks (v2 + Essentia + YouTube, stacked) */}
      <Card>
        <CardHeader>
          <CardTitle>Similar tracks</CardTitle>
          <CardDescription className="text-xs">
            weighted metric: timbre · rhythm · harmony · character · instruments
            · genre · lyrics · themes
          </CardDescription>
        </CardHeader>
        <CardContent>
          {similarQuery.isPending ? (
            <LoadingNote size="sm" />
          ) : similarItems.length > 0 ? (
            <>
              <ul className="flex flex-col">
                {similarItems.map((s, i) => (
                  <SimilarRow
                    key={s.track.video_id}
                    item={s}
                    index={i}
                    maxD={similarMaxD}
                    showMatch={false}
                    onOpen={() => navigate(`/track/${s.track.video_id}`)}
                  />
                ))}
              </ul>
              {similarQuery.hasNextPage ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2 w-full"
                  disabled={similarQuery.isFetchingNextPage}
                  onClick={() => similarQuery.fetchNextPage()}
                >
                  {similarQuery.isFetchingNextPage
                    ? "Loading…"
                    : `Show more (${similarTotal - similarItems.length})`}
                </Button>
              ) : (
                <p className="text-muted-foreground py-1.5 text-center text-xs">
                  showing all {similarTotal} tracks
                </p>
              )}
            </>
          ) : (
            <p className="text-muted-foreground text-sm">
              Not enough analyzed tracks to compare.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Similar tracks (Essentia)</CardTitle>
          <CardDescription className="text-xs">
            genres · instruments · moods · vocals · {essentiaTotal} total
          </CardDescription>
        </CardHeader>
        <CardContent>
          {essentiaQuery.isPending ? (
            <LoadingNote size="sm" />
          ) : essentiaItems.length > 0 ? (
            <>
              <ul className="flex flex-col">
                {essentiaItems.map((s, i) => (
                  <SimilarRow
                    key={`${s.track.video_id}-${i}`}
                    item={s}
                    index={i}
                    maxD={essentiaMaxD}
                    showMatch
                    onOpen={() => navigate(`/track/${s.track.video_id}`)}
                  />
                ))}
              </ul>
              {essentiaQuery.hasNextPage ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2 w-full"
                  disabled={essentiaQuery.isFetchingNextPage}
                  onClick={() => essentiaQuery.fetchNextPage()}
                >
                  {essentiaQuery.isFetchingNextPage
                    ? "Loading…"
                    : `Show more (${essentiaTotal - essentiaItems.length})`}
                </Button>
              ) : (
                <p className="text-muted-foreground py-1.5 text-center text-xs">
                  showing all {essentiaTotal} tracks
                </p>
              )}
            </>
          ) : (
            <p className="text-muted-foreground text-sm">
              No essentia tag data for this track.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Similar tracks from YouTube Music (native radio) */}
      {ytmData?.enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Similar tracks (YouTube)</CardTitle>
            <CardDescription className="text-xs">
              YouTube Music radio seeded by this track · {ytmItems.length} total
            </CardDescription>
          </CardHeader>
          <CardContent>
            {ytmVisible.length > 0 ? (
              <>
                <YtmTable
                  items={ytmVisible}
                  onOpen={(s) =>
                    s.in_history ? navigate(`/track/${s.video_id}`) : null
                  }
                />
                {ytmShown < ytmItems.length ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2 w-full"
                    onClick={() => setYtmShown((v) => v + 10)}
                  >
                    Show more ({ytmItems.length - ytmShown})
                  </Button>
                ) : (
                  <p className="text-muted-foreground py-1.5 text-center text-xs">
                    showing all {ytmItems.length} tracks
                  </p>
                )}
              </>
            ) : (
              <p className="text-muted-foreground text-sm">
                YouTube Music has no similar tracks for this video.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Similar artists */}
      {recs?.similar_artists && recs.similar_artists.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Similar artists from your history</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-2 md:grid-cols-2">
              {recs.similar_artists.map((a) => (
                <li
                  key={a.channel}
                  className="flex items-center justify-between gap-2 border border-[#cccccc] px-2 py-1.5"
                >
                  <span className="min-w-0">
                    <Link
                      to={artistPath(a.channel)}
                      className="block truncate text-sm font-bold hover:underline"
                    >
                      {a.channel}
                    </Link>
                    <span className="text-muted-foreground text-xs">
                      {a.tracks_analyzed} of {a.tracks_total} tracks analyzed ·{" "}
                      {a.plays} plays
                    </span>
                  </span>
                  <Badge variant="secondary" className="shrink-0">
                    {a.distance}
                  </Badge>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* MusicBrainz */}
      {recs?.mb_artists && recs.mb_artists.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>New artists</CardTitle>
            <CardDescription>
              MusicBrainz
              {recs.mood_name && ` · mood "${recs.mood_name}"`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-5">
              {recs.mb_artists.map((a) => (
                <li key={a.name} className="text-sm">
                  <b>{a.name}</b>
                  {a.country && (
                    <span className="text-muted-foreground">
                      {" "}
                      ({a.country})
                    </span>
                  )}
                  {a.tags && (
                    <span className="text-muted-foreground"> — {a.tags}</span>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <p className="text-muted-foreground text-sm">
        <Link to="/" className="hover:underline">
          ← back to all tracks
        </Link>
      </p>
    </div>
  );
}
