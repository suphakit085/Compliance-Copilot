"use client";

import { Suspense, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, History, Loader2, Quote, Scale, ShieldCheck } from "lucide-react";
import { DemoCard } from "@/components/login/demo-card";
import { SsoButton } from "@/components/login/sso-button";

const DEMO = [
  { username: "somchai", label: "พนักงานสาขา", hint: "ระดับภายใน" },
  { username: "nida", label: "เจ้าหน้าที่ Compliance", hint: "เห็นเอกสารลับ" },
  { username: "kittipong", label: "ผู้ตรวจสอบภายใน", hint: "ดู Audit Trail" },
];

const FEATURES = [
  { icon: Quote, title: "อ้างอิงที่ตรวจสอบได้", body: "ตรวจข้อความที่อ้างกับต้นฉบับทุกครั้ง" },
  { icon: ShieldCheck, title: "สิทธิ์และความเป็นส่วนตัว", body: "เห็นเฉพาะที่มีสิทธิ์ ปิดบัง PII ก่อนส่ง AI" },
  { icon: History, title: "รู้ว่ากฎฉบับไหนมีผล", body: "ตอบตามฉบับที่มีผล ณ วันที่เลือก" },
];

/** Inline style helper for staggered entrance delays. */
const d = (ms: number) => ({ ["--d" as string]: `${ms}ms` });

export default function LoginPage() {
  const router = useRouter();
  const root = useRef<HTMLDivElement>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(0);

  function onMove(e: React.MouseEvent) {
    const el = root.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      setLoading(false);
      const data = await res.json().catch(() => null);
      setError(data?.detail ?? "เข้าสู่ระบบไม่สำเร็จ");
      setShake((n) => n + 1);
      return;
    }
    router.replace("/");
    router.refresh();
  }

  return (
    <div ref={root} onMouseMove={onMove} className="relative min-h-screen overflow-hidden bg-background">
      {/* animated backdrop */}
      <div className="aurora-blob a" />
      <div className="aurora-blob b" />
      <div className="aurora-blob c" />
      <div className="hairline-grid pointer-events-none absolute inset-0 [mask-image:radial-gradient(75%_65%_at_50%_10%,black,transparent)]" />
      <div className="spotlight pointer-events-none absolute inset-0" />

      <header className="enter relative flex items-center justify-between px-4 py-4 md:px-8 md:py-6" style={d(0)}>
        <div className="flex items-center gap-2.5 text-[15px] font-semibold">
          <span className="flex size-7 items-center justify-center rounded-lg bg-foreground text-background">
            <Scale className="size-4" />
          </span>
          Compliance Copilot
        </div>
        <span className="text-sm text-muted-foreground">Thai Banking & Securities</span>
      </header>

      <main className="relative mx-auto grid max-w-6xl items-center gap-10 px-4 pb-12 pt-2 md:px-8 lg:gap-14 lg:pb-16 lg:pt-12 lg:grid-cols-[1.15fr_1fr] ">
        <section>
          <div className="enter mb-6 inline-flex items-center gap-2 rounded-full border bg-card/60 px-3 py-1 text-xs text-muted-foreground backdrop-blur" style={d(80)}>
            <span className="pulse-ring size-1.5 rounded-full bg-brand" />
            PDPA · AMLA · กฎกระทรวง CDD · ธปท. · ก.ล.ต.
          </div>
          <h1 className="text-3xl font-semibold leading-[1.2] tracking-tight sm:text-5xl xl:text-[56px]">
            <span className="enter block sm:whitespace-nowrap" style={d(160)}>คำตอบด้าน Compliance</span>
            <span className="enter block sm:whitespace-nowrap" style={d(260)}>
              <span className="text-shimmer">ที่ตรวจสอบได้ทุกประโยค</span>
            </span>
          </h1>
          <p className="enter mt-5 max-w-xl text-lg text-muted-foreground" style={d(360)}>
            ผู้ช่วย AI สำหรับทีมกำกับการปฏิบัติงาน — ค้นกฎหมาย ประกาศหน่วยงานกำกับ และนโยบายภายใน
            แล้วตอบพร้อมหลักฐานจากต้นฉบับ
          </p>
          <div className="enter mt-8 max-w-xl" style={d(480)}>
            <DemoCard />
          </div>
          <div className="mt-6 grid max-w-xl gap-3 sm:grid-cols-3">
            {FEATURES.map((f, k) => (
              <div key={f.title} className="enter" style={d(600 + k * 90)}>
                <div className="lift panel h-full p-3.5">
                  <f.icon className="mb-2 size-4 text-brand" />
                  <div className="text-[13px] font-medium">{f.title}</div>
                  <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">{f.body}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="enter order-first lg:order-none" style={d(300)}>
          <div key={shake} className={shake ? "animate-[shake_0.4s_ease-in-out]" : undefined}>
            <div className="glow-shell border-spin p-5 sm:p-7">
              <h2 className="text-xl font-semibold">เข้าสู่ระบบ</h2>
              <p className="mt-1 text-sm text-muted-foreground">ใช้บัญชีพนักงานของธนาคาร</p>
              <form onSubmit={submit} className="mt-6 space-y-3">
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="ชื่อผู้ใช้"
                  autoComplete="username"
                  className="h-11 w-full rounded-[10px] border bg-background/60 px-3.5 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand/60 focus:ring-2 focus:ring-brand/20"
                />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="รหัสผ่าน"
                  autoComplete="current-password"
                  className="h-11 w-full rounded-[10px] border bg-background/60 px-3.5 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand/60 focus:ring-2 focus:ring-brand/20"
                />
                {error && <p className="pop-in text-sm text-destructive">{error}</p>}
                <button
                  type="submit"
                  disabled={loading || !username || !password}
                  className="group flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-foreground text-sm font-medium text-background transition hover:opacity-90 disabled:opacity-40"
                >
                  {loading ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <>
                      เข้าสู่ระบบ <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
                    </>
                  )}
                </button>
              </form>
              <Suspense fallback={null}>
                <SsoButton />
              </Suspense>
              <div className="mt-7 border-t pt-5">
                <p className="mb-2 text-xs text-muted-foreground">บัญชีทดลอง · รหัสผ่านอยู่ใน config/users.yaml</p>
                <div className="grid gap-1">
                  {DEMO.map((u) => (
                    <button
                      key={u.username}
                      type="button"
                      onClick={() => setUsername(u.username)}
                      className="flex items-center justify-between rounded-lg px-2.5 py-2 text-left text-sm transition hover:bg-white/5"
                    >
                      <span>
                        <span className="font-medium">{u.username}</span>
                        <span className="text-muted-foreground"> · {u.label}</span>
                      </span>
                      <span className="text-xs text-muted-foreground">{u.hint}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
