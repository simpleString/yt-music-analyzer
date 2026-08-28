import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Square } from "lucide-react"

import { api, type Job, type JobStatus } from "@/lib/api"
import { useStateQuery } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
  lyrics: "Тексты песен",
}

const STATUS_LABELS: Record<JobStatus, string> = {
  pending: "ожидает",
  running: "выполняется",
  done: "готово",
  error: "ошибка",
  cancelled: "остановлено",
}

const STATUS_VARIANTS: Record<
  JobStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  pending: "outline",
  running: "default",
  done: "secondary",
  error: "destructive",
  cancelled: "secondary",
}

export function JobsPanel() {
  const queryClient = useQueryClient()
  const { data } = useStateQuery()

  const cancel = useMutation({
    mutationFn: (kind: string) => api.cancelJob(kind),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["state"] }),
  })

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
      <CardContent className="flex flex-col gap-2.5">
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
              "border border-[#cccccc] p-1.5",
              job.status === "error" && "border-[#cc0000]"
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
              {job.status === "running" && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="hover:text-[#cc0000] h-6 gap-1 px-2 text-xs"
                  disabled={cancel.isPending}
                  title="Остановить задание"
                  onClick={() => cancel.mutate(job.kind)}
                >
                  <Square className="size-3" />
                  Стоп
                </Button>
              )}
            </div>
            {job.total > 0 && (
              <Progress
                className="mt-1.5"
                value={(job.done / job.total) * 100}
              />
            )}
            {job.detail && (
              <p className="text-muted-foreground mt-1.5 text-xs">{job.detail}</p>
            )}
            {job.error && (
              <p className="mt-1.5 text-xs text-[#cc0000]">{job.error}</p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
