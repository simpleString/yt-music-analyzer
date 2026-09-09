import { useEffect, useRef, useState, type ReactNode } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Square } from "lucide-react"

import { api, type JobKind, useStateQuery } from "@/lib/api"
import { ErrorsPanel } from "@/components/ErrorsPanel"
import { JobsPanel } from "@/components/JobsPanel"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"

function StopButton({
  kind,
  pending,
  onCancel,
}: {
  kind: JobKind
  pending: boolean
  onCancel: (kind: JobKind) => void
}) {
  return (
    <Button
      type="button"
      variant="outline"
      disabled={pending}
      onClick={() => onCancel(kind)}
    >
      <Square className="size-3" />
      Stop
    </Button>
  )
}

export function ImportPage() {
  const queryClient = useQueryClient()
  const { data: state } = useStateQuery()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState("")
  const [info, setInfo] = useState("")

  const prevStatuses = useRef<Record<string, string>>({})
  useEffect(() => {
    if (!state) return
    const statuses = Object.fromEntries(
      state.jobs.map((j) => [j.kind, j.status])
    )
    const justFinished = Object.entries(statuses).some(
      ([kind, status]) =>
        status === "done" &&
        ["running", "pending"].includes(prevStatuses.current[kind])
    )
    prevStatuses.current = statuses
    if (justFinished) queryClient.invalidateQueries()
  }, [state, queryClient])

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["state"] })

  const importFile = useMutation({
    mutationFn: api.importFile,
    onSuccess: () => {
      setError("")
      if (fileInputRef.current) fileInputRef.current.value = ""
      invalidate()
    },
    onError: (e) => setError(e.message),
  })

  const pipeline = useMutation({
    mutationFn: (kind: Exclude<JobKind, "import">) => {
      if (kind === "filter") return api.runFilter()
      if (kind === "audio") return api.runAudio()
      if (kind === "clusters") return api.runClusters()
      if (kind === "mb-genres") return api.runMbGenres()
      if (kind === "sessions") return api.runSessions()
      return api.runLyrics()
    },
    onSuccess: invalidate,
    onError: (e) => setError(e.message),
  })

  const retryFailed = useMutation({
    mutationFn: () => api.retryFailedAudio(),
    onSuccess: (r) => {
      setError("")
      setInfo(
        r.reset > 0
          ? `Cleared ${r.reset} unavailable mark(s) — audio analysis restarted`
          : "No unavailable marks — audio analysis restarted",
      )
      invalidate()
    },
    onError: (e) => setError(e.message),
  })

  const cancel = useMutation({
    mutationFn: (kind: JobKind) => api.cancelJob(kind),
    onSuccess: invalidate,
    onError: (e) => setError(e.message),
  })

  const busyKinds = new Set(
    state?.jobs
      .filter((j) => j.status === "running" || j.status === "pending")
      .map((j) => j.kind) ?? []
  )
  const busy = importFile.isPending || pipeline.isPending

  const pipelineButtons: { kind: Exclude<JobKind, "import">; label: ReactNode }[] =
    [
      { kind: "filter", label: "Music filter" },
      {
        kind: "audio",
        label: (
          <>
            Audio analysis{" "}
            {state?.audio_limit
              ? `(top ${state.audio_limit})`
              : "(all tracks)"}
          </>
        ),
      },
      { kind: "clusters", label: "Clustering → playlists" },
      { kind: "lyrics", label: "Lyrics" },
      { kind: "mb-genres", label: "Artist genres (MusicBrainz)" },
      { kind: "sessions", label: "Sessions (co-listened + next)" },
    ]

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-lg font-bold text-black">
        Import and processing
      </h1>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {info && (
        <Alert>
          <AlertDescription>{info}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>1. Watch history (Google Takeout)</CardTitle>
          <CardDescription>
            At takeout.google.com select "My Activity" → its content
            "YouTube" → JSON format, then upload the watch history file
            here
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              const file = fileInputRef.current?.files?.[0]
              if (file) importFile.mutate(file)
            }}
          >
            <Input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              required
              className="max-w-sm"
            />
            {busyKinds.has("import") ? (
              <StopButton
                kind="import"
                pending={cancel.isPending}
                onCancel={(k) => cancel.mutate(k)}
              />
            ) : (
              <Button type="submit" disabled={busy}>
                Upload file
              </Button>
            )}
          </form>
        </CardContent>
      </Card>

      <JobsPanel />

      <ErrorsPanel />

      <Card>
        <CardHeader>
          <CardTitle>2. Pipeline</CardTitle>
          <CardDescription>
            Order: import → filter → audio analysis → clustering.
            {!state?.has_api_key &&
              " No YouTube API key set — the filter relies on heuristics (\"YouTube Music\" header, VEVO/-Topic channels, title patterns)."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-1.5">
          {pipelineButtons.map(({ kind, label }) =>
            busyKinds.has(kind) ? (
              <StopButton
                key={kind}
                kind={kind}
                pending={cancel.isPending}
                onCancel={(k) => cancel.mutate(k)}
              />
            ) : (
              <Button
                key={kind}
                disabled={busy}
                onClick={() => pipeline.mutate(kind)}
              >
                {label}
              </Button>
            )
          )}
          <Button
            variant="outline"
            disabled={busy || retryFailed.isPending}
            onClick={() => {
              setInfo("")
              retryFailed.mutate()
            }}
          >
            Retry failed videos
          </Button>
        </CardContent>
      </Card>

    </div>
  )
}
