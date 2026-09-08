import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function artistPath(name: string): string {
  return `/artist/${encodeURIComponent(name)}`
}
