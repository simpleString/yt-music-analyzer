import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { useNavigate } from "react-router-dom";

import { api, type ArtistListItem } from "@/lib/api";
import { cn, artistPath } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingNote } from "@/components/LoadingNote";

const GRID =
  "grid grid-cols-[2.25rem_2.75rem_minmax(0,1fr)_9rem_6rem_6rem_7rem] items-center gap-1.5 px-1.5";

type ArtistSort = "channel" | "genre" | "plays" | "tracks" | "last_listen";

const SORT_COLUMNS: { key: ArtistSort; label: string; align?: "right" }[] = [
  { key: "channel", label: "Artist" },
  { key: "genre", label: "genre" },
  { key: "plays", label: "plays", align: "right" },
  { key: "tracks", label: "tracks", align: "right" },
  { key: "last_listen", label: "last listen", align: "right" },
];

export function Artists() {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const [sort, setSort] = useState<ArtistSort>("plays");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["artists"],
    queryFn: api.artists,
    staleTime: 60 * 1000,
  });

  const q = input.trim().toLowerCase();
  const rows = useMemo(() => {
    const filtered = (data ?? []).filter(
      (a) => !q || a.channel.toLowerCase().includes(q),
    );
    const dir = order === "asc" ? 1 : -1;
    const cmp = (a: ArtistListItem, b: ArtistListItem): number => {
      switch (sort) {
        case "channel":
          return a.channel.localeCompare(b.channel);
        case "genre":
          return (
            (a.genre ?? "").localeCompare(b.genre ?? "") ||
            a.channel.localeCompare(b.channel)
          );
        case "tracks":
          return a.tracks - b.tracks;
        case "last_listen":
          return (a.last_listen ?? "").localeCompare(b.last_listen ?? "");
        default:
          return a.plays - b.plays;
      }
    };
    return [...filtered].sort((a, b) => cmp(a, b) * dir);
  }, [data, q, sort, order]);

  const toggleSort = (key: ArtistSort) => {
    if (sort === key) {
      setOrder(order === "desc" ? "asc" : "desc");
    } else {
      setSort(key);
      setOrder("desc");
    }
  };

  const controlsRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [scrollMargin, setScrollMargin] = useState(0);
  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    // fixed-height rows (h-12), same as the tracks table
    estimateSize: () => 48,
    overscan: 10,
    scrollMargin,
  });

  useEffect(() => {
    const el = controlsRef.current;
    if (!el) return;
    const measure = () => {
      document.documentElement.style.setProperty(
        "--controls-h",
        `${el.offsetHeight}px`,
      );
      const list = listRef.current;
      if (list) {
        setScrollMargin(list.getBoundingClientRect().top + window.scrollY);
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-2.5">
      <div
        ref={controlsRef}
        className="sticky z-20 flex flex-col gap-2.5 bg-background pb-1"
        style={{ top: "var(--header-h, 0px)" }}
      >
        <h1 className="text-lg font-bold text-black text-center">Artists</h1>
        <form
          className="flex w-full items-center justify-center gap-1.5"
          onSubmit={(e) => e.preventDefault()}
        >
          <Input
            type="search"
            placeholder="Search artist…"
            className="max-w-md flex-1"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <Button type="submit">Search</Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => setInput("")}
          >
            Clear
          </Button>
        </form>

        {isLoading && <LoadingNote />}
        {isError && <p>Failed to load data.</p>}

        {data && rows.length === 0 && q && (
          <p className="text-muted-foreground text-sm">
            Nothing found for "{input.trim()}".
          </p>
        )}

        {data && rows.length > 0 && (
          <p className="text-muted-foreground text-sm">
            {q ? (
              <>
                Found: <b className="text-foreground">{rows.length}</b> for "
                {input.trim()}"
              </>
            ) : (
              <>
                Total: <b className="text-foreground">{data.length}</b> artists
              </>
            )}
          </p>
        )}
      </div>

      {rows.length > 0 && (
        <div ref={listRef} className="border border-[#999999]">
          <div
            className={cn(
              GRID,
              "sticky z-10 h-12 min-w-[46rem] border-b border-[#999999] bg-[#eeeeee] text-xs font-bold text-black whitespace-nowrap",
            )}
            style={{
              top: "calc(var(--header-h, 0px) + var(--controls-h, 0px))",
            }}
          >
            <span>#</span>
            <span />
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

          <div
            className="min-w-[46rem]"
            style={{
              height: virtualizer.getTotalSize(),
              position: "relative",
            }}
          >
            {virtualizer.getVirtualItems().map((vi) => {
              const a = rows[vi.index];
              return (
                <div
                  key={a.channel}
                  data-index={vi.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${vi.start - scrollMargin}px)`,
                  }}
                  className={cn(
                    GRID,
                    "h-12 hover:bg-[#ffffcc] cursor-pointer border-b border-[#e0e0e0]",
                  )}
                  onClick={() => navigate(artistPath(a.channel))}
                >
                  <span className="text-muted-foreground tabular-nums">
                    {vi.index + 1}
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
                  <span className="truncate text-sm">{a.channel}</span>
                  <span className="min-w-0">
                    {a.genre ? (
                      <Badge
                        variant="secondary"
                        className="max-w-full truncate font-normal"
                      >
                        {a.genre}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </span>
                  <span className="text-right text-sm tabular-nums">
                    {a.plays}
                  </span>
                  <span className="text-muted-foreground text-right text-sm tabular-nums">
                    {a.tracks}
                  </span>
                  <span className="text-muted-foreground text-right text-sm tabular-nums">
                    {a.last_listen?.slice(0, 10) ?? "—"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
