import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "../ui";
import type { AgentStep } from "../../types/api";
import { cn } from "../../lib/utils";

export interface AgentStepsProps {
  steps: AgentStep[];
  isStreaming?: boolean;
}

export function AgentSteps({ steps, isStreaming = false }: AgentStepsProps) {
  const [open, setOpen] = useState(true);

  if (steps.length === 0) return null;

  return (
    <div className="rounded-md border border-zinc-200 bg-zinc-50/80">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-medium text-zinc-600 hover:bg-zinc-100/80"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
        )}
        Steps
        <span className="font-normal text-zinc-400">({steps.length})</span>
      </button>

      {open ? (
        <ul className="space-y-1 border-t border-zinc-200 px-3 py-2">
          {steps.map((step, index) => {
            const isLast = index === steps.length - 1;
            const status =
              isStreaming && isLast
                ? "running"
                : "done";

            return (
              <li
                key={`${step.name}-${index}`}
                className="flex items-start gap-2 py-1"
              >
                <Badge
                  variant={status === "running" ? "warning" : "success"}
                  className="mt-0.5 shrink-0"
                >
                  {status}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p
                    className={cn(
                      "text-xs font-medium text-zinc-800",
                      status === "running" && "text-zinc-900",
                    )}
                  >
                    {step.name}
                  </p>
                  {step.detail ? (
                    <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">
                      {step.detail}
                    </p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
