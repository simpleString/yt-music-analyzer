import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useSearchParams } from "react-router-dom"

import { api } from "@/lib/api"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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

export function Recommendations() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const trackId = searchParams.get("track_id") ?? ""

  const { data, isLoading, isError } = useQuery({
    queryKey: ["recommendations", trackId],
    queryFn: () => api.recommendations(trackId),
  })

  if (isLoading) return <p className="text-muted-foreground">Загрузка…</p>
  if (isError || !data) return <p>Не удалось загрузить данные.</p>

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Рекомендации</h1>

      {data.options.length === 0 ? (
        <Alert>
          <AlertDescription>
            Нет треков с фичами. Запустите «Кластеризация → плейлисты» (создаст
            предварительные оценки) или аудио-анализ.
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Похожие треки</CardTitle>
              <CardDescription>
                nearest neighbors по вектору фич
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-6">
              <Select
                value={trackId || undefined}
                onValueChange={(v) => {
                  queryClient.removeQueries({
                    queryKey: ["recommendations"],
                  })
                  setSearchParams(v ? { track_id: v } : {})
                }}
              >
                <SelectTrigger className="w-full max-w-md">
                  <SelectValue placeholder="Выберите трек" />
                </SelectTrigger>
                <SelectContent>
                  {data.options.map((o) => (
                    <SelectItem key={o.track.video_id} value={o.track.video_id}>
                      {o.track.title.slice(0, 70)} ({o.track.play_count} просл.)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {data.selected && (
                <>
                  <div>
                    <span className="font-medium">{data.selected.title}</span>{" "}
                    <span className="text-muted-foreground">
                      — {data.selected.channel}
                    </span>
                  </div>
                  {data.similar.length > 0 ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-10">#</TableHead>
                          <TableHead>Трек</TableHead>
                          <TableHead>BPM</TableHead>
                          <TableHead>расстояние</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {data.similar.map((s, i) => (
                          <TableRow key={s.track.video_id}>
                            <TableData className="text-muted-foreground tabular-nums">
                              {i + 1}
                            </TableData>
                            <TableData>
                              <a
                                href={`https://www.youtube.com/watch?v=${s.track.video_id}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="hover:underline"
                              >
                                {s.track.title}
                              </a>
                              <span className="text-muted-foreground block text-xs">
                                {s.track.channel}
                              </span>
                            </TableData>
                            <TableData className="tabular-nums">
                              {s.tempo || "—"}
                            </TableData>
                            <TableData className="tabular-nums">
                              {s.distance}
                            </TableData>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <p className="text-muted-foreground text-sm">
                      Пока недостаточно треков для сравнения (нужно ≥ 2
                      проанализированных).
                    </p>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          {data.selected && (
            <Card>
              <CardHeader>
                <CardTitle>Новые исполнители</CardTitle>
                <CardDescription>
                  MusicBrainz
                  {data.mood_name && ` · настроение «${data.mood_name}»`}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {data.mb_error ? (
                  <Alert variant="destructive">
                    <AlertDescription>{data.mb_error}</AlertDescription>
                  </Alert>
                ) : data.mb_artists.length > 0 ? (
                  <ul className="list-disc space-y-1 pl-5">
                    {data.mb_artists.map((a) => (
                      <li key={a.name} className="text-sm">
                        <b>{a.name}</b>
                        {a.country && (
                          <span className="text-muted-foreground">
                            {" "}
                            ({a.country})
                          </span>
                        )}
                        {a.tags && (
                          <span className="text-muted-foreground">
                            {" "}
                            — {a.tags}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-muted-foreground text-sm">
                    Ничего не найдено.
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
