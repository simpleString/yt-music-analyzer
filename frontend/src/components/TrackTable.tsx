import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { type TrackExtraInfo, type YtmHistoryInfo } from "@/lib/api";
import { artistPath, cn } from "@/lib/utils";
import { TrackBadges } from "@/components/TrackBadges";

function fmtDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TrackTable({
  grid,
  extraHead,
  children,
}: {
  grid: string;
  extraHead?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto border border-[#999999]">
      <div
        className={cn(
          grid,
          "h-12 border-b border-[#999999] bg-[#eeeeee] text-xs font-bold text-black whitespace-nowrap",
        )}
      >
        <span>#</span>
        <span />
        <span>Track</span>
        <span>Mood</span>
        <span className="text-right">BPM</span>
        <span className="text-right">energy</span>
        <span className="text-right">dance.</span>
        <span className="text-right">acoust.</span>
        <span className="text-right">length</span>
        <span className="text-right">plays</span>
        {extraHead}
      </div>
      <div>{children}</div>
    </div>
  );
}

export function TrackRow({
  videoId,
  title,
  channel,
  artist,
  plays,
  info,
  index,
  grid,
  rowClassName,
  rowTitle,
  extra,
  tail,
  asDiv = false,
}: {
  videoId: string;
  title: string;
  channel: string;
  artist?: string;
  plays?: number;
  info?: TrackExtraInfo | YtmHistoryInfo | null;
  index: number;
  grid: string;
  rowClassName?: string;
  rowTitle?: string;
  extra?: ReactNode;
  /** overrides the default [length, plays] cells (used by the YTM table) */
  tail?: ReactNode;
  /** plain div instead of a Link (tracks outside the library, no card) */
  asDiv?: boolean;
}) {
  const sub = artist ?? channel;
  const cells = (
    <>
      <span className="text-muted-foreground tabular-nums">{index + 1}</span>
      <a
        href={`https://www.youtube.com/watch?v=${videoId}`}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={`https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`}
          alt=""
          loading="lazy"
          className="h-10 w-[71px] shrink-0 border border-[#999999] object-cover"
        />
      </a>
      <span className="min-w-0">
        <a
          href={`https://www.youtube.com/watch?v=${videoId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="block truncate text-sm hover:underline max-w-fit"
          title={title}
          onClick={(e) => e.stopPropagation()}
        >
          {title}
        </a>
        {channel ? (
          <Link
            to={artistPath(sub)}
            className="text-muted-foreground block truncate text-xs hover:underline max-w-fit"
          >
            {channel}
          </Link>
        ) : (
          <span className="text-muted-foreground block truncate text-xs">
            {"\u00a0"}
          </span>
        )}
      </span>
      <TrackBadges
        cluster={info?.cluster ?? null}
        genre={info?.genre ?? null}
        language={info?.language ?? null}
      />
      <span className="text-right text-sm tabular-nums">
        {info?.tempo != null ? Math.round(info.tempo) : "—"}
      </span>
      <span className="text-muted-foreground text-right text-sm tabular-nums">
        {info?.energy != null ? info.energy.toFixed(2) : "—"}
      </span>
      <span className="text-muted-foreground text-right text-sm tabular-nums">
        {info?.danceability != null ? info.danceability.toFixed(2) : "—"}
      </span>
      <span className="text-muted-foreground text-right text-sm tabular-nums">
        {info?.acousticness != null ? info.acousticness.toFixed(2) : "—"}
      </span>
      {tail ?? (
        <>
          <span className="text-muted-foreground text-right text-sm tabular-nums">
            {fmtDuration(info?.duration ?? null)}
          </span>
          <span className="text-right text-sm tabular-nums">
            {plays ?? "—"}
          </span>
        </>
      )}
      {extra}
    </>
  );
  const cls = cn(
    grid,
    "text-inherit no-underline hover:text-inherit visited:text-inherit h-12 hover:bg-[#ffffcc] border-b border-[#e0e0e0]",
    rowClassName,
  );
  if (asDiv) {
    return (
      <div className={cls} title={rowTitle}>
        {cells}
      </div>
    );
  }
  return (
    <Link
      to={`/track/${videoId}`}
      className={cls}
      title={rowTitle}
      onClick={() => sessionStorage.setItem("tracks-open-track", videoId)}
    >
      {cells}
    </Link>
  );
}
