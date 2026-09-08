import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api } from "@/lib/api";
import { cn, artistPath } from "@/lib/utils";
import { Input } from "@/components/ui/input";

const GRID =
  "grid grid-cols-[2.25rem_minmax(0,1fr)_6rem_6rem_7rem] items-center gap-1.5 px-1.5";

export function Artists() {
  const navigate = useNavigate();
  const [input, setInput] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["artists"],
    queryFn: api.artists,
    staleTime: 60 * 1000,
  });

  const q = input.trim().toLowerCase();
  const rows = useMemo(
    () => (data ?? []).filter((a) => !q || a.channel.toLowerCase().includes(q)),
    [data, q],
  );

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-lg font-bold text-black text-center">Artists</h1>
        <form
          className="flex w-full items-center justify-center gap-1.5"
          onSubmit={(e) => e.preventDefault()}
        >
          <Input
            type="search"
            placeholder="Search artist…"
            className="max-w-md flex-1"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
        </form>

        {isLoading && <p className="text-muted-foreground">Loading…</p>}
        {isError && <p>Failed to load data.</p>}

        {data && (
          <p className="text-muted-foreground text-sm">
            {q ? (
              <>
                Found: <b className="text-foreground">{rows.length}</b> for "
                {input.trim()}"
              </>
            ) : (
              <>
                Total: <b className="text-foreground">{data.length}</b> artists
              </>
            )}
          </p>
        )}
      </div>

      {rows.length > 0 && (
        <div className="border border-[#999999]">
          <div
            className={cn(
              GRID,
              "sticky z-10 min-w-[34rem] border-b border-[#999999] bg-[#eeeeee] py-1 text-xs font-bold text-black whitespace-nowrap",
            )}
            style={{ top: "var(--header-h, 0px)" }}
          >
            <span>#</span>
            <span>Artist</span>
            <span className="text-right">plays</span>
            <span className="text-right">tracks</span>
            <span className="text-right">last listen</span>
          </div>

          {rows.map((a, i) => (
            <div
              key={a.channel}
              className={cn(
                GRID,
                "hover:bg-[#ffffcc] cursor-pointer border-b border-[#e0e0e0] py-1",
              )}
              onClick={() => navigate(artistPath(a.channel))}
            >
              <span className="text-muted-foreground tabular-nums">
                {i + 1}
              </span>
              <span className="truncate text-sm">{a.channel}</span>
              <span className="text-right text-sm tabular-nums">
                {a.plays}
              </span>
              <span className="text-muted-foreground text-right text-sm tabular-nums">
                {a.tracks}
              </span>
              <span className="text-muted-foreground text-right text-sm tabular-nums">
                {a.last_listen?.slice(0, 10) ?? "—"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
