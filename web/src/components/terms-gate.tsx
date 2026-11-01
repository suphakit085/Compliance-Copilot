"use client";

import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { api, type TermsInfo, type User } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/modal";

/** Blocks the app until the signed-in user accepts the current acceptable-use terms. The server
 *  refuses questions until then; this is the part the user sees. */
export function TermsGate({ user, onAccepted }: { user: User | null; onAccepted: (u: User) => void }) {
  const needed = !!user && user.terms_required && !user.terms_accepted;
  const [terms, setTerms] = useState<TermsInfo | null>(null);
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (needed) api<TermsInfo>("/terms").then(setTerms).catch(() => {});
  }, [needed]);

  async function accept() {
    if (!terms) return;
    setBusy(true);
    try {
      onAccepted(await api<User>("/me/accept-terms", { body: { version: terms.version } }));
      toast.success("บันทึกการยอมรับข้อตกลงแล้ว");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
      api<TermsInfo>("/terms").then(setTerms).catch(() => {}); // the text may have changed meanwhile
      setAgree(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={needed} title="ข้อตกลงการใช้งาน" blocking className="sm:max-w-2xl">
      <div className="flex items-center gap-2.5 border-b px-5 py-4 text-sm font-medium">
        <ShieldCheck className="size-4 text-brand" /> ข้อตกลงการใช้งานก่อนเริ่มใช้
        {terms && <span className="ml-auto text-xs font-normal text-muted-foreground">เวอร์ชัน {terms.version}</span>}
      </div>
      <div className="answer-prose min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm">
        {terms ? <Markdown remarkPlugins={[remarkGfm]}>{terms.text}</Markdown> : <Loader2 className="mx-auto my-8 size-5 animate-spin text-brand" />}
      </div>
      <div className="space-y-3 border-t px-5 py-4">
        <label className="flex cursor-pointer items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={agree}
            onChange={(e) => setAgree(e.target.checked)}
            className="mt-1 size-4 accent-[#0099ff]"
          />
          ข้าพเจ้าได้อ่านและเข้าใจข้อตกลงข้างต้น และยอมรับว่าคำตอบเป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่ความเห็นทางกฎหมาย
        </label>
        <Button className="w-full" disabled={!agree || !terms || busy} onClick={accept}>
          {busy ? <Loader2 className="animate-spin" /> : "ยอมรับและเริ่มใช้งาน"}
        </Button>
      </div>
    </Modal>
  );
}
