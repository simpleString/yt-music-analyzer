import { useEffect, useState, type ReactNode } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
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

import { api } from "@/lib/api";
import { artistPath } from "@/lib/utils";
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

function RadarCard({
  title,
  data,
  color,
}: {
  title: string;
  data: { axis: string; value: number }[];
  color: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartContainer
          config={{ value: { label: "value" } }}
          className="aspect-auto h-64 w-full"
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
      </CardContent>
    </Card>
  );
}

function DonutCard({
  title,
  data,
  unit,
  legendCols = 1,
}: {
  title: string
  data: { name: string; value: number }[]
  unit: string
  legendCols?: 1 | 2
}) {
  const total = data.reduce((s, d) => s + d.value, 0)
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-2 sm:flex-row sm:items-center sm:gap-4">
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
      </CardContent>
    </Card>
  )
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
  return (
    <li
      className="hover:bg-[#ffffcc] flex cursor-pointer items-center gap-1.5 border-b border-[#e0e0e0] px-1 py-1 last:border-b-0"
      title={`distance: ${item.distance}`}
      onClick={onOpen}
    >
      <span className="text-muted-foreground w-5 shrink-0 text-right text-xs tabular-nums">
        {index + 1}
      </span>
      <img
        src={`https://i.ytimg.com/vi/${item.track.video_id}/mqdefault.jpg`}
        alt=""
        loading="lazy"
        className="h-8 w-[52px] shrink-0 border border-[#999999] object-cover"
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm">{item.track.title}</span>
        <Link
          to={artistPath(item.track.artist ?? item.track.channel)}
          className="text-muted-foreground block truncate text-xs hover:underline"
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
    </li>
  );
}

export function TrackCard() {
  const { videoId } = useParams();
  const navigate = useNavigate();
  const [showLyrics, setShowLyrics] = useState(false);

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

  const essentiaQuery = useInfiniteQuery({
    queryKey: ["essentia-recommendations", videoId],
    queryFn: ({ pageParam = 0 }) =>
      api.recommendationsEssentia(videoId!, pageParam, 6),
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
      api.recommendationsSimilar(videoId!, pageParam, 6),
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

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
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
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => navigate(-1)}>
          ← Back
        </Button>
      </div>

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

      {/* Charts */}
      {hasFeatures ? (
        <div className="grid gap-3 md:grid-cols-2">
          <RadarCard title="Moods" data={moodData} color="var(--chart-1)" />
          <RadarCard
            title="Features"
            data={featureData}
            color="var(--chart-2)"
          />
          {genreData.length > 0 && (
            <DonutCard title="Genres" data={genreData} unit="genres" />
          )}
          {instrumentData.length > 0 && (
            <DonutCard
              title="Instruments"
              data={instrumentData}
              unit="instruments"
              legendCols={2}
            />
          )}
        </div>
      ) : (
        <Alert>
          <AlertDescription>
            Track not analyzed yet — run "Audio analysis" on the import page to
            see moods, genres, and instruments.
          </AlertDescription>
        </Alert>
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

      {/* Similar tracks (v2 + Essentia side by side) */}
      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Similar tracks</CardTitle>
            <CardDescription className="text-xs">
              weighted metric: timbre · rhythm · harmony · character ·
              instruments · genre · lyrics · themes
            </CardDescription>
          </CardHeader>
          <CardContent>
            {similarQuery.isPending ? (
              <p className="text-muted-foreground text-sm">
                Finding similar tracks…
              </p>
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
              <p className="text-muted-foreground text-sm">
                Finding similar tracks…
              </p>
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
      </div>

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
