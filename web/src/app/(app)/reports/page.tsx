"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, Siren } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, REPORT_CATEGORIES, type ProblemReport } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader, useUser } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const FILTERS = [
  { v: "open", label: "รอดำเนินการ" },
  { v: "", label: "ทั้งหมด" },
];

export default function ReportsPage() {
  const user = useUser();
  const canResolve = user?.role === "compliance_officer" || user?.role === "admin";
  const [filter, setFilter] = useState("open");
  const [rows, setRows] = useState<ProblemReport[] | null>(null);
  const [denied, setDenied] = useState(false);
  const [note, setNote] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(() => {
    api<ProblemReport[]>(`/feedback/reports${filter ? `?status=${filter}` : ""}`)
      .then(setRows)
      .catch((e) => { if (e instanceof ApiError && e.status === 403) setDenied(true); });
  }, [filter]);
  useEffect(load, [load]);

  async function resolve(id: number, status: "resolved" | "dismissed") {
    setBusy(id);
    try {
      await api(`/feedback/${id}/resolve`, { body: { status, note: note[id] ?? "" } });
      toast.success("ปิดเรื่องแล้ว ผู้รายงานจะเห็นผลที่หน้าคู่มือ");
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(null);
    }
  }

  if (denied) return <div className="p-8 text-sm text-muted-foreground">หน้านี้สำหรับเจ้าหน้าที่ Compliance ผู้ตรวจสอบภายใน และผู้ดูแลระบบเท่านั้น</div>;

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="รายงานปัญหา" description="คำตอบที่ผู้ใช้กดรายงาน — แก้ที่ต้นเหตุ แล้วบันทึกผลเพื่อแจ้งผู้รายงาน">
        <div className="flex gap-1.5">
          {FILTERS.map((f) => (
            <Button key={f.label} size="sm" variant={filter === f.v ? "secondary" : "ghost"} onClick={() => setFilter(f.v)}>{f.label}</Button>
          ))}
        </div>
      </PageHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-3 px-4 py-5 md:px-8">
          {rows === null ? (
            <Loader2 className="mx-auto mt-10 size-5 animate-spin text-brand" />
          ) : rows.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">ไม่มีรายงานในช่วงนี้</p>
          ) : (
            rows.map((r) => (
              <article key={r.id} className={cn("panel space-y-2.5 p-4 text-sm", r.category === "leak" && r.report_status === "open" && "border-red-500/40")}>
                <div className="flex flex-wrap items-center gap-2">
                  {r.category === "leak" && <Siren className="size-4 text-red-500" />}
                  <Badge variant="outline">{REPORT_CATEGORIES.find((c) => c.value === r.category)?.label ?? r.category}</Badge>
                  <Badge className={r.report_status === "open" ? "bg-amber-500/15 text-amber-700 dark:text-amber-400" : "bg-emerald-600/10 text-emerald-700 dark:text-emerald-400"}>
                    {r.report_status === "open" ? "รอดำเนินการ" : r.report_status === "resolved" ? "แก้ไขแล้ว" : "ปิดเรื่อง"}
                  </Badge>
                  <span className="ml-auto text-xs text-muted-foreground">
                    #{r.id} · audit #{r.audit_id} · {r.user} ({r.role}) · {r.ts.slice(0, 16).replace("T", " ")}
                  </span>
                </div>
                <div><span className="text-muted-foreground">คำถาม:</span> {r.question}</div>
                {r.comment && <div className="rounded-lg bg-muted/50 px-3 py-2"><span className="text-muted-foreground">ความเห็น:</span> {r.comment}</div>}
                <div className="text-xs text-muted-foreground">
                  สถานะคำตอบ: {r.status} · อ้างอิงที่ยืนยันได้ {r.support_rate ?? "-"} · เอกสาร {r.retrieved.length} หน่วย
                </div>
                {r.resolution && (
                  <div className="flex gap-2 rounded-lg border border-emerald-600/20 bg-emerald-600/5 px-3 py-2">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
                    <span>{r.resolution} <span className="text-xs text-muted-foreground">— {r.resolved_by}</span></span>
                  </div>
                )}
                {canResolve && r.report_status === "open" && (
                  <div className="space-y-2 border-t pt-3">
                    <textarea
                      value={note[r.id] ?? ""}
                      onChange={(e) => setNote((n) => ({ ...n, [r.id]: e.target.value }))}
                      rows={2}
                      placeholder="บันทึกสิ่งที่แก้ หรือเหตุผลที่ไม่แก้ (ผู้รายงานจะเห็นข้อความนี้)"
                      className="block w-full resize-none rounded-[10px] border bg-background/60 px-3 py-2 outline-none focus:border-brand/60"
                    />
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="ghost" disabled={busy === r.id || (note[r.id] ?? "").trim().length < 3} onClick={() => resolve(r.id, "dismissed")}>ปิดเรื่อง (ไม่ใช่ข้อผิดพลาด)</Button>
                      <Button size="sm" disabled={busy === r.id || (note[r.id] ?? "").trim().length < 3} onClick={() => resolve(r.id, "resolved")}>แก้ไขแล้ว</Button>
                    </div>
                  </div>
                )}
              </article>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
