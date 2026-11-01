"use client";

/** Typed browser-side client. Every call goes through the same-origin BFF (/api/backend/*). */

export type Role = "employee" | "compliance_officer" | "auditor" | "admin";

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  department: string;
  clearance: number;
  terms_required: boolean;
  terms_accepted: boolean;
}

export interface TermsInfo {
  version: string;
  text: string;
  required: boolean;
  accepted: boolean;
}

export type ReportCategory = "wrong_answer" | "missing_source" | "outdated" | "should_refuse" | "leak" | "other";

export const REPORT_CATEGORIES: { value: ReportCategory; label: string; hint: string }[] = [
  { value: "wrong_answer", label: "คำตอบไม่ถูกต้อง", hint: "ตัวเลข เงื่อนไข หรือข้อสรุปไม่ตรงกับต้นฉบับ" },
  { value: "missing_source", label: "อ้างอิงไม่ตรงหรือขาดหายไป", hint: "ป้ายอ้างอิงชี้ไปข้อความที่ไม่เกี่ยวข้อง หรือไม่มีแหล่งที่ควรมี" },
  { value: "outdated", label: "ใช้ฉบับที่ล้าสมัย", hint: "มีฉบับแก้ไขหรือฉบับใหม่ที่ระบบไม่ได้ใช้" },
  { value: "should_refuse", label: "ควรตอบได้ แต่ระบบปฏิเสธ", hint: "ข้อมูลมีในเอกสารแต่ระบบบอกว่าไม่พบ" },
  { value: "leak", label: "เห็นข้อมูลที่ไม่ควรเห็น", hint: "เอกสารลับหรือข้อมูลที่เกินสิทธิ์ของฉัน (เหตุการณ์ด่วน)" },
  { value: "other", label: "อื่น ๆ", hint: "ปัญหาอื่นที่ไม่เข้าข้อข้างต้น" },
];

export interface MyReport {
  id: number;
  ts: string;
  category: ReportCategory;
  report_status: "open" | "resolved" | "dismissed";
  resolution: string | null;
  question: string;
}

export interface ProblemReport extends MyReport {
  audit_id: number;
  user: string;
  role: string;
  status: string;
  support_rate: number | null;
  comment: string | null;
  resolved_by: string | null;
  retrieved: string[];
}

export interface Source {
  id: string;
  chunk_id: string;
  document_id: string;
  doc_title: string;
  short_title: string;
  label: string;
  path: string[];
  text: string;
  page_start: number | null;
  page_end: number | null;
  version: string | null;
  effective_from: string | null;
  effective_to: string | null;
  classification: string;
  source_kind: "regulation" | "internal";
  official_url: string | null;
  source_url: string | null;
  synthetic: boolean;
  extraction: string;
  notes: string[];
  rerank_score: number | null;
  cited: boolean;
  quotes: string[];
}

export type Status =
  | "answered" | "partial" | "insufficient_evidence" | "out_of_scope" | "blocked"
  | "retrieval_only" | "unverified";

export interface ChatResponse {
  status: Status;
  answer: string;
  sources: Source[];
  notices: string[];
  follow_up_questions: string[];
  standalone_question: string;
  as_of: string;
  audit_id: number | null;
  conversation_id?: string | null;
  pii_masked: Record<string, number>;
  guard_flags: string[];
  grounding: {
    citations?: number; verified?: number; markers?: number; markers_supported?: number;
    support_rate?: number; unsupported_markers?: string[];
  };
  trace: Record<string, unknown>;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  messages: number;
}

export interface DocumentInfo {
  id: string;
  title: string;
  short_title: string;
  doc_type: string;
  source_kind: "regulation" | "internal";
  issuer: string | null;
  classification: string;
  version: string | null;
  effective_from: string | null;
  effective_to: string | null;
  in_force: boolean;
  supersedes: string | null;
  superseded_by: string | null;
  amended_by: { ref: string; effective_from: string; note?: string }[];
  official_ref: string | null;
  official_url: string | null;
  source_url: string | null;
  source_name: string | null;
  sha256: string | null;
  synthetic: boolean;
  pages: number | null;
  chunks: number;
  quality: { dictionary_coverage?: number; ocr_pages?: number[]; footnotes?: number };
  governance: {
    owner?: string;
    approved_by?: string;
    approved_on?: string;
    review_due?: string;
    status?: string;
    review_state?: "ok" | "due_soon" | "overdue";
    review_days_left?: number;
  };
  source_checked_at: string | null;
}

export interface Section {
  id: string;
  label: string;
  path: string[];
  title: string | null;
  text: string;
  pages: [number, number];
  notes: string[];
  extraction: string;
}

export interface GapFinding {
  clause_label: string;
  clause_text: string;
  status: string;
  severity: string;
  finding: string;
  recommendation: string;
  citations: { source_id: string; citation: string; chunk_id: string; quote: string; verified: boolean; official_url: string | null }[];
  top_score: number;
}

export interface GapReport {
  policy_id: string;
  policy_title: string;
  as_of: string;
  findings: GapFinding[];
  summary: Record<string, number>;
  model: string | null;
  prompt_version: string;
  elapsed_s: number;
  audit_id: number | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`/api/backend${path}`, {
    method: init?.method ?? (init?.body ? "POST" : "GET"),
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    body: init?.body ? JSON.stringify(init.body) : undefined,
  });
  if (res.status === 401) {
    window.location.assign(new URL("/login", window.location.origin));
    throw new ApiError(401, "session expired");
  }
  const ctype = res.headers.get("content-type") ?? "";
  const data = ctype.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = typeof data === "object" && data && "detail" in data ? String(data.detail) : String(data);
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export type ChatStage = "guard" | "condense" | "retrieve" | "generate" | "verify";

/** Events of POST /chat/stream. Only `final` is verified; `delta` text is a draft preview. */
export type ChatEvent =
  | { type: "stage"; stage: ChatStage }
  | { type: "sources"; sources: ChatResponse["sources"]; notices: string[] }
  | { type: "delta"; text: string }
  | { type: "reset" } // the server restarted the generation: discard the draft so far
  | { type: "final"; response: ChatResponse }
  | { type: "error"; message: string };

export async function streamChat(
  body: unknown,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/backend/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (res.status === 401) {
    window.location.assign(new URL("/login", window.location.origin));
    throw new ApiError(401, "session expired");
  }
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null);
    const detail = data && typeof data.detail === "string" ? data.detail : "เกิดข้อผิดพลาด กรุณาลองใหม่";
    throw new ApiError(res.status, detail);
  }
  // newline-delimited JSON: one event per line, possibly split across network chunks
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += value;
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
  if (buf.trim()) onEvent(JSON.parse(buf));
}

export const ROLE_LABEL: Record<Role, string> = {
  employee: "พนักงาน",
  compliance_officer: "เจ้าหน้าที่ Compliance",
  auditor: "ผู้ตรวจสอบภายใน",
  admin: "ผู้ดูแลระบบ",
};

export const CLEARANCE_LABEL = ["สาธารณะ", "ภายใน", "ลับ", "ลับมาก"];
