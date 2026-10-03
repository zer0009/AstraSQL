import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge, Button, Spinner } from "../ui";
import type { ChatMessage } from "../../hooks/useStreamQuery";
import { formatConfidence } from "../../lib/confidence";
import { statusCopy } from "../../lib/ambiguity";
import { AgentSteps } from "./AgentSteps.tsx";
import { FeedbackBar } from "./FeedbackBar.tsx";
import { ResultTabs } from "./ResultTabs.tsx";
import { SQLViewer } from "./SQLViewer.tsx";
import { SuggestedFollowUps } from "./SuggestedFollowUps.tsx";
import { TrustBadge, TrustCard } from "./TrustCard.tsx";

export interface AgentMessageProps {
  message: ChatMessage;
  isStreaming?: boolean;
  isRerunning?: boolean;
  onFollowUp?: (question: string) => void;
  /** Re-ask the natural-language question through the LLM pipeline. */
  onAskAgain?: () => void;
  /** Re-execute SQL directly (no LLM). Optional override for edited SQL. */
  onRerunSql?: (sql?: string) => void;
  /** Retry the same user question after an error. */
  onRetry?: () => void;
}

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

export function AgentMessage({
  message,
  isStreaming = false,
  isRerunning = false,
  onFollowUp,
  onAskAgain,
  onRerunSql,
  onRetry,
}: AgentMessageProps) {
  const confidence = formatConfidence(message.confidence);
  const hasSql = Boolean(message.sql);
  const hasSteps = Boolean(message.steps && message.steps.length > 0);
  const tablesUsed = useMemo(() => tablesFromSteps(message), [message]);
  const hasTables = tablesUsed.length > 0;
  const ambiguityStatus = message.ambiguity?.status;
  const statusInfo = statusCopy(ambiguityStatus);
  const isClarifying =
    message.trustLevel === "clarifying" ||
    Boolean(message.ambiguity?.should_clarify) ||
    ambiguityStatus === "ambiguous";
  const isNonSql =
    ambiguityStatus === "not_a_data_question" ||
    ambiguityStatus === "unanswerable";
  const hasTrust =
    !isNonSql && (hasSql || hasSteps || hasTables || Boolean(message.assumption));
  const [trustOpen, setTrustOpen] = useState(false);

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
    hasSteps ||
    Boolean(message.clarificationOptions?.length);

  const clarificationOptions = message.clarificationOptions ?? [];
  const showClarifications =
    !isRerunning && clarificationOptions.length > 0 && Boolean(onFollowUp);
  // Show clarification options as soon as they arrive (including late in stream).
  const showClarificationsNow =
    showClarifications && (!isStreaming || clarificationOptions.length > 0);

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[95%] space-y-3">
        <div className="flex flex-wrap items-center gap-2">
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
          <TrustBadge
            level={message.trustLevel}
            usedGolden={message.usedGolden}
            ambiguityStatus={ambiguityStatus}
          />
          {isStreaming || isRerunning ? <Spinner size="sm" /> : null}
        </div>

        {message.error ? (
          <div className="space-y-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <p>{message.error}</p>
            {onRetry && !isStreaming ? (
              <Button type="button" size="sm" variant="outline" onClick={onRetry}>
                Retry
              </Button>
            ) : null}
          </div>
        ) : null}

        {statusInfo && ambiguityStatus !== "clear" ? (
          <div
            className={
              isClarifying
                ? "rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
                : "rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-700"
            }
            role={isClarifying ? "status" : undefined}
          >
            <p className="font-medium">{statusInfo.title}</p>
            {statusInfo.body ? (
              <p className="mt-0.5 text-xs opacity-90">{statusInfo.body}</p>
            ) : null}
            {message.ambiguity?.decision_why ? (
              <p className="mt-1 text-[11px] text-zinc-500">
                Why: {message.ambiguity.decision_why}
              </p>
            ) : null}
          </div>
        ) : null}

        {message.content ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-800">
            {message.content}
          </p>
        ) : isStreaming && !showBody ? (
          <p className="text-sm text-zinc-500" aria-live="polite">
            Working…
          </p>
        ) : null}

        {!isStreaming || message.assumption || message.keyFinding ? (
          <TrustCard
            assumption={message.assumption}
            keyFinding={message.keyFinding}
            decisionWhy={message.ambiguity?.decision_why}
            usedGolden={message.usedGolden}
            onChangeAssumption={
              ambiguityStatus === "assumed" && onFollowUp
                ? () =>
                    onFollowUp(
                      "Please ask me which interpretation to use instead of assuming.",
                    )
                : undefined
            }
          />
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
              aria-expanded={trustOpen}
              onClick={() => setTrustOpen((v) => !v)}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-medium text-zinc-600 hover:bg-zinc-100/80"
            >
              {trustOpen ? (
                <ChevronDown className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
              )}
              How this was answered
              {hasTables && !trustOpen ? (
                <span className="ml-1 font-normal text-zinc-400">
                  · {tablesUsed.length} table
                  {tablesUsed.length === 1 ? "" : "s"}
                </span>
              ) : null}
              {message.usedGolden ? (
                <Badge variant="warning" className="ml-auto">
                  Used saved answer
                </Badge>
              ) : null}
            </button>
            {trustOpen ? (
              <div className="space-y-2 border-t border-zinc-200 bg-white p-2.5">
                {hasTables ? (
                  <div className="space-y-1.5">
                    <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
                      Tables used
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {tablesUsed.map((table) => (
                        <span
                          key={table}
                          className="rounded-md border border-zinc-200 bg-zinc-50 px-2 py-0.5 font-mono text-[11px] text-zinc-700"
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
                  <AgentSteps
                    steps={message.steps!}
                    isStreaming={isStreaming}
                  />
                ) : null}
                {message.usage?.total_cost_usd != null ? (
                  <p className="text-[11px] text-zinc-400">
                    Est. cost $
                    {Number(message.usage.total_cost_usd).toFixed(4)}
                    {message.usage.total_latency_ms != null
                      ? ` · ${Math.round(Number(message.usage.total_latency_ms))} ms`
                      : ""}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {!isStreaming && !isRerunning && message.historyId ? (
          <FeedbackBar historyId={message.historyId} sql={message.sql} />
        ) : null}

        {showClarificationsNow ? (
          <SuggestedFollowUps
            label={isClarifying ? "Choose one:" : "Did you mean?"}
            questions={clarificationOptions}
            onSelect={onFollowUp!}
            variant={isClarifying ? "clarify" : "default"}
          />
        ) : null}

        {!isStreaming &&
        !isRerunning &&
        message.followUps &&
        message.followUps.length > 0 &&
        onFollowUp ? (
          <SuggestedFollowUps
            label="Suggested follow-ups"
            questions={message.followUps}
            onSelect={onFollowUp}
          />
        ) : null}
      </div>
    </div>
  );
}
