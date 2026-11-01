"use client";

import { createContext, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import {
  BarChart3, BookOpenText, FileSearch, LogOut, Menu, MessageSquareText, Moon, Scale, ScrollText, Sun,
} from "lucide-react";
import { api, CLEARANCE_LABEL, ROLE_LABEL, type Role, type User } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { HistoryList } from "@/components/history-list";

const UserContext = createContext<User | null>(null);
export const useUser = () => useContext(UserContext);

interface Health {
  status: string;
  models_ready: boolean;
  llm_configured: boolean;
  llm_model: string;
}

const NAV: { href: string; label: string; icon: React.ElementType; roles?: Role[] }[] = [
  { href: "/", label: "ถาม-ตอบ", icon: MessageSquareText },
  { href: "/documents", label: "คลังเอกสาร", icon: BookOpenText },
  { href: "/gap", label: "Gap Analysis", icon: FileSearch, roles: ["compliance_officer", "admin"] },
  { href: "/audit", label: "Audit Trail", icon: ScrollText, roles: ["compliance_officer", "auditor", "admin"] },
  { href: "/eval", label: "Evaluation", icon: BarChart3 },
];

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className={cn("flex items-center justify-center rounded-[9px] bg-foreground text-background", compact ? "size-7" : "size-8")}>
        <Scale className="size-4" />
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight">Compliance Copilot</div>
        {!compact && <div className="text-xs text-muted-foreground">Banking & Securities</div>}
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();

  useEffect(() => {
    api<User>("/me").then(setUser).catch(() => {});
    const load = () => api<Health>("/health").then(setHealth).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  const nav = NAV.filter((n) => !n.roles || (user && n.roles.includes(user.role)));

  // Rendered in the desktop sidebar and in the phone drawer.
  const sidebar = (
    <>
      <div className="px-5 py-5">
        <Logo />
      </div>
      <nav className="shrink-0 space-y-1 px-3">
        {nav.map((n) => {
          const active = n.href === "/" ? pathname === "/" || pathname.startsWith("/c/") : pathname.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              onClick={() => setNavOpen(false)}
              className={cn(
                "relative flex items-center gap-3 rounded-[10px] px-3 py-2.5 text-[14px] transition-colors md:py-2 md:text-[13.5px]",
                active
                  ? "bg-white/[0.07] font-medium text-foreground before:absolute before:-left-3 before:top-1/2 before:h-4 before:w-[3px] before:-translate-y-1/2 before:rounded-r before:bg-brand before:shadow-[0_0_10px_#0099ff]"
                  : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
              )}
            >
              <n.icon className={cn("size-4", active && "text-brand")} />
              {n.label}
            </Link>
          );
        })}
      </nav>
      <HistoryList onNavigate={() => setNavOpen(false)} />
      <div className="space-y-3 border-t p-4">
        {health && (
          <div className="space-y-1 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <span className={cn("size-1.5 rounded-full", health.status === "ok" ? "bg-success shadow-[0_0_8px_#00bb88]" : "bg-amber-500")} />
              API {health.status === "ok" ? "พร้อมใช้งาน" : "มีปัญหา"}
              {!health.models_ready && " · กำลังโหลดโมเดล"}
            </div>
            <div className="truncate">
              {health.llm_configured ? `LLM: ${health.llm_model}` : "โหมดค้นคืนเท่านั้น (ไม่มี LLM)"}
            </div>
          </div>
        )}
        {user && (
          <div className="rounded-[10px] border bg-card p-3">
            <div className="truncate text-sm font-medium">{user.display_name}</div>
            <div className="text-xs text-muted-foreground">
              {ROLE_LABEL[user.role]} · ชั้นความลับ: {CLEARANCE_LABEL[user.clearance]}
            </div>
          </div>
        )}
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="flex-1" onClick={logout}>
            <LogOut /> ออกจากระบบ
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="สลับธีม"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          >
            {/* both icons render; CSS picks one, so server and client HTML match */}
            <Sun className="hidden dark:block" />
            <Moon className="dark:hidden" />
          </Button>
        </div>
      </div>
    </>
  );

  return (
    <UserContext.Provider value={user}>
      <div className="flex h-dvh overflow-hidden">
        <aside className="hidden w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex">
          {sidebar}
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          {/* phone / small-tablet top bar */}
          <header className="flex h-14 shrink-0 items-center justify-between border-b border-sidebar-border bg-sidebar px-3 md:hidden">
            <Logo compact />
            <Button variant="ghost" size="icon" aria-label="เปิดเมนู" onClick={() => setNavOpen(true)}>
              <Menu />
            </Button>
          </header>
          <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
        </div>

        <Sheet open={navOpen} onOpenChange={setNavOpen}>
          <SheetContent side="left" className="w-72 gap-0 bg-sidebar p-0">
            <SheetTitle className="sr-only">เมนู</SheetTitle>
            <div className="flex h-full flex-col">{sidebar}</div>
          </SheetContent>
        </Sheet>
      </div>
    </UserContext.Provider>
  );
}

export function PageHeader({ title, description, children }: {
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b bg-background/70 px-4 py-4 backdrop-blur-xl md:gap-4 md:px-8 md:py-5">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight md:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-xs text-muted-foreground md:text-sm">{description}</p>}
      </div>
      {children}
    </div>
  );
}
