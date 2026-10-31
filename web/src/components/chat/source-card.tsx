"use client";

import { forwardRef } from "react";
import { ExternalLink, FileScan, FlaskConical, Lock, StickyNote } from "lucide-react";
import type { Source } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

function highlight(text: string, quotes: string[]) {
  // Mark verified quotes inside the original passage (exact match first, whitespace-tolerant fallback).
  const ranges: [number, number][] = [];
  for (const q of quotes) {
    const needle = q.trim();
    const i = text.indexOf(needle);
    if (i < 0) {
      const pattern = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
      const m = new RegExp(pattern).exec(text);
      if (m) ranges.push([m.index, m.index + m[0].length]);
      continue;
    }
    ranges.push([i, i + needle.length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const out: React.ReactNode[] = [];
  let pos = 0;
  ranges.forEach(([s, e], k) => {
    if (s < pos) return;
    out.push(text.slice(pos, s), <mark key={k}>{text.slice(s, e)}</mark>);
    pos = e;
  });
  out.push(text.slice(pos));
  return out;
}

export const SourceCard = forwardRef<HTMLDivElement, { source: Source; active: boolean; onSelect: () => void }>(
  function SourceCard({ source: s, active, onSelect }, ref) {
    const eff = [s.effective_from, s.effective_to].filter(Boolean).join(" → ");
    return (
      <div
        ref={ref}
        onClick={onSelect}
        className={cn(
          "cursor-pointer rounded-[14px] border bg-card p-4 transition-all",
          active ? "border-brand/60 shadow-[0_0_24px_rgba(0,153,255,0.18)]" : "hover:border-white/15",
          !s.cited && !active && "opacity-80",
        )}
      >
        <div className="mb-2 flex items-start gap-2">
          <span
            className={cn(
              "mt-0.5 rounded-md px-1.5 py-0.5 text-xs font-semibold",
              s.cited ? "bg-brand text-white shadow-[0_0_10px_rgba(0,153,255,0.6)]" : "bg-muted text-muted-foreground",
            )}
          >
            {s.id}
          </span>
          <div className="min-w-0">
            <div className="text-sm font-medium leading-snug">{s.label}</div>
            <div className="truncate text-xs text-muted-foreground">{s.short_title}</div>
          </div>
        </div>
        <div className="mb-2 flex flex-wrap gap-1.5">
          <Badge variant="outline">{s.source_kind === "internal" ? "นโยบายภายใน" : "กฎหมาย/ประกาศ"}</Badge>
          {eff && <Badge variant="outline">มีผล {eff}</Badge>}
          {s.cited && <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-400">อ้างอิงในคำตอบ ✓</Badge>}
          {(s.classification === "confidential" || s.classification === "restricted") && (
            <Badge className="bg-red-600/10 text-red-700 dark:text-red-400"><Lock /> ลับ</Badge>
          )}
          {s.extraction === "ocr" && (
            <Badge className="bg-amber-500/15 text-amber-700 dark:text-amber-400"><FileScan /> OCR</Badge>
          )}
          {s.synthetic && (
            <Badge className="bg-violet-500/10 text-violet-700 dark:text-violet-400"><FlaskConical /> เอกสารจำลอง</Badge>
          )}
        </div>
        {s.path.length > 0 && <div className="mb-2 text-xs text-muted-foreground">{s.path.join(" › ")}</div>}
        <div className={cn("source-text text-foreground/90", !active && "line-clamp-6")}>
          {highlight(s.text, s.quotes)}
        </div>
        {active && s.notes.length > 0 && (
          <div className="mt-3 space-y-1 border-t pt-2">
            {s.notes.map((n) => (
              <p key={n} className="flex gap-1.5 text-xs text-muted-foreground">
                <StickyNote className="mt-0.5 size-3 shrink-0" /> {n}
              </p>
            ))}
          </div>
        )}
        {active && (s.official_url || s.source_url) && (
          <div className="mt-3 flex flex-wrap gap-3 text-xs">
            {s.official_url && (
              <a href={s.official_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                แหล่งทางการ <ExternalLink className="size-3" />
              </a>
            )}
            {s.source_url && s.source_url !== s.official_url && (
              <a href={s.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                ไฟล์ที่ใช้ <ExternalLink className="size-3" />
              </a>
            )}
            {s.page_start && <span className="text-muted-foreground">หน้า {s.page_start}{s.page_end !== s.page_start ? `–${s.page_end}` : ""}</span>}
          </div>
        )}
      </div>
    );
  },
);
