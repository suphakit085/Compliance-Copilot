"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type ConversationSummary } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CONVERSATIONS_CHANGED } from "@/lib/events";

const DAY = 86_400_000;

/** Bucket by last activity so threads with the same first question stay distinguishable. */
function groupByDay(items: ConversationSummary[]) {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const t0 = start.getTime();
  const label = (ts: number) =>
    ts >= t0 ? "วันนี้" : ts >= t0 - DAY ? "เมื่อวาน" : ts >= t0 - 6 * DAY ? "7 วันที่ผ่านมา" : "ก่อนหน้านี้";
  const groups: { label: string; items: ConversationSummary[] }[] = [];
  for (const c of items) {
    const g = label(new Date(c.updated_at).getTime());
    if (groups.at(-1)?.label !== g) groups.push({ label: g, items: [] });
    groups.at(-1)!.items.push(c);
  }
  return groups;
}

function timeLabel(iso: string) {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("th-TH", { day: "numeric", month: "short" });
}

/** The signed-in user's own conversations (sidebar / phone drawer). */
export function HistoryList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(() => {
    api<ConversationSummary[]>("/conversations").then(setItems).catch(() => setItems([]));
  }, []);

  useEffect(() => {
    load();
    window.addEventListener(CONVERSATIONS_CHANGED, load);
    return () => window.removeEventListener(CONVERSATIONS_CHANGED, load);
  }, [load]);

  async function remove(id: string) {
    await api(`/conversations/${id}/delete`, { method: "POST" });
    setConfirming(null);
    setItems((xs) => xs?.filter((x) => x.id !== id) ?? null);
    toast.success("ลบบทสนทนาแล้ว");
    if (pathname === `/c/${id}`) router.push("/");
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col px-3 pt-4">
      <div className="mb-1.5 flex items-center justify-between px-3">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">ประวัติแชต</span>
        <Link
          href="/"
          onClick={onNavigate}
          aria-label="แชทใหม่"
          className="rounded-md p-1 text-muted-foreground transition hover:bg-white/[0.06] hover:text-foreground"
        >
          <Plus className="size-3.5" />
        </Link>
      </div>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto pb-2">
        {items?.length === 0 && (
          <p className="px-3 py-2 text-xs text-muted-foreground">ยังไม่มีบทสนทนา</p>
        )}
        {items && groupByDay(items).map((g) => (
          <div key={g.label} className="pb-2">
            <p className="px-3 pb-1 pt-2 text-[10.5px] font-medium text-muted-foreground/60">{g.label}</p>
            {g.items.map((c) => {
          const active = pathname === `/c/${c.id}`;
          return (
            <div
              key={c.id}
              className={cn(
                "group flex items-center gap-1 rounded-[10px] pr-1 transition-colors",
                active ? "bg-white/[0.07]" : "hover:bg-white/[0.04]",
              )}
            >
              {confirming === c.id ? (
                <div className="flex flex-1 items-center justify-between gap-2 px-3 py-1.5 text-xs">
                  <span className="text-muted-foreground">ลบบทสนทนานี้?</span>
                  <span className="flex gap-1">
                    <button onClick={() => remove(c.id)} className="rounded-md bg-destructive/15 px-2 py-0.5 text-destructive">ลบ</button>
                    <button onClick={() => setConfirming(null)} className="rounded-md px-2 py-0.5 text-muted-foreground hover:bg-white/5">ยกเลิก</button>
                  </span>
                </div>
              ) : (
                <>
                  <Link
                    href={`/c/${c.id}`}
                    onClick={onNavigate}
                    title={c.title}
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2 text-[13px]",
                      active ? "text-foreground" : "text-muted-foreground group-hover:text-foreground",
                    )}
                  >
                    <MessageSquare className="size-3.5 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{c.title}</span>
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground/60">
                      {timeLabel(c.updated_at)}
                    </span>
                  </Link>
                  <button
                    onClick={() => setConfirming(c.id)}
                    aria-label="ลบบทสนทนา"
                    className="rounded-md p-1.5 text-muted-foreground opacity-100 transition hover:bg-white/5 hover:text-destructive md:opacity-0 md:group-hover:opacity-100"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </>
              )}
            </div>
          );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
