interface EmptyStateProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="relative mb-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted">
          {icon}
        </div>
      </div>
      <h3 className="font-display text-base font-semibold text-foreground">
        {title}
      </h3>
      <p className="mt-1 max-w-xs text-sm text-muted-foreground">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-4 rounded-xl border border-border bg-background p-4"
        >
          <div className="h-4 w-4 animate-pulse rounded bg-muted" />
          <div className="h-4 w-32 animate-pulse rounded bg-muted" />
          <div className="h-4 w-24 animate-pulse rounded bg-muted" />
          <div className="h-4 flex-1 animate-pulse rounded bg-muted" />
          <div className="h-4 w-20 animate-pulse rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="rounded-2xl border border-border bg-background p-5">
      <div className="h-10 w-10 animate-pulse rounded-xl bg-muted" />
      <div className="mt-4 h-6 w-24 animate-pulse rounded bg-muted" />
      <div className="mt-2 h-4 w-16 animate-pulse rounded bg-muted" />
    </div>
  );
}
