import type { Job, JobStatus } from "@/lib/api"
import { useStateQuery } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"

const KIND_LABELS: Record<Job["kind"], string> = {
  import: "Импорт истории",
  filter: "Фильтр музыки",
  audio: "Аудио-анализ",
  clusters: "Кластеризация",
}

const STATUS_LABELS: Record<JobStatus, string> = {
  pending: "ожидает",
  running: "выполняется",
  done: "готово",
  error: "ошибка",
}

const STATUS_VARIANTS: Record<JobStatus, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  running: "default",
  done: "secondary",
  error: "destructive",
}

export function JobsPanel() {
  const { data } = useStateQuery()
  if (!data) return null

  const { totals, jobs } = data

  return (
    <Card>
      <CardHeader>
        <CardTitle>Задания</CardTitle>
        <CardDescription>
          Обновляется автоматически (1 раз в секунду во время выполнения)
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {totals.tracks_total > 0 && (
          <p className="text-muted-foreground text-sm">
            Прослушиваний музыки:{" "}
            <b className="text-foreground">{totals.music_listens}</b> из{" "}
            {totals.listens_total} · музыкальных треков:{" "}
            <b className="text-foreground">{totals.music_tracks}</b> · оценочное
            время: <b className="text-foreground">{totals.hours_est} ч</b>
            {totals.first_listen && (
              <>
                {" "}
                · период: {totals.first_listen.slice(0, 10)} —{" "}
                {totals.last_listen?.slice(0, 10)}
              </>
            )}
          </p>
        )}
        {jobs.length === 0 && (
          <p className="text-muted-foreground text-sm">
            Заданий пока не было. Начните с импорта истории ниже.
          </p>
        )}
        {jobs.map((job) => (
          <div
            key={job.kind}
            className={cn(
              "rounded-lg border p-3",
              job.status === "error" && "border-destructive/50"
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">
                {KIND_LABELS[job.kind]}
              </span>
              <Badge variant={STATUS_VARIANTS[job.status]}>
                {STATUS_LABELS[job.status]}
              </Badge>
              {job.status === "running" && job.total > 0 && (
                <span className="text-muted-foreground text-xs tabular-nums">
                  {job.done} / {job.total}
                </span>
              )}
            </div>
            {job.total > 0 && (
              <Progress
                className="mt-2"
                value={(job.done / job.total) * 100}
              />
            )}
            {job.detail && (
              <p className="text-muted-foreground mt-2 text-xs">{job.detail}</p>
            )}
            {job.error && (
              <p className="text-destructive mt-2 text-xs">{job.error}</p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
