"use client";

import { createContext, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import {
  BarChart3, BookOpenText, FileSearch, LogOut, MessageSquareText, Moon, Scale, ScrollText, Sun,
} from "lucide-react";
import { api, CLEARANCE_LABEL, ROLE_LABEL, type Role, type User } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

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

export function AppShell({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const pathname = usePathname();
  const router = useRouter();
  const { theme, setTheme } = useTheme();

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

  return (
    <UserContext.Provider value={user}>
      <div className="flex h-screen overflow-hidden">
        <aside className="flex w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
          <div className="flex items-center gap-2.5 px-5 py-5">
            <div className="flex size-8 items-center justify-center rounded-[9px] bg-foreground text-background">
              <Scale className="size-4" />
            </div>
            <div className="leading-tight">
              <div className="text-[15px] font-semibold tracking-tight">Compliance Copilot</div>
              <div className="text-xs text-muted-foreground">Banking & Securities</div>
            </div>
          </div>
          <nav className="flex-1 space-y-1 px-3">
            {nav.map((n) => {
              const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  className={cn(
                    "relative flex items-center gap-3 rounded-[10px] px-3 py-2 text-[13.5px] transition-colors",
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
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              >
                {theme === "dark" ? <Sun /> : <Moon />}
              </Button>
            </div>
          </div>
        </aside>
        <main className="min-w-0 flex-1 overflow-hidden">{children}</main>
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
    <div className="flex flex-wrap items-end justify-between gap-4 border-b bg-background/70 px-8 py-5 backdrop-blur-xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}
