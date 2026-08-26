import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function Moods() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["moods"],
    queryFn: api.moods,
  })

  if (isLoading) return <p className="text-muted-foreground">Загрузка…</p>
  if (isError || !data) return <p>Не удалось загрузить данные.</p>

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">
        Плейлисты по настроению
      </h1>

      {data.cards.length === 0 && (
        <Alert>
          <AlertDescription>
            Кластеров нет. Нужны импорт → фильтр → аудио-анализ →
            кластеризация.
          </AlertDescription>
        </Alert>
      )}

      {data.cards.length > 0 && data.analyzed < 20 && (
        <Alert>
          <AlertDescription>
            Проанализировано всего {data.analyzed} треков — плейлисты
            неполные. Запустите «Аудио-анализ» на странице импорта.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {data.cards.map((card) => (
          <Card key={card.cluster.id}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {card.cluster.name}
                <Badge variant="secondary">
                  {card.cluster.size} треков
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="list-decimal space-y-1.5 pl-5">
                {card.tracks.map((t) => (
                  <li key={t.video_id} className="text-sm leading-snug">
                    <a
                      href={`https://www.youtube.com/watch?v=${t.video_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:underline"
                    >
                      {t.title}
                    </a>
                    <span className="text-muted-foreground">
                      {" "}
                      — {t.channel} · {t.play_count} просл.
                    </span>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
