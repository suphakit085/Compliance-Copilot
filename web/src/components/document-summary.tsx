"use client";

import { useEffect, useState } from "react";
import { BadgeCheck, Download, Loader2, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api, SUMMARY_SECTIONS, type DocSummary, type DocumentInfo } from "@/lib/api";
import { useUser } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const REVIEWERS = new Set(["compliance_officer", "admin"]);

/** Key points of the whole document. Every point carries quotes that the server found verbatim in
 *  the unit it names; clicking a unit opens it in the text below. A reading aid, not a substitute. */
export function DocumentSummary({ doc, onOpenUnit }: { doc: DocumentInfo; onOpenUnit: (chunkId: string) => void }) {
  const user = useUser();
  const [summary, setSummary] = useState<DocSummary | null | undefined>(undefined); // undefined = loading
  const [busy, setBusy] = useState<"make" | "review" | null>(null);
  const canReview = !!user && REVIEWERS.has(user.role);

  useEffect(() => {
    let stale = false;
    api<{ summary: DocSummary | null }>(`/documents/${doc.id}/summary`)
      .then((r) => { if (!stale) setSummary(r.summary); })
      .catch(() => { if (!stale) setSummary(null); });
    return () => { stale = true; };
  }, [doc.id]);

  async function make(force: boolean) {
    setBusy("make");
    try {
      const r = await api<{ summary: DocSummary }>(`/documents/${doc.id}/summary`, { body: { force } });
      setSummary(r.summary);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "สร้างสรุปไม่สำเร็จ");
    } finally {
      setBusy(null);
    }
  }

  async function review() {
    setBusy("review");
    try {
      const r = await api<{ summary: DocSummary }>(`/documents/${doc.id}/summary/review`, { body: {} });
      setSummary(r.summary);
      toast.success("บันทึกการรับรองสรุปแล้ว");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(null);
    }
  }

  async function download() {
    try {
      const md = await api<string>(`/documents/${doc.id}/summary/markdown`);
      const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `summary-${doc.id}.md` });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "ดาวน์โหลดไม่สำเร็จ");
    }
  }

  if (summary === undefined) return <Skeleton className="h-24" />;

  if (!summary) {
    return (
      <div className="panel flex flex-col items-start gap-3 p-5 sm:flex-row sm:items-center">
        <Sparkles className="size-5 shrink-0 text-brand" />
        <div className="min-w-0 flex-1 text-sm">
          <div className="font-medium">สรุปใจความสำคัญของเอกสารนี้</div>
          <p className="text-muted-foreground">
            ระบบจะอ่านครบทั้ง {doc.chunks} หน่วย แล้วสรุปเป็นประเด็น ทุกประเด็นมีข้อความอ้างอิงที่ตรวจกับต้นฉบับ
            {doc.chunks > 40 ? " · เอกสารยาว ใช้เวลาประมาณ 1–2 นาที" : ""}
          </p>
        </div>
        <Button onClick={() => make(false)} disabled={busy !== null}>
          {busy ? <><Loader2 className="animate-spin" /> กำลังอ่านเอกสาร…</> : "สรุปเอกสารนี้"}
        </Button>
      </div>
    );
  }

  const st = summary.stats;
  return (
    <div className="space-y-4">
      {summary.stale && (
        <div className="flex gap-2 rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-sm text-red-700 dark:text-red-300">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          เอกสารถูกแก้ไขหลังจากสรุปนี้ถูกสร้าง สรุปด้านล่างอาจไม่ตรงกับฉบับปัจจุบัน — สร้างสรุปใหม่ก่อนใช้
        </div>
      )}
      <div className="panel flex flex-wrap items-center gap-x-4 gap-y-2 px-3.5 py-2.5 text-sm">
        {summary.reviewed_by && !summary.stale ? (
          <span className="inline-flex items-center gap-1.5 font-medium text-success">
            <BadgeCheck className="size-4" /> รับรองโดย {summary.reviewed_by} · {summary.reviewed_at?.slice(0, 10)}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-amber-600 dark:text-amber-400">
            <TriangleAlert className="size-4" /> สรุปโดย AI ยังไม่ผ่านการรับรองโดยเจ้าหน้าที่ Compliance
          </span>
        )}
        <span className="text-muted-foreground">
          อ่านครบ {st.units} หน่วย · {st.points} ประเด็น อ้างถึง {st.units_cited} หน่วย
          {st.dropped_points > 0 && ` · ตัดออก ${st.dropped_points} ประเด็นที่ยืนยันกับต้นฉบับไม่ได้`}
        </span>
        <span className="ml-auto flex flex-wrap gap-1.5">
          <Button variant="ghost" size="sm" onClick={download}><Download /> Markdown</Button>
          {canReview && (
            <Button variant="ghost" size="sm" onClick={() => make(true)} disabled={busy !== null}>
              {busy === "make" ? <Loader2 className="animate-spin" /> : <RefreshCw />} สร้างใหม่
            </Button>
          )}
          {canReview && !summary.stale && !summary.reviewed_by && (
            <Button size="sm" onClick={review} disabled={busy !== null}>
              {busy === "review" ? <Loader2 className="animate-spin" /> : <BadgeCheck />} รับรองสรุปนี้
            </Button>
          )}
        </span>
      </div>

      {SUMMARY_SECTIONS.map(({ key, label }) => {
        const points = summary.points.filter((p) => p.section === key);
        if (!points.length) return null;
        return (
          <section key={key} className="panel">
            <h3 className="border-b px-4 py-2.5 text-sm font-semibold">
              {label} <span className="font-normal text-muted-foreground">· {points.length}</span>
            </h3>
            <ul className="divide-y">
              {points.map((p, i) => (
                <li key={i} className="space-y-1.5 px-4 py-3">
                  <p className="text-sm leading-relaxed">{p.text}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {p.citations.map((c, k) => (
                      <button
                        key={k}
                        title={`"${c.quote}"`}
                        onClick={() => onOpenUnit(c.chunk_id)}
                        className="rounded-md bg-brand/15 px-2 py-0.5 text-xs font-semibold text-[#4db8ff] transition hover:bg-brand/25"
                      >
                        {c.label}
                      </button>
                    ))}
                  </div>
                  <p className="border-l-2 border-brand/30 pl-2.5 text-xs leading-relaxed text-muted-foreground">
                    “{p.citations[0].quote}”
                  </p>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      <p className="text-xs text-muted-foreground">
        สรุปนี้เป็นตัวช่วยอ่านเพื่อให้รู้ว่าควรอ่านส่วนใด ไม่ใช้แทนการอ่านต้นฉบับในเรื่องที่มีผลจริง · {summary.model} · {summary.prompt_version}
      </p>
    </div>
  );
}
