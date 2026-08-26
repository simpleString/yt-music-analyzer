import { useQuery } from "@tanstack/react-query"

export const TRACKS_PER_PAGE = 200

export type TrackSort = "play_count" | "first_listen" | "last_listen"
export type SortOrder = "asc" | "desc"

export type JobKind = "import" | "filter" | "audio" | "clusters" | "lyrics"
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

export interface MoodCard {
  cluster: ClusterInfo
  tracks: TrackInfo[]
}

export interface MoodsData {
  analyzed: number
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
  similar: SimilarTrack[]
  similar_artists: SimilarArtist[] | null
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

async function postJson(url: string, body: object): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error((await res.json()).detail ?? res.statusText)
  }
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
  runLyrics: () => postForm("/api/pipeline/lyrics", new FormData()),
  cancelJob: (kind: string) =>
    postJson(`/api/jobs/${encodeURIComponent(kind)}/cancel`, {}),
  trackDetail: (videoId: string) =>
    getJson<TrackDetail>(`/api/tracks/${encodeURIComponent(videoId)}`),
  trackLyrics: (videoId: string) =>
    getJson<{ track_id: string; text: string; synced: boolean; language: string; sentiment: number }>(
      `/api/tracks/${encodeURIComponent(videoId)}/lyrics`
    ),
}
