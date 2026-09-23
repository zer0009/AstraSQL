import { LogOut } from "lucide-react";
import { useAuth } from "../../auth/AuthProvider";
import { Button } from "../ui";
import { cn } from "../../lib/utils";

export function UserMenu({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
}) {
  const { user, logout } = useAuth();
  if (!user) return null;

  if (compact) {
    return (
      <button
        type="button"
        title={`Sign out ${user.username}`}
        aria-label="Sign out"
        onClick={() => void logout()}
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800",
          className,
        )}
      >
        <LogOut className="h-3.5 w-3.5" strokeWidth={1.75} />
      </button>
    );
  }

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="truncate text-xs text-zinc-500" title={user.username}>
        {user.username}
      </span>
      <Button type="button" variant="ghost" size="sm" onClick={() => void logout()}>
        <LogOut className="h-3.5 w-3.5" strokeWidth={1.75} />
        Log out
      </Button>
    </div>
  );
}
