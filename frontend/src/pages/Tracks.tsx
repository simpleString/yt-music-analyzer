import { useEffect, useMemo, useRef, useState } from "react"
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { useWindowVirtualizer } from "@tanstack/react-virtual"
import { Link, useNavigate } from "react-router-dom"
import { Ban, Check, EyeOff } from "lucide-react"

import { api, type TrackListItem, type TrackSort } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const GRID =
  "grid grid-cols-[2.25rem_4.25rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_6rem_6rem_4.5rem_5.5rem] items-center gap-1.5 px-1.5"

const REASON_LABELS: [string, string][] = [
  ["yt-music-app", "слушал в YouTube Music"],
  ["topic-channel", "канал - Topic"],
  ["vevo", "VEVO-канал"],
  ["api:cat10", "YouTube API: категория Music"],
  ["api:too-long", "слишком длинное (>12 ч, радиострим)"],
  ["api:not-music", "YouTube API: не музыка"],
  ["api-miss", "YouTube API: видео недоступно"],
  ["manual", "вручную"],
  ["manual-not-music", "вручную: канал скрыт"],
  ["anti-pattern", "анти-паттерн в названии"],
  ["no-signal", "нет признаков музыки"],
  ["artist-dash", "формат «артист - трек»"],
  ["channel-music", "музыкальный канал (голосование)"],
  ["channel-not-music", "немузыкальный канал (голосование)"],
]

function reasonLabel(reason: string): string {
  if (!reason) return "—"
  for (const [prefix, label] of REASON_LABELS) {
    if (reason.startsWith(prefix)) return label
  }
  return reason
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return "—"
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${String(s).padStart(2, "0")}`
}

const LANG_OPTIONS = [
  { value: "ru", label: "русский" },
  { value: "en", label: "английский" },
  { value: "cjk", label: "яп./кит." },
]

function techTooltip(t: TrackListItem): string {
  const parts = [`классификация: ${reasonLabel(t.music_reason)}`]
  if (t.tempo != null) {
    parts.push(`BPM: ${Math.round(t.tempo ?? 0)}`)
    parts.push(`яркость: ${(t.brightness ?? 0).toFixed(2)}`)
    if (t.key) parts.push(`тональность: ${t.key}`)
    if (t.loudness != null)
      parts.push(`громкость: ${t.loudness.toFixed(1)} дБ`)
    if (t.dynamics != null)
      parts.push(`динамика: ${t.dynamics.toFixed(2)}`)
    if (t.vocal_ratio != null)
      parts.push(`вокал: ${Math.round(t.vocal_ratio * 100)}%`)
    if (t.genres?.length)
      parts.push(`жанр: ${t.genres.join(", ")}`)
    if (t.instruments?.length)
      parts.push(`инструменты: ${t.instruments.join(", ")}`)
    const moods = [
      `весёлость ${Math.round((t.mood_happy ?? 0) * 100)}%`,
      `грусть ${Math.round((t.mood_sad ?? 0) * 100)}%`,
      `спокойствие ${Math.round((t.mood_relaxed ?? 0) * 100)}%`,
      `агрессия ${Math.round((t.mood_aggressive ?? 0) * 100)}%`,
      `электронность ${Math.round((t.mood_electronic ?? 0) * 100)}%`,
      `акустика ${Math.round((t.mood_acoustic ?? 0) * 100)}%`,
      `танцевальность-вечеринки ${Math.round((t.mood_party ?? 0) * 100)}%`,
      `эпичность ${Math.round((t.mood_epic ?? 0) * 100)}%`,
      `мрачность ${Math.round((t.mood_dark ?? 0) * 100)}%`,
      `романтика ${Math.round((t.mood_romantic ?? 0) * 100)}%`,
      `атмосферность ${Math.round((t.mood_atmospheric ?? 0) * 100)}%`,
    ]
    parts.push(`настроение: ${moods.join(", ")}`)
    parts.push(
      `источник фич: ${t.features_source === "audio" ? "аудио" : "метаданные"}`
    )
  }
  if (t.language) parts.push(`язык текста: ${t.language}`)
  return parts.join("\n")
}

const SORT_COLUMNS: { key: TrackSort; label: string; align?: "right" }[] = [
  { key: "tempo", label: "BPM", align: "right" },
  { key: "energy", label: "энергия", align: "right" },
  { key: "danceability", label: "танц.", align: "right" },
  { key: "acousticness", label: "акуст.", align: "right" },
  { key: "play_count", label: "просл.", align: "right" },
  { key: "first_listen", label: "первое", align: "right" },
  { key: "last_listen", label: "последнее", align: "right" },
  { key: "duration", label: "длит.", align: "right" },
]

export function Tracks() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [input, setInput] = useState("")
  const [q, setQ] = useState("")
  const [sort, setSort] = useState<TrackSort>("play_count")
  const [order, setOrder] = useState<"asc" | "desc">("desc")
  const [clusterId, setClusterId] = useState<number | null>(null)
  const [hidden, setHidden] = useState(false)
  const [genre, setGenre] = useState("")
  const [language, setLanguage] = useState("")
  const [instrumental, setInstrumental] = useState(false)
  const [showFilters, setShowFilters] = useState(false)

  const applySearch = () => setQ(input.trim())

  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 300)
    return () => clearTimeout(t)
  }, [input])

  const clearFilters = () => {
    setInput("")
    setQ("")
    setClusterId(null)
    setHidden(false)
    setGenre("")
    setLanguage("")
    setInstrumental(false)
  }

  const { data: clusters } = useQuery({
    queryKey: ["clusters"],
    queryFn: api.clusters,
  })
  const { data: genres } = useQuery({
    queryKey: ["genres"],
    queryFn: api.genres,
    staleTime: 5 * 60 * 1000,
  })
  const genreLabel = (name: string): string =>
    genres?.find((g) => g.name === name)?.name_ru ?? name

  const {
    data,
    isPending,
    isError,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
  } = useInfiniteQuery({
    queryKey: ["tracks", q, sort, order, clusterId, hidden, genre, language, instrumental],
    queryFn: ({ pageParam }) =>
      api.tracks({
        q,
        page: pageParam,
        sort,
        order,
        clusterId,
        hidden,
        genre,
        language,
        instrumental,
      }),
    initialPageParam: 1,
    getNextPageParam: (last) => {
      const lastPageNum = Math.ceil(last.total / last.per_page)
      return last.page < lastPageNum ? last.page + 1 : undefined
    },
    placeholderData: keepPreviousData,
  })

  const classify = useMutation({
    mutationFn: ({
      videoId,
      isMusic,
    }: {
      videoId: string
      isMusic: boolean
    }) => api.classifyTrack(videoId, isMusic),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tracks"] })
      queryClient.invalidateQueries({ queryKey: ["state"] })
    },
  })

  const hideChannel = useMutation({
    mutationFn: (channel: string) => api.hideChannel(channel),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tracks"] })
      queryClient.invalidateQueries({ queryKey: ["state"] })
    },
  })

  const rows = useMemo(
    () => data?.pages.flatMap((p) => p.tracks) ?? [],
    [data]
  )
  const total = data?.pages[0]?.total ?? 0

  const controlsRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [scrollMargin, setScrollMargin] = useState(0)
  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => 60,
    overscan: 10,
    scrollMargin,
  })

  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [q, sort, order, clusterId, hidden, genre, language, instrumental])

  useEffect(() => {
    const el = controlsRef.current
    if (!el) return
    const measure = () => {
      document.documentElement.style.setProperty(
        "--controls-h",
        `${el.offsetHeight}px`
      )
      const list = listRef.current
      if (list) {
        setScrollMargin(list.getBoundingClientRect().top + window.scrollY)
      }
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const sentinelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { rootMargin: "800px 0px" }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, rows.length])

  const toggleSort = (key: TrackSort) => {
    if (sort === key) {
      setOrder((o) => (o === "desc" ? "asc" : "desc"))
    } else {
      setSort(key)
      setOrder("desc")
    }
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div
        ref={controlsRef}
        className="sticky z-20 flex flex-col gap-2.5 bg-background pb-1"
        style={{ top: "var(--header-h, 0px)" }}
      >
        <h1 className="text-lg font-bold text-black text-center">Вся музыка</h1>

        <form
          className="flex w-full items-center justify-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            applySearch()
          }}
        >
          <Input
            type="search"
            placeholder="Поиск по названию или каналу…"
            className="max-w-md flex-1"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <Button type="submit">Поиск</Button>
          <Button type="button" variant="secondary" onClick={clearFilters}>
            Очистить
          </Button>
        </form>

        <div className="flex justify-center">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowFilters((v) => !v)}
          >
            {showFilters ? "[Скрыть фильтры]" : "[Дополнительные фильтры]"}
          </Button>
        </div>

        {showFilters && (
          <div className="flex flex-col items-center gap-2 border p-2">
            <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-1">
              <label className="flex cursor-pointer select-none items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={hidden}
                  onChange={(e) => setHidden(e.target.checked)}
                />
                Исключённые
              </label>
              <label className="flex cursor-pointer select-none items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={instrumental}
                  onChange={(e) => setInstrumental(e.target.checked)}
                  title="Только треки без вокала"
                />
                Инструментал
              </label>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-1.5">
              <Select
                value={clusterId != null ? String(clusterId) : "all"}
                onValueChange={(v) => setClusterId(v === "all" ? null : Number(v))}
              >
                <SelectTrigger className="w-60">
                  <SelectValue placeholder="Все настроения" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все настроения</SelectItem>
                  {clusters?.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name} · {c.size}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={genre || "any"}
                onValueChange={(v) => setGenre(v === "any" ? "" : v)}
              >
                <SelectTrigger className="w-44">
                  <SelectValue placeholder="Любой жанр" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Любой жанр</SelectItem>
                  {(genres ?? []).map((g) => (
                    <SelectItem key={g.name} value={g.name}>
                      {g.name_ru} ({g.count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={language || "any"}
                onValueChange={(v) => setLanguage(v === "any" ? "" : v)}
              >
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Любой язык" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Любой язык</SelectItem>
                  {LANG_OPTIONS.map((l) => (
                    <SelectItem key={l.value} value={l.value}>
                      {l.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}

        {hidden && (
          <p className="text-muted-foreground text-sm">
            Треки, помеченные как «не музыка». Кнопка ✓ возвращает трек в
            библиотеку.
          </p>
        )}

        {isPending && <p className="text-muted-foreground">Загрузка…</p>}
        {isError && <p>Не удалось загрузить данные.</p>}

        {data && total === 0 && !q && (
          <Alert>
            <AlertDescription>
              Нет музыки.{" "}
              <Link to="/import" className="underline">
                Импортируйте
              </Link>{" "}
              историю и запустите фильтр музыки.
            </AlertDescription>
          </Alert>
        )}

        {data && total === 0 && q && (
          <p className="text-muted-foreground text-sm">
            Ничего не найдено по запросу «{q}».
          </p>
        )}

        {data && total > 0 && (
          <p className="text-muted-foreground text-sm">
            {q ? (
              <>
                Найдено: <b className="text-foreground">{total}</b> по запросу
                «{q}»
              </>
            ) : (
              <>
                Всего: <b className="text-foreground">{total}</b> треков ·
                загружено: {rows.length}
              </>
            )}
          </p>
        )}
      </div>

      {data && total > 0 && (
        <>
          <div ref={listRef} className="border border-[#999999]">
            <div
              className={cn(
                GRID,
                "sticky z-10 min-w-[80rem] border-b border-[#999999] bg-[#eeeeee] py-1 text-xs font-bold text-black whitespace-nowrap"
              )}
              style={{
                top: "calc(var(--header-h, 0px) + var(--controls-h, 0px))",
              }}
            >
              <span>#</span>
              <span />
              <span>Название</span>
              <span>Настроение</span>
              {SORT_COLUMNS.map((col) => (
                <button
                  key={col.key}
                  type="button"
                  onClick={() => toggleSort(col.key)}
                  className={cn(
                    "text-[#0000cc] underline flex items-center gap-1",
                    col.align === "right" && "justify-end"
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
              <span className="text-right">действия</span>
            </div>

            <div
              className="min-w-[80rem]"
              style={{
                height: virtualizer.getTotalSize(),
                position: "relative",
              }}
            >
              {virtualizer.getVirtualItems().map((vi) => {
                const t = rows[vi.index]
                return (
                  <div
                    key={t.video_id}
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
                      "hover:bg-[#ffffcc] cursor-pointer border-b border-[#e0e0e0]"
                    )}
                    title={techTooltip(t)}
                    onClick={(e) => {
                      if (
                        e.target instanceof HTMLElement &&
                        (e.target.closest("a") || e.target.closest("button"))
                      )
                        return
                      navigate(`/track/${t.video_id}`)
                    }}
                  >
                    <span className="text-muted-foreground tabular-nums">
                      {vi.index + 1}
                    </span>
                    <a
                      href={`https://www.youtube.com/watch?v=${t.video_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0"
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
                        className="block truncate text-sm hover:underline"
                        title={t.title}
                      >
                        {t.title}
                      </a>
                      <span className="text-muted-foreground block truncate text-xs">
                        {t.channel}
                      </span>
                    </span>
                    <span className="flex flex-col items-start gap-0.5">
                      {t.cluster_name ? (
                        <Badge variant="outline">{t.cluster_name}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                      {t.genres?.[0] && (
                        <Badge variant="secondary" className="font-normal">
                          {genreLabel(t.genres[0])}
                          {t.language ? ` · ${t.language}` : ""}
                        </Badge>
                      )}
                      {!t.genres?.length && t.language && (
                        <Badge variant="secondary" className="font-normal">
                          {t.language}
                        </Badge>
                      )}
                    </span>
                    <span className="text-right text-sm tabular-nums">
                      {t.tempo != null ? Math.round(t.tempo) : "—"}
                    </span>
                    <span className="text-muted-foreground text-right text-sm tabular-nums">
                      {t.energy != null ? t.energy.toFixed(2) : "—"}
                    </span>
                    <span className="text-muted-foreground text-right text-sm tabular-nums">
                      {t.danceability != null
                        ? t.danceability.toFixed(2)
                        : "—"}
                    </span>
                    <span className="text-muted-foreground text-right text-sm tabular-nums">
                      {t.acousticness != null
                        ? t.acousticness.toFixed(2)
                        : "—"}
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
                    <span className="flex items-center justify-end gap-1">
                      {hidden ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          title="Вернуть в библиотеку (это музыка)"
                          disabled={classify.isPending}
                          onClick={() =>
                            classify.mutate({
                              videoId: t.video_id,
                              isMusic: true,
                            })
                          }
                        >
                          <Check className="size-4" />
                        </Button>
                      ) : (
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="hover:text-[#cc0000] size-7"
                            title="Это не музыка"
                            disabled={classify.isPending}
                            onClick={() =>
                              classify.mutate({
                                videoId: t.video_id,
                                isMusic: false,
                              })
                            }
                          >
                            <Ban className="size-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="hover:text-[#cc0000] size-7"
                            title={`Скрыть весь канал «${t.channel}»`}
                            disabled={hideChannel.isPending}
                            onClick={() =>
                              hideChannel.mutate(t.channel)
                            }
                          >
                            <EyeOff className="size-4" />
                          </Button>
                        </>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>

          <div
            ref={sentinelRef}
            className="flex h-10 items-center justify-center"
          >
            {isFetchingNextPage && (
              <span className="text-muted-foreground text-sm">Загрузка…</span>
            )}
            {!hasNextPage && (
              <span className="text-muted-foreground text-sm">
                Все {total.toLocaleString("ru-RU")} треков загружены
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
