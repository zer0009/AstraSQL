import {
  useCallback,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Send } from "lucide-react";
import { Button, Textarea } from "../ui";

export interface ChatInputProps {
  onSend: (question: string) => void;
  disabled?: boolean;
  placeholder?: string;
  value?: string;
  onChange?: (value: string) => void;
}

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Ask a question about your data…",
  value: controlledValue,
  onChange,
}: ChatInputProps) {
  const [uncontrolled, setUncontrolled] = useState("");
  const isControlled = controlledValue !== undefined;
  const value = isControlled ? controlledValue : uncontrolled;

  const setValue = useCallback(
    (next: string) => {
      if (isControlled) onChange?.(next);
      else setUncontrolled(next);
    },
    [isControlled, onChange],
  );

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }, [disabled, onSend, setValue, value]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form
      onSubmit={onSubmit}
      className="flex items-end gap-2 border-t border-zinc-200 bg-white px-4 py-3"
    >
      <Textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled}
        placeholder={placeholder}
        rows={2}
        className="min-h-[64px] resize-none"
      />
      <Button
        type="submit"
        size="md"
        disabled={disabled || !value.trim()}
        aria-label="Send"
        className="shrink-0"
      >
        <Send className="h-3.5 w-3.5" strokeWidth={1.75} />
        Send
      </Button>
    </form>
  );
}
