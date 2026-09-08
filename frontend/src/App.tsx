import { Route, Routes } from "react-router-dom"

import { Layout } from "@/components/Layout"
import { ArtistPage } from "@/pages/Artist"
import { Artists } from "@/pages/Artists"
import { Dashboard } from "@/pages/Dashboard"
import { ImportPage } from "@/pages/Import"
import { SettingsPage } from "@/pages/Settings"
import { TrackCard } from "@/pages/TrackCard"
import { Tracks } from "@/pages/Tracks"

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Tracks />} />
        <Route path="artists" element={<Artists />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="track/:videoId" element={<TrackCard />} />
        <Route path="artist/*" element={<ArtistPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
