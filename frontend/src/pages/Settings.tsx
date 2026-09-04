import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api, type SettingsValues } from "@/lib/api"
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

export function SettingsPage() {
  const queryClient = useQueryClient()
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings })
  const [values, setValues] = useState<SettingsValues>({})
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (data && Object.keys(values).length === 0) {
      setValues(
        Object.fromEntries(data.fields.map((f) => [f.key, f.value])) as Record<
          string,
          string | number | boolean
        >
      )
    }
  }, [data, values])

  const save = useMutation({
    mutationFn: () => api.saveSettings(values),
    onSuccess: () => {
      setError("")
      setSaved(true)
      queryClient.invalidateQueries({ queryKey: ["settings"] })
      queryClient.invalidateQueries({ queryKey: ["state"] })
    },
    onError: (e) => {
      setSaved(false)
      setError(e.message)
    },
  })

  const set = (key: string, v: string | number | boolean) => {
    setValues((prev) => ({ ...prev, [key]: v }))
    setSaved(false)
  }

  const fields = data?.fields ?? []

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-lg font-bold text-black">Settings</h1>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {saved && (
        <Alert>
          <AlertDescription>
            Saved to .env and applied without a restart.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>.env parameters</CardTitle>
          <CardDescription>
            Changes are written to the .env file and take effect immediately.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {fields.length === 0 && (
            <p className="text-muted-foreground text-sm">Loading…</p>
          )}
          <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
            {fields.map((f) => {
              const v = values[f.key]
              const numeric = f.type === "int" || f.type === "float"
              return (
                <div key={f.key} className="flex flex-col gap-1">
                  {f.type === "bool" ? (
                    <label className="flex h-9 cursor-pointer items-center gap-2 text-sm font-medium">
                      <input
                        type="checkbox"
                        checked={Boolean(v)}
                        onChange={(e) => set(f.key, e.target.checked)}
                      />
                      {f.label}
                    </label>
                  ) : (
                    <>
                      <label
                        htmlFor={f.key}
                        className="text-sm font-medium"
                      >
                        {f.label}
                      </label>
                      <Input
                        id={f.key}
                        type={numeric ? "number" : "text"}
                        step={f.type === "float" ? "0.05" : undefined}
                        className="w-full"
                        value={String(v ?? "")}
                        onChange={(e) =>
                          set(
                            f.key,
                            numeric
                              ? e.target.value === ""
                                ? ""
                                : Number(e.target.value)
                              : e.target.value
                          )
                        }
                      />
                    </>
                  )}
                  {f.hint && (
                    <p className="text-muted-foreground text-xs leading-snug">
                      {f.hint}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
          <div>
            <Button
              disabled={save.isPending || fields.length === 0}
              onClick={() => save.mutate()}
            >
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
