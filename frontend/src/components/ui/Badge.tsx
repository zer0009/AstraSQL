import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "outline" | "success" | "warning" | "danger";
}

const variants: Record<NonNullable<BadgeProps["variant"]>, string> = {
  default: "bg-zinc-900 text-white border-transparent",
  secondary: "bg-zinc-100 text-zinc-700 border-transparent",
  outline: "bg-transparent text-zinc-700 border-zinc-300",
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  warning: "bg-amber-50 text-amber-700 border-amber-200",
  danger: "bg-red-50 text-red-700 border-red-200",
};

export function Badge({
  className,
  variant = "default",
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium leading-none",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
