import { Route, Routes } from "react-router-dom"

import { Layout } from "@/components/Layout"
import { Dashboard } from "@/pages/Dashboard"
import { ImportPage } from "@/pages/Import"
import { Moods } from "@/pages/Moods"
import { Recommendations } from "@/pages/Recommendations"
import { Tracks } from "@/pages/Tracks"

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Tracks />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="moods" element={<Moods />} />
        <Route path="recommendations" element={<Recommendations />} />
      </Route>
    </Routes>
  )
}
