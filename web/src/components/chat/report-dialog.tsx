"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, REPORT_CATEGORIES, type ReportCategory } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/modal";

/** "รายงานปัญหา" under an answer: what kind of problem, and a comment. Creates an open report that a
 *  compliance officer triages (see /reports); a `leak` report is raised as an incident immediately. */
export function ReportDialog({ auditId, open, onClose, onSent }: {
  auditId: number;
  open: boolean;
  onClose: () => void;
  onSent: () => void;
}) {
  const [category, setCategory] = useState<ReportCategory | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    if (!category) return;
    setBusy(true);
    try {
      await api("/feedback", { body: { audit_id: auditId, rating: -1, category, comment: comment.trim() || undefined } });
      toast.success(category === "leak" ? "รายงานเป็นเหตุการณ์ด่วนแล้ว เจ้าหน้าที่จะติดต่อกลับ" : "ส่งรายงานแล้ว ขอบคุณที่ช่วยปรับปรุงระบบ");
      onSent();
      onClose();
      setCategory(null);
      setComment("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "ส่งรายงานไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="รายงานปัญหาของคำตอบ">
      <div className="border-b px-5 py-4 text-sm font-medium">รายงานปัญหาของคำตอบนี้</div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-5 py-4">
        {REPORT_CATEGORIES.map((c) => (
          <label
            key={c.value}
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-[10px] border px-3 py-2.5 text-sm transition",
              category === c.value ? "border-brand/60 bg-brand/5" : "hover:bg-white/[0.03]",
              c.value === "leak" && "border-red-500/30",
            )}
          >
            <input type="radio" name="category" checked={category === c.value} onChange={() => setCategory(c.value)} className="mt-1 accent-[#0099ff]" />
            <span>
              <span className="font-medium">{c.label}</span>
              <span className="block text-xs text-muted-foreground">{c.hint}</span>
            </span>
          </label>
        ))}
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          maxLength={1000}
          rows={3}
          placeholder="อธิบายเพิ่มเติม (ไม่บังคับ) — ไม่ต้องใส่ข้อมูลส่วนบุคคลของลูกค้า"
          className="mt-1 block w-full resize-none rounded-[10px] border bg-background/60 px-3 py-2 text-sm outline-none focus:border-brand/60"
        />
      </div>
      <div className="flex justify-end gap-2 border-t px-5 py-3">
        <Button variant="ghost" onClick={onClose}>ยกเลิก</Button>
        <Button disabled={!category || busy} onClick={send}>{busy ? <Loader2 className="animate-spin" /> : "ส่งรายงาน"}</Button>
      </div>
    </Modal>
  );
}
