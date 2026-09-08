import { cn } from "@/lib/utils"

/**
 * The app mascot: a music note with a googly eye scanning the ground
 * with a magnifying glass, sparkle on "found". Pure inline SVG;
 * animation classes (.ln-*) live in index.css.
 */
export function NoteLogo({
  size = 30,
  animated = true,
  className,
}: {
  size?: number
  animated?: boolean
  className?: string
}) {
  const cls = (name: string) => (animated ? name : undefined)
  return (
    <svg
      // tight crop around the drawing (content bounds ≈ 21..71 × 15..61),
      // so the note is visually centered in its box
      viewBox="6 10 82 54"
      width={size}
      height={Math.round((size * 54) / 82)}
      className={cn("shrink-0", className)}
      aria-hidden
    >
      {/* ground shadow */}
      <ellipse cx="34" cy="58" rx="17" ry="2.5" fill="#000" opacity="0.08" />

      {/* the note (tilting while searching) */}
      <g className={cls("ln-note")}>
        <path d="M36.8 47 V 15" stroke="#111111" strokeWidth="2.6" fill="none" />
        <path d="M36.8 15 q 11 2 13 13 q -2.5 -7 -13 -6.5 z" fill="#111111" />
        <ellipse
          cx="30"
          cy="48"
          rx="8.2"
          ry="6.2"
          transform="rotate(-15 30 48)"
          fill="#111111"
        />
        {/* googly eye on the head */}
        <circle
          cx="29.5"
          cy="46"
          r="4.4"
          fill="#ffffff"
          stroke="#111111"
          strokeWidth="0.9"
        />
        <circle
          className={cls("ln-pupil")}
          cx="29"
          cy="46.2"
          r="1.9"
          fill="#111111"
        />
      </g>

      {/* magnifying glass (sweeps an arc) */}
      <g className={cls("ln-glass")}>
        <line
          x1="39"
          y1="47"
          x2="51"
          y2="37.5"
          stroke="#555555"
          strokeWidth="3.2"
          strokeLinecap="round"
        />
        <circle
          cx="53"
          cy="35"
          r="8.6"
          fill="#bcd9f5"
          fillOpacity="0.5"
          stroke="#4d4d4d"
          strokeWidth="2.4"
        />
        <path
          d="M48.6 32.4 q 3 -3 6.8 -2.2"
          stroke="#ffffff"
          strokeWidth="1.6"
          fill="none"
          opacity="0.85"
          strokeLinecap="round"
        />
      </g>

      {/* sparkle: "found something!" */}
      <g transform="translate(66 22)">
        <path
          className={cls("ln-sparkle")}
          d="M0 -5 L1.4 -1.4 L5 0 L1.4 1.4 L0 5 L-1.4 1.4 L-5 0 L-1.4 -1.4 Z"
          fill="#ff9900"
        />
      </g>
    </svg>
  )
}

/** Page loader: the searching note alone, no caption. */
export function LoadingNote({
  size = "md",
  className,
}: {
  size?: "sm" | "md"
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex w-full justify-center",
        size === "sm" ? "py-1" : "py-4",
        className,
      )}
      role="status"
      aria-label="Loading"
    >
      <NoteLogo size={size === "sm" ? 40 : 128} />
    </div>
  )
}
