"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, CircleDashed, CircleX, Download, FileSearch, Loader2, OctagonAlert, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, type DocumentInfo, type GapReport } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const STATUS: Record<string, { label: string; icon: React.ElementType; className: string; ring: string }> = {
  conflict: { label: "ขัดแย้งกับกฎ", icon: CircleX, className: "text-red-600", ring: "border-red-500/40 bg-red-500/5" },
  partial: { label: "ไม่ครบถ้วน", icon: CircleAlert, className: "text-orange-600", ring: "border-orange-500/40 bg-orange-500/5" },
  needs_review: { label: "ต้องทบทวน", icon: OctagonAlert, className: "text-amber-600", ring: "border-amber-500/40 bg-amber-500/5" },
  compliant: { label: "สอดคล้อง", icon: CheckCircle2, className: "text-emerald-600", ring: "" },
  not_applicable: { label: "ไม่เกี่ยวข้อง", icon: CircleDashed, className: "text-muted-foreground", ring: "" },
  not_covered: { label: "ไม่มีกฎที่เกี่ยวข้องในคลัง", icon: CircleDashed, className: "text-muted-foreground", ring: "" },
  error: { label: "ประเมินไม่สำเร็จ", icon: XCircle, className: "text-muted-foreground", ring: "" },
};
const SEVERITY: Record<string, string> = { high: "สูง", medium: "กลาง", low: "ต่ำ", none: "-" };

export default function GapPage() {
  const [policies, setPolicies] = useState<DocumentInfo[]>([]);
  const [policy, setPolicy] = useState("");
  const [report, setReport] = useState<GapReport | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    api<DocumentInfo[]>("/documents").then((d) => {
      const p = d.filter((x) => x.source_kind === "internal" && x.in_force);
      setPolicies(p);
      setPolicy(p[0]?.id ?? "");
    });
  }, []);

  async function run() {
    setRunning(true);
    setReport(null);
    try {
      setReport(await api<GapReport>("/gap-analysis", { body: { policy_id: policy } }));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "วิเคราะห์ไม่สำเร็จ");
    } finally {
      setRunning(false);
    }
  }

  async function download() {
    if (!report) return;
    const md = await api<string>("/gap-analysis/markdown", { body: report });
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    Object.assign(document.createElement("a"), { href: url, download: `gap-${report.policy_id}.md` }).click();
    URL.revokeObjectURL(url);
  }

  const counts = report?.summary ?? {};

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Policy Gap Analysis"
        description="ตรวจนโยบายภายในทีละข้อเทียบกับกฎหมาย/ประกาศที่มีผลบังคับ — ผลลัพธ์เป็นรายการให้เจ้าหน้าที่ทบทวน ไม่ใช่คำวินิจฉัย"
      >
        <div className="flex items-center gap-2">
          <select
            value={policy}
            onChange={(e) => setPolicy(e.target.value)}
            className="h-8 rounded-lg border bg-background px-2 text-sm"
          >
            {policies.map((p) => <option key={p.id} value={p.id}>{p.short_title}</option>)}
          </select>
          <Button onClick={run} disabled={!policy || running}>
            {running ? <Loader2 className="animate-spin" /> : <FileSearch />} วิเคราะห์
          </Button>
          {report && <Button variant="outline" onClick={download}><Download /> รายงาน</Button>}
        </div>
      </PageHeader>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-6 px-8 py-6">
          {running && (
            <div className="flex items-center gap-3 panel p-6 text-sm text-muted-foreground">
              <Loader2 className="size-5 animate-spin text-brand" />
              กำลังค้นกฎที่เกี่ยวข้องและประเมินนโยบายทีละข้อ (ประมาณ 20–60 วินาที)…
            </div>
          )}
          {!report && !running && (
            <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
              เลือกนโยบายแล้วกด “วิเคราะห์” — ระบบจะค้นบทบัญญัติที่เกี่ยวข้องให้แต่ละข้อ ประเมินความสอดคล้อง
              และแนบข้อความกฎที่ตรวจสอบกับต้นฉบับแล้ว
            </div>
          )}
          {report && (
            <>
              <div className="grid gap-3 sm:grid-cols-4">
                {(["conflict", "partial", "needs_review", "compliant"] as const).map((k) => {
                  const S = STATUS[k];
                  return (
                    <div key={k} className="panel p-4">
                      <div className={cn("flex items-center gap-2 text-sm", S.className)}><S.icon className="size-4" /> {S.label}</div>
                      <div className="mt-1 text-3xl font-semibold">{counts[k] ?? 0}</div>
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-muted-foreground">
                {report.policy_title} · ณ วันที่ {report.as_of} · โมเดล {report.model} · {report.elapsed_s} วินาที · audit #{report.audit_id}
              </p>
              <div className="space-y-3">
                {report.findings.map((f) => {
                  const S = STATUS[f.status] ?? STATUS.error;
                  const important = ["conflict", "partial", "needs_review"].includes(f.status);
                  return (
                    <div key={f.clause_label} className={cn("panel p-5", important && S.ring)}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={cn("flex items-center gap-1.5 text-sm font-medium", S.className)}><S.icon className="size-4" /> {S.label}</span>
                        <Badge variant="outline">{f.clause_label}</Badge>
                        {f.severity !== "none" && <Badge variant="outline">ความรุนแรง: {SEVERITY[f.severity]}</Badge>}
                      </div>
                      <blockquote className="mt-3 border-l-2 pl-3 text-sm text-muted-foreground">{f.clause_text}</blockquote>
                      {important || f.status === "compliant" ? (
                        <div className="mt-3 space-y-2 text-sm">
                          <p><span className="font-medium">ข้อค้นพบ:</span> {f.finding}</p>
                          {important && <p><span className="font-medium">ข้อเสนอแนะ:</span> {f.recommendation}</p>}
                        </div>
                      ) : (
                        <p className="mt-3 text-sm text-muted-foreground">{f.finding}</p>
                      )}
                      {f.citations.length > 0 && (
                        <div className="mt-3 space-y-1.5">
                          {f.citations.map((c) => (
                            <div key={c.chunk_id + c.quote} className="flex gap-2 rounded-lg bg-muted/50 px-3 py-2 text-xs">
                              {c.verified ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" /> : <XCircle className="mt-0.5 size-3.5 shrink-0 text-red-500" />}
                              <span><span className="font-medium">{c.citation}</span> — “{c.quote}”</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
