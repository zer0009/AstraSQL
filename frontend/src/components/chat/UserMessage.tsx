export interface UserMessageProps {
  content: string;
}

export function UserMessage({ content }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl bg-zinc-900 px-3.5 py-2.5 text-white">
        <p className="whitespace-pre-wrap text-sm leading-relaxed">
          {content}
        </p>
      </div>
    </div>
  );
}
