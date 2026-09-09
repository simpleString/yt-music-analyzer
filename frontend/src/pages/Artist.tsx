import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type TrackListItem, type TrackSort } from "@/lib/api";
import { techTooltip } from "@/lib/track";
import { cn, artistPath } from "@/lib/utils";
import { LoadingNote } from "@/components/LoadingNote";
import { TrackBadges } from "@/components/TrackBadges";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_6rem_6rem_4.5rem] items-center gap-1.5 px-1.5";

function formatDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

const SORT_COLUMNS: { key: TrackSort; label: string; align?: "right" }[] = [
  { key: "tempo", label: "BPM", align: "right" },
  { key: "energy", label: "energy", align: "right" },
  { key: "danceability", label: "dance.", align: "right" },
  { key: "acousticness", label: "acoust.", align: "right" },
  { key: "play_count", label: "plays", align: "right" },
  { key: "first_listen", label: "first", align: "right" },
  { key: "last_listen", label: "last", align: "right" },
  { key: "duration", label: "length", align: "right" },
];

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <span>
      <span className="text-muted-foreground">{label}: </span>
      <span className="font-medium">{value}</span>
    </span>
  );
}

export function ArtistPage() {
  const navigate = useNavigate();
  const splat = useParams()["*"] ?? "";
  const artist = decodeURIComponent(splat);

  const [sort, setSort] = useState<TrackSort>("play_count");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const summary = useQuery({
    queryKey: ["artist", artist],
    queryFn: () => api.artist(artist),
    enabled: !!artist,
    retry: false,
  });

  const { data: genres } = useQuery({
    queryKey: ["genres"],
    queryFn: api.genres,
    staleTime: 5 * 60 * 1000,
  });
  const genreLabel = (name: string): string =>
    genres?.find((g) => g.name === name)?.name_ru ?? name;

  const {
    data,
    isPending,
    isError,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
  } = useInfiniteQuery({
    queryKey: ["artist-tracks", artist, sort, order],
    queryFn: ({ pageParam }) =>
      api.tracks({
        q: "",
        page: pageParam,
        sort,
        order,
        clusterId: null,
        hidden: false,
        genre: "",
        language: "",
        key: "",
        instrumental: false,
        artist,
      }),
    initialPageParam: 1,
    getNextPageParam: (last) => {
      const lastPageNum = Math.ceil(last.total / last.per_page);
      return last.page < lastPageNum ? last.page + 1 : undefined;
    },
    placeholderData: keepPreviousData,
    enabled: !!artist,
  });

  const rows = useMemo(
    () => data?.pages.flatMap((p) => p.tracks) ?? [],
    [data],
  );
  const total = data?.pages[0]?.total ?? 0;

  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { rootMargin: "800px 0px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, rows.length]);

  const toggleSort = (key: TrackSort) => {
    if (sort === key) {
      setOrder(order === "desc" ? "asc" : "desc");
    } else {
      setSort(key);
      setOrder("desc");
    }
  };

  if (!artist) {
    return <p className="text-muted-foreground">Artist not specified.</p>;
  }

  if (summary.isPending) {
    return <LoadingNote />;
  }

  if (summary.isError || !summary.data) {
    return (
      <div className="flex flex-col gap-4">
        <Alert variant="destructive">
          <AlertDescription>Artist not found.</AlertDescription>
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
  }

  const s = summary.data;

  const mb = s.mb;
  const mbGenres = mb
    ? (mb.genres.length > 0 ? mb.genres : mb.tags)
        .slice(0, 5)
        .map((t) => t.name)
    : [];
  const country = mb?.country || mb?.area || "";
  const years = mb
    ? [mb.life_span.begin, mb.life_span.end].filter(Boolean).join("–")
    : "";

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <Card>
        <CardContent className="flex items-start gap-3">
          <a
            href={`https://www.youtube.com/watch?v=${s.top_track.video_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0"
            title="Open top track on YouTube"
          >
            <img
              src={`https://i.ytimg.com/vi/${s.top_track.video_id}/mqdefault.jpg`}
              alt={s.name}
              className="h-[70px] w-[70px] border border-[#999999] object-cover"
            />
          </a>
          <div className="flex min-w-0 flex-1 flex-col justify-center gap-1 overflow-hidden">
            <div className="flex flex-col min-w-0 items-baseline">
              <span className="min-w-0 truncate text-base font-bold">
                {s.name}
              </span>
              <span className="text-muted-foreground min-w-0 shrink-[2] truncate text-xs">
                {mb?.disambiguation
                  ? `artist · ${mb.disambiguation}`
                  : "artist"}
              </span>
            </div>
            <div className="grid grid-cols-2 items-center gap-1">
              <div className="flex min-w-0 flex-wrap gap-1 items-center">
                <a
                  href={`https://www.youtube.com/watch?v=${s.top_track.video_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0"
                  title={`Top track: ${s.top_track.title} (YouTube)`}
                >
                  <Badge
                    variant="outline"
                    className="max-w-[24rem] truncate px-1.5 py-0 text-xs font-normal"
                  >
                    ▶ {s.top_track.title} ({s.top_track.plays})
                  </Badge>
                </a>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-sm">
                <div className="flex flex-col sm:border-l sm:border-[#e0e0e0] sm:pl-4">
                  <Stat label="plays" value={s.plays} />
                  <Stat label="tracks" value={s.tracks} />
                </div>
                <div className="flex flex-col sm:border-l sm:border-[#e0e0e0] sm:pl-4">
                  <Stat
                    label="last listen"
                    value={s.last_listen?.slice(0, 10) ?? "—"}
                  />
                </div>
              </div>
            </div>
            {(mbGenres.length > 0 || country || years || mb?.mbid) && (
              <div className="flex flex-wrap items-center gap-1">
                {mbGenres.map((g) => (
                  <Badge key={g} variant="secondary" className="font-normal">
                    {genreLabel(g)}
                  </Badge>
                ))}
                {country && (
                  <Badge
                    variant="outline"
                    className="font-normal"
                    title={mb?.country ? undefined : mb?.area}
                  >
                    {country}
                  </Badge>
                )}
                {years && (
                  <Badge variant="outline" className="font-normal">
                    {years}
                  </Badge>
                )}
                {mb?.mbid && (
                  <Badge variant="outline" className="font-normal" asChild>
                    <a
                      href={`https://musicbrainz.org/artist/${mb.mbid}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="MusicBrainz page"
                    >
                      MB ↗
                    </a>
                  </Badge>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {isPending && <LoadingNote />}
      {isError && <p>Failed to load tracks.</p>}

      {data && total === 0 && (
        <p className="text-muted-foreground text-sm">
          No music tracks found for this artist.
        </p>
      )}

      {data && total > 0 && (
        <>
          <p className="text-muted-foreground text-sm">
            Total: <b className="text-foreground">{total}</b> tracks · loaded:{" "}
            {rows.length}
          </p>

          <div className="border border-[#999999]">
            <div
              className={cn(
                GRID,
                "sticky z-10 min-w-[74.5rem] border-b border-[#999999] bg-[#eeeeee] py-1 text-xs font-bold text-black whitespace-nowrap",
              )}
              style={{ top: "var(--header-h, 0px)" }}
            >
              <span>#</span>
              <span />
              <span>Title</span>
              <span>Mood</span>
              {SORT_COLUMNS.map((col) => (
                <button
                  key={col.key}
                  type="button"
                  onClick={() => toggleSort(col.key)}
                  className={cn(
                    "text-[#0000cc] underline flex items-center gap-1",
                    col.align === "right" && "justify-end",
                  )}
                >
                  {col.label}
                  {sort === col.key ? (
                    order === "desc" ? (
                      <span className="text-black">▼</span>
                    ) : (
                      <span className="text-black">▲</span>
                    )
                  ) : null}
                </button>
              ))}
            </div>

            <div className="min-w-[74.5rem]">
              {rows.map((t: TrackListItem, i) => (
                <Link
                  key={t.video_id}
                  to={`/track/${t.video_id}`}
                  className={cn(
                    GRID,
                    "text-inherit no-underline hover:text-inherit visited:text-inherit h-12 overflow-hidden hover:bg-[#ffffcc] border-b border-[#e0e0e0]",
                  )}
                  title={techTooltip(t)}
                >
                  <span className="text-muted-foreground tabular-nums">
                    {i + 1}
                  </span>
                  <a
                    href={`https://www.youtube.com/watch?v=${t.video_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <img
                      src={`https://i.ytimg.com/vi/${t.video_id}/mqdefault.jpg`}
                      alt=""
                      loading="lazy"
                      className="h-10 w-[71px] border border-[#999999] object-cover"
                    />
                  </a>
                  <span className="min-w-0">
                    <a
                      href={`https://www.youtube.com/watch?v=${t.video_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block truncate text-sm hover:underline max-w-fit"
                      title={t.title}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {t.title}
                    </a>
                    <Link
                      to={artistPath(t.artist ?? t.channel)}
                      className="text-muted-foreground block truncate text-xs hover:underline max-w-fit"
                    >
                      {t.channel}
                    </Link>
                  </span>
                  <TrackBadges
                    cluster={t.cluster_name}
                    genres={t.genres}
                    language={t.language}
                  />
                  <span className="text-right text-sm tabular-nums">
                    {t.tempo != null ? Math.round(t.tempo) : "—"}
                  </span>
                  <span className="text-muted-foreground text-right text-sm tabular-nums">
                    {t.energy != null ? t.energy.toFixed(2) : "—"}
                  </span>
                  <span className="text-muted-foreground text-right text-sm tabular-nums">
                    {t.danceability != null ? t.danceability.toFixed(2) : "—"}
                  </span>
                  <span className="text-muted-foreground text-right text-sm tabular-nums">
                    {t.acousticness != null ? t.acousticness.toFixed(2) : "—"}
                  </span>
                  <span className="text-right text-sm tabular-nums">
                    {t.play_count}
                  </span>
                  <span className="text-muted-foreground text-right text-sm tabular-nums">
                    {t.first_listen ?? "—"}
                  </span>
                  <span className="text-muted-foreground text-right text-sm tabular-nums">
                    {t.last_listen ?? "—"}
                  </span>
                  <span className="text-muted-foreground text-right text-sm tabular-nums">
                    {formatDuration(t.duration)}
                  </span>
                </Link>
              ))}
            </div>
          </div>

          <div
            ref={sentinelRef}
            className="flex h-10 items-center justify-center"
          >
            {isFetchingNextPage && <LoadingNote size="sm" />}
            {!hasNextPage && (
              <span className="text-muted-foreground text-sm">
                All tracks loaded
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
