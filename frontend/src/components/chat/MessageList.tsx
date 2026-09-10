import { useEffect, useRef } from "react";
import type { ChatMessage } from "../../hooks/useStreamQuery";
import { AgentMessage } from "./AgentMessage";
import { UserMessage } from "./UserMessage";

export interface MessageListProps {
  messages: ChatMessage[];
  isStreaming?: boolean;
  onFollowUp?: (question: string) => void;
  onAskAgain?: (question: string) => void;
  originalQuestions?: Record<string, string>;
}

export function MessageList({
  messages,
  isStreaming = false,
  onFollowUp,
  onAskAgain,
  originalQuestions = {},
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isStreaming]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6">
        <p className="text-sm text-zinc-500">
          Ask a natural-language question to generate SQL and results.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4">
      <div className="mx-auto flex max-w-4xl flex-col gap-4">
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
              onFollowUp={onFollowUp}
              onAskAgain={
                onAskAgain && originalQuestion
                  ? () => onAskAgain(originalQuestion)
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
