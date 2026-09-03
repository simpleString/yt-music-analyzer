import { useEffect, useRef, useState } from "react"
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

function formatEta(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return ""
  const m = Math.round(seconds / 60)
  if (m < 1) return "меньше минуты"
  if (m < 60) return `~${m} мин`
  const h = Math.floor(m / 60)
  const rest = m % 60
  return `~${h} ч${rest ? ` ${rest} мин` : ""}`
}

function ageSeconds(updatedAt: string | undefined): number | null {
  if (!updatedAt) return null
  const t = Date.parse(
    updatedAt.endsWith("Z") ? updatedAt : `${updatedAt}Z`
  )
  if (Number.isNaN(t)) return null
  return Math.max(0, Math.round((Date.now() - t) / 1000))
}

/** Скорость выполнения (треков/сек) по истории значений done за минуту. */
function useJobRate(kind: string, done: number, active: boolean) {
  const hist = useRef<{ t: number; done: number }[]>([])
  useEffect(() => {
    if (!active) {
      hist.current = []
      return
    }
    const now = Date.now()
    const h = hist.current
    h.push({ t: now, done })
    while (h.length > 2 && now - h[0].t > 60_000) h.shift()
  }, [kind, done, active])
  const h = hist.current
  if (!active || h.length < 2) return null
  const first = h[0]
  const last = h[h.length - 1]
  const dt = (last.t - first.t) / 1000
  const dd = last.done - first.done
  if (dt < 5 || dd <= 0) return null
  return dd / dt
}

function JobRow({
  job,
  onCancel,
  cancelPending,
}: {
  job: Job
  onCancel: (kind: string) => void
  cancelPending: boolean
}) {
  const running = job.status === "running"
  // тик каждую секунду: «обновлено N с назад» живёт между запросами
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [running])
  const rate = useJobRate(job.kind, job.done, running)
  const age = running ? ageSeconds(job.updated_at) : null
  const cachedMatch = running ? /кэш (\d+)/.exec(job.detail) : null
  const downloadMatch = running ? /скачка (\d+)/.exec(job.detail) : null
  const eta =
    running && rate && job.total > job.done
      ? formatEta((job.total - job.done) / rate)
      : ""

  return (
    <div
      className={cn(
        "border border-[#cccccc] p-1.5",
        job.status === "error" && "border-[#cc0000]"
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{KIND_LABELS[job.kind]}</span>
        <Badge variant={STATUS_VARIANTS[job.status]}>
          {STATUS_LABELS[job.status]}
        </Badge>
        {running && job.total > 0 && (
          <span className="text-muted-foreground text-xs tabular-nums">
            {job.done} / {job.total}
          </span>
        )}
        {running && cachedMatch && (
          <Badge variant="outline" className="text-xs">
            осталось · кэш: {cachedMatch[1]}
          </Badge>
        )}
        {running && downloadMatch && (
          <Badge variant="outline" className="text-xs">
            осталось · скачка: {downloadMatch[1]}
          </Badge>
        )}
        {running && rate != null && (
          <span className="text-muted-foreground text-xs tabular-nums">
            {rate >= 1 / 60
              ? `${Math.max(1, Math.round(rate * 60))} тр/мин`
              : `${rate.toFixed(2)} тр/с`}
            {eta && ` · осталось ${eta}`}
          </span>
        )}
        {running && age != null && (
          <span
            className={cn(
              "text-xs tabular-nums",
              age > 30 ? "text-[#cc6600]" : "text-muted-foreground"
            )}
            title={
              age > 30
                ? "Давно нет обновлений — возможно, задание зависло"
                : undefined
            }
          >
            обновлено {age} с назад
          </span>
        )}
        {running && (
          <Button
            variant="ghost"
            size="sm"
            className="hover:text-[#cc0000] h-6 gap-1 px-2 text-xs"
            disabled={cancelPending}
            title="Остановить задание"
            onClick={() => onCancel(job.kind)}
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
  )
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
          <JobRow
            key={job.kind}
            job={job}
            onCancel={(kind) => cancel.mutate(kind)}
            cancelPending={cancel.isPending}
          />
        ))}
      </CardContent>
    </Card>
  )
}
