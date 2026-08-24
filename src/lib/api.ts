import { useQuery } from "@tanstack/react-query"

export type JobKind = "import" | "filter" | "audio" | "clusters"
export type JobStatus = "pending" | "running" | "done" | "error"

export interface Job {
  kind: JobKind
  status: JobStatus
  total: number
  done: number
  detail: string
  error: string
}

export interface Totals {
  tracks_total: number
  music_tracks: number
  listens_total: number
  music_listens: number
  hours_est: number
  first_listen: string | null
  last_listen: string | null
  analyzed: number
}

export interface AppState {
  totals: Totals
  jobs: Job[]
  has_api_key: boolean
  audio_limit: number
  root_history_exists: boolean
  root_json_name: string
}

export interface TopArtist {
  channel: string
  plays: number
  tracks: number
}

export interface TopTrack {
  video_id: string
  title: string
  channel: string
  plays: number
}

export interface DashboardData {
  totals: Totals
  top_artists: TopArtist[]
  top_tracks: TopTrack[]
  by_hour: [string, number][]
  by_weekday: [string, number][]
  by_month: [string, number][]
}

export interface ClusterInfo {
  id: number
  name: string
  size: number
}

export interface TrackInfo {
  video_id: string
  title: string
  channel: string
  play_count: number
}

export interface MoodCard {
  cluster: ClusterInfo
  tracks: TrackInfo[]
}

export interface MoodsData {
  meta_only: boolean
  cards: MoodCard[]
}

export interface MbArtist {
  name: string
  country: string
  tags: string
}

export interface SimilarTrack {
  track: TrackInfo
  tempo: number
  distance: number
}

export interface RecommendationsData {
  options: { track: TrackInfo }[]
  selected: TrackInfo | null
  similar: SimilarTrack[]
  mb_artists: MbArtist[]
  mb_error: string
  mood_name: string
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error((await res.json()).detail ?? res.statusText)
  }
  return res.json() as Promise<T>
}

async function postForm(url: string, form: FormData): Promise<void> {
  const res = await fetch(url, { method: "POST", body: form })
  if (!res.ok) {
    throw new Error((await res.json()).detail ?? res.statusText)
  }
}

export function useStateQuery() {
  return useQuery({
    queryKey: ["state"],
    queryFn: () => getJson<AppState>("/api/state"),
    refetchInterval: (query) =>
      query.state.data?.jobs.some(
        (j) => j.status === "running" || j.status === "pending"
      )
        ? 1000
        : 5000,
  })
}

export const api = {
  dashboard: () => getJson<DashboardData>("/api/dashboard"),
  moods: () => getJson<MoodsData>("/api/moods"),
  recommendations: (trackId: string) =>
    getJson<RecommendationsData>(
      `/api/recommendations${trackId ? `?track_id=${encodeURIComponent(trackId)}` : ""}`
    ),
  importFile: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return postForm("/api/import", form)
  },
  importPath: (path: string) => {
    const form = new FormData()
    form.append("path", path)
    return postForm("/api/import", form)
  },
  runFilter: () => postForm("/api/pipeline/filter", new FormData()),
  runAudio: () => postForm("/api/pipeline/audio", new FormData()),
  runClusters: () => postForm("/api/pipeline/clusters", new FormData()),
}
