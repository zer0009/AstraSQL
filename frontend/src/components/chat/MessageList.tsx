import { useEffect, useRef } from "react";
import type { ChatMessage } from "../../hooks/useStreamQuery";
import { AgentMessage } from "./AgentMessage.tsx";
import { UserMessage } from "./UserMessage.tsx";

export interface MessageListProps {
  messages: ChatMessage[];
  isStreaming?: boolean;
  rerunningMessageId?: string | null;
  onFollowUp?: (question: string) => void;
  onAskAgain?: (question: string) => void;
  onRerunSql?: (messageId: string, sql?: string) => void;
  originalQuestions?: Record<string, string>;
}

export function MessageList({
  messages,
  isStreaming = false,
  rerunningMessageId = null,
  onFollowUp,
  onAskAgain,
  onRerunSql,
  originalQuestions = {},
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isStreaming, rerunningMessageId]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 py-10">
        <div className="mx-auto w-full max-w-lg text-center">
          <h2 className="text-xl font-semibold tracking-tight text-zinc-900">
            Ask your data
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-zinc-600">
            Ask in plain language. AstraSQL runs read-only SQL on your connected
            database.
          </p>
          <p className="mt-1.5 text-xs text-zinc-400">
            Live results from the DB. Row data is not stored in chat history.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-5">
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
            />
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
