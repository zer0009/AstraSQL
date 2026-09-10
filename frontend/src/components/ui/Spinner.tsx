import { cn } from "../../lib/utils";

export interface SpinnerProps {
  className?: string;
  size?: "sm" | "md" | "lg";
}

const sizes = {
  sm: "h-3.5 w-3.5 border",
  md: "h-5 w-5 border-2",
  lg: "h-7 w-7 border-2",
};

export function Spinner({ className, size = "md" }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block animate-spin rounded-full border-zinc-300 border-t-zinc-700",
        sizes[size],
        className,
      )}
    />
  );
}
