import { Route, Routes } from "react-router-dom"

import { Layout } from "@/components/Layout"
import { Dashboard } from "@/pages/Dashboard"
import { Home } from "@/pages/Home"
import { Moods } from "@/pages/Moods"
import { Recommendations } from "@/pages/Recommendations"

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="moods" element={<Moods />} />
        <Route path="recommendations" element={<Recommendations />} />
      </Route>
    </Routes>
  )
}
