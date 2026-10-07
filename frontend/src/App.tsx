import { NavLink, Outlet, useLocation } from "react-router-dom";
import { cn } from "./lib/utils";
import { AstraLogo } from "./components/brand";
import { UserMenu } from "./components/layout/UserMenu";
import { NAV_ITEMS } from "./components/layout/navItems";
import { ScanStatusBanner } from "./components/ScanStatusBanner";
import { OnboardingBanner } from "./components/OnboardingBanner";

export default function App() {
  const location = useLocation();
  const isChatRoute = location.pathname === "/";

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--surface)]">
      {!isChatRoute ? (
        <aside className="flex w-56 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-raised)]">
          <div className="flex h-12 items-center border-b border-[var(--border)] px-4">
            <AstraLogo size={22} />
          </div>

          <nav className="flex flex-1 flex-col gap-0.5 p-2" aria-label="Primary">
            {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
                    isActive
                      ? "bg-zinc-900 text-white"
                      : "text-zinc-600 hover:bg-[var(--surface-muted)] hover:text-zinc-900",
                  )
                }
              >
                <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="border-t border-[var(--border)] px-3 py-2">
            <UserMenu className="mb-1 justify-between" />
            <p className="text-[11px] text-[var(--text-muted)]">
              Self-hosted NL2SQL
            </p>
          </div>
        </aside>
      ) : null}

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <ScanStatusBanner />
        <OnboardingBanner />
        <Outlet />
      </main>
    </div>
  );
}
