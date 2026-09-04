import { useEffect, useRef, useState } from "react"
import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  Cell,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
} from "recharts"

import { api } from "@/lib/api"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"

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
]

const FEATURE_LABELS: [string, string][] = [
  ["energy", "Energy"],
  ["danceability", "Danceability"],
  ["acousticness", "Acousticness"],
  ["brightness", "Brightness"],
  ["dynamics", "Dynamics"],
  ["percussive", "Percussion"],
]

const PIE_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
]

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
}

function fmtDuration(sec: number | null): string {
  if (!sec) return "—"
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, "0")}`
}

export function TrackCard() {
  const { videoId } = useParams()
  const navigate = useNavigate()
  const [showLyrics, setShowLyrics] = useState(false)
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const similarSentinelRef = useRef<HTMLDivElement | null>(null)

  const { data: t, isLoading, isError } = useQuery({
    queryKey: ["track", videoId],
    queryFn: () => api.trackDetail(videoId!),
    enabled: !!videoId,
  })

  const { data: lyrics } = useQuery({
    queryKey: ["lyrics", videoId],
    queryFn: () => api.trackLyrics(videoId!),
    enabled: !!videoId && !!t?.has_lyrics,
  })

  const { data: recs } = useQuery({
    queryKey: ["recommendations", videoId],
    queryFn: () => api.recommendations(videoId!),
    enabled: !!videoId,
  })

  const essentiaQuery = useInfiniteQuery({
    queryKey: ["essentia-recommendations", videoId],
    queryFn: ({ pageParam = 0 }) =>
      api.recommendationsEssentia(videoId!, pageParam, 6),
    initialPageParam: 0,
    enabled: !!videoId,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.similar.length, 0)
      return loaded < lastPage.total ? loaded : undefined
    },
  })

  const similarQuery = useInfiniteQuery({
    queryKey: ["similar-recommendations", videoId],
    queryFn: ({ pageParam = 0 }) =>
      api.recommendationsSimilar(videoId!, pageParam, 6),
    initialPageParam: 0,
    enabled: !!videoId,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.similar.length, 0)
      return loaded < lastPage.total ? loaded : undefined
    },
  })

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (
          entry.isIntersecting &&
          essentiaQuery.hasNextPage &&
          !essentiaQuery.isFetchingNextPage
        ) {
          essentiaQuery.fetchNextPage()
        }
      },
      { rootMargin: "200px" }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [essentiaQuery.hasNextPage, essentiaQuery.isFetchingNextPage, essentiaQuery.fetchNextPage])

  useEffect(() => {
    const el = similarSentinelRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (
          entry.isIntersecting &&
          similarQuery.hasNextPage &&
          !similarQuery.isFetchingNextPage
        ) {
          similarQuery.fetchNextPage()
        }
      },
      { rootMargin: "200px" }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [similarQuery.hasNextPage, similarQuery.isFetchingNextPage, similarQuery.fetchNextPage])

  const essentiaItems = essentiaQuery.data?.pages.flatMap((p) => p.similar) ?? []
  const essentiaTotal = essentiaQuery.data?.pages[0]?.total ?? 0
  const similarItems = similarQuery.data?.pages.flatMap((p) => p.similar) ?? []
  const similarTotal = similarQuery.data?.pages[0]?.total ?? 0

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>
  if (isError || !t)
    return (
      <div className="flex flex-col gap-4">
        <Alert variant="destructive">
          <AlertDescription>Track not found.</AlertDescription>
        </Alert>
        <Button variant="outline" className="w-fit" onClick={() => navigate(-1)}>
          Back
        </Button>
      </div>
    )

  const moodData = MOOD_LABELS.map(([key, label]) => ({
    axis: label,
    value: (t as unknown as Record<string, number | null>)[key] ?? 0,
  }))
  const featureData = FEATURE_LABELS.map(([key, label]) => ({
    axis: label,
    value: (t as unknown as Record<string, number | null>)[key] ?? 0,
  }))
  const genreData = t.genre_scores.map((g) => ({
    name: g.name,
    value: Math.max(g.score, 0.0001),
  }))
  const instrumentData = t.instrument_scores.map((g) => ({
    name: g.name,
    value: Math.max(g.score, 0.0001),
  }))
  const hasFeatures = t.energy != null || t.tempo != null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => navigate(-1)}>
          ← Back
        </Button>
      </div>

      {/* Header */}
      <Card>
        <CardContent className="flex flex-wrap items-start gap-3">
          <a
            href={`https://www.youtube.com/watch?v=${t.video_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0"
          >
            <img
              src={`https://i.ytimg.com/vi/${t.video_id}/mqdefault.jpg`}
              alt=""
              className="h-24 border border-[#999999]"
              loading="lazy"
            />
          </a>
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <h1 className="text-lg font-bold text-black break-words">
              {t.title}
            </h1>
            <p className="text-muted-foreground">{t.channel}</p>
            <div className="flex flex-wrap items-center gap-2">
              {t.cluster_name && (
                <Badge variant="secondary">{t.cluster_name}</Badge>
              )}
              {t.topic && <Badge variant="outline">topic: {t.topic}</Badge>}
              {t.language && <Badge variant="outline">{t.language}</Badge>}
              {t.sentiment != null && (
                <Badge variant="outline">
                  sentiment: {t.sentiment > 0 ? "+" : ""}
                  {t.sentiment}
                </Badge>
              )}
            </div>
            <dl className="text-muted-foreground mt-1 grid grid-cols-2 gap-x-6 gap-y-0.5 text-sm sm:grid-cols-3">
              <div>
                <dt className="inline">plays: </dt>
                <dd className="text-foreground inline font-medium">
                  {t.play_count}
                </dd>
              </div>
              <div>
                <dt className="inline">duration: </dt>
                <dd className="text-foreground inline font-medium">
                  {fmtDuration(t.duration)}
                </dd>
              </div>
              <div>
                <dt className="inline">BPM: </dt>
                <dd className="text-foreground inline font-medium">
                  {t.tempo ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="inline">key: </dt>
                <dd className="text-foreground inline font-medium">
                  {t.key || "—"}
                </dd>
              </div>
              <div>
                <dt className="inline">first listen: </dt>
                <dd className="text-foreground inline font-medium">
                  {t.first_listen ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="inline">last listen: </dt>
                <dd className="text-foreground inline font-medium">
                  {t.last_listen ?? "—"}
                </dd>
              </div>
            </dl>
          </div>
        </CardContent>
      </Card>

      {/* Charts */}
      {hasFeatures ? (
        <div className="grid gap-3 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Moods</CardTitle>
            </CardHeader>
            <CardContent>
              <ChartContainer
                config={{ value: { label: "value" } }}
                className="aspect-auto h-72 w-full"
              >
                <RadarChart data={moodData}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="axis" />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Radar
                    dataKey="value"
                    stroke="var(--chart-1)"
                    fill="var(--chart-1)"
                    fillOpacity={0.35}
                  />
                </RadarChart>
              </ChartContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Features</CardTitle>
            </CardHeader>
            <CardContent>
              <ChartContainer
                config={{ value: { label: "value" } }}
                className="aspect-auto h-72 w-full"
              >
                <RadarChart data={featureData}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="axis" />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Radar
                    dataKey="value"
                    stroke="var(--chart-2)"
                    fill="var(--chart-2)"
                    fillOpacity={0.35}
                  />
                </RadarChart>
              </ChartContainer>
            </CardContent>
          </Card>

          {genreData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Genres</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartContainer
                  config={{ value: { label: "weight" } }}
                  className="aspect-auto h-64 w-full"
                >
                  <PieChart>
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Pie
                      data={genreData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius="45%"
                      outerRadius="80%"
                      paddingAngle={2}
                    >
                      {genreData.map((g, i) => (
                        <Cell
                          key={g.name}
                          fill={PIE_COLORS[i % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                  </PieChart>
                </ChartContainer>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {genreData.map((g, i) => (
                    <li
                      key={g.name}
                      className="flex items-center gap-1.5 text-xs"
                    >
                      <span
                        className="inline-block h-2.5 w-2.5 border border-[#666666]"
                        style={{
                          background: PIE_COLORS[i % PIE_COLORS.length],
                        }}
                      />
                      {g.name}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {instrumentData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Instruments</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartContainer
                  config={{ value: { label: "weight" } }}
                  className="aspect-auto h-64 w-full"
                >
                  <PieChart>
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Pie
                      data={instrumentData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius="45%"
                      outerRadius="80%"
                      paddingAngle={2}
                    >
                      {instrumentData.map((g, i) => (
                        <Cell
                          key={g.name}
                          fill={PIE_COLORS[i % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                  </PieChart>
                </ChartContainer>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {instrumentData.map((g, i) => (
                    <li
                      key={g.name}
                      className="flex items-center gap-1.5 text-xs"
                    >
                      <span
                        className="inline-block h-2.5 w-2.5 border border-[#666666]"
                        style={{
                          background: PIE_COLORS[i % PIE_COLORS.length],
                        }}
                      />
                      {g.name}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      ) : (
        <Alert>
          <AlertDescription>
            Track not analyzed yet — run "Audio analysis" on the import page
            to see moods, genres, and instruments.
          </AlertDescription>
        </Alert>
      )}

      {/* Lyrics */}
      {t.has_lyrics && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Lyrics</CardTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowLyrics((v) => !v)}
            >
              {showLyrics ? "Collapse" : "Expand"}
            </Button>
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

      {/* Similar tracks */}
      <Card>
        <CardHeader>
          <CardTitle>Similar tracks</CardTitle>
          <CardDescription>
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
              <div className="mb-3 flex flex-wrap gap-1.5">
                {Array.from(
                  new Set(similarItems.map((s) => s.match).filter(Boolean))
                ).map((m) => (
                  <Badge
                    key={m}
                    variant="outline"
                    className="text-xs"
                    style={{
                      borderColor: MATCH_COLORS[m] ?? "var(--chart-5)",
                      color: MATCH_COLORS[m] ?? "var(--chart-5)",
                    }}
                  >
                    {m}
                  </Badge>
                ))}
              </div>
              <ul className="flex flex-col">
                {similarItems.map((s, i) => {
                  const maxD = Math.max(
                    ...similarItems.map((x) => x.distance)
                  )
                  // skewed scale: everything in recommendations is already
                  // "similar", so worst of the top ≥ 50%, best → 100%
                  const sim = maxD > 0 ? 0.5 + 0.5 * (1 - s.distance / maxD) : 1
                  const pct = Math.round(sim * 100)
                  // full gradient gamma over the skewed 50-100% range
                  const hue = 45 + (142 - 45) * ((sim - 0.5) * 2)
                  return (
                    <li
                      key={s.track.video_id}
                      className="hover:bg-[#ffffcc] flex cursor-pointer items-center gap-1.5 border-b border-[#e0e0e0] px-1 py-0.5 last:border-b-0"
                      title={`distance: ${s.distance}`}
                      onClick={() => navigate(`/track/${s.track.video_id}`)}
                    >
                      <span className="text-muted-foreground w-6 shrink-0 text-right text-sm tabular-nums">
                        {i + 1}
                      </span>
                      <img
                        src={`https://i.ytimg.com/vi/${s.track.video_id}/mqdefault.jpg`}
                        alt=""
                        loading="lazy"
                        className="h-9 w-[56px] shrink-0 border border-[#999999] object-cover"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm">
                          {s.track.title}
                        </span>
                        <span className="text-muted-foreground block truncate text-xs">
                          {s.track.channel}
                        </span>
                      </span>
                      <span className="text-muted-foreground hidden w-12 shrink-0 text-right text-sm tabular-nums sm:inline">
                        {s.tempo ? Math.round(s.tempo) : "—"}
                      </span>
                      {s.match ? (
                        <Badge
                          variant="outline"
                          className="shrink-0 text-xs"
                          style={{
                            borderColor:
                              MATCH_COLORS[s.match] ?? "var(--chart-5)",
                            color: MATCH_COLORS[s.match] ?? "var(--chart-5)",
                          }}
                        >
                          {s.match}
                        </Badge>
                      ) : null}
                      <span className="flex w-32 shrink-0 items-center gap-2">
                        <span className="h-3 flex-1 overflow-hidden border border-[#999999] bg-[#eeeeee]">
                          <span
                            className="block h-full"
                            style={{
                              width: `${pct}%`,
                              background: `hsl(${hue} 70% 45%)`,
                            }}
                          />
                        </span>
                        <span className="w-9 text-right text-xs tabular-nums">
                          {pct}%
                        </span>
                      </span>
                    </li>
                  )
                })}
              </ul>
              {/* sentinel for infinite scroll */}
              <div ref={similarSentinelRef} className="h-4" />
              {similarQuery.isFetchingNextPage && (
                <p className="text-muted-foreground py-2 text-center text-sm">
                  Loading more…
                </p>
              )}
              {!similarQuery.hasNextPage && similarItems.length > 0 && (
                <p className="text-muted-foreground py-2 text-center text-xs">
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

      {/* Similar tracks (Essentia) — infinite feed */}
      {essentiaItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Similar tracks (Essentia)</CardTitle>
            <CardDescription>
              genres · instruments · moods · vocals ·{" "}
              {essentiaTotal} total
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col">
              {essentiaItems.map((s, i) => {
                const maxD = Math.max(...essentiaItems.map((x) => x.distance))
                const sim = maxD > 0 ? 0.5 + 0.5 * (1 - s.distance / maxD) : 1
                const pct = Math.round(sim * 100)
                const hue = 45 + (142 - 45) * ((sim - 0.5) * 2)
                return (
                  <li
                    key={`${s.track.video_id}-${i}`}
                    className="hover:bg-[#ffffcc] flex cursor-pointer items-center gap-1.5 border-b border-[#e0e0e0] px-1 py-0.5 last:border-b-0"
                    title={`distance: ${s.distance}`}
                    onClick={() => navigate(`/track/${s.track.video_id}`)}
                  >
                    <span className="text-muted-foreground w-6 shrink-0 text-right text-sm tabular-nums">
                      {i + 1}
                    </span>
                    <img
                      src={`https://i.ytimg.com/vi/${s.track.video_id}/mqdefault.jpg`}
                      alt=""
                      loading="lazy"
                      className="h-9 w-[56px] shrink-0 border border-[#999999] object-cover"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">
                        {s.track.title}
                      </span>
                      <span className="text-muted-foreground block truncate text-xs">
                        {s.track.channel}
                      </span>
                    </span>
                    <Badge
                      variant="outline"
                      className="shrink-0 text-xs"
                      style={{
                        borderColor:
                          MATCH_COLORS[s.match] ?? "var(--chart-5)",
                        color: MATCH_COLORS[s.match] ?? "var(--chart-5)",
                      }}
                    >
                      {s.match}
                    </Badge>
                    <span className="flex w-32 shrink-0 items-center gap-2">
                      <span className="h-3 flex-1 overflow-hidden border border-[#999999] bg-[#eeeeee]">
                        <span
                          className="block h-full"
                          style={{
                            width: `${pct}%`,
                            background: `hsl(${hue} 70% 45%)`,
                          }}
                        />
                      </span>
                      <span className="w-9 text-right text-xs tabular-nums">
                        {pct}%
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>
            {/* sentinel for infinite scroll */}
            <div ref={sentinelRef} className="h-4" />
            {essentiaQuery.isFetchingNextPage && (
              <p className="text-muted-foreground py-2 text-center text-sm">
                Loading more…
              </p>
            )}
            {!essentiaQuery.hasNextPage && essentiaItems.length > 0 && (
              <p className="text-muted-foreground py-2 text-center text-xs">
                showing all {essentiaTotal} tracks
              </p>
            )}
          </CardContent>
        </Card>
      )}
      {essentiaQuery.isPending && videoId && (
        <Card>
          <CardContent className="py-6">
            <p className="text-muted-foreground text-center text-sm">
              Finding similar tracks…
            </p>
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
                    <b className="block truncate text-sm">{a.channel}</b>
                    <span className="text-muted-foreground text-xs">
                      {a.tracks_analyzed} of {a.tracks_total} tracks
                      analyzed · {a.plays} plays
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
                    <span className="text-muted-foreground"> ({a.country})</span>
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
  )
}
