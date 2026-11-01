"use client";

import { useEffect, useMemo, useState } from "react";
import { ClipboardCheck, ExternalLink, FileScan, FlaskConical, Lock, Search, StickyNote, TriangleAlert } from "lucide-react";
import { api, type DocumentInfo, type Section } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [sections, setSections] = useState<Section[] | null>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api<DocumentInfo[]>("/documents").then((d) => { setDocs(d); setActive(d[0]?.id ?? null); });
  }, []);
  useEffect(() => {
    if (!active) return;
    let stale = false;
    api<Section[]>(`/documents/${active}/sections`).then((s) => { if (!stale) setSections(s); });
    return () => { stale = true; };
  }, [active]);

  const doc = docs?.find((d) => d.id === active);
  const shown = useMemo(
    () => (sections ?? []).filter((s) => !q || s.text.includes(q) || s.label.includes(q)),
    [sections, q],
  );
  const groups = [
    { key: "regulation", label: "กฎหมายและประกาศหน่วยงานกำกับ" },
    { key: "internal", label: "นโยบายและคู่มือภายใน" },
  ] as const;

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="คลังเอกสาร" description="แสดงเฉพาะเอกสารที่คุณมีสิทธิ์เข้าถึง · แยกเป็นหน่วยที่อ้างอิงได้ (มาตรา / ข้อ)" />
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="max-h-44 shrink-0 overflow-y-auto border-b p-3 md:max-h-none md:w-80 md:border-b-0 md:border-r md:p-4">
          {!docs && <div className="space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-16" />)}</div>}
          {docs && groups.map((g) => (
            <div key={g.key} className="mb-5">
              <div className="mb-2 px-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">{g.label}</div>
              <div className="space-y-1">
                {docs.filter((d) => d.source_kind === g.key).map((d) => (
                  <button
                    key={d.id}
                    onClick={() => { setActive(d.id); setSections(null); setQ(""); setOpen(null); }}
                    className={cn(
                      "w-full rounded-lg px-3 py-2.5 text-left transition",
                      active === d.id ? "bg-white/[0.07]" : "hover:bg-white/[0.04]",
                    )}
                  >
                    <div className={cn("text-sm leading-snug", active === d.id && "font-medium text-foreground")}>{d.short_title}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      <span className={cn("size-1.5 rounded-full", d.in_force ? "bg-emerald-500" : "bg-zinc-400")} />
                      {d.in_force ? "มีผลบังคับ" : d.effective_to ? "สิ้นผลแล้ว" : "ยังไม่มีผล"}
                      <span>· {d.chunks} หน่วย</span>
                      {d.classification === "confidential" && <Lock className="size-3 text-red-500" />}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="min-w-0 flex-1 overflow-y-auto">
          {doc && (
            <div className="mx-auto max-w-4xl space-y-5 px-4 py-4 md:px-8 md:py-6">
              <div className="space-y-3">
                <h2 className="text-lg font-semibold leading-snug">{doc.title}</h2>
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="outline">{doc.issuer}</Badge>
                  {doc.version && <Badge variant="outline">ฉบับ {doc.version}</Badge>}
                  <Badge variant="outline">มีผล {doc.effective_from}{doc.effective_to ? ` → ${doc.effective_to}` : ""}</Badge>
                  {doc.classification === "confidential" && <Badge className="bg-red-600/10 text-red-700"><Lock /> ลับ</Badge>}
                  {doc.synthetic && <Badge className="bg-violet-500/10 text-violet-700 dark:text-violet-400"><FlaskConical /> เอกสารจำลองเพื่อการสาธิต</Badge>}
                  {!!doc.quality?.ocr_pages?.length && <Badge className="bg-amber-500/15 text-amber-700"><FileScan /> OCR หน้า {doc.quality.ocr_pages.join(", ")}</Badge>}
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    ["หน้า", doc.pages ?? "-"],
                    ["หน่วยที่อ้างอิงได้", doc.chunks],
                    ["Dictionary coverage", doc.quality?.dictionary_coverage ?? "-"],
                    ["เชิงอรรถการแก้ไข", doc.quality?.footnotes ?? 0],
                  ].map(([k, v]) => (
                    <div key={k} className="panel p-3">
                      <div className="text-xs text-muted-foreground">{k}</div>
                      <div className="text-lg font-semibold">{v}</div>
                    </div>
                  ))}
                </div>
                {doc.source_kind === "internal" && doc.governance?.owner && (
                  <div className="panel flex flex-wrap items-center gap-x-5 gap-y-1.5 px-3.5 py-2.5 text-sm">
                    <ClipboardCheck className="size-4 text-muted-foreground" />
                    <span><span className="text-muted-foreground">เจ้าของ </span>{doc.governance.owner}</span>
                    <span><span className="text-muted-foreground">อนุมัติโดย </span>{doc.governance.approved_by} · {doc.governance.approved_on}</span>
                    <span
                      className={cn(
                        doc.governance.review_state === "overdue" && "font-medium text-red-600 dark:text-red-400",
                        doc.governance.review_state === "due_soon" && "font-medium text-amber-600 dark:text-amber-400",
                      )}
                    >
                      <span className="font-normal text-muted-foreground">ทบทวนภายใน </span>
                      {doc.governance.review_due}
                      {doc.governance.review_state === "overdue" && " · เกินกำหนดทบทวน"}
                      {doc.governance.review_state === "due_soon" && ` · อีก ${doc.governance.review_days_left} วัน`}
                    </span>
                  </div>
                )}
                {doc.source_kind === "regulation" && doc.source_checked_at && (
                  <p className="text-xs text-muted-foreground">
                    ตรวจสอบกับต้นฉบับล่าสุด {new Date(doc.source_checked_at).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" })}
                  </p>
                )}
                {doc.amended_by?.map((a) => (
                  <div key={a.ref} className="flex gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
                    <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                    แก้ไขเพิ่มเติมโดย {a.ref} (มีผล {a.effective_from}) {a.note}
                  </div>
                ))}
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {doc.official_ref && <span>อ้างอิงทางการ: {doc.official_ref}</span>}
                  {doc.official_url && <a className="inline-flex items-center gap-1 text-primary hover:underline" href={doc.official_url} target="_blank" rel="noreferrer">แหล่งทางการ <ExternalLink className="size-3" /></a>}
                  {doc.source_name && <span>ไฟล์จาก: {doc.source_name}</span>}
                  {doc.sha256 && <span className="font-mono">sha256 {doc.sha256.slice(0, 16)}…</span>}
                </div>
              </div>

              <div className="relative">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ค้นหาในเอกสารนี้ เช่น ระยะเวลา, ยินยอม, มาตรา 26" className="h-10 pl-9" />
              </div>

              <div className="divide-y panel">
                {!sections && <div className="space-y-2 p-4">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10" />)}</div>}
                {shown.map((s) => (
                  <div key={s.id}>
                    <button onClick={() => setOpen(open === s.id ? null : s.id)} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-muted/50">
                      <span className="mt-0.5 shrink-0 rounded-md bg-brand/15 px-2 py-0.5 text-xs font-semibold text-[#4db8ff]">{s.label}</span>
                      <span className={cn("min-w-0 text-sm text-foreground/80", open !== s.id && "line-clamp-1")}>
                        {s.title ?? s.text.replace(s.label, "").slice(0, 160)}
                      </span>
                    </button>
                    {open === s.id && (
                      <div className="space-y-2 px-4 pb-4">
                        {s.path.length > 0 && <div className="text-xs text-muted-foreground">{s.path.join(" › ")}</div>}
                        <div className="source-text rounded-lg bg-muted/40 p-4">{s.text}</div>
                        {s.notes.map((n) => (
                          <p key={n} className="flex gap-1.5 text-xs text-muted-foreground"><StickyNote className="mt-0.5 size-3 shrink-0" /> {n}</p>
                        ))}
                        <div className="text-xs text-muted-foreground">หน้า {s.pages[0]}{s.pages[1] !== s.pages[0] ? `–${s.pages[1]}` : ""}{s.extraction === "ocr" ? " · ข้อความจาก OCR" : ""}</div>
                      </div>
                    )}
                  </div>
                ))}
                {sections && shown.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">ไม่พบข้อความที่ค้นหา</p>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
