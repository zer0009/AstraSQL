export function PageHeader({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <header className="flex h-12 shrink-0 items-center border-b border-zinc-200 bg-white px-5">
      <div>
        <h1 className="text-sm font-semibold text-zinc-900">{title}</h1>
        {description ? (
          <p className="text-xs text-zinc-500">{description}</p>
        ) : null}
      </div>
    </header>
  );
}
