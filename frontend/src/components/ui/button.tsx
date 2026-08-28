import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap text-sm font-normal shrink-0 outline-none focus-visible:border-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "border-2 [border-style:outset] border-[#cccccc] bg-[#cccccc] text-black hover:bg-[#d9d9d9] active:[border-style:inset]",
        destructive:
          "border-2 [border-style:outset] border-[#cccccc] bg-[#cccccc] text-[#cc0000] font-bold hover:bg-[#d9d9d9] active:[border-style:inset]",
        outline:
          "border-2 [border-style:outset] border-[#cccccc] bg-[#cccccc] text-black hover:bg-[#d9d9d9] active:[border-style:inset]",
        secondary:
          "border-2 [border-style:outset] border-[#cccccc] bg-[#eeeeee] text-black hover:bg-[#f5f5f5] active:[border-style:inset]",
        ghost:
          "border-2 border-transparent text-[#0000cc] underline hover:bg-[#ffffcc]",
        link: "text-[#0000cc] underline hover:text-[#ff0000]",
      },
      size: {
        default: "h-7 px-3 py-0.5 has-[>svg]:px-2.5",
        sm: "h-6 gap-1.5 px-2.5 py-0 has-[>svg]:px-2",
        lg: "h-8 px-5 has-[>svg]:px-3.5",
        icon: "size-7",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
