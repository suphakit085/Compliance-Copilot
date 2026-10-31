"use client";

import { useEffect, useState } from "react";
import { FlaskConical, Gauge, ShieldCheck, Target } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/app-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface AblationRow { config: string; "hit@1": number; "hit@3": number; "hit@6": number; "recall@6": number; mrr: number; leakage: number; latency_ms: number }
interface EvalData {
  created_at: string;
  n_questions: number;
  retrieval_ablation?: AblationRow[];
  threshold_calibration?: { current: number; current_accuracy: number; min_answerable_score: number; max_out_of_corpus_score: number };
  end_to_end?: {
    model: string | null;
    stopped_early: string | null;
    summary: Record<string, number | null>;
    by_category: { category: string; n: number; behaviour_accuracy: number | null; key_fact_accuracy: number | null; citation_recall: number | null }[];
  };
}

const E2E_LABEL: Record<string, string> = {
  behaviour_accuracy: "พฤติกรรมถูกต้อง (ตอบ/ปฏิเสธ/บล็อก)",
  key_fact_accuracy: "ข้อเท็จจริงสำคัญถูกต้อง",
  citation_precision: "Citation precision",
  citation_recall: "Citation recall",
  quote_verification_rate: "ข้อความอ้างอิงยืนยันได้",
  leakage_count: "เอกสารลับรั่วไหล",
  pii_masking_recall: "ปิดบัง PII",
  latency_p50_ms: "Latency p50 (ms)",
  latency_p95_ms: "Latency p95 (ms)",
  n_evaluated: "จำนวนคำถามที่ประเมิน",
};

function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`;
}

export default function EvalPage() {
  const [ev, setEv] = useState<EvalData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<EvalData>("/eval/latest").then(setEv).catch((e) => setErr(e.message)); }, []);

  const best = ev?.retrieval_ablation?.at(-1);
  const base = ev?.retrieval_ablation?.[0];

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Evaluation" description="วัดคุณภาพด้วย golden set ที่ตรวจด้วยกฎตายตัว (evidence string / key facts) — ไม่พึ่ง LLM เป็นผู้ตัดสิน" />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-6 px-8 py-6">
          {err && <p className="text-sm text-muted-foreground">{err}</p>}
          {!ev && !err && <Skeleton className="h-64" />}
          {ev && (
            <>
              <p className="text-xs text-muted-foreground">รันเมื่อ {new Date(ev.created_at).toLocaleString("th-TH")} · golden set {ev.n_questions} คำถาม</p>
              {best && base && (
                <div className="grid gap-3 sm:grid-cols-4">
                  {[
                    { icon: Target, label: "Hit@6 (production)", value: pct(best["hit@6"]), sub: `baseline ${pct(base["hit@6"])}` },
                    { icon: Gauge, label: "MRR", value: best.mrr.toFixed(2), sub: `baseline ${base.mrr.toFixed(2)}` },
                    { icon: ShieldCheck, label: "เอกสารลับรั่วไหล", value: String(best.leakage), sub: "ทุก configuration" },
                    { icon: FlaskConical, label: "แยกคำถามนอกคลังได้", value: pct(ev.threshold_calibration?.current_accuracy), sub: `threshold ${ev.threshold_calibration?.current}` },
                  ].map((c) => (
                    <div key={c.label} className="panel p-4">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground"><c.icon className="size-4 text-brand" /> {c.label}</div>
                      <div className="mt-1 text-3xl font-semibold">{c.value}</div>
                      <div className="text-xs text-muted-foreground">{c.sub}</div>
                    </div>
                  ))}
                </div>
              )}

              {ev.retrieval_ablation && (
                <div className="panel p-5">
                  <h3 className="font-medium">Retrieval ablation</h3>
                  <p className="mb-4 text-xs text-muted-foreground">แต่ละขั้นของ pipeline ช่วยอะไร — วัดบนคำถามที่ตอบได้ ด้วย top-6 context</p>
                  <div className="space-y-3">
                    {ev.retrieval_ablation.map((r, i) => (
                      <div key={r.config} className="grid grid-cols-[1fr_auto] items-center gap-4">
                        <div>
                          <div className={cn("mb-1 text-sm", i === ev.retrieval_ablation!.length - 1 && "font-medium")}>{r.config}</div>
                          <div className="h-2.5 overflow-hidden rounded-full bg-muted">
                            <div className={cn("h-full rounded-full", i === ev.retrieval_ablation!.length - 1 ? "bg-primary" : "bg-primary/40")} style={{ width: `${r["hit@6"] * 100}%` }} />
                          </div>
                        </div>
                        <div className="w-28 text-right text-sm tabular-nums">{pct(r["hit@6"])} <span className="text-xs text-muted-foreground">hit@6</span></div>
                      </div>
                    ))}
                  </div>
                  <Table className="mt-5">
                    <TableHeader>
                      <TableRow>
                        {["config", "hit@1", "hit@3", "hit@6", "recall@6", "mrr", "leakage", "latency_ms"].map((h) => <TableHead key={h}>{h}</TableHead>)}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {ev.retrieval_ablation.map((r) => (
                        <TableRow key={r.config}>
                          <TableCell className="max-w-64 whitespace-normal text-xs">{r.config}</TableCell>
                          {(["hit@1", "hit@3", "hit@6", "recall@6", "mrr"] as const).map((k) => <TableCell key={k} className="tabular-nums">{r[k].toFixed(3)}</TableCell>)}
                          <TableCell>{r.leakage}</TableCell>
                          <TableCell className="tabular-nums">{r.latency_ms}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {ev.end_to_end ? (
                <div className="panel p-5">
                  <h3 className="font-medium">End-to-end (โมเดล {ev.end_to_end.model})</h3>
                  {ev.end_to_end.stopped_early && <p className="mt-1 text-xs text-amber-600">หยุดก่อนครบ: {ev.end_to_end.stopped_early}</p>}
                  <div className="mt-4 grid gap-3 sm:grid-cols-3">
                    {Object.entries(ev.end_to_end.summary).map(([k, v]) => (
                      <div key={k} className="rounded-lg bg-muted/50 p-3">
                        <div className="text-xs text-muted-foreground">{E2E_LABEL[k] ?? k}</div>
                        <div className="text-xl font-semibold tabular-nums">
                          {v === null ? "–" : k.includes("ms") || k.includes("count") || k.startsWith("n_") ? v : pct(v)}
                        </div>
                      </div>
                    ))}
                  </div>
                  <Table className="mt-5">
                    <TableHeader>
                      <TableRow><TableHead>หมวด</TableHead><TableHead>n</TableHead><TableHead>พฤติกรรม</TableHead><TableHead>ข้อเท็จจริง</TableHead><TableHead>citation recall</TableHead></TableRow>
                    </TableHeader>
                    <TableBody>
                      {ev.end_to_end.by_category.map((c) => (
                        <TableRow key={c.category}>
                          <TableCell>{c.category}</TableCell><TableCell>{c.n}</TableCell>
                          <TableCell>{pct(c.behaviour_accuracy)}</TableCell><TableCell>{pct(c.key_fact_accuracy)}</TableCell><TableCell>{pct(c.citation_recall)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
                  ยังไม่มีผล end-to-end — รัน <code className="rounded bg-muted px-1">uv run copilot eval</code> เมื่อมีโควตา LLM
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
