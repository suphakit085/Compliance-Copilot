"use client";

import { useEffect, useState } from "react";
import { BadgeCheck, Scale, Search } from "lucide-react";
import { cn } from "@/lib/utils";

/** Looping product preview: a question is typed, sources are searched, and the answer
 *  appears with a citation that gets "verified against the original". */
const EXAMPLES = [
  {
    q: "ข้อมูลลูกค้ารั่ว ต้องแจ้ง สคส. ภายในกี่ชั่วโมง?",
    a: "ต้องแจ้งโดยไม่ชักช้าภายใน 72 ชั่วโมงนับแต่ทราบเหตุ",
    cite: "PDPA มาตรา 37 (4)",
    quote: "…แจ้งเหตุการละเมิดข้อมูลส่วนบุคคลแก่สำนักงานโดยไม่ชักช้าภายในเจ็ดสิบสองชั่วโมง…",
  },
  {
    q: "ต้องเก็บข้อมูล CDD กี่ปีหลังปิดบัญชี?",
    a: "10 ปี นับแต่วันที่ปิดบัญชีหรือยุติความสัมพันธ์กับลูกค้า",
    cite: "พ.ร.บ.ฟอกเงิน มาตรา 22/1",
    quote: "…เป็นเวลาสิบปีนับแต่วันที่มีการปิดบัญชีหรือยุติความสัมพันธ์กับลูกค้า…",
  },
  {
    q: "แจกของรางวัลทันทีที่ลูกค้าสมัครสินเชื่อได้ไหม?",
    a: "ไม่ได้ — ห้ามให้รางวัลหรือของขวัญก่อนการอนุมัติสินเชื่อ",
    cite: "ธปท. Responsible Lending แนบ 2 ข้อ 2.3.2",
    quote: "…ห้ามผู้ให้บริการทำกิจกรรมส่งเสริมการขายที่ให้รางวัลหรือของขวัญก่อนการอนุมัติสินเชื่อ…",
  },
];

type Phase = "typing" | "searching" | "answer" | "verified";

export function DemoCard() {
  const [i, setI] = useState(0);
  const [typed, setTyped] = useState(0);
  const [phase, setPhase] = useState<Phase>("typing");
  const ex = EXAMPLES[i];

  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    if (phase === "typing") {
      t = typed < ex.q.length
        ? setTimeout(() => setTyped((n) => n + 1), 38)
        : setTimeout(() => setPhase("searching"), 350);
    } else if (phase === "searching") {
      t = setTimeout(() => setPhase("answer"), 1100);
    } else if (phase === "answer") {
      t = setTimeout(() => setPhase("verified"), 900);
    } else {
      t = setTimeout(() => {
        setI((x) => (x + 1) % EXAMPLES.length);
        setTyped(0);
        setPhase("typing");
      }, 3200);
    }
    return () => clearTimeout(t);
  }, [phase, typed, ex.q.length]);

  const shown = phase === "answer" || phase === "verified";

  return (
    <div className="panel relative overflow-hidden p-4 backdrop-blur" aria-hidden>
      <div className="mb-3 flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-success shadow-[0_0_8px_#00bb88]" /> ตัวอย่างการทำงานจริง
        </span>
        <span className="flex gap-1">
          {EXAMPLES.map((_, k) => (
            <span key={k} className={cn("h-1 w-4 rounded-full transition-colors", k === i ? "bg-brand" : "bg-white/10")} />
          ))}
        </span>
      </div>

      {/* question */}
      <div className="flex justify-end">
        <div className={cn("max-w-[90%] rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-sm", phase === "typing" && "caret")}>
          {ex.q.slice(0, typed) || " "}
        </div>
      </div>

      {/* answer */}
      <div className="mt-3 flex gap-2.5">
        <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-foreground text-background">
          <Scale className="size-3.5" />
        </div>
        <div className="min-h-[92px] flex-1 text-sm">
          {phase === "searching" && (
            <div className="flex items-center gap-2 pt-1 text-muted-foreground">
              <Search className="size-3.5 animate-pulse text-brand" />
              ค้นหาในกฎหมาย 8 ฉบับ และนโยบายภายใน…
            </div>
          )}
          {shown && (
            <div key={i} className="enter space-y-2" style={{ ["--d" as string]: "0ms" }}>
              <p className="leading-relaxed">
                {ex.a}{" "}
                <span className="rounded bg-brand/15 px-1 text-[0.7rem] font-semibold text-[#4db8ff]">S1</span>
              </p>
              <div className="rounded-lg border border-brand/25 bg-brand/[0.06] px-3 py-2 text-xs">
                <div className="mb-1 font-medium text-foreground/90">{ex.cite}</div>
                <div className="text-muted-foreground">
                  <mark className="rounded bg-brand/20 px-0.5 text-foreground/90">{ex.quote}</mark>
                </div>
              </div>
              {phase === "verified" && (
                <span className="pop-in inline-flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-[11px] font-medium text-success">
                  <BadgeCheck className="size-3.5" /> ยืนยันกับต้นฉบับแล้ว
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
