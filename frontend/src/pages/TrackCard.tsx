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

import {
  api,
  type MixableItem,
  type TrackExtraInfo,
  type YtmSimilarTrack,
} from "@/lib/api";
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
        <Radar dataKey="value" stroke={color} fill={color} fillOpacity={0.35} />
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

// recommendation tables: common columns (#, thumb, track, mood, bpm,
// energy, dance., acoust., length, plays) + per-card extra columns.
// NB: every class string must be a full literal — Tailwind's scanner
// cannot resolve grid-cols-[...] assembled from pieces at runtime
const SIM_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem_8rem_3.5rem_4rem] items-center gap-1.5 px-1.5";
const ESS_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem_3.5rem_4rem] items-center gap-1.5 px-1.5";
const CO_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem_6rem_7rem] items-center gap-1.5 px-1.5";
const NEXT_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem_4rem_3.5rem_7rem] items-center gap-1.5 px-1.5";
const MIX_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem_4.5rem_7.5rem_4.5rem] items-center gap-1.5 px-1.5";

function TrackTable({
  grid,
  extraHead,
  children,
}: {
  grid: string;
  extraHead: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto border border-[#999999]">
      <div
        className={cn(
          grid,
          "h-12 border-b border-[#999999] bg-[#eeeeee] text-xs font-bold text-black whitespace-nowrap",
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
        <span className="text-right">length</span>
        <span className="text-right">plays</span>
        {extraHead}
      </div>
      <div>{children}</div>
    </div>
  );
}

function TrackGridRow({
  videoId,
  title,
  channel,
  artist,
  plays,
  info,
  index,
  grid,
  rowTitle,
  extra,
}: {
  videoId: string;
  title: string;
  channel: string;
  artist?: string;
  plays: number;
  info?: TrackExtraInfo | null;
  index: number;
  grid: string;
  rowTitle?: string;
  extra?: ReactNode;
}) {
  return (
    <Link
      to={`/track/${videoId}`}
      className={cn(
        grid,
        "text-inherit no-underline hover:text-inherit visited:text-inherit h-12 hover:bg-[#ffffcc] border-b border-[#e0e0e0]",
      )}
      title={rowTitle}
      onClick={() => sessionStorage.setItem("tracks-open-track", videoId)}
    >
      <span className="text-muted-foreground tabular-nums">{index + 1}</span>
      <a
        href={`https://www.youtube.com/watch?v=${videoId}`}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={`https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`}
          alt=""
          loading="lazy"
          className="h-10 w-[71px] shrink-0 border border-[#999999] object-cover"
        />
      </a>
      <span className="min-w-0">
        <a
          href={`https://www.youtube.com/watch?v=${videoId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="block truncate text-sm hover:underline max-w-fit"
          title={title}
          onClick={(e) => e.stopPropagation()}
        >
          {title}
        </a>
        <Link
          to={artistPath(artist ?? channel)}
          className="text-muted-foreground block truncate text-xs hover:underline max-w-fit"
        >
          {channel}
        </Link>
      </span>
      <span className="min-w-0">
        {info?.cluster ? (
          <Badge variant="outline" className="max-w-full">
            <span className="truncate">{info.cluster}</span>
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
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
      <span className="text-muted-foreground text-right text-sm tabular-nums">
        {fmtDuration(info?.duration ?? null)}
      </span>
      <span className="text-right text-sm tabular-nums">{plays}</span>
      {extra}
    </Link>
  );
}

function fmtDate(v: string | null): string {
  return v ? v.slice(0, 10) : "—";
}

// artist tables: icon column + arbitrary columns per card
const ART_HIST_GRID =
  "grid grid-cols-[4.25rem_minmax(0,1fr)_9rem_6rem_6rem] items-center gap-1.5 px-1.5";
const ART_LB_GRID =
  "grid grid-cols-[4.25rem_minmax(0,1fr)_minmax(0,1.2fr)_7rem_7rem] items-center gap-1.5 px-1.5";

function ArtistTable({
  grid,
  head,
  children,
}: {
  grid: string;
  head: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto border border-[#999999]">
      <div
        className={cn(
          grid,
          "h-12 border-b border-[#999999] bg-[#eeeeee] text-xs font-bold text-black whitespace-nowrap",
        )}
      >
        <span />
        {head}
      </div>
      <div>{children}</div>
    </div>
  );
}

function ArtistIcon({
  videoId,
  name,
}: {
  videoId?: string;
  name: string;
}) {
  if (videoId) {
    return (
      <img
        src={`https://i.ytimg.com/vi/${videoId}/default.jpg`}
        alt=""
        loading="lazy"
        className="h-10 w-10 border border-[#999999] object-cover"
      />
    );
  }
  const init = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => (w[0] ?? "").toUpperCase())
    .join("");
  return (
    <span
      className="text-muted-foreground flex h-10 w-10 shrink-0 items-center justify-center border border-[#e0e0e0] bg-[#eeeeee] text-xs font-bold"
      title="no artist image"
    >
      {init || "?"}
    </span>
  );
}

const YTM_GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_4rem_4rem_3.5rem_4.5rem] items-center gap-1.5 px-1.5";

const RELATION_LABELS: Record<MixableItem["relation"], string> = {
  same: "same key",
  relative: "relative",
  "energy-up": "energy up",
  "energy-down": "energy down",
};

function YtmRow({ item, index }: { item: YtmSimilarTrack; index: number }) {
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
  const rowCls = cn(
    YTM_GRID,
    "text-inherit no-underline hover:text-inherit visited:text-inherit h-12 min-w-[62rem] hover:bg-[#ffffcc] border-b border-[#e0e0e0]",
  );
  const cells = (
    <>
      <span className="text-muted-foreground tabular-nums">{index + 1}</span>
      <a
        href={`https://www.youtube.com/watch?v=${item.video_id}`}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0"
        onClick={(e) => e.stopPropagation()}
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
          onClick={(e) => e.stopPropagation()}
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
    </>
  );
  if (item.in_history) {
    return (
      <Link
        to={`/track/${item.video_id}`}
        className={rowCls}
        title={tooltip || undefined}
        onClick={() =>
          sessionStorage.setItem("tracks-open-track", item.video_id)
        }
      >
        {cells}
      </Link>
    );
  }
  return <div className={rowCls}>{cells}</div>;
}

function YtmTable({ items }: { items: YtmSimilarTrack[] }) {
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
            <YtmRow key={`${s.video_id}-${i}`} item={s} index={i} />
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

  const {
    data: recs,
    isLoading: recsLoading,
    isError: recsError,
  } = useQuery({
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

  // history/mix tables are fetched in one request (capped) and paginated
  // client-side with the shared "Show more" button
  const { data: coData } = useQuery({
    queryKey: ["co-listened", videoId],
    queryFn: () => api.coListened(videoId!, 50),
    enabled: !!videoId,
  });

  const { data: nextData } = useQuery({
    queryKey: ["next-tracks", videoId],
    queryFn: () => api.nextTracks(videoId!, 50),
    enabled: !!videoId,
  });

  const { data: mixData } = useQuery({
    queryKey: ["mixable", videoId],
    queryFn: () => api.mixable(videoId!, 50),
    enabled: !!videoId,
  });

  const [coShown, setCoShown] = useState(10);
  const [nextShown, setNextShown] = useState(10);
  const [mixShown, setMixShown] = useState(12);
  useEffect(() => {
    setCoShown(10);
    setNextShown(10);
    setMixShown(12);
  }, [videoId]);

  const coItems = coData?.built ? coData.items.slice(0, coShown) : [];
  const nextItems = nextData?.built ? nextData.items.slice(0, nextShown) : [];

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
      {/* Processing errors (audio/lyrics pipeline) */}
      {t.errors && t.errors.length > 0 && (
        <Alert variant="destructive">
          <AlertDescription>
            <div className="flex flex-col gap-1">
              {t.errors.map((e) => (
                <div key={e.stage} className="text-xs">
                  <b className="uppercase">{e.stage}</b>{" "}
                  <span className="text-muted-foreground">
                    ({new Date(e.created_at).toLocaleString()})
                  </span>
                  : {e.error}
                </div>
              ))}
            </div>
          </AlertDescription>
        </Alert>
      )}

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
                  <Badge
                    variant="secondary"
                    className="px-1.5 py-0 text-xs"
                    title={`Mood cluster: tracks with a similar sound, grouped by audio features ("${t.cluster_name}")`}
                  >
                    {t.cluster_name}
                  </Badge>
                )}
                {t.topic && (
                  <Badge
                    variant="outline"
                    className="px-1.5 py-0 text-xs"
                    title={`Main theme of the lyrics, detected from the text ("${t.topic}")`}
                  >
                    {t.topic}
                  </Badge>
                )}
                {t.language && (
                  <Badge
                    variant="outline"
                    className="px-1.5 py-0 text-xs"
                    title={`Language of the lyrics: ${t.language}`}
                  >
                    {t.language}
                  </Badge>
                )}
                {t.ytm?.album && (
                  <Badge
                    variant="outline"
                    className="px-1.5 py-0 text-xs"
                    title={`Album from the YouTube Music catalog${t.ytm.year ? `, ${t.ytm.year}` : ""}`}
                  >
                    {t.ytm.album}
                    {t.ytm.year ? ` · ${t.ytm.year}` : ""}
                  </Badge>
                )}
                {t.sentiment != null && (
                  <Badge
                    variant="outline"
                    className="px-1.5 py-0 text-xs"
                    title="Lyrics sentiment: emotional tone of the text, from −1 (sad/negative) to +1 (happy/positive)"
                  >
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
            <button
              type="button"
              aria-label={showLyrics ? "Collapse" : "Expand"}
              onClick={() => setShowLyrics((v) => !v)}
            >
              <CardTitle className="flex items-center gap-2 cursor-pointer">
                Lyrics
                {lyrics?.source === "whisper" && (
                  <Badge variant="outline" className="text-xs">
                    whisper draft
                  </Badge>
                )}
                <ChevronDown
                  className={` h-4 w-4 transition-transform ${showLyrics ? "rotate-180" : ""}`}
                />
              </CardTitle>
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
              <TrackTable
                grid={SIM_GRID}
                extraHead={
                  <>
                    <span>match</span>
                    <span
                      className="text-right"
                      title="similarity, skewed: best of the list → 100%"
                    >
                      sim
                    </span>
                    <span
                      className="text-right"
                      title="weighted distance (lower = more similar)"
                    >
                      dist
                    </span>
                  </>
                }
              >
                {similarItems.map((s, i) => {
                  const sim =
                    similarMaxD > 0
                      ? 0.5 + 0.5 * (1 - s.distance / similarMaxD)
                      : 1;
                  return (
                    <TrackGridRow
                      key={s.track.video_id}
                      videoId={s.track.video_id}
                      title={s.track.title}
                      channel={s.track.channel}
                      artist={s.track.artist}
                      plays={s.track.play_count}
                      info={s.info}
                      index={i}
                      grid={SIM_GRID}
                      rowTitle={techTooltip(s.track, [
                        `distance: ${s.distance.toFixed(3)} (lower = more similar)`,
                        `match: ${s.match}`,
                      ])}
                      extra={
                        <>
                          <Badge
                            variant="outline"
                            className="max-w-full px-1.5 py-0 text-xs"
                            style={{
                              borderColor:
                                MATCH_COLORS[s.match] ?? "var(--chart-5)",
                              color: MATCH_COLORS[s.match] ?? "var(--chart-5)",
                            }}
                          >
                            <span className="truncate">{s.match}</span>
                          </Badge>
                          <span className="text-right text-xs tabular-nums">
                            {Math.round(sim * 100)}%
                          </span>
                          <span className="text-muted-foreground text-right text-xs tabular-nums">
                            {s.distance.toFixed(3)}
                          </span>
                        </>
                      }
                    />
                  );
                })}
              </TrackTable>
              {similarQuery.hasNextPage ? (
                <div className="mt-2 flex justify-center">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={similarQuery.isFetchingNextPage}
                    onClick={() => similarQuery.fetchNextPage()}
                  >
                    {similarQuery.isFetchingNextPage
                      ? "Loading…"
                      : `Show more (${similarTotal - similarItems.length})`}
                  </Button>
                </div>
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

      {/* Listened together (history sessions, co-occurrence) */}
      {coItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Listened together</CardTitle>
            <CardDescription className="text-xs">
              shares listening sessions with this track in your history ·{" "}
              {coData?.items.length ?? 0} loaded
            </CardDescription>
          </CardHeader>
          <CardContent>
            <TrackTable
              grid={CO_GRID}
                extraHead={
                  <>
                    <span
                      className="text-right"
                      title="how many listening sessions they share"
                    >
                      sessions
                    </span>
                    <span className="text-right">last together</span>
                  </>
                }
            >
              {coItems.map((item, i) => (
                <TrackGridRow
                  key={item.track.video_id}
                  videoId={item.track.video_id}
                  title={item.track.title}
                  channel={item.track.channel}
                  artist={item.track.artist}
                  plays={item.track.play_count}
                  info={item.info}
                  index={i}
                  grid={CO_GRID}
                  extra={
                    <>
                      <span className="text-right text-sm tabular-nums">
                        {item.cnt}
                      </span>
                      <span className="text-muted-foreground text-right text-xs tabular-nums">
                        {fmtDate(item.last_listen)}
                      </span>
                    </>
                  }
                />
              ))}
            </TrackTable>
            {coData && coData.items.length > coShown ? (
              <div className="mt-2 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCoShown((v) => v + 10)}
                >
                  Show more ({coData.items.length - coShown})
                </Button>
              </div>
            ) : (
              <p className="text-muted-foreground py-1.5 text-center text-xs">
                showing all {coItems.length} tracks
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* What comes next (Markov over sessions) */}
      {nextItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>What comes next</CardTitle>
            <CardDescription className="text-xs">
              tracks that usually follow this one in your history ·{" "}
              {nextData?.items.length ?? 0} loaded
            </CardDescription>
          </CardHeader>
          <CardContent>
            <TrackTable
              grid={NEXT_GRID}
                extraHead={
                  <>
                    <span
                      className="text-right"
                      title="how many times it followed this track"
                    >
                      next
                    </span>
                    <span
                      className="text-right"
                      title="probability that this track is followed by it"
                    >
                      P
                    </span>
                    <span className="text-right">last together</span>
                  </>
                }
            >
              {nextItems.map((item, i) => (
                <TrackGridRow
                  key={item.track.video_id}
                  videoId={item.track.video_id}
                  title={item.track.title}
                  channel={item.track.channel}
                  artist={item.track.artist}
                  plays={item.track.play_count}
                  info={item.info}
                  index={i}
                  grid={NEXT_GRID}
                  extra={
                    <>
                      <span className="text-right text-sm tabular-nums">
                        {item.cnt}×
                      </span>
                      <span className="text-right text-xs tabular-nums">
                        {Math.round((item.p ?? 0) * 100)}%
                      </span>
                      <span className="text-muted-foreground text-right text-xs tabular-nums">
                        {fmtDate(item.last_listen)}
                      </span>
                    </>
                  }
                />
              ))}
            </TrackTable>
            {nextData && nextData.items.length > nextShown ? (
              <div className="mt-2 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setNextShown((v) => v + 10)}
                >
                  Show more ({nextData.items.length - nextShown})
                </Button>
              </div>
            ) : (
              <p className="text-muted-foreground py-1.5 text-center text-xs">
                showing all {nextItems.length} tracks
              </p>
            )}
          </CardContent>
        </Card>
      )}

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
              <TrackTable
                grid={ESS_GRID}
                extraHead={
                  <>
                    <span
                      className="text-right"
                      title="similarity, skewed: best of the list → 100%"
                    >
                      sim
                    </span>
                    <span
                      className="text-right"
                      title="tag distance (lower = more similar)"
                    >
                      dist
                    </span>
                  </>
                }
              >
                {essentiaItems.map((s, i) => {
                  const sim =
                    essentiaMaxD > 0
                      ? 0.5 + 0.5 * (1 - s.distance / essentiaMaxD)
                      : 1;
                  return (
                    <TrackGridRow
                      key={`${s.track.video_id}-${i}`}
                      videoId={s.track.video_id}
                      title={s.track.title}
                      channel={s.track.channel}
                      artist={s.track.artist}
                      plays={s.track.play_count}
                      info={s.info}
                      index={i}
                      grid={ESS_GRID}
                      rowTitle={techTooltip(s.track, [
                        `essentia tag distance: ${s.distance.toFixed(3)} (lower = more similar)`,
                      ])}
                      extra={
                        <>
                          <span className="text-right text-xs tabular-nums">
                            {Math.round(sim * 100)}%
                          </span>
                          <span className="text-muted-foreground text-right text-xs tabular-nums">
                            {s.distance.toFixed(3)}
                          </span>
                        </>
                      }
                    />
                  );
                })}
              </TrackTable>
              {essentiaQuery.hasNextPage ? (
                <div className="mt-2 flex justify-center">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={essentiaQuery.isFetchingNextPage}
                    onClick={() => essentiaQuery.fetchNextPage()}
                  >
                    {essentiaQuery.isFetchingNextPage
                      ? "Loading…"
                      : `Show more (${essentiaTotal - essentiaItems.length})`}
                  </Button>
                </div>
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
                <YtmTable items={ytmVisible} />
                {ytmShown < ytmItems.length ? (
                  <div className="mt-2 flex justify-center">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setYtmShown((v) => v + 10)}
                    >
                      Show more ({ytmItems.length - ytmShown})
                    </Button>
                  </div>
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

      {/* Mix-compatible (Camelot wheel + BPM) */}
      {mixData?.available && mixData.items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Mix-compatible</CardTitle>
            <CardDescription className="text-xs">
              harmonic mixing · seed {mixData.seed.key} ({mixData.seed.camelot})
              · {Math.round(mixData.seed.tempo)} BPM · {mixData.total} total
            </CardDescription>
          </CardHeader>
          <CardContent>
            <TrackTable
              grid={MIX_GRID}
              extraHead={
                <>
                  <span title="Camelot code of the track's key">key</span>
                  <span>relation</span>
                  <span
                    className="text-right"
                    title="tempo difference to the seed track"
                  >
                    Δ BPM
                  </span>
                </>
              }
            >
              {mixData.items.slice(0, mixShown).map((item, i) => (
                <TrackGridRow
                  key={item.track.video_id}
                  videoId={item.track.video_id}
                  title={item.track.title}
                  channel={item.track.channel}
                  artist={item.track.artist}
                  plays={item.track.play_count}
                  info={item.info}
                  index={i}
                  grid={MIX_GRID}
                  rowTitle={techTooltip(item.track, [
                    `key: ${item.key} (${item.camelot})`,
                    `relation: ${RELATION_LABELS[item.relation]}`,
                  ])}
                  extra={
                    <>
                      <Badge
                        variant="outline"
                        className="max-w-full px-1.5 py-0 text-xs"
                      >
                        <span className="truncate">{item.camelot}</span>
                      </Badge>
                      <Badge
                        variant="secondary"
                        className="max-w-full px-1.5 py-0 text-xs font-normal"
                      >
                        <span className="truncate">
                          {RELATION_LABELS[item.relation]}
                        </span>
                      </Badge>
                      <span className="text-muted-foreground text-right text-xs tabular-nums">
                        {item.tempo_delta > 0 ? "+" : ""}
                        {(item.tempo_delta * 100).toFixed(1)}%
                      </span>
                    </>
                  }
                />
              ))}
            </TrackTable>
            {mixData.items.length > mixShown ? (
              <div className="mt-2 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setMixShown((v) => v + 12)}
                >
                  Show more ({mixData.items.length - mixShown})
                </Button>
              </div>
            ) : (
              <p className="text-muted-foreground py-1.5 text-center text-xs">
                showing all {Math.min(mixShown, mixData.items.length)} tracks
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Similar artists */}
      <Card>
        <CardHeader>
          <CardTitle>Similar artists from your history</CardTitle>
        </CardHeader>
        <CardContent>
          {recsLoading ? (
            <LoadingNote size="sm" />
          ) : recsError ? (
            <Alert variant="destructive">
              <AlertDescription>
                Failed to load recommendations.
              </AlertDescription>
            </Alert>
          ) : recs?.similar_artists && recs.similar_artists.length > 0 ? (
            <ArtistTable
              grid={ART_HIST_GRID}
              head={
                <>
                  <span>Artist</span>
                  <span className="text-right" title="tracks with audio analysis of all their tracks">tracks</span>
                  <span className="text-right">plays</span>
                  <span
                    className="text-right"
                    title="distance between artist feature centroids (lower = more similar)"
                  >
                    dist
                  </span>
                </>
              }
            >
              {recs.similar_artists.map((a) => (
                <Link
                  key={a.channel}
                  to={artistPath(a.channel)}
                  className={cn(
                    ART_HIST_GRID,
                    "text-inherit no-underline hover:text-inherit visited:text-inherit h-12 hover:bg-[#ffffcc] border-b border-[#e0e0e0]",
                  )}
                  title={`feature-centroid distance: ${a.distance} (lower = more similar)`}
                >
                  <ArtistIcon videoId={a.top_video_id} name={a.channel} />
                  <span className="truncate text-sm">{a.channel}</span>
                  <span className="text-muted-foreground text-right text-xs tabular-nums">
                    {a.tracks_analyzed} of {a.tracks_total}
                  </span>
                  <span className="text-right text-sm tabular-nums">
                    {a.plays}
                  </span>
                  <span className="text-right">
                    <Badge variant="secondary" className="px-1.5 py-0 text-xs">
                      {a.distance}
                    </Badge>
                  </span>
                </Link>
              ))}
            </ArtistTable>
          ) : (
            <p className="text-muted-foreground text-sm">
              Not enough analyzed tracks to compare artists.
            </p>
          )}
        </CardContent>
      </Card>

      {/* ListenBrainz: global similar artists */}
      <Card>
        <CardHeader>
          <CardTitle>Similar artists (ListenBrainz)</CardTitle>
          <CardDescription>
            global listening data · seed artist from MusicBrainz
          </CardDescription>
        </CardHeader>
        <CardContent>
          {recsLoading ? (
            <LoadingNote size="sm" />
          ) : recsError ? (
            <Alert variant="destructive">
              <AlertDescription>
                Failed to load recommendations.
              </AlertDescription>
            </Alert>
          ) : recs?.lb_error ? (
            <p className="text-muted-foreground text-sm">
              ListenBrainz: {recs.lb_error}
            </p>
          ) : recs?.lb_artists && recs.lb_artists.length > 0 ? (
            <ArtistTable
              grid={ART_LB_GRID}
              head={
                <>
                  <span>Artist</span>
                  <span>about</span>
                  <span className="text-right">your plays</span>
                  <span className="text-right">status</span>
                </>
              }
            >
              {recs.lb_artists.map((a) => {
                const rowCls = cn(
                  ART_LB_GRID,
                  "h-12 hover:bg-[#ffffcc] border-b border-[#e0e0e0]",
                  a.in_history &&
                    "text-inherit no-underline hover:text-inherit visited:text-inherit",
                );
                const cells = (
                  <>
                    <ArtistIcon name={a.name} />
                    <span className="min-w-0">
                      {a.in_history ? (
                        <span
                          className="block truncate text-sm"
                          title={`${a.name} — open artist page`}
                        >
                          {a.name}
                        </span>
                      ) : a.mbid ? (
                        <a
                          href={`https://musicbrainz.org/artist/${a.mbid}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block truncate text-sm hover:underline max-w-fit"
                          title={`${a.name} on MusicBrainz`}
                        >
                          {a.name}
                        </a>
                      ) : (
                        <span className="block truncate text-sm">{a.name}</span>
                      )}
                    </span>
                    <span className="text-muted-foreground min-w-0 truncate text-xs">
                      {a.comment || "—"}
                    </span>
                    <span className="text-right text-sm tabular-nums">
                      {a.in_history ? a.plays : "—"}
                    </span>
                    <span className="text-right">
                      {a.in_history ? (
                        <Badge
                          variant="secondary"
                          className="px-1.5 py-0 text-xs"
                          title="this artist is in your history — click the row to open their page"
                        >
                          in history
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="px-1.5 py-0 text-xs"
                          title="you have never listened to this artist"
                        >
                          new to you
                        </Badge>
                      )}
                    </span>
                  </>
                );
                return a.in_history ? (
                  <Link
                    key={a.mbid || a.name}
                    to={artistPath(a.name)}
                    className={rowCls}
                  >
                    {cells}
                  </Link>
                ) : (
                  <div key={a.mbid || a.name} className={rowCls}>
                    {cells}
                  </div>
                );
              })}
            </ArtistTable>
          ) : (
            <p className="text-muted-foreground text-sm">
              No global similar artists for this seed artist.
            </p>
          )}
        </CardContent>
      </Card>

      <p className="text-muted-foreground text-sm">
        <Link to="/" className="hover:underline">
          ← back to all tracks
        </Link>
      </p>
    </div>
  );
}
