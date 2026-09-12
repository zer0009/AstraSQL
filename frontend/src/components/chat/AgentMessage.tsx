import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge, Spinner } from "../ui";
import type { ChatMessage } from "../../hooks/useStreamQuery";
import { AgentSteps } from "./AgentSteps.tsx";
import { FeedbackBar } from "./FeedbackBar.tsx";
import { ResultTabs } from "./ResultTabs.tsx";
import { SQLViewer } from "./SQLViewer.tsx";
import { SuggestedFollowUps } from "./SuggestedFollowUps.tsx";

export interface AgentMessageProps {
  message: ChatMessage;
  isStreaming?: boolean;
  isRerunning?: boolean;
  onFollowUp?: (question: string) => void;
  /** Re-ask the natural-language question through the LLM pipeline. */
  onAskAgain?: () => void;
  /** Re-execute SQL directly (no LLM). Optional override for edited SQL. */
  onRerunSql?: (sql?: string) => void;
}

function formatConfidence(value: string | number | undefined): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") {
    if (value >= 0.8) return "HIGH";
    if (value >= 0.4) return "MEDIUM";
    return "LOW";
  }
  return String(value).toUpperCase();
}

export function AgentMessage({
  message,
  isStreaming = false,
  isRerunning = false,
  onFollowUp,
  onAskAgain,
  onRerunSql,
}: AgentMessageProps) {
  const confidence = formatConfidence(message.confidence);
  const hasSql = Boolean(message.sql);
  const hasSteps = Boolean(message.steps && message.steps.length > 0);
  const hasTrust = hasSql || hasSteps;
  const [trustOpen, setTrustOpen] = useState(false);

  // Auto-open trust panel while the agent is actively working so progress is visible.
  useEffect(() => {
    if (isStreaming && hasSteps) {
      setTrustOpen(true);
    }
  }, [isStreaming, hasSteps]);

  const showBody =
    Boolean(message.content) ||
    Boolean(message.sql) ||
    Boolean(message.results) ||
    Boolean(message.error) ||
    hasSteps;

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[95%] space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
            Assistant
          </span>
          {confidence ? (
            <Badge
              variant={
                confidence === "HIGH"
                  ? "success"
                  : confidence === "MEDIUM"
                    ? "warning"
                    : "secondary"
              }
            >
              {confidence}
            </Badge>
          ) : null}
          {isStreaming || isRerunning ? <Spinner size="sm" /> : null}
        </div>

        {message.error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {message.error}
          </div>
        ) : null}

        {message.content ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-800">
            {message.content}
          </p>
        ) : isStreaming && !showBody ? (
          <p className="text-sm text-zinc-500">Working…</p>
        ) : null}

        {message.results && message.results.columns.length > 0 ? (
          <ResultTabs results={message.results} />
        ) : null}

        {isRerunning && message.results == null ? (
          <p className="text-sm text-zinc-500">Executing saved SQL…</p>
        ) : null}

        {hasTrust ? (
          <div className="overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50/60">
            <button
              type="button"
              onClick={() => setTrustOpen((v) => !v)}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-medium text-zinc-600 hover:bg-zinc-100/80"
            >
              {trustOpen ? (
                <ChevronDown className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
              )}
              How this was answered
            </button>
            {trustOpen ? (
              <div className="space-y-2 border-t border-zinc-200 bg-white p-2.5">
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
                  <AgentSteps
                    steps={message.steps!}
                    isStreaming={isStreaming}
                  />
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {!isStreaming && !isRerunning && message.historyId ? (
          <FeedbackBar historyId={message.historyId} sql={message.sql} />
        ) : null}

        {!isStreaming &&
        !isRerunning &&
        message.followUps &&
        message.followUps.length > 0 &&
        onFollowUp ? (
          <SuggestedFollowUps
            questions={message.followUps}
            onSelect={onFollowUp}
          />
        ) : null}
      </div>
    </div>
  );
}
