import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export function MessageBubble({
  align,
  children,
  className,
  maxWidthClass = "max-w-[95%]",
}: {
  align: "start" | "end";
  children: ReactNode;
  className?: string;
  maxWidthClass?: string;
}) {
  return (
    <div
      className={cn(
        "flex",
        align === "end" ? "justify-end" : "justify-start",
      )}
    >
      <div className={cn("w-full space-y-3", maxWidthClass, className)}>
        {children}
      </div>
    </div>
  );
}
