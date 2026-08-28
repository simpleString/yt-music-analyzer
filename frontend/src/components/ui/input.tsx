import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "file:text-foreground placeholder:text-muted-foreground border-2 [border-style:inset] border-[#999999] flex h-7 w-full min-w-0 bg-white px-1.5 py-0.5 text-sm outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 focus:border-[#0000cc] aria-invalid:border-[#cc0000]",
        className
      )}
      {...props}
    />
  )
}

export { Input }
