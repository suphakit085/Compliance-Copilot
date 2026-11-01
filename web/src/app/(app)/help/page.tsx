"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Clock, Flag, LifeBuoy, ShieldAlert, Siren } from "lucide-react";
import { api, REPORT_CATEGORIES, type MyReport } from "@/lib/api";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";

const STEPS = [
  { t: "ถามให้เฉพาะเจาะจง", d: "ระบุชื่อกฎหมาย หัวข้อ หรือสถานการณ์จริง เช่น \"ลูกค้าส่งกระเช้า 4,000 บาท รับได้ไหม\" ดีกว่า \"เรื่องของขวัญ\"" },
  { t: "ตรวจวันที่ \"ตามกฎ ณ วันที่\"", d: "ระบบตอบตามฉบับที่มีผลบังคับในวันที่เลือก ถ้าตรวจสอบเหตุการณ์ในอดีต ให้เลือกวันที่ของเหตุการณ์นั้น" },
  { t: "กดป้าย [S1] [S2] อ่านต้นฉบับ", d: "ข้อความที่ถูกอ้างอิงจะถูกไฮไลต์ในแผงด้านขวา อย่านำไปใช้ถ้ายังไม่ได้เทียบกับต้นฉบับ" },
  { t: "ดูสถานะของคำตอบ", d: "เขียว = ตอบจากแหล่งที่ตรวจสอบแล้ว · เหลือง = ตอบได้บางส่วน · แดง \"ยืนยันแหล่งอ้างอิงไม่ได้\" = ห้ามใช้ ให้อ่านต้นฉบับ · \"ไม่พบหลักฐาน\" = ไม่ได้แปลว่ากฎหมายไม่มี" },
  { t: "เรื่องสำคัญ ให้ผู้มีอำนาจยืนยัน", d: "คำตอบเป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่ความเห็นทางกฎหมาย เรื่องที่กระทบลูกค้า การรายงานหน่วยงานกำกับ หรือความรับผิดของธนาคาร ต้องปรึกษาฝ่ายกำกับการปฏิบัติงาน" },
];

const STATUS: Record<string, { label: string; icon: React.ElementType; cls: string }> = {
  open: { label: "รอดำเนินการ", icon: Clock, cls: "bg-amber-500/15 text-amber-700 dark:text-amber-400" },
  resolved: { label: "แก้ไขแล้ว", icon: CheckCircle2, cls: "bg-emerald-600/10 text-emerald-700 dark:text-emerald-400" },
  dismissed: { label: "ปิดเรื่อง", icon: CheckCircle2, cls: "bg-muted text-muted-foreground" },
};

export default function HelpPage() {
  const [mine, setMine] = useState<MyReport[] | null>(null);
  useEffect(() => { api<MyReport[]>("/feedback/mine").then(setMine).catch(() => setMine([])); }, []);

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="คู่มือการใช้งาน" description="ใช้ให้ถูกวิธี อ่านผลให้เป็น และรายงานเมื่อพบปัญหา" />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-8 px-4 py-6 md:px-8">
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-base font-semibold"><LifeBuoy className="size-4 text-brand" /> 5 ข้อก่อนเชื่อคำตอบ</h2>
            <ol className="space-y-2.5">
              {STEPS.map((s, i) => (
                <li key={s.t} className="panel flex gap-3 p-3.5">
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand/15 text-xs font-semibold text-[#4db8ff]">{i + 1}</span>
                  <span><span className="text-sm font-medium">{s.t}</span><span className="mt-0.5 block text-sm text-muted-foreground">{s.d}</span></span>
                </li>
              ))}
            </ol>
          </section>

          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-base font-semibold"><Flag className="size-4 text-brand" /> พบคำตอบผิดหรือน่าสงสัย</h2>
            <p className="text-sm text-muted-foreground">
              กดปุ่มนิ้วหัวแม่มือชี้ลง (👎) ใต้คำตอบ เลือกประเภทปัญหา และอธิบายสั้น ๆ เรื่องจะถึงเจ้าหน้าที่ Compliance ซึ่งจะแก้ที่ต้นเหตุ
              (เอกสาร คำศัพท์ หรือการตั้งค่า) แล้วแจ้งผลกลับมาที่หน้านี้ ประเภทที่ใช้ได้:
            </p>
            <ul className="grid gap-2 sm:grid-cols-2">
              {REPORT_CATEGORIES.map((c) => (
                <li key={c.value} className="panel p-3 text-sm">
                  <span className="font-medium">{c.label}</span>
                  <span className="block text-xs text-muted-foreground">{c.hint}</span>
                </li>
              ))}
            </ul>
            <div className="flex gap-2.5 rounded-[10px] border border-red-500/30 bg-red-500/5 p-3.5 text-sm">
              <Siren className="mt-0.5 size-4 shrink-0 text-red-500" />
              <span>ถ้าระบบแสดงเอกสารที่คุณ<strong>ไม่ควรเห็น</strong> (เช่น คู่มือลับของหน่วยงานอื่น) ให้รายงานประเภท “เห็นข้อมูลที่ไม่ควรเห็น” ทันที เรื่องนี้ถูกจัดเป็นเหตุการณ์ด่วนและบันทึกในบันทึกตรวจสอบ</span>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-base font-semibold"><ShieldAlert className="size-4 text-brand" /> เรื่องที่ฉันรายงาน</h2>
            {mine === null ? (
              <p className="text-sm text-muted-foreground">กำลังโหลด…</p>
            ) : mine.length === 0 ? (
              <p className="text-sm text-muted-foreground">ยังไม่มีเรื่องที่รายงาน</p>
            ) : (
              <ul className="space-y-2">
                {mine.map((m) => {
                  const st = STATUS[m.report_status] ?? STATUS.open;
                  return (
                    <li key={m.id} className="panel space-y-1.5 p-3.5 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge className={st.cls}><st.icon /> {st.label}</Badge>
                        <span className="text-xs text-muted-foreground">
                          {REPORT_CATEGORIES.find((c) => c.value === m.category)?.label ?? m.category} · {new Date(m.ts).toLocaleDateString("th-TH", { day: "numeric", month: "short" })}
                        </span>
                      </div>
                      <div className="text-muted-foreground">{m.question}</div>
                      {m.resolution && <div className="rounded-lg bg-muted/50 px-3 py-2">ผลการดำเนินการ: {m.resolution}</div>}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
