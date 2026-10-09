import { useEffect, useRef } from "react";
import type { ChatMessage } from "../../hooks/useStreamQuery";
import { AgentMessage } from "./AgentMessage";
import { UserMessage } from "./UserMessage";

const EXAMPLE_QUESTIONS = [
  "How many rows are in each table?",
  "Show me the top 10 records by date",
  "What are the distinct status values?",
];

export interface MessageListProps {
  messages: ChatMessage[];
  isStreaming?: boolean;
  rerunningMessageId?: string | null;
  onFollowUp?: (question: string) => void;
  onRefine?: (runId: string, choice: string) => void;
  onRemember?: (definition: string) => void;
  onAskAgain?: (question: string) => void;
  onRerunSql?: (messageId: string, sql?: string) => void;
  onRetry?: (question: string) => void;
  originalQuestions?: Record<string, string>;
}

export function MessageList({
  messages,
  isStreaming = false,
  rerunningMessageId = null,
  onFollowUp,
  onRefine,
  onRemember,
  onAskAgain,
  onRerunSql,
  onRetry,
  originalQuestions = {},
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isStreaming, rerunningMessageId]);

  if (messages.length === 0) {
    return (
      <div className="chat-scroll flex flex-1 items-center justify-center px-6 py-10">
        <div className="mx-auto w-full max-w-md text-center">
          <h2 className="text-xl font-semibold tracking-tight text-[var(--text)]">
            Ask your data
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-zinc-600">
            Plain-language questions. Read-only SQL on your connection — with a
            clear trust level on every answer.
          </p>
          {onFollowUp ? (
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => onFollowUp(q)}
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-1.5 text-left text-xs text-zinc-700 hover:border-zinc-300 hover:bg-[var(--surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                >
                  {q}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="chat-scroll flex-1 overflow-y-auto px-4 py-5">
      <div className="mx-auto flex max-w-4xl flex-col gap-5">
        {messages.map((msg, index) => {
          if (msg.role === "user") {
            return <UserMessage key={msg.id} content={msg.content} />;
          }

          const priorUser = [...messages]
            .slice(0, index)
            .reverse()
            .find((m) => m.role === "user");
          const originalQuestion =
            originalQuestions[msg.id] ?? priorUser?.content ?? "";

          const isLast = index === messages.length - 1;
          return (
            <AgentMessage
              key={msg.id}
              message={msg}
              isStreaming={isStreaming && isLast}
              isRerunning={rerunningMessageId === msg.id}
              onFollowUp={onFollowUp}
              onRefine={onRefine}
              onRemember={onRemember}
              onAskAgain={
                onAskAgain && originalQuestion
                  ? () => onAskAgain(originalQuestion)
                  : undefined
              }
              onRerunSql={
                onRerunSql && msg.sql
                  ? (sql?: string) => onRerunSql(msg.id, sql)
                  : undefined
              }
              onRetry={
                onRetry && originalQuestion && msg.error
                  ? () => onRetry(originalQuestion)
                  : undefined
              }
            />
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
