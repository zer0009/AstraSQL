export interface UserMessageProps {
  content: string;
}

export function UserMessage({ content }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-md border border-zinc-200 bg-zinc-50 px-3.5 py-2.5">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-800">
          {content}
        </p>
      </div>
    </div>
  );
}
