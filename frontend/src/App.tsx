import { Route, Routes } from "react-router-dom"

import { Layout } from "@/components/Layout"
import { Dashboard } from "@/pages/Dashboard"
import { ImportPage } from "@/pages/Import"
import { Moods } from "@/pages/Moods"
import { TrackCard } from "@/pages/TrackCard"
import { Tracks } from "@/pages/Tracks"

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Tracks />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="moods" element={<Moods />} />
        <Route path="track/:videoId" element={<TrackCard />} />
      </Route>
    </Routes>
  )
}
