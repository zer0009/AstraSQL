import { Badge, Spinner } from "../ui";
import type { ChatMessage } from "../../hooks/useStreamQuery";
import { AgentSteps } from "./AgentSteps.tsx";
import { FeedbackBar } from "./FeedbackBar.tsx";
import { ResultsTable } from "./ResultsTable.tsx";
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
  const showBody =
    Boolean(message.content) ||
    Boolean(message.sql) ||
    Boolean(message.results) ||
    Boolean(message.error) ||
    (message.steps && message.steps.length > 0);

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[95%] space-y-3 rounded-md border border-zinc-200 bg-white px-3.5 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
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

        {message.steps && message.steps.length > 0 ? (
          <AgentSteps steps={message.steps} isStreaming={isStreaming} />
        ) : null}

        {message.error ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
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

        {message.sql ? (
          <SQLViewer
            sql={message.sql}
            onAskAgain={onAskAgain}
            onRerunSql={onRerunSql}
            isRerunning={isRerunning}
          />
        ) : null}

        {message.results && message.results.columns.length > 0 ? (
          <ResultsTable results={message.results} />
        ) : null}

        {isRerunning && message.results == null ? (
          <p className="text-sm text-zinc-500">Executing saved SQL…</p>
        ) : null}

        {!isStreaming && !isRerunning && message.historyId ? (
          <FeedbackBar historyId={message.historyId} />
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
