import { useEffect, useRef, useState } from "react"

import { type Job, type JobStatus, useStateQuery } from "@/lib/api"
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
  import: "History import",
  filter: "Music filter",
  audio: "Audio analysis",
  clusters: "Clustering",
  lyrics: "Lyrics",
  "mb-genres": "Artist genres",
  sessions: "Listening sessions",
}

const STATUS_LABELS: Record<JobStatus, string> = {
  pending: "pending",
  running: "running",
  done: "done",
  error: "error",
  cancelled: "cancelled",
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
  if (m < 1) return "less than a minute"
  if (m < 60) return `~${m} min`
  const h = Math.floor(m / 60)
  const rest = m % 60
  return `~${h} h${rest ? ` ${rest} min` : ""}`
}

function ageSeconds(updatedAt: string | undefined): number | null {
  if (!updatedAt) return null
  const t = Date.parse(
    updatedAt.endsWith("Z") ? updatedAt : `${updatedAt}Z`
  )
  if (Number.isNaN(t)) return null
  return Math.max(0, Math.round((Date.now() - t) / 1000))
}

/** Processing rate (tracks/sec) from the done-value history over the last minute. */
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

function JobRow({ job }: { job: Job }) {
  const running = job.status === "running"
  // tick every second: the "updated N s ago" label lives between requests
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [running])
  const rate = useJobRate(job.kind, job.done, running)
  const age = running ? ageSeconds(job.updated_at) : null
  const cachedMatch = running ? /cache (\d+)/.exec(job.detail) : null
  const downloadMatch = running ? /download (\d+)/.exec(job.detail) : null
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
            remaining · cache: {cachedMatch[1]}
          </Badge>
        )}
        {running && downloadMatch && (
          <Badge variant="outline" className="text-xs">
            remaining · download: {downloadMatch[1]}
          </Badge>
        )}
        {running && rate != null && (
          <span className="text-muted-foreground text-xs tabular-nums">
            {rate >= 1 / 60
              ? `${Math.max(1, Math.round(rate * 60))} tracks/min`
              : `${rate.toFixed(2)} tracks/sec`}
            {eta && ` · ${eta} remaining`}
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
                ? "No updates for a while — the job may be stuck"
                : undefined
            }
          >
            updated {age} s ago
          </span>
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
  const { data } = useStateQuery()

  if (!data) return null

  const { totals, jobs } = data

  return (
    <Card>
      <CardHeader>
        <CardTitle>Jobs</CardTitle>
        <CardDescription>
          Refreshes automatically (once per second while running)
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5">
        {totals.tracks_total > 0 && (
          <p className="text-muted-foreground text-sm">
            Music listens:{" "}
            <b className="text-foreground">{totals.music_listens}</b> of{" "}
            {totals.listens_total} · music tracks:{" "}
            <b className="text-foreground">{totals.music_tracks}</b> · estimated
            time: <b className="text-foreground">{totals.hours_est} h</b>
            {totals.first_listen && (
              <>
                {" "}
                · period: {totals.first_listen.slice(0, 10)} —{" "}
                {totals.last_listen?.slice(0, 10)}
              </>
            )}
          </p>
        )}
        {jobs.length === 0 && (
          <p className="text-muted-foreground text-sm">
            No jobs yet. Start by importing your history below.
          </p>
        )}
        {jobs.map((job) => (
          <JobRow key={job.kind} job={job} />
        ))}
      </CardContent>
    </Card>
  )
}
