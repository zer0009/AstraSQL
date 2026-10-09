import { Button, Spinner } from "../ui";
import type { ChatMessage } from "../../hooks/useStreamQuery";
import { FeedbackBar } from "./actions/FeedbackBar";
import { SuggestedFollowUps } from "./actions/SuggestedFollowUps";
import { MessageBubble } from "./MessageBubble";
import { AnswerEvidence } from "./panels/AnswerEvidence";
import { ResultTabs } from "./results/ResultTabs";
import { AmbiguityBanner } from "./status/AmbiguityBanner";
import { TrustBadge } from "./status/TrustBadge";
import { TrustCard } from "./status/TrustCard";
import { resolveTrustStatus } from "./status/trustStatus";
import type { AgentMessageActions } from "./types";

export interface AgentMessageProps extends AgentMessageActions {
  message: ChatMessage;
  isStreaming?: boolean;
  isRerunning?: boolean;
}

export function AgentMessage({
  message,
  isStreaming = false,
  isRerunning = false,
  onFollowUp,
  onRefine,
  onRemember,
  onAskAgain,
  onRerunSql,
  onRetry,
}: AgentMessageProps) {
  const trust = resolveTrustStatus({
    trustLevel: message.trustLevel,
    usedGolden: message.usedGolden,
    ambiguity: message.ambiguity,
    assumption: message.assumption,
    keyFinding: message.keyFinding,
    error: message.error,
    onFollowUp,
  });

  const showBody =
    Boolean(message.content) ||
    Boolean(message.sql) ||
    Boolean(message.results) ||
    Boolean(message.error) ||
    Boolean(message.steps?.length) ||
    Boolean(message.clarificationOptions?.length);

  const clarificationOptions = message.clarificationOptions ?? [];
  const canRefine = Boolean(onRefine && message.runId);
  const showClarifications =
    !isRerunning &&
    clarificationOptions.length > 0 &&
    (canRefine || Boolean(onFollowUp));
  const showClarificationsNow =
    showClarifications && (!isStreaming || clarificationOptions.length > 0);

  const handleChip = (choice: string) => {
    if (canRefine && message.runId && onRefine) {
      onRefine(message.runId, choice);
      return;
    }
    onFollowUp?.(choice);
  };

  const showTrustCard =
    (!isStreaming || message.assumption || message.keyFinding) &&
    (Boolean(trust.assumption) || Boolean(trust.keyFinding));

  return (
    <MessageBubble align="start">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
          Assistant
        </span>
        <TrustBadge status={trust} />
        {isStreaming || isRerunning ? <Spinner size="sm" /> : null}
      </div>

      {message.error ? (
        <div
          className="space-y-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
        >
          <p>{message.error}</p>
          {onRetry && !isStreaming ? (
            <Button type="button" size="sm" variant="outline" onClick={onRetry}>
              Retry
            </Button>
          ) : null}
        </div>
      ) : null}

      {trust.banner ? <AmbiguityBanner banner={trust.banner} /> : null}

      {message.content ? (
        <p
          className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-800"
          aria-live="polite"
        >
          {message.content}
        </p>
      ) : isStreaming && !showBody ? (
        <p className="text-sm text-[var(--text-muted)]">Working…</p>
      ) : null}

      {showTrustCard ? (
        <TrustCard
          assumption={trust.assumption}
          keyFinding={trust.keyFinding}
          decisionWhy={
            trust.bannerShowsWhy
              ? undefined
              : message.ambiguity?.decision_why
          }
          onChangeAssumption={
            trust.showAssumptionChange && onFollowUp
              ? () =>
                  onFollowUp(
                    "Please ask me which interpretation to use instead of assuming.",
                  )
              : undefined
          }
          onRemember={
            onRemember && message.assumption
              ? () => onRemember(message.assumption!)
              : undefined
          }
        />
      ) : null}

      {message.results && message.results.columns.length > 0 ? (
        <ResultTabs results={message.results} />
      ) : null}

      {isRerunning && message.results == null ? (
        <p className="text-sm text-[var(--text-muted)]">Executing saved SQL…</p>
      ) : null}

      <AnswerEvidence
        message={message}
        isStreaming={isStreaming}
        isRerunning={isRerunning}
        isNonSql={trust.isNonSql}
        onAskAgain={onAskAgain}
        onRerunSql={onRerunSql}
      />

      {!isStreaming && !isRerunning && message.historyId ? (
        <FeedbackBar historyId={message.historyId} sql={message.sql} />
      ) : null}

      {showClarificationsNow ? (
        <SuggestedFollowUps
          label={
            trust.isClarifying
              ? "Choose one:"
              : canRefine
                ? "Try another reading:"
                : "Did you mean?"
          }
          questions={clarificationOptions}
          onSelect={handleChip}
          variant={trust.isClarifying ? "clarify" : "default"}
        />
      ) : null}

      {!isStreaming &&
      !isRerunning &&
      message.followUps &&
      message.followUps.length > 0 &&
      (canRefine || onFollowUp) ? (
        <SuggestedFollowUps
          label="Suggested follow-ups"
          questions={message.followUps}
          onSelect={handleChip}
        />
      ) : null}
    </MessageBubble>
  );
}
