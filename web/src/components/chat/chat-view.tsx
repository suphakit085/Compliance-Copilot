"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUp, BookMarked, CalendarClock, Gift, HandCoins, Landmark, Loader2, RotateCcw, Scale, ShieldCheck,
} from "lucide-react";
import { api, type ChatResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useUser } from "@/components/app-shell";
import { useToday } from "@/lib/use-today";
import { CONVERSATIONS_CHANGED } from "@/lib/events";
import { Answer } from "@/components/chat/answer";
import { SourceCard } from "@/components/chat/source-card";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

type Msg = { role: "user"; content: string } | { role: "assistant"; content: string; response: ChatResponse };

const EXAMPLES = [
  { icon: ShieldCheck, tag: "PDPA", q: "ถ้าข้อมูลลูกค้ารั่วไหล ต้องแจ้งสำนักงานคุ้มครองข้อมูลภายในกี่ชั่วโมง และนโยบายภายในเราสอดคล้องไหม" },
  { icon: Landmark, tag: "AML / CDD", q: "ต้องเก็บรักษาข้อมูล CDD ของลูกค้านานกี่ปีหลังปิดบัญชี" },
  { icon: Gift, tag: "นโยบายภายใน", q: "พนักงานรับของขวัญตามเทศกาลจากลูกค้าได้ไม่เกินกี่บาท" },
  { icon: HandCoins, tag: "ธปท.", q: "ธนาคารจัดโปรแจกของรางวัลให้ลูกค้าทันทีที่สมัครสินเชื่อได้หรือไม่" },
];

const STEPS = [
  "ตรวจสอบคำถามและปิดบังข้อมูลส่วนบุคคล",
  "ค้นหาในเอกสารที่คุณมีสิทธิ์เข้าถึง",
  "จัดอันดับความเกี่ยวข้องด้วย cross-encoder",
  "สร้างคำตอบจากแหล่งอ้างอิง",
  "ตรวจสอบข้อความที่อ้างกับต้นฉบับ",
];

function Thinking() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((x) => Math.min(x + 1, STEPS.length - 1)), 1400);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="space-y-2.5 py-1">
      {STEPS.map((s, k) => (
        <div key={s} className={cn("flex items-center gap-2.5 text-sm transition-opacity duration-500", k > i ? "opacity-25" : "opacity-100")}>
          {k < i ? (
            <span className="flex size-4 items-center justify-center text-success">✓</span>
          ) : k === i ? (
            <Loader2 className="size-4 animate-spin text-brand" />
          ) : (
            <span className="size-4" />
          )}
          <span className={k === i ? "text-foreground" : "text-muted-foreground"}>{s}</span>
        </div>
      ))}
    </div>
  );
}

function Composer({
  value, onChange, onSubmit, loading, asOf, setAsOf, autoFocus, big,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
  asOf: string;
  setAsOf: (v: string) => void;
  autoFocus?: boolean;
  big?: boolean;
}) {
  return (
    <form
      className="glow-shell w-full p-3"
      onSubmit={(e) => { e.preventDefault(); onSubmit(); }}
    >
      <textarea
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSubmit();
          }
        }}
        rows={big ? 3 : 1}
        placeholder="ถามเรื่องกฎหมาย ประกาศ หรือนโยบายภายใน…"
        className="block max-h-40 w-full resize-none bg-transparent px-2 py-1.5 text-base outline-none placeholder:text-muted-foreground/70 sm:text-[15px]"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <label
          className="flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted-foreground transition hover:bg-white/5"
          title="ตอบตามกฎ/นโยบายที่มีผลบังคับ ณ วันที่เลือก"
        >
          <CalendarClock className="size-3.5" /> <span className="hidden sm:inline">ตามกฎ ณ วันที่</span>
          <input
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            className="bg-transparent text-foreground outline-none [color-scheme:dark]"
          />
        </label>
        <button
          type="submit"
          disabled={!value.trim() || loading}
          aria-label="ส่ง"
          className="flex size-8 items-center justify-center rounded-[9px] bg-foreground text-background transition hover:opacity-90 disabled:opacity-30"
        >
          {loading ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
        </button>
      </div>
    </form>
  );
}

/** Messages handed over when a new chat gets its id, so /c/<id> renders without a refetch flash. */
const handover = new Map<string, Msg[]>();


export function ChatView({ conversationId }: { conversationId?: string }) {
  const user = useUser();
  const router = useRouter();
  const [messages, setMessages] = useState<Msg[]>(() => (conversationId && handover.get(conversationId)) || []);
  const [historyState, setHistoryState] = useState<"idle" | "loading" | "missing">(
    conversationId && !handover.has(conversationId) ? "loading" : "idle",
  );
  const [input, setInput] = useState("");
  const today = useToday();
  const [asOfChoice, setAsOf] = useState<string | null>(null);
  const asOf = asOfChoice ?? today;
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<{ msg: number; source: string | null } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [sheetOpen, setSheetOpen] = useState(false); // sources drawer on phones/tablets

  const lastAssistant = [...messages.keys()].reverse().find((k) => messages[k].role === "assistant");
  const panelMsg = selected?.msg ?? lastAssistant;
  const panelEntry = panelMsg !== undefined ? messages[panelMsg] : undefined;
  const panel = panelEntry?.role === "assistant" ? panelEntry.response : undefined;

  useEffect(() => {
    // scrollIntoView() returns a Promise in recent browsers - an effect must not return it
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, loading]);

  // Open a saved conversation (the server re-checks access to every cited source).
  useEffect(() => {
    if (!conversationId || handover.delete(conversationId)) return;
    let stale = false;
    api<{ messages: Msg[] }>(`/conversations/${conversationId}`)
      .then((d) => { if (!stale) { setMessages(d.messages); setHistoryState("idle"); } })
      .catch(() => { if (!stale) setHistoryState("missing"); });
    return () => { stale = true; };
  }, [conversationId]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || loading) return;
    const history = messages.slice(-6).map((m) => ({ role: m.role, content: m.content }));
    const next: Msg[] = [...messages, { role: "user", content: question }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const r = await api<ChatResponse>("/chat", {
        body: { question, history, as_of: asOf || undefined, conversation_id: conversationId },
      });
      const all: Msg[] = [...next, { role: "assistant", content: r.answer, response: r }];
      setMessages(all);
      setSelected(null);
      window.dispatchEvent(new Event(CONVERSATIONS_CHANGED));
      if (r.conversation_id && r.conversation_id !== conversationId) {
        handover.set(r.conversation_id, all);
        router.replace(`/c/${r.conversation_id}`);
      }
    } catch (e) {
      const err = e instanceof Error ? e.message : "เกิดข้อผิดพลาด";
      setMessages((m) => [...m, {
        role: "assistant", content: err,
        response: {
          status: "unverified", answer: `เกิดข้อผิดพลาด: ${err}`, sources: [], notices: [], follow_up_questions: [],
          standalone_question: question, as_of: asOf, audit_id: null, pii_masked: {}, guard_flags: [], grounding: {}, trace: {},
        },
      }]);
    } finally {
      setLoading(false);
    }
  }

  function cite(msgIndex: number, id: string | null) {
    setSelected({ msg: msgIndex, source: id });
    const wide = window.matchMedia("(min-width: 1280px)").matches;
    if (!wide) setSheetOpen(true);
    if (id) {
      const key = `${wide ? "panel" : "sheet"}-${msgIndex}-${id}`;
      setTimeout(() => cardRefs.current[key]?.scrollIntoView({ behavior: "smooth", block: "center" }), wide ? 50 : 300);
    }
  }

  function renderSources(prefix: "panel" | "sheet") {
    if (!panel) {
      return (
        <div className="px-4 pt-16 text-center">
          <div className="mx-auto mb-4 flex size-10 items-center justify-center rounded-xl border bg-card">
            <BookMarked className="size-4 text-muted-foreground" />
          </div>
          <p className="text-sm text-muted-foreground">
            ข้อความต้นฉบับที่ใช้ตอบจะแสดงที่นี่
            <br />
            พร้อมไฮไลต์ประโยคที่ถูกอ้างอิง
          </p>
        </div>
      );
    }
    if (panel.sources.length === 0) {
      return <p className="px-2 pt-6 text-center text-sm text-muted-foreground">ไม่มีเอกสารอ้างอิงสำหรับคำตอบนี้</p>;
    }
    return [...panel.sources]
      .sort((a, b) => Number(b.cited) - Number(a.cited))
      .map((s) => (
        <SourceCard
          key={s.id}
          ref={(el) => { cardRefs.current[`${prefix}-${panelMsg}-${s.id}`] = el; }}
          source={s}
          active={selected?.msg === panelMsg && selected?.source === s.id}
          onSelect={() => setSelected({ msg: panelMsg!, source: s.id })}
        />
      ));
  }

  const sourcesHeader = (
    <>
      <BookMarked className="size-4 text-brand" /> แหล่งอ้างอิง
      {panel && (
        <span className="text-xs font-normal text-muted-foreground">
          · ใช้ตอบ {panel.sources.filter((s) => s.cited).length} จาก {panel.sources.length}
        </span>
      )}
    </>
  );

  const verifiedOf = (r: ChatResponse) => new Set(r.sources.filter((s) => s.cited).map((s) => s.id));
  const empty = messages.length === 0 && historyState === "idle";

  return (
    <div className="flex h-full">
      <div className="relative flex min-w-0 flex-1 flex-col">
        {empty && <div className="aurora pointer-events-none absolute inset-x-0 top-0 h-[520px]" />}

        <div className="relative flex items-center justify-between px-4 py-3 md:px-8 md:py-4">
          <div className="text-sm text-muted-foreground">
            {user ? `สวัสดี ${user.display_name.split(" ")[0]}` : " "}
          </div>
          {!empty && (
            <button
              onClick={() => router.push("/")}
              className="flex items-center gap-1.5 rounded-[10px] border bg-card px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
            >
              <RotateCcw className="size-3.5" /> แชทใหม่
            </button>
          )}
        </div>

        {historyState !== "idle" ? (
          <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-muted-foreground">
            {historyState === "loading" ? (
              <span className="flex items-center gap-2"><Loader2 className="size-4 animate-spin text-brand" /> กำลังเปิดบทสนทนา…</span>
            ) : (
              <span>ไม่พบบทสนทนานี้ อาจถูกลบหรือหมดอายุการเก็บรักษาแล้ว</span>
            )}
          </div>
        ) : empty ? (
          <div className="relative flex flex-1 flex-col items-center overflow-y-auto px-4 pb-10 pt-[4vh] sm:px-6 sm:pt-[8vh]">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border bg-card/70 px-3 py-1 text-[11px] text-muted-foreground backdrop-blur sm:mb-6 sm:text-xs">
              <span className="size-1.5 rounded-full bg-brand shadow-[0_0_8px_#0099ff]" />
              ทุกคำตอบอ้างอิงถึงระดับมาตรา และตรวจกับต้นฉบับแล้ว
            </div>
            <h1 className="max-w-3xl text-center text-[28px] font-semibold leading-tight tracking-tight sm:text-5xl">
              ถามเรื่องกฎระเบียบ
              <br />
              <span className="text-muted-foreground">ได้คำตอบพร้อมหลักฐาน</span>
            </h1>
            <div className="mt-7 w-full max-w-2xl sm:mt-10">
              <Composer value={input} onChange={setInput} onSubmit={() => send(input)} loading={loading} asOf={asOf} setAsOf={setAsOf} autoFocus big />
            </div>
            <div className="mt-6 grid w-full max-w-2xl gap-2.5 sm:mt-8 sm:grid-cols-2 sm:gap-3">
              {EXAMPLES.map((e) => (
                <button
                  key={e.q}
                  onClick={() => send(e.q)}
                  className="group panel flex flex-col gap-1.5 p-3.5 text-left transition hover:border-brand/40 hover:bg-white/[0.03] sm:gap-2 sm:p-4"
                >
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    <e.icon className="size-3.5 text-brand" /> {e.tag}
                  </span>
                  <span className="text-sm leading-relaxed text-foreground/85 group-hover:text-foreground">{e.q}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto max-w-3xl space-y-6 px-3 py-4 sm:space-y-8 sm:px-6 sm:py-6">
                {messages.map((m, i) =>
                  m.role === "user" ? (
                    <div key={i} className="flex justify-end">
                      <div className="max-w-[88%] rounded-[18px] rounded-br-md bg-secondary px-4 py-2.5 text-[15px]">
                        {m.content}
                      </div>
                    </div>
                  ) : (
                    <div key={i} className="flex gap-3">
                      <div className="hidden size-8 shrink-0 items-center justify-center rounded-[9px] bg-foreground text-background sm:flex">
                        <Scale className="size-4" />
                      </div>
                      <div
                        className={cn("panel min-w-0 flex-1 p-4 transition sm:p-5", panelMsg === i && "border-brand/30")}
                        onClick={() => setSelected((s) => (s?.msg === i ? s : { msg: i, source: null }))}
                      >
                        <Answer
                          r={m.response}
                          verified={verifiedOf(m.response)}
                          activeSource={selected?.msg === i ? selected.source : null}
                          onCite={(id) => cite(i, id)}
                          onFollowUp={send}
                        />
                        {m.response.sources.length > 0 && (
                          <button
                            onClick={(e) => { e.stopPropagation(); cite(i, null); }}
                            className="mt-3 flex w-full items-center justify-center gap-2 rounded-[10px] border bg-secondary/50 py-2 text-xs text-muted-foreground transition hover:text-foreground xl:hidden"
                          >
                            <BookMarked className="size-3.5 text-brand" />
                            ดูแหล่งอ้างอิง ({m.response.sources.filter((s) => s.cited).length} รายการที่ใช้ตอบ)
                          </button>
                        )}
                      </div>
                    </div>
                  ),
                )}
                {loading && (
                  <div className="flex gap-3">
                    <div className="hidden size-8 shrink-0 items-center justify-center rounded-[9px] bg-foreground text-background sm:flex">
                      <Scale className="size-4" />
                    </div>
                    <div className="panel flex-1 p-4 sm:p-5"><Thinking /></div>
                  </div>
                )}
                <div ref={bottom} />
              </div>
            </div>
            <div className="px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 sm:px-6 sm:pb-5">
              <div className="mx-auto max-w-3xl">
                <Composer value={input} onChange={setInput} onSubmit={() => send(input)} loading={loading} asOf={asOf} setAsOf={setAsOf} />
                <p className="mt-2 hidden text-center text-[11px] text-muted-foreground sm:block">
                  ข้อมูลส่วนบุคคลในคำถามจะถูกปิดบังก่อนประมวลผล · คำตอบเป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่ความเห็นทางกฎหมาย
                </p>
              </div>
            </div>
          </>
        )}
      </div>

      <aside className="hidden w-[420px] shrink-0 flex-col border-l bg-sidebar xl:flex">
        <div className="flex items-center gap-2 border-b px-5 py-4 text-sm font-medium">{sourcesHeader}</div>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">{renderSources("panel")}</div>
      </aside>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="bottom" className="max-h-[85dvh] gap-0 rounded-t-2xl p-0">
          <SheetTitle className="flex items-center gap-2 border-b px-4 py-3.5 pr-12 text-sm font-medium">
            {sourcesHeader}
          </SheetTitle>
          <div className="space-y-3 overflow-y-auto p-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
            {renderSources("sheet")}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
