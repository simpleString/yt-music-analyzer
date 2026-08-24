import { useQuery } from "@tanstack/react-query"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts"

import { api } from "@/lib/api"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import {
  Table,
  TableBody,
  TableData,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const chartConfig = {
  listens: { label: "прослушивания" },
}

export function Dashboard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
  })

  if (isLoading) return <p className="text-muted-foreground">Загрузка…</p>
  if (isError || !data) return <p>Не удалось загрузить данные.</p>

  if (!data.totals.music_listens) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-2xl font-semibold tracking-tight">Дашборд</h1>
        <Alert>
          <AlertDescription>
            Нет данных. Сначала импортируйте историю и запустите фильтр музыки.
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const months = data.by_month.map(([m, v]) => ({ month: m, listens: v }))
  const hours = data.by_hour.map(([h, v]) => ({ hour: `${h}:00`, listens: v }))
  const weekdays = data.by_weekday.map(([d, v]) => ({ day: d, listens: v }))

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Дашборд</h1>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Топ исполнителей</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Канал</TableHead>
                  <TableHead>просл.</TableHead>
                  <TableHead>треков</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.top_artists.map((a, i) => (
                  <TableRow key={a.channel}>
                    <TableData className="text-muted-foreground tabular-nums">
                      {i + 1}
                    </TableData>
                    <TableData>{a.channel}</TableData>
                    <TableData className="tabular-nums">{a.plays}</TableData>
                    <TableData className="tabular-nums">{a.tracks}</TableData>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Топ треков</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Название</TableHead>
                  <TableHead>просл.</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.top_tracks.map((t, i) => (
                  <TableRow key={t.video_id}>
                    <TableData className="text-muted-foreground tabular-nums">
                      {i + 1}
                    </TableData>
                    <TableData className="max-w-[22rem] truncate">
                      <a
                        href={`https://www.youtube.com/watch?v=${t.video_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:underline"
                      >
                        {t.title}
                      </a>
                      <span className="text-muted-foreground block truncate text-xs">
                        {t.channel}
                      </span>
                    </TableData>
                    <TableData className="tabular-nums">{t.plays}</TableData>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Динамика по месяцам</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer
            config={chartConfig}
            className="aspect-auto h-72 w-full"
          >
            <LineChart data={months}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="month"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={24}
              />
              <YAxis width={36} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Line
                dataKey="listens"
                type="monotone"
                stroke="var(--chart-1)"
                fill="var(--chart-1)"
                fillOpacity={0.15}
                dot={false}
                strokeWidth={2}
              />
            </LineChart>
          </ChartContainer>
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>По часам суток</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartContainer
              config={chartConfig}
              className="aspect-auto h-56 w-full"
            >
              <BarChart data={hours}>
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="hour"
                  tickLine={false}
                  axisLine={false}
                  tickMargin={8}
                  minTickGap={16}
                />
                <YAxis width={36} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="listens" fill="var(--chart-2)" radius={4} />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>По дням недели</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartContainer
              config={chartConfig}
              className="aspect-auto h-56 w-full"
            >
              <BarChart data={weekdays}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="day" tickLine={false} axisLine={false} />
                <YAxis width={36} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="listens" fill="var(--chart-4)" radius={4} />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
