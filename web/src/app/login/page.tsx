"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, History, Loader2, Quote, Scale, ShieldCheck } from "lucide-react";

const DEMO = [
  { username: "somchai", label: "พนักงานสาขา", hint: "ระดับภายใน" },
  { username: "nida", label: "เจ้าหน้าที่ Compliance", hint: "เห็นเอกสารลับ" },
  { username: "kittipong", label: "ผู้ตรวจสอบภายใน", hint: "ดู Audit Trail" },
];

const FEATURES = [
  { icon: Quote, title: "อ้างอิงที่ตรวจสอบได้", body: "ทุกประโยคอ้างถึงมาตรา/ข้อ และระบบตรวจข้อความที่อ้างกับต้นฉบับทุกครั้ง" },
  { icon: ShieldCheck, title: "สิทธิ์และความเป็นส่วนตัว", body: "เห็นเฉพาะเอกสารที่มีสิทธิ์ ปิดบังข้อมูลส่วนบุคคลก่อนส่งให้ AI" },
  { icon: History, title: "รู้ว่ากฎฉบับไหนมีผล", body: "ตอบตามฉบับที่มีผล ณ วันที่เลือก พร้อม audit trail แบบ hash chain" },
];

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    setLoading(false);
    if (!res.ok) {
      setError((await res.json()).detail ?? "เข้าสู่ระบบไม่สำเร็จ");
      return;
    }
    router.replace("/");
    router.refresh();
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      <div className="aurora pointer-events-none absolute inset-0" />
      <div className="hairline-grid pointer-events-none absolute inset-0 [mask-image:radial-gradient(70%_60%_at_50%_0%,black,transparent)]" />

      <header className="relative flex items-center justify-between px-8 py-6">
        <div className="flex items-center gap-2.5 text-[15px] font-semibold">
          <Scale className="size-5" /> Compliance Copilot
        </div>
        <span className="text-sm text-muted-foreground">Thai Banking & Securities</span>
      </header>

      <main className="relative mx-auto grid max-w-6xl items-center gap-16 px-8 pb-16 pt-10 lg:grid-cols-[1.15fr_1fr] lg:pt-20">
        <section>
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border bg-card/60 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
            <span className="size-1.5 rounded-full bg-brand shadow-[0_0_8px_#0099ff]" />
            PDPA · AMLA · กฎกระทรวง CDD · ธปท. · ก.ล.ต.
          </div>
          <h1 className="text-4xl font-semibold leading-[1.15] tracking-tight sm:text-5xl xl:text-[56px]">
            <span className="whitespace-nowrap">คำตอบด้าน Compliance</span>
            <br />
            <span className="whitespace-nowrap bg-gradient-to-r from-[#0099ff] via-[#5cc4ff] to-[#a78bfa] bg-clip-text text-transparent">
              ที่ตรวจสอบได้ทุกประโยค
            </span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-muted-foreground">
            ผู้ช่วย AI สำหรับทีมกำกับการปฏิบัติงาน — ค้นกฎหมาย ประกาศหน่วยงานกำกับ และนโยบายภายใน
            แล้วตอบพร้อมหลักฐานจากต้นฉบับ
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="panel p-4">
                <f.icon className="mb-3 size-5 text-brand" />
                <div className="text-sm font-medium">{f.title}</div>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="glow-shell p-7">
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
            {error && <p className="text-sm text-destructive">{error}</p>}
            <button
              type="submit"
              disabled={loading || !username || !password}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-foreground text-sm font-medium text-background transition hover:opacity-90 disabled:opacity-40"
            >
              {loading ? <Loader2 className="size-4 animate-spin" /> : <>เข้าสู่ระบบ <ArrowRight className="size-4" /></>}
            </button>
          </form>
          <div className="mt-7 border-t pt-5">
            <p className="mb-2 text-xs text-muted-foreground">บัญชีทดลอง · รหัสผ่านอยู่ใน config/users.yaml</p>
            <div className="grid gap-1">
              {DEMO.map((d) => (
                <button
                  key={d.username}
                  type="button"
                  onClick={() => setUsername(d.username)}
                  className="flex items-center justify-between rounded-lg px-2.5 py-2 text-left text-sm transition hover:bg-white/5"
                >
                  <span>
                    <span className="font-medium">{d.username}</span>
                    <span className="text-muted-foreground"> · {d.label}</span>
                  </span>
                  <span className="text-xs text-muted-foreground">{d.hint}</span>
                </button>
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
