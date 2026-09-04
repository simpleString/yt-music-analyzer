import { useEffect, useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { api, type JobKind, useStateQuery } from "@/lib/api"
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

export function ImportPage() {
  const queryClient = useQueryClient()
  const { data: state } = useStateQuery()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [pathValue, setPathValue] = useState("")
  const [error, setError] = useState("")

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

  const importPath = useMutation({
    mutationFn: api.importPath,
    onSuccess: () => {
      setError("")
      invalidate()
    },
    onError: (e) => setError(e.message),
  })

  const pipeline = useMutation({
    mutationFn: (kind: Exclude<JobKind, "import">) => {
      if (kind === "filter") return api.runFilter()
      if (kind === "audio") return api.runAudio()
      if (kind === "clusters") return api.runClusters()
      return api.runLyrics()
    },
    onSuccess: invalidate,
    onError: (e) => setError(e.message),
  })

  const busyKinds = new Set(
    state?.jobs
      .filter((j) => j.status === "running" || j.status === "pending")
      .map((j) => j.kind) ?? []
  )
  const busy = importFile.isPending || importPath.isPending || pipeline.isPending

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

      <Card>
        <CardHeader>
          <CardTitle>1. Watch history (Google Takeout)</CardTitle>
          <CardDescription>
            "YouTube watch history" file in JSON format
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
            <Button type="submit" disabled={busy}>
              Upload file
            </Button>
          </form>
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (pathValue.trim()) importPath.mutate(pathValue.trim())
            }}
          >
            <Input
              type="text"
              placeholder="or a file path on disk"
              className="max-w-sm"
              value={pathValue}
              onChange={(e) => setPathValue(e.target.value)}
            />
            <Button
              type="submit"
              variant="outline"
              disabled={busy || !state?.root_history_exists}
            >
              Import from path
            </Button>
          </form>
          {state?.root_history_exists && (
            <p className="text-muted-foreground text-sm">
              Found <code>{state.root_json_name}</code> in the project root —
              you can import it directly.
            </p>
          )}
        </CardContent>
      </Card>

      <JobsPanel />

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
          <Button
            disabled={busy || busyKinds.has("filter")}
            onClick={() => pipeline.mutate("filter")}
          >
            Music filter
          </Button>
          <Button
            disabled={busy || busyKinds.has("audio")}
            onClick={() => pipeline.mutate("audio")}
          >
            Audio analysis{" "}
            {state?.audio_limit
              ? `(top ${state.audio_limit})`
              : "(all tracks)"}
          </Button>
          <Button
            disabled={busy || busyKinds.has("clusters")}
            onClick={() => pipeline.mutate("clusters")}
          >
            Clustering → playlists
          </Button>
          <Button
            disabled={busy || busyKinds.has("lyrics")}
            onClick={() => pipeline.mutate("lyrics")}
          >
            Lyrics
          </Button>
        </CardContent>
      </Card>

    </div>
  )
}
