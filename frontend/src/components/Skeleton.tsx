export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-ink-700/60 ${className}`} />;
}

export function GameCardSkeleton() {
  return (
    <div className="flex overflow-hidden rounded-card border border-line bg-ink-850 p-3">
      <Skeleton className="h-16 w-28 flex-shrink-0" />
      <div className="ml-3 flex-1 space-y-2 py-1">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
        <Skeleton className="h-1.5 w-full" />
        <Skeleton className="h-4 w-16" />
      </div>
    </div>
  );
}

export function GameRowSkeleton() {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line bg-ink-850 px-3 py-2">
      <Skeleton className="h-9 w-16 flex-shrink-0" />
      <div className="flex-1 space-y-1.5">
        <Skeleton className="h-3.5 w-1/3" />
        <Skeleton className="h-3 w-1/4" />
      </div>
      <Skeleton className="h-6 w-14 flex-shrink-0" />
    </div>
  );
}

export function AccountCardSkeleton() {
  return (
    <div className="rounded-card border border-line bg-ink-850 p-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-16" />
      </div>
      <Skeleton className="mt-3 h-3 w-32" />
      <Skeleton className="mt-4 h-8 w-full" />
    </div>
  );
}
