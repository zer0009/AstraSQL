import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Send } from "lucide-react";
import { Button, Textarea } from "../../ui";
import { cn } from "../../../lib/utils";

export interface ChatInputProps {
  onSend: (question: string) => void;
  disabled?: boolean;
  placeholder?: string;
  value?: string;
  onChange?: (value: string) => void;
  evidence?: string;
  onEvidenceChange?: (value: string) => void;
  showEvidence?: boolean;
  onToggleEvidence?: () => void;
}

export interface ChatInputHandle {
  focus: () => void;
}

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  function ChatInput(
    {
      onSend,
      disabled = false,
      placeholder = "Ask a question about your data…",
      value: controlledValue,
      onChange,
      evidence = "",
      onEvidenceChange,
      showEvidence = false,
      onToggleEvidence,
    },
    ref,
  ) {
    const [uncontrolled, setUncontrolled] = useState("");
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const isControlled = controlledValue !== undefined;
    const value = isControlled ? controlledValue : uncontrolled;

    useImperativeHandle(ref, () => ({
      focus: () => textareaRef.current?.focus(),
    }));

    const setValue = useCallback(
      (next: string) => {
        if (isControlled) onChange?.(next);
        else setUncontrolled(next);
      },
      [isControlled, onChange],
    );

    const resize = useCallback(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
    }, []);

    const submit = useCallback(() => {
      const trimmed = value.trim();
      if (!trimmed || disabled) return;
      onSend(trimmed);
      setValue("");
      requestAnimationFrame(() => {
        if (textareaRef.current) {
          textareaRef.current.style.height = "auto";
        }
      });
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
      <div className="chat-composer border-t border-[var(--border)] bg-[var(--surface-raised)] px-4 py-3">
        <form onSubmit={onSubmit} className="mx-auto w-full max-w-4xl">
          {showEvidence ? (
            <div className="mb-2">
              <label
                htmlFor="chat-evidence"
                className="mb-1 block text-[11px] font-medium text-[var(--text-muted)]"
              >
                Context note (optional evidence for this question)
              </label>
              <Textarea
                id="chat-evidence"
                value={evidence}
                onChange={(e) => onEvidenceChange?.(e.target.value)}
                disabled={disabled}
                rows={2}
                placeholder="e.g. active means status = 'A'; revenue is order total"
                className="min-h-[48px] resize-y text-xs"
              />
            </div>
          ) : null}
          <div
            className={cn(
              "flex items-end gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2 shadow-sm",
              "focus-within:border-zinc-300 focus-within:ring-2 focus-within:ring-[var(--focus-ring)]",
            )}
          >
            <Textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                resize();
              }}
              onKeyDown={onKeyDown}
              disabled={disabled}
              placeholder={placeholder}
              rows={1}
              aria-label="Ask a question"
              className="min-h-[40px] max-h-32 flex-1 resize-none border-0 bg-transparent px-0 py-2 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
            />
            <Button
              type="submit"
              size="md"
              disabled={disabled || !value.trim()}
              aria-label="Send"
              className="mb-0.5 h-9 w-9 shrink-0 rounded-full p-0"
            >
              <Send className="h-4 w-4" strokeWidth={1.75} />
            </Button>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2 px-1">
            <p className="text-[11px] text-[var(--text-muted)]">
              Enter to send · Shift+Enter for newline
            </p>
            {onToggleEvidence ? (
              <button
                type="button"
                className="text-[11px] text-[var(--text-muted)] hover:text-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] rounded"
                onClick={onToggleEvidence}
              >
                {showEvidence ? "Hide context note" : "Add context note"}
              </button>
            ) : null}
          </div>
        </form>
      </div>
    );
  },
);
