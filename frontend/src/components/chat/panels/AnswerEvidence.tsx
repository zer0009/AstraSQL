import { useEffect, useMemo, useState } from "react";
import type { ChatMessage } from "../../../hooks/useStreamQuery";
import { formatConfidence } from "../../../lib/confidence";
import { AgentSteps } from "../AgentSteps";
import { SQLViewer } from "../SQLViewer";
import type { AgentMessageActions } from "../types";
import { Disclosure } from "./Disclosure";

function tablesFromSteps(message: ChatMessage): string[] {
  const steps = message.steps ?? [];
  for (let i = steps.length - 1; i >= 0; i--) {
    const step = steps[i];
    if (step.tables && step.tables.length > 0) {
      return step.tables;
    }
  }
  return [];
}

export function AnswerEvidence({
  message,
  isStreaming = false,
  isRerunning = false,
  isNonSql = false,
  onAskAgain,
  onRerunSql,
}: {
  message: ChatMessage;
  isStreaming?: boolean;
  isRerunning?: boolean;
  isNonSql?: boolean;
  onAskAgain?: AgentMessageActions["onAskAgain"];
  onRerunSql?: AgentMessageActions["onRerunSql"];
}) {
  const hasSql = Boolean(message.sql);
  const hasSteps = Boolean(message.steps && message.steps.length > 0);
  const tablesUsed = useMemo(() => tablesFromSteps(message), [message]);
  const hasTables = tablesUsed.length > 0;
  const confidence = formatConfidence(message.confidence);
  const visible =
    !isNonSql &&
    (hasSql || hasSteps || hasTables || Boolean(message.assumption));

  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (isStreaming && hasSteps) {
      setOpen(true);
    }
  }, [isStreaming, hasSteps]);

  if (!visible) return null;

  const summary =
    hasTables && !open
      ? `· ${tablesUsed.length} table${tablesUsed.length === 1 ? "" : "s"}`
      : null;

  return (
    <Disclosure
      title="How this was answered"
      open={open}
      onOpenChange={setOpen}
      summary={summary}
    >
      {confidence ? (
        <p className="text-[11px] text-[var(--text-muted)]">
          Confidence: {confidence}
        </p>
      ) : null}
      {hasTables ? (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            Tables used
          </p>
          <div className="flex flex-wrap gap-1.5">
            {tablesUsed.map((table) => (
              <span
                key={table}
                className="rounded-md border border-[var(--border)] bg-[var(--surface-muted)] px-2 py-0.5 font-mono text-[11px] text-zinc-700"
              >
                {table}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {message.sql ? (
        <SQLViewer
          sql={message.sql}
          onAskAgain={onAskAgain}
          onRerunSql={onRerunSql}
          isRerunning={isRerunning}
          defaultExpanded={false}
        />
      ) : null}
      {hasSteps ? (
        <AgentSteps steps={message.steps!} isStreaming={isStreaming} />
      ) : null}
      {message.usage?.total_cost_usd != null ? (
        <p className="text-[11px] text-[var(--text-muted)]">
          Est. cost ${Number(message.usage.total_cost_usd).toFixed(4)}
          {message.usage.total_latency_ms != null
            ? ` · ${Math.round(Number(message.usage.total_latency_ms))} ms`
            : ""}
        </p>
      ) : null}
    </Disclosure>
  );
}
