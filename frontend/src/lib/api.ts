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
  | "mb-genres"
  | "sessions"
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

export interface TrackErrorItem {
  stage: string
  error: string
  created_at: string
}

export interface TrackDetail {
  video_id: string
  title: string
  channel: string
  artist?: string
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
  ytm?: YtmMeta | null
  errors?: TrackErrorItem[]
}

export interface TrackListItem {
  video_id: string
  title: string
  channel: string
  artist?: string
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
  has_error?: boolean
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
  key: string
  mood?: string
  instrumental: boolean
  artist?: string
  errors?: boolean
}

export interface ProcessingErrorItem {
  video_id: string
  title: string
  channel: string
  artist: string
  stage: string
  error: string
  created_at: string
}

export interface ArtistTopTrack {
  video_id: string
  title: string
  channel: string
  plays: number
}

export interface MbLifeSpan {
  begin: string
  end: string
  ended: boolean
}

export interface MbTag {
  name: string
  count: number
}

export interface MbInfo {
  mbid: string
  name: string
  disambiguation: string
  country: string
  area: string
  type: string
  life_span: MbLifeSpan
  genres: MbTag[]
  tags: MbTag[]
}

export interface ArtistSummary {
  name: string
  plays: number
  tracks: number
  first_listen: string | null
  last_listen: string | null
  top_track: ArtistTopTrack
  mb: MbInfo | null
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

export interface MoodCount {
  name: string
  count: number
}

export interface KeyOption {
  key: string
  count: number
}

export interface ArtistListItem {
  channel: string
  plays: number
  tracks: number
  last_listen: string | null
  genre?: string
  top_video_id?: string
}

export interface KpiValue {
  value: number
  prev: number | null
}

export interface DashboardKpi {
  listens: KpiValue
  hours: KpiValue
  artists: KpiValue
  tracks: KpiValue
}

export interface NewArtist {
  name: string
  plays: number
  top_video_id: string
}

export interface NewTrack {
  video_id: string
  title: string
  channel: string
  artist: string
  plays: number
  duration: number | null
  tempo: number | null
  energy: number | null
  info?: TrackExtraInfo | null
}

export interface Discoveries {
  new_artists_total: number
  top_new_artists: NewArtist[]
  new_tracks_total: number
  top_new_tracks: NewTrack[]
}

export interface GenreCount {
  name: string
  listens: number
}

export interface AvgFeatures {
  tempo: number | null
  energy: number | null
  danceability: number | null
  acousticness: number | null
  brightness: number | null
  coverage: number
}

export interface MoodPoint {
  happy: number
  sad: number
  relaxed: number
  party: number
  listens: number
}

export interface VocalSplit {
  vocal: number
  instrumental: number
  coverage: number
}

export interface DashboardData {
  totals: Totals
  kpi: DashboardKpi
  genre_distribution: GenreCount[]
  genre_coverage: number
  avg_features: AvgFeatures
  mood_profile: Record<string, number>
  by_key: [string, number][]
  vocal_split: VocalSplit
  language_distribution: [string, number][]
  mood_trend: [string, MoodPoint][]
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
  artist?: string
  play_count: number
}

export interface SimilarTrack {
  track: TrackInfo
  tempo: number
  distance: number
  match: string
  info?: TrackExtraInfo | null
}

export interface TrackExtraInfo {
  cluster: string
  genre?: string
  language?: string
  tempo: number | null
  energy: number | null
  danceability: number | null
  acousticness: number | null
  duration: number | null
}

export interface SimilarArtist {
  channel: string
  distance: number
  tracks_analyzed: number
  tracks_total: number
  plays: number
  top_video_id?: string
}

export interface LbArtist {
  name: string
  mbid: string
  comment: string
  type: string
  score: number
  plays: number
  in_history: boolean
}

export interface RecommendationsData {
  options: { track: TrackInfo }[]
  selected: TrackInfo | null
  similar_artists: SimilarArtist[] | null
  lb_artists: LbArtist[]
  lb_error: string
}

export interface HistoryPairItem {
  track: TrackInfo
  cnt: number
  last_listen: string | null
  score: number
  p?: number
  info?: TrackExtraInfo | null
}

export interface HistoryRecsData {
  built: boolean
  items: HistoryPairItem[]
  total: number
}

export interface MixableItem {
  track: TrackInfo
  key: string
  camelot: string
  tempo: number
  tempo_delta: number
  relation: "same" | "relative" | "energy-up" | "energy-down"
  info?: TrackExtraInfo | null
}

export interface MixableData {
  available: boolean
  seed: { key: string; camelot: string; tempo: number }
  items: MixableItem[]
  total: number
}

export interface ContextItem {
  track: TrackInfo
  plays: number
  at_hour: number
  at_weekday: number
  score: number
  reason: string
  info?: TrackExtraInfo | null
}

export interface ContextData {
  hour: number
  weekday: number
  total: number
  items: ContextItem[]
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
  info?: TrackExtraInfo | null
}

export interface YtmMeta {
  album: string
  year: string
  artists: { name: string }[]
  thumbnail: string
}

export interface YtmHistoryInfo {
  play_count: number
  cluster: string
  genre: string
  language: string
  first_listen: string | null
  last_listen: string | null
  duration: number | null
  tempo?: number | null
  energy?: number | null
  danceability?: number | null
  acousticness?: number | null
  match?: number
}

export interface YtmSimilarTrack {
  video_id: string
  title: string
  artist: string
  album: string
  year: string
  thumbnail: string
  duration: number | null
  in_history?: boolean
  info?: YtmHistoryInfo | null
}

export interface YtmSimilarData {
  enabled: boolean
  similar: YtmSimilarTrack[]
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
    key,
    mood,
    instrumental,
    artist,
    errors: errorsOnly,
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
    if (key) sp.set("key", key)
    if (mood) sp.set("mood", mood)
    if (instrumental) sp.set("instrumental", "true")
    if (artist) sp.set("artist", artist)
    if (errorsOnly) sp.set("errors", "true")
    return getJson<TracksData>(`/api/tracks?${sp}`)
  },
  artist: (name: string) =>
    getJson<ArtistSummary>(`/api/artist?name=${encodeURIComponent(name)}`),
  artists: () => getJson<ArtistListItem[]>("/api/artists"),
  clusters: () => getJson<ClusterOption[]>("/api/clusters"),
  genres: () => getJson<GenreOption[]>("/api/genres"),
  languages: () => getJson<LanguageOption[]>("/api/languages"),
  keys: () => getJson<KeyOption[]>("/api/keys"),
  errors: () => getJson<ProcessingErrorItem[]>("/api/errors"),
  moodCounts: () => getJson<MoodCount[]>("/api/mood-counts"),
  discoveries: (
    artistsLimit = 8,
    tracksLimit = 8,
    from?: string | null,
    to?: string | null
  ) => {
    const sp = new URLSearchParams({
      artists_limit: String(artistsLimit),
      tracks_limit: String(tracksLimit),
    })
    if (from) sp.set("date_from", from)
    if (to) sp.set("date_to", to)
    return getJson<Discoveries>(`/api/discoveries?${sp}`)
  },
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
  youtubeSimilar: (videoId: string) =>
    getJson<YtmSimilarData>(
      `/api/tracks/${encodeURIComponent(videoId)}/youtube-similar`
    ),
  coListened: (videoId: string, limit = 10) =>
    getJson<HistoryRecsData>(
      `/api/tracks/${encodeURIComponent(videoId)}/co-listened?limit=${limit}`
    ),
  nextTracks: (videoId: string, limit = 10) =>
    getJson<HistoryRecsData>(
      `/api/tracks/${encodeURIComponent(videoId)}/next?limit=${limit}`
    ),
  mixable: (videoId: string, limit = 12) =>
    getJson<MixableData>(
      `/api/tracks/${encodeURIComponent(videoId)}/mixable?limit=${limit}`
    ),
  contextRecs: (limit = 12, from?: string | null, to?: string | null) => {
    const now = new Date()
    const sp = new URLSearchParams({
      hour: String(now.getHours()),
      weekday: String((now.getDay() + 6) % 7),
      limit: String(limit),
      tz: browserTimezone(),
    })
    if (from) sp.set("date_from", from)
    if (to) sp.set("date_to", to)
    return getJson<ContextData>(`/api/recommendations/context?${sp}`)
  },
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
  runMbGenres: () => postForm("/api/pipeline/mb-genres", new FormData()),
  runSessions: () => postForm("/api/pipeline/sessions", new FormData()),
  cancelJob: (kind: string) =>
    postJson(`/api/jobs/${encodeURIComponent(kind)}/cancel`, {}),
  trackDetail: (videoId: string) =>
    getJson<TrackDetail>(`/api/tracks/${encodeURIComponent(videoId)}`),
  trackLyrics: (videoId: string) =>
    getJson<{ track_id: string; text: string; synced: boolean; source: string; language: string; sentiment: number }>(
      `/api/tracks/${encodeURIComponent(videoId)}/lyrics`
    ),
  analyzeTrack: (videoId: string) =>
    postJson<{ ok: boolean; status: string }>(
      `/api/tracks/${encodeURIComponent(videoId)}/analyze`,
      {}
    ),
  analyzeStatus: (videoId: string) =>
    getJson<{ status?: string; detail?: string }>(
      `/api/tracks/${encodeURIComponent(videoId)}/analyze-status`
    ),
  settings: () => getJson<{ fields: SettingsField[] }>("/api/settings"),
  saveSettings: (values: SettingsValues) =>
    postJson("/api/settings", values),
}
