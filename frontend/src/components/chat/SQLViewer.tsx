import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, Copy, Pencil, Play } from "lucide-react";
import { Button, Textarea } from "../ui";

export interface SQLViewerProps {
  sql: string;
  onAskAgain?: () => void;
  onRerunSql?: (sql?: string) => void;
  isRerunning?: boolean;
  /** When false (default), SQL body is collapsed like Wren/Snowflake View SQL. */
  defaultExpanded?: boolean;
}

export function SQLViewer({
  sql,
  onAskAgain,
  onRerunSql,
  isRerunning = false,
  defaultExpanded = false,
}: SQLViewerProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(sql);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setDraft(sql);
  }, [sql]);

  const displaySql = editing ? draft : sql;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(displaySql);
    } catch {
      // ignore clipboard failures
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  const toggleEdit = () => {
    if (!editing) {
      setDraft(sql);
      setExpanded(true);
    }
    setEditing((v) => !v);
  };

  return (
    <div className="overflow-hidden rounded-md border border-zinc-200">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 bg-zinc-50 px-3 py-1.5">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex items-center gap-1 text-xs font-medium text-zinc-600 hover:text-zinc-900"
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.75} />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" strokeWidth={1.75} />
          )}
          {expanded ? "Hide SQL" : "View SQL"}
        </button>
        <div className="flex flex-wrap items-center gap-1">
          {onRerunSql ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onRerunSql(editing ? draft : sql)}
              disabled={isRerunning}
              title="Execute this SQL directly (no LLM)"
            >
              <Play className="h-3 w-3" strokeWidth={1.75} />
              {isRerunning ? "Running…" : "Run SQL"}
            </Button>
          ) : null}
          <Button type="button" variant="ghost" size="sm" onClick={toggleEdit}>
            <Pencil className="h-3 w-3" strokeWidth={1.75} />
            {editing ? "Done" : "Edit"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={copy}>
            {copied ? (
              <Check className="h-3 w-3" strokeWidth={1.75} />
            ) : (
              <Copy className="h-3 w-3" strokeWidth={1.75} />
            )}
            {copied ? "Copied" : "Copy"}
          </Button>
          {onAskAgain ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onAskAgain}
              disabled={isRerunning}
              title="Re-ask the question through the AI agent"
            >
              Ask again
            </Button>
          ) : null}
        </div>
      </div>

      {expanded ? (
        editing ? (
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="min-h-[120px] rounded-none border-0 font-mono text-xs leading-relaxed focus-visible:ring-0 focus-visible:ring-offset-0"
            spellCheck={false}
          />
        ) : (
          <pre className="overflow-x-auto bg-white px-3 py-2.5 font-mono text-xs leading-relaxed text-zinc-800 whitespace-pre-wrap">
            {sql}
          </pre>
        )
      ) : null}
    </div>
  );
}
