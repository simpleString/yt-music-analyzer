import { useQuery } from "@tanstack/react-query"

export const TRACKS_PER_PAGE = 200

export type TrackSort =
  | "play_count"
  | "first_listen"
  | "last_listen"
  | "duration"
  | "tempo"
  | "energy"
  | "danceability"
  | "acousticness"
export type SortOrder = "asc" | "desc"

export type JobKind =
  | "import"
  | "filter"
  | "audio"
  | "clusters"
  | "lyrics"
export type JobStatus =
  | "pending"
  | "running"
  | "done"
  | "error"
  | "cancelled"

export interface Job {
  kind: JobKind
  status: JobStatus
  total: number
  done: number
  detail: string
  error: string
  updated_at: string
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
}

export interface TagScore {
  name: string
  score: number
}

export interface TrackDetail {
  video_id: string
  title: string
  channel: string
  play_count: number
  duration: number | null
  cluster_id: number | null
  cluster_name: string
  first_listen: string | null
  last_listen: string | null
  music_reason: string
  language: string
  sentiment: number | null
  topic: string
  has_lyrics: boolean
  has_vocals?: boolean | null
  genre_scores: TagScore[]
  instrument_scores: TagScore[]
  tempo?: number | null
  energy?: number | null
  danceability?: number | null
  acousticness?: number | null
  brightness?: number | null
  key?: string
  loudness?: number | null
  dynamics?: number | null
  percussive?: number | null
  vocal_ratio?: number | null
  mood_happy?: number | null
  mood_sad?: number | null
  mood_relaxed?: number | null
  mood_aggressive?: number | null
  mood_electronic?: number | null
  mood_acoustic?: number | null
  mood_party?: number | null
  mood_epic?: number | null
  mood_dark?: number | null
  mood_romantic?: number | null
  mood_atmospheric?: number | null
}

export interface TrackListItem {
  video_id: string
  title: string
  channel: string
  play_count: number
  duration: number | null
  cluster_id: number | null
  cluster_name: string
  first_listen: string | null
  last_listen: string | null
  music_reason: string
  tempo?: number | null
  energy?: number | null
  danceability?: number | null
  acousticness?: number | null
  brightness?: number | null
  key?: string
  loudness?: number | null
  dynamics?: number | null
  percussive?: number | null
  vocal_ratio?: number | null
  has_vocals?: boolean | null
  genres?: string[]
  instruments?: string[]
  language?: string
  sentiment?: number | null
  mood_epic?: number | null
  mood_dark?: number | null
  mood_romantic?: number | null
  mood_atmospheric?: number | null
  mood_happy?: number | null
  mood_sad?: number | null
  mood_relaxed?: number | null
  mood_aggressive?: number | null
  mood_electronic?: number | null
  mood_acoustic?: number | null
  mood_party?: number | null
  features_source?: string
}

export interface TracksData {
  total: number
  page: number
  per_page: number
  tracks: TrackListItem[]
}

export interface TracksParams {
  q: string
  page: number
  sort: TrackSort
  order: SortOrder
  clusterId: number | null
  hidden: boolean
  genre: string
  language: string
  instrumental: boolean
}

export interface ClusterOption {
  id: number
  name: string
  size: number
}

export interface GenreOption {
  name: string
  name_ru: string
  count: number
}

export interface LanguageOption {
  code: string
  count: number
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
  timeline: [string, number][]
}

export interface DashboardParams {
  from: string | null
  to: string | null
  granularity: "month" | "week"
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

export interface MbArtist {
  name: string
  country: string
  tags: string
}

export interface SimilarTrack {
  track: TrackInfo
  tempo: number
  distance: number
  match: string
}

export interface SimilarArtist {
  channel: string
  distance: number
  tracks_analyzed: number
  tracks_total: number
  plays: number
}

export interface RecommendationsData {
  options: { track: TrackInfo }[]
  selected: TrackInfo | null
  similar_artists: SimilarArtist[] | null
  mb_artists: MbArtist[]
  mb_error: string
  mood_name: string
}

export interface EssentiaRecommendationsData {
  similar: EssentiaSimilarTrack[]
  total: number
}

export interface SimilarRecommendationsData {
  similar: SimilarTrack[]
  total: number
}

export interface EssentiaSimilarTrack {
  track: TrackInfo
  distance: number
  match: string
}

export interface SettingsField {
  key: string
  type: "str" | "int" | "float" | "bool"
  label: string
  hint: string
  value: string | number | boolean
}

export type SettingsValues = Record<string, string | number | boolean>

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error((await res.json()).detail ?? res.statusText)
  }
  return res.json() as Promise<T>
}

async function postJson<T = void>(url: string, body: object): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
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

export const browserTimezone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ""
  } catch {
    return ""
  }
}

export const api = {
  tracks: ({
    q,
    page,
    sort,
    order,
    clusterId,
    hidden,
    genre,
    language,
    instrumental,
  }: TracksParams) => {
    const sp = new URLSearchParams({
      q,
      page: String(page),
      per_page: String(TRACKS_PER_PAGE),
      sort,
      order,
    })
    if (clusterId != null) sp.set("cluster_id", String(clusterId))
    if (hidden) sp.set("hidden", "true")
    if (genre) sp.set("genre", genre)
    if (language) sp.set("language", language)
    if (instrumental) sp.set("instrumental", "true")
    return getJson<TracksData>(`/api/tracks?${sp}`)
  },
  clusters: () => getJson<ClusterOption[]>("/api/clusters"),
  genres: () => getJson<GenreOption[]>("/api/genres"),
  languages: () => getJson<LanguageOption[]>("/api/languages"),
  classifyTrack: (videoId: string, isMusic: boolean) =>
    postJson("/api/tracks/" + encodeURIComponent(videoId) + "/classify", {
      is_music: isMusic,
    }),
  hideChannel: (channel: string) =>
    postJson("/api/channels/hide", { channel }),
  dashboard: ({ from, to, granularity }: DashboardParams) => {
    const sp = new URLSearchParams({ granularity })
    if (from) sp.set("date_from", from)
    if (to) sp.set("date_to", to)
    return getJson<DashboardData>(`/api/dashboard?${sp}`)
  },
  recommendations: (trackId: string) =>
    getJson<RecommendationsData>(
      `/api/recommendations${trackId ? `?track_id=${encodeURIComponent(trackId)}` : ""}`
    ),
  recommendationsEssentia: (trackId: string, offset = 0, limit = 6) =>
    getJson<EssentiaRecommendationsData>(
      `/api/recommendations/essentia?track_id=${encodeURIComponent(trackId)}&offset=${offset}&limit=${limit}`
    ),
  recommendationsSimilar: (trackId: string, offset = 0, limit = 6) =>
    getJson<SimilarRecommendationsData>(
      `/api/recommendations/similar?track_id=${encodeURIComponent(trackId)}&offset=${offset}&limit=${limit}`
    ),
  importFile: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    form.append("tz", browserTimezone())
    return postForm("/api/import", form)
  },
  runFilter: () => postForm("/api/pipeline/filter", new FormData()),
  runAudio: () => postForm("/api/pipeline/audio", new FormData()),
  retryFailedAudio: () =>
    postJson<{ ok: boolean; reset: number }>("/api/pipeline/audio-retry", {}),
  runClusters: () => postForm("/api/pipeline/clusters", new FormData()),
  runLyrics: () => postForm("/api/pipeline/lyrics", new FormData()),
  cancelJob: (kind: string) =>
    postJson(`/api/jobs/${encodeURIComponent(kind)}/cancel`, {}),
  trackDetail: (videoId: string) =>
    getJson<TrackDetail>(`/api/tracks/${encodeURIComponent(videoId)}`),
  trackLyrics: (videoId: string) =>
    getJson<{ track_id: string; text: string; synced: boolean; source: string; language: string; sentiment: number }>(
      `/api/tracks/${encodeURIComponent(videoId)}/lyrics`
    ),
  settings: () => getJson<{ fields: SettingsField[] }>("/api/settings"),
  saveSettings: (values: SettingsValues) =>
    postJson("/api/settings", values),
}
