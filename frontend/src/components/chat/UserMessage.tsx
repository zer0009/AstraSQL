import { MessageBubble } from "./MessageBubble";

export interface UserMessageProps {
  content: string;
}

export function UserMessage({ content }: UserMessageProps) {
  return (
    <MessageBubble align="end" maxWidthClass="max-w-[85%]">
      <div className="rounded-2xl border border-[var(--border)] bg-zinc-800 px-3.5 py-2.5 text-zinc-50">
        <p className="whitespace-pre-wrap text-sm leading-relaxed">{content}</p>
      </div>
    </MessageBubble>
  );
}
