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
        Импорт и обработка
      </h1>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>1. История просмотров (Google Takeout)</CardTitle>
          <CardDescription>
            Файл «История просмотров YouTube» в формате JSON
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
              Загрузить файл
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
              placeholder="или путь к файлу на диске"
              className="max-w-sm"
              value={pathValue}
              onChange={(e) => setPathValue(e.target.value)}
            />
            <Button
              type="submit"
              variant="outline"
              disabled={busy || !state?.root_history_exists}
            >
              Импортировать по пути
            </Button>
          </form>
          {state?.root_history_exists && (
            <p className="text-muted-foreground text-sm">
              В корне проекта найден <code>{state.root_json_name}</code> — можно
              импортировать его.
            </p>
          )}
        </CardContent>
      </Card>

      <JobsPanel />

      <Card>
        <CardHeader>
          <CardTitle>2. Конвейер</CardTitle>
          <CardDescription>
            Порядок: импорт → фильтр → аудио-анализ → кластеризация.
            {!state?.has_api_key &&
              " YouTube API-ключ не задан — фильтр работает на эвристиках (header «YouTube Музыка», VEVO/-Topic каналы, паттерны названий)."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-1.5">
          <Button
            disabled={busy || busyKinds.has("filter")}
            onClick={() => pipeline.mutate("filter")}
          >
            Фильтр музыки
          </Button>
          <Button
            disabled={busy || busyKinds.has("audio")}
            onClick={() => pipeline.mutate("audio")}
          >
            Аудио-анализ{" "}
            {state?.audio_limit
              ? `(топ ${state.audio_limit})`
              : "(все треки)"}
          </Button>
          <Button
            disabled={busy || busyKinds.has("clusters")}
            onClick={() => pipeline.mutate("clusters")}
          >
            Кластеризация → плейлисты
          </Button>
          <Button
            disabled={busy || busyKinds.has("lyrics")}
            onClick={() => pipeline.mutate("lyrics")}
          >
            Тексты песен
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
