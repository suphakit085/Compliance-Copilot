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

export const ROLE_LABEL: Record<Role, string> = {
  employee: "พนักงาน",
  compliance_officer: "เจ้าหน้าที่ Compliance",
  auditor: "ผู้ตรวจสอบภายใน",
  admin: "ผู้ดูแลระบบ",
};

export const CLEARANCE_LABEL = ["สาธารณะ", "ภายใน", "ลับ", "ลับมาก"];
