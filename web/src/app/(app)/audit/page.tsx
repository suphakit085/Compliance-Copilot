"use client";

import { useCallback, useEffect, useState } from "react";
import { Link2, Loader2, ShieldCheck, ShieldX } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface AuditRow {
  id: number;
  ts: string;
  username: string | null;
  role: string | null;
  event: string;
  payload: Record<string, unknown> & { status?: string; question_masked?: string };
  hash: string;
  prev_hash: string;
  feedback: number | null;
}

const EVENTS = ["ทั้งหมด", "chat", "gap_analysis", "login", "login_failed", "access_denied"];

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [event, setEvent] = useState("ทั้งหมด");
  const [selected, setSelected] = useState<AuditRow | null>(null);
  const [verify, setVerify] = useState<{ valid: boolean; checked: number; head?: string; broken_at_id?: number } | null>(null);
  const [checking, setChecking] = useState(false);
  const [denied, setDenied] = useState<string | null>(null);

  const load = useCallback(() => {
    const qs = event === "ทั้งหมด" ? "" : `&event=${event}`;
    api<AuditRow[]>(`/audit?limit=200${qs}`)
      .then((r) => { setRows(r); setSelected(r[0] ?? null); })
      .catch((e) => setDenied(e instanceof ApiError && e.status === 403 ? "หน้านี้สำหรับเจ้าหน้าที่ Compliance ผู้ตรวจสอบภายใน และผู้ดูแลระบบเท่านั้น" : String(e)));
  }, [event]);
  useEffect(load, [load]);

  async function check() {
    setChecking(true);
    try {
      setVerify(await api("/audit/verify"));
    } catch {
      setDenied("ไม่สามารถตรวจสอบ hash chain ได้");
    } finally {
      setChecking(false);
    }
  }

  if (denied) {
    return (
      <div className="flex h-full flex-col">
        <PageHeader title="Audit Trail" />
        <div className="m-8 rounded-[14px] border border-dashed p-10 text-center text-sm text-muted-foreground">
          {denied}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Audit Trail" description="บันทึกทุกคำถาม คำตอบ และการเข้าถึง แบบ append-only พร้อม hash chain ตรวจจับการแก้ไขย้อนหลัง">
        <div className="flex items-center gap-2">
          {verify && (
            <span className={cn("flex items-center gap-1.5 text-sm", verify.valid ? "text-emerald-600" : "text-red-600")}>
              {verify.valid ? <ShieldCheck className="size-4" /> : <ShieldX className="size-4" />}
              {verify.valid ? `ถูกต้องทั้ง ${verify.checked} รายการ` : `พบการแก้ไขที่รายการ #${verify.broken_at_id}`}
            </span>
          )}
          <Button onClick={check} disabled={checking}>
            {checking ? <Loader2 className="animate-spin" /> : <Link2 />} ตรวจสอบ hash chain
          </Button>
        </div>
      </PageHeader>
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto px-6 py-4">
          <div className="mb-3 flex flex-wrap gap-1.5">
            {EVENTS.map((e) => (
              <button
                key={e}
                onClick={() => setEvent(e)}
                className={cn("rounded-full border px-3 py-1 text-xs", event === e ? "border-primary bg-brand/15 text-[#4db8ff]" : "text-muted-foreground hover:bg-muted")}
              >
                {e}
              </button>
            ))}
          </div>
          <div className="panel">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-14">#</TableHead>
                  <TableHead className="w-40">เวลา</TableHead>
                  <TableHead>ผู้ใช้</TableHead>
                  <TableHead>เหตุการณ์</TableHead>
                  <TableHead>คำถาม (ปิดบัง PII แล้ว)</TableHead>
                  <TableHead className="w-28">hash</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows?.map((r) => (
                  <TableRow key={r.id} onClick={() => setSelected(r)} className={cn("cursor-pointer", selected?.id === r.id && "bg-primary/5")}>
                    <TableCell className="text-muted-foreground">{r.id}</TableCell>
                    <TableCell className="text-xs">{new Date(r.ts).toLocaleString("th-TH")}</TableCell>
                    <TableCell className="text-sm">{r.username ?? "-"}<div className="text-xs text-muted-foreground">{r.role}</div></TableCell>
                    <TableCell>
                      <Badge variant="outline">{r.event}</Badge>
                      {r.payload.status && <div className="mt-1 text-xs text-muted-foreground">{String(r.payload.status)}</div>}
                    </TableCell>
                    <TableCell className="max-w-72 truncate text-sm">{r.payload.question_masked ?? ""}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{r.hash.slice(0, 10)}…</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
        <aside className="hidden w-[440px] shrink-0 overflow-y-auto border-l bg-muted/30 p-5 xl:block">
          {selected && (
            <div className="space-y-3">
              <div className="text-sm font-medium">รายการ #{selected.id} · {selected.event}</div>
              <div className="space-y-1 rounded-lg bg-card p-3 font-mono text-[0.7rem] text-muted-foreground">
                <div>prev: {selected.prev_hash}</div>
                <div>hash: {selected.hash}</div>
              </div>
              <pre className="max-h-[70vh] overflow-auto rounded-lg bg-card p-3 text-[0.7rem] leading-relaxed">
                {JSON.stringify(selected.payload, null, 2)}
              </pre>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
