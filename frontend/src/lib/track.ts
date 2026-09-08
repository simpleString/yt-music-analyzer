import type { TrackListItem } from "@/lib/api"

const REASON_LABELS: [string, string][] = [
  ["yt-music-app", "played in YouTube Music"],
  ["topic-channel", "Topic channel"],
  ["vevo", "VEVO channel"],
  ["api:cat10", "YouTube API: Music category"],
  ["api:too-long", "too long (>12 h, radio stream)"],
  ["api:not-music", "YouTube API: not music"],
  ["api-miss", "YouTube API: video unavailable"],
  ["manual", "manually"],
  ["manual-not-music", "manually: channel hidden"],
  ["anti-pattern", "anti-pattern in title"],
  ["no-signal", "no music signals"],
  ["artist-dash", '"artist - track" title format'],
  ["channel-music", "music channel (voted)"],
  ["channel-not-music", "non-music channel (voted)"],
]

export function reasonLabel(reason: string): string {
  if (!reason) return "—"
  for (const [prefix, label] of REASON_LABELS) {
    if (reason.startsWith(prefix)) return label
  }
  return reason
}

// tooltip input is a subset of TrackListItem: some tables (similar tracks,
// YT radio) only carry a few of these fields; missing lines are skipped
export type TrackTooltipData = Partial<TrackListItem>

export function techTooltip(
  t: TrackTooltipData,
  extra: string[] = [],
): string {
  const parts: string[] = []
  if (t.music_reason) {
    parts.push(`classification: ${reasonLabel(t.music_reason)}`)
  }
  if (t.tempo != null) {
    parts.push(`BPM: ${Math.round(t.tempo ?? 0)}`)
    parts.push(`brightness: ${(t.brightness ?? 0).toFixed(2)}`)
    if (t.key) parts.push(`key: ${t.key}`)
    if (t.loudness != null) parts.push(`loudness: ${t.loudness.toFixed(1)} dB`)
    if (t.dynamics != null) parts.push(`dynamics: ${t.dynamics.toFixed(2)}`)
    if (t.vocal_ratio != null)
      parts.push(`vocals: ${Math.round(t.vocal_ratio * 100)}%`)
    if (t.has_vocals === false) parts.push("vocals: none (whisper-checked)")
    if (t.genres?.length) parts.push(`genres: ${t.genres.join(", ")}`)
    if (t.instruments?.length)
      parts.push(`instruments: ${t.instruments.join(", ")}`)
    const moods: [string, number | null | undefined][] = [
      ["happiness", t.mood_happy],
      ["sadness", t.mood_sad],
      ["calmness", t.mood_relaxed],
      ["aggression", t.mood_aggressive],
      ["electronic", t.mood_electronic],
      ["acoustic", t.mood_acoustic],
      ["party/danceability", t.mood_party],
      ["epicness", t.mood_epic],
      ["darkness", t.mood_dark],
      ["romance", t.mood_romantic],
      ["atmospheric", t.mood_atmospheric],
    ]
    if (moods.some(([, v]) => v != null)) {
      parts.push(
        `mood: ${moods
          .map(([label, v]) => `${label} ${Math.round((v ?? 0) * 100)}%`)
          .join(", ")}`,
      )
    }
    if (t.features_source) {
      parts.push(
        `feature source: ${t.features_source === "audio" ? "audio" : "metadata"}`,
      )
    }
  }
  if (t.language) parts.push(`lyrics language: ${t.language}`)
  parts.push(...extra.filter(Boolean))
  return parts.join("\n")
}
