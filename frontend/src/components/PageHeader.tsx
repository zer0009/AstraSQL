export function PageHeader({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <header className="flex h-12 shrink-0 items-center border-b border-[var(--border)] bg-[var(--surface-raised)] px-5">
      <div>
        <h1 className="text-sm font-semibold text-[var(--text)]">{title}</h1>
        {description ? (
          <p className="text-xs text-[var(--text-muted)]">{description}</p>
        ) : null}
      </div>
    </header>
  );
}
