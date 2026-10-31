"use client";

import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle, Ban, CheckCircle2, ChevronDown, CircleHelp, EyeOff, SearchX, ShieldAlert,
  ThumbsDown, ThumbsUp,
} from "lucide-react";
import { toast } from "sonner";
import { api, type ChatResponse, type Status } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToday } from "@/lib/use-today";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

const STATUS: Record<Status, { label: string; className: string; icon: React.ElementType }> = {
  answered: { label: "ตอบจากแหล่งอ้างอิงที่ตรวจสอบแล้ว", className: "bg-emerald-600/10 text-emerald-700 dark:text-emerald-400", icon: CheckCircle2 },
  partial: { label: "ตอบได้บางส่วน", className: "bg-amber-500/15 text-amber-700 dark:text-amber-400", icon: CircleHelp },
  insufficient_evidence: { label: "ไม่พบหลักฐานเพียงพอ", className: "bg-muted text-muted-foreground", icon: SearchX },
  out_of_scope: { label: "นอกขอบเขต", className: "bg-muted text-muted-foreground", icon: Ban },
  blocked: { label: "ถูกบล็อกโดย guardrail", className: "bg-red-600/10 text-red-700 dark:text-red-400", icon: ShieldAlert },
  retrieval_only: { label: "แสดงข้อความต้นฉบับ (ไม่มีคำตอบจาก AI)", className: "bg-sky-500/10 text-sky-700 dark:text-sky-400", icon: SearchX },
  unverified: { label: "ยืนยันแหล่งอ้างอิงไม่ได้", className: "bg-red-600/10 text-red-700 dark:text-red-400", icon: AlertTriangle },
};

export function Answer({
  r, verified, activeSource, onCite, onFollowUp,
}: {
  r: ChatResponse;
  verified: Set<string>;
  activeSource: string | null;
  onCite: (id: string) => void;
  onFollowUp: (q: string) => void;
}) {
  const [rated, setRated] = useState<number | null>(null);
  const today = useToday();
  const st = STATUS[r.status];
  const g = r.grounding ?? {};
  const md = r.answer.replace(/\[S(\d+)\]/g, "[S$1](#cite-S$1)");

  async function rate(v: number) {
    if (!r.audit_id) return;
    await api("/feedback", { body: { audit_id: r.audit_id, rating: v } });
    setRated(v);
    toast.success(v > 0 ? "ขอบคุณสำหรับ feedback" : "บันทึกแล้ว ทีมจะนำไปปรับปรุง");
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={st.className}><st.icon /> {st.label}</Badge>
        {!!g.markers && (
          <Badge variant="outline">อ้างอิงที่ยืนยันได้ {g.markers_supported}/{g.markers}</Badge>
        )}
        {Object.keys(r.pii_masked ?? {}).length > 0 && (
          <Badge className="bg-amber-500/15 text-amber-700 dark:text-amber-400">
            <EyeOff /> ปิดบังข้อมูลส่วนบุคคล: {Object.entries(r.pii_masked).map(([k, v]) => `${k}×${v}`).join(", ")}
          </Badge>
        )}
        {today && r.as_of !== today && (
          <Badge variant="outline">ตามกฎ ณ วันที่ {r.as_of}</Badge>
        )}
      </div>

      <div className="answer-prose">
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              if (href?.startsWith("#cite-")) {
                const id = href.slice(6);
                const ok = verified.has(id);
                return (
                  <button
                    type="button"
                    onClick={() => onCite(id)}
                    title={ok ? "ดูข้อความต้นฉบับที่อ้างอิง" : "อ้างอิงนี้ยืนยันกับต้นฉบับไม่ได้"}
                    className={cn(
                      "mx-0.5 inline-flex -translate-y-0.5 items-center rounded px-1 text-[0.7rem] font-semibold transition",
                      ok ? "bg-brand/15 text-[#4db8ff] hover:bg-brand/25" : "bg-red-600/15 text-red-400",
                      activeSource === id && "ring-1 ring-brand shadow-[0_0_10px_rgba(0,153,255,0.5)]",
                    )}
                  >
                    {children}
                  </button>
                );
              }
              return <a href={href} target="_blank" rel="noreferrer" className="text-primary underline">{children}</a>;
            },
          }}
        >
          {md}
        </Markdown>
      </div>

      {r.notices.map((n) => (
        <div key={n} className="flex gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {n}
        </div>
      ))}

      {r.follow_up_questions?.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-1">
          {r.follow_up_questions.map((q) => (
            <button
              key={q}
              onClick={() => onFollowUp(q)}
              className="rounded-full border bg-secondary/60 px-3 py-1 text-xs text-muted-foreground transition hover:border-brand/40 hover:text-foreground"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-1 pt-1">
        {r.audit_id && (
          <>
            <Button variant="ghost" size="icon-sm" aria-label="มีประโยชน์" onClick={() => rate(1)} className={cn(rated === 1 && "text-success")}>
              <ThumbsUp />
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="ไม่มีประโยชน์" onClick={() => rate(-1)} className={cn(rated === -1 && "text-red-600")}>
              <ThumbsDown />
            </Button>
          </>
        )}
        <Collapsible>
          <CollapsibleTrigger className="ml-1 inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted">
            รายละเอียดการประมวลผล <ChevronDown className="size-3" />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-muted p-3 text-[0.7rem] leading-relaxed">
              {JSON.stringify({
                audit_id: r.audit_id, standalone_question: r.standalone_question, as_of: r.as_of,
                grounding: r.grounding, guard_flags: r.guard_flags, trace: r.trace,
              }, null, 2)}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  );
}
