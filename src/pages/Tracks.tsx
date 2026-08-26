import { useEffect, useMemo, useRef, useState } from "react"
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { useVirtualizer } from "@tanstack/react-virtual"
import { Link } from "react-router-dom"
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Ban,
  Check,
  EyeOff,
  Music,
  Search,
} from "lucide-react"

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
  "grid grid-cols-[2.5rem_4.5rem_minmax(0,1fr)_10.5rem_4rem_4.5rem_4.5rem_4.5rem_4.5rem_6rem_6rem_4.5rem_5.5rem] items-center gap-3 px-3"

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

const GENRE_OPTIONS = [
  "Rock music",
  "Pop music",
  "Hip hop music",
  "Electronic music",
  "Heavy metal",
  "Jazz",
  "Classical music",
  "Folk music",
  "Punk rock",
  "Techno",
  "House music",
  "Drum and bass",
  "Funk",
  "Ambient music",
  "Trance music",
  "Soundtrack music",
]

function genreRu(name: string): string {
  const map: Record<string, string> = {
    "Rock music": "рок",
    "Pop music": "поп",
    "Hip hop music": "хип-хоп",
    "Electronic music": "электроника",
    "Heavy metal": "метал",
    Jazz: "джаз",
    "Classical music": "классика",
    "Folk music": "фолк",
    "Punk rock": "панк",
    Techno: "техно",
    "House music": "хаус",
    "Drum and bass": "dnb",
    Funk: "фанк",
    "Ambient music": "эмбиент",
    "Trance music": "транс",
    "Soundtrack music": "саундтрек",
    "Rhythm and blues": "r&b",
    Reggae: "регги",
    "Soul music": "соул",
    Disco: "диско",
    Opera: "опера",
    "Vocal music": "вокал",
    "Dance music": "танц.",
    "Video game music": "игры",
  }
  return map[name] ?? name
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
      parts.push(`жанр: ${t.genres.map(genreRu).join(", ")}`)
    if (t.instruments?.length)
      parts.push(`инструменты: ${t.instruments.join(", ")}`)
    const moods = [
      `весёлость ${Math.round((t.mood_happy ?? 0) * 100)}%`,
      `грусть ${Math.round((t.mood_sad ?? 0) * 100)}%`,
      `спокойствие ${Math.round((t.mood_relaxed ?? 0) * 100)}%`,
      `агрессия ${Math.round((t.mood_aggressive ?? 0) * 100)}%`,
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
  { key: "play_count", label: "просл.", align: "right" },
  { key: "first_listen", label: "первое", align: "right" },
  { key: "last_listen", label: "последнее", align: "right" },
]

export function Tracks() {
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

  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 300)
    return () => clearTimeout(t)
  }, [input])

  const { data: clusters } = useQuery({
    queryKey: ["clusters"],
    queryFn: api.clusters,
  })

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

  const parentRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 60,
    overscan: 10,
  })

  useEffect(() => {
    parentRef.current?.scrollTo({ top: 0 })
  }, [q, sort, order, clusterId, hidden, genre, language, instrumental])

  const sentinelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = sentinelRef.current
    const root = parentRef.current
    if (!el || !root) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { root, rootMargin: "800px 0px" }
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
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Вся музыка</h1>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-md">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            type="search"
            placeholder="Поиск по названию или каналу…"
            className="pl-9"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
        </div>
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
        <Button
          variant={hidden ? "default" : "outline"}
          size="sm"
          onClick={() => setHidden((h) => !h)}
        >
          <EyeOff />
          Исключённые
        </Button>
        <Select
          value={genre || "any"}
          onValueChange={(v) => setGenre(v === "any" ? "" : v)}
        >
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Любой жанр" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Любой жанр</SelectItem>
            {GENRE_OPTIONS.map((g) => (
              <SelectItem key={g} value={g}>
                {genreRu(g)}
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
        <Button
          variant={instrumental ? "default" : "outline"}
          size="sm"
          onClick={() => setInstrumental((v) => !v)}
          title="Только треки без вокала"
        >
          <Music />
          Инструментал
        </Button>
      </div>

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
        <>
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

          <div
            ref={parentRef}
            className="h-[calc(100svh-16rem)] min-h-80 overflow-y-auto rounded-lg border"
          >
            <div
              className={cn(
                GRID,
                "bg-background sticky top-0 z-10 border-b py-2 text-muted-foreground text-xs font-medium whitespace-nowrap"
              )}
            >
              <span>#</span>
              <span />
              <span>Название</span>
              <span>Настроение</span>
              <span className="text-right">BPM</span>
              <span className="text-right">энергия</span>
              <span className="text-right">танц.</span>
              <span className="text-right">акуст.</span>
              {SORT_COLUMNS.map((col) => (
                <button
                  key={col.key}
                  type="button"
                  onClick={() => toggleSort(col.key)}
                  className={cn(
                    "hover:text-foreground flex items-center gap-1 transition-colors",
                    col.align === "right" && "justify-end"
                  )}
                >
                  {col.label}
                  {sort === col.key ? (
                    order === "desc" ? (
                      <ArrowDown className="size-3" />
                    ) : (
                      <ArrowUp className="size-3" />
                    )
                  ) : (
                    <ArrowUpDown className="size-3 opacity-40" />
                  )}
                </button>
              ))}
              <span className="text-right">длит.</span>
              <span className="text-right">действия</span>
            </div>

            <div
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
                      transform: `translateY(${vi.start}px)`,
                    }}
                    className={cn(
                      GRID,
                      "hover:bg-muted/50 border-b border-transparent",
                      vi.index % 2 === 1 && "bg-muted/20"
                    )}
                    title={techTooltip(t)}
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
                        className="bg-muted h-10 w-[71px] rounded object-cover"
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
                          {genreRu(t.genres[0])}
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
                            className="hover:text-destructive size-7"
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
                            className="hover:text-destructive size-7"
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

            <div
              ref={sentinelRef}
              className="flex h-14 items-center justify-center"
            >
              {isFetchingNextPage && (
                <span className="text-muted-foreground text-sm">
                  Загрузка…
                </span>
              )}
              {!hasNextPage && (
                <span className="text-muted-foreground text-sm">
                  Все {total.toLocaleString("ru-RU")} треков загружены
                </span>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
