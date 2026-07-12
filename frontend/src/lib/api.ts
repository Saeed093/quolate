// Typed API client. The ONLY way the frontend talks to the backend.
// Base URL comes from env so cloud migration only changes NEXT_PUBLIC_API_URL.

import { logClientError } from "@/lib/error-log";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "quolate_token";

let inMemoryToken: string | null = null;

export function setToken(token: string | null) {
  inMemoryToken = token;
  if (typeof window !== "undefined") {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  }
}

export function getToken(): string | null {
  if (inMemoryToken) return inMemoryToken;
  if (typeof window !== "undefined") {
    inMemoryToken = localStorage.getItem(TOKEN_KEY);
  }
  return inMemoryToken;
}

export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** FastAPI validation errors return `detail` as a list of objects — flatten to text. */
function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (d && typeof d === "object" && "msg" in d) {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc)
            ? (d as { loc: unknown[] }).loc.slice(1).join(".")
            : "";
          const msg = String((d as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(d);
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return "Request failed";
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(options.body instanceof FormData) && options.body) {
    headers.set("Content-Type", "application/json");
  }

  const action = `${options.method ?? "GET"} ${path}`;
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  } catch (err) {
    logClientError(action, err);
    throw err;
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ?? detail;
    } catch {
      /* ignore */
    }
    const apiError = new ApiError(res.status, formatErrorDetail(detail));
    logClientError(action, apiError, res.status);
    throw apiError;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- Types ----
export interface AuthToken {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
}

export interface QuotationTerms {
  validity_days?: number | null;
  payment_terms?: string | null;
  delivery?: string | null;
  warranty?: string | null;
  notes?: string | null;
}

export interface Project {
  id: string;
  name: string;
  status: string;
  base_currency: string;
  landed_cost_defaults: Record<string, unknown>;
  // Sell-side quotation defaults (fractions; e.g. margin_pct "0.15" == 15%).
  margin_pct?: string;
  gst_enabled?: boolean;
  gst_pct?: string;
  terms?: QuotationTerms;
}

export type QuotationSourceKind = "text" | "document" | "library" | "tender";

export interface QuotationSourceRef {
  kind: QuotationSourceKind;
  id?: string;
  text?: string;
}

export interface QuotationLine {
  id: string;
  version_id: string;
  line_no: number;
  description: string;
  spec: string | null;
  qty: string | null;
  unit_cost: string | null;
  cost_source: string | null;
  unit_price: string | null;
  line_total: string | null;
  gap_flag: boolean;
}

export interface QuotationVersion {
  id: string;
  quotation_id: string;
  version_no: number;
  status: "draft" | "final";
  currency: string;
  margin_pct: string;
  gst_enabled: boolean;
  gst_pct: string;
  validity_days: number | null;
  terms_snapshot: QuotationTerms;
  subtotal: string | null;
  tax_total: string | null;
  grand_total: string | null;
  docx_key: string | null;
  xlsx_key: string | null;
  created_at: string;
  lines: QuotationLine[];
}

export interface Quotation {
  id: string;
  project_id: string;
  quote_no: string;
  seq: number;
  title: string | null;
  status: "draft" | "final";
  created_at: string;
  versions: QuotationVersion[];
}

export interface QuotationLineInput {
  id?: string;
  line_no?: number;
  description?: string;
  spec?: string | null;
  qty?: string | number | null;
  unit_cost?: string | number | null;
  unit_price?: string | number | null;
  cost_source?: string | null;
  remove?: boolean;
}

export interface QuotationVersionUpdate {
  margin_pct?: string | number;
  gst_enabled?: boolean;
  gst_pct?: string | number;
  validity_days?: number | null;
  terms?: QuotationTerms;
  lines?: QuotationLineInput[];
}

export interface BomItem {
  id: string;
  project_id: string;
  line_no: number;
  part_name: string;
  spec_requirement: string | null;
  quantity: string | null;
  target_price: string | null;
  notes: string | null;
  hs_code: string | null;
}

export interface Supplier {
  id: string;
  project_id: string;
  name: string;
  country: string | null;
  contact: string | null;
  default_currency: string | null;
}

export interface Document {
  id: string;
  project_id: string;
  supplier_id: string | null;
  kind: string;
  original_filename: string;
  mime_type: string | null;
  status: string;
  page_count: number | null;
  ocr_used: boolean;
  error: string | null;
  created_at: string;
  auto_bom_created?: number;
}

export interface ExtractedField {
  id: string;
  document_id: string;
  bom_item_id: string | null;
  supplier_id: string | null;
  field_type: string;
  value_text: string | null;
  value_num: string | null;
  unit: string | null;
  confidence: string | null;
  status: string;
  provenance: {
    page?: number | null;
    bbox?: [number, number, number, number] | null;
    source_snippet?: string | null;
  };
}

export interface DocumentReview {
  document: Document;
  fields: ExtractedField[];
  page_urls: string[];
}

export type CellState = "ok" | "verify" | "gap";

export interface DutyBreakdown {
  fx_rate: number;
  assessed_value_pkr: number;
  total_duty_tax_pkr: number;
  levies: {
    levy_type: string;
    label: string;
    rate: number;
    amount_pkr: number;
  }[];
}

export interface MatrixCell {
  supplier_id: string;
  quote_id: string | null;
  document_id: string | null;
  fob: number | null;
  landed: number | null;
  hs_code: string | null;
  duty: number | null;
  duty_source: "statutory" | "flat" | null;
  duty_breakdown: DutyBreakdown | null;
  currency: string;
  moq: number | null;
  lead_time_days: number | null;
  incoterms: string | null;
  valid_until: string | null;
  payment_terms: string | null;
  warranty: string | null;
  validity_days: string | null;
  extra_fields: Record<string, string | null>;
  confidence_state: CellState;
  best_value: boolean;
  field_ids: string[];
}

export interface MatrixRow {
  bom_item_id: string;
  line_no: number;
  part_name: string;
  spec_requirement: string | null;
  quantity: number | null;
  target_price: number | null;
  hs_code: string | null;
  best_supplier_id: string | null;
  spread_pct: number | null;
  cells: Record<string, MatrixCell>;
}

export interface Matrix {
  project_id: string;
  currency: string;
  assumptions: {
    duty_pct: number;
    freight_per_unit: number;
    lc_pct: number;
    fx_overrides: Record<string, number>;
    fx_rate_pkr_usd: number | null;
    fx_rate_source: "override" | "live" | "static" | null;
    duty_as_of: string | null;
  };
  suppliers: { id: string; name: string; country: string | null }[];
  rows: MatrixRow[];
  summary: {
    lines_total: number;
    suppliers_total: number;
    docs_parsed: number;
    fields_needing_review: number;
    lowest_landed: number | null;
    overall_spread_pct: number | null;
  };
  matrix_hash: string;
}

export interface MatrixParams {
  currency?: string;
  duty_pct?: number;
  freight_per_unit?: number;
  lc_pct?: number;
  fx_rate?: number;
}

export interface ChatMessage {
  id: string;
  project_id: string | null;
  role: string;
  content: string;
  tool_calls: Record<string, unknown> | null;
  created_at: string;
}

export interface LibraryDocument {
  id: string;
  filename: string;
  kind: string;
  status: string;
  page_count: number | null;
  error: string | null;
  comment_count?: number;
  created_at: string | null;
  size_bytes?: number;
  projects?: { id: string; name: string }[];
}

export interface LibraryQuota {
  used_bytes: number;
  limit_bytes: number;
  document_count: number;
  remaining_bytes: number;
}

export interface LibraryListParams {
  sort?: "newest" | "oldest" | "name";
  project_id?: string;
}

export interface DocumentComment {
  id: string;
  content: string;
  created_at: string | null;
}

export interface LibraryUploadResult {
  created: { id: string; filename: string; kind: string }[];
  skipped: { filename: string; id: string; reason: string }[];
  errors: { filename?: string; error: string }[];
}

export interface ProjectLibraryDocument {
  id: string; // link id
  library_document_id: string;
  filename: string;
  kind: string;
  status: string;
  linked_at: string | null;
}

export interface Tender {
  id: string;
  source_id: string;
  tender_no: string | null;
  title: string | null;
  organization: string | null;
  org_type: string | null;
  category: string | null;
  sector_tags: string[] | null;
  city: string | null;
  closing_date: string | null;
  advertise_date: string | null;
  estimated_value: string | null;
  corrigendum_of: string | null;
  created_at: string;
}

export interface TenderMatch {
  document_id: string;
  project_id: string;
  supplier: string | null;
  item: string;
  unit_price: number | null;
  currency: string | null;
  date: string | null;
  similarity: number;
}

export interface TenderSource {
  id: string;
  name: string;
  base_url: string;
  adapter: string;
  enabled: boolean;
  last_run: string | null;
  last_status: string | null;
}

export type DutyLevyType = "CD" | "ACD" | "RD" | "FED" | "ST" | "WHT_148";
export type AtlStatus = "atl" | "non_atl";

export const IMPORTER_CATEGORIES: { value: string; label: string }[] = [
  { value: "commercial_importer", label: "Commercial importer" },
  {
    value: "industrial_undertaking_own_use",
    label: "Industrial undertaking (own use)",
  },
];

export interface DutyLevyLine {
  levy_type: DutyLevyType;
  label: string;
  rate: string;
  rate_type: string;
  basis_pkr: string;
  amount_pkr: string;
  legal_reference: string | null;
  sro_reference: string | null;
  exemption_applied: boolean;
  notes: string | null;
}

export interface DutyCalculation {
  hs_code: string;
  declared_value_usd: string;
  exchange_rate: string;
  assessed_value_pkr: string;
  importer_category: string | null;
  atl_status: AtlStatus | null;
  as_of_date: string;
  levies: DutyLevyLine[];
  total_duty_tax_pkr: string;
  total_landed_pkr: string;
  disclaimer: string;
}

export interface DutyCalcParams {
  declared_value_usd: number;
  exchange_rate: number;
  importer_category?: string;
  atl_status?: AtlStatus;
  as_of_date?: string;
}

export interface HsCandidate {
  hs_code: string;
  description: string | null;
  confidence: number;
  reasoning: string | null;
}

export interface HsClassificationResult {
  product_summary: string | null;
  candidates: HsCandidate[];
  disclaimer: string;
}

export interface ClassifyHsCodeParams {
  library_document_id?: string;
  text?: string;
}

// ---- Invoice duty calculator (clearing-agent sheet workflow) ----
export type SheetLevyType = "CD" | "ACD" | "RD" | "ST" | "AST" | "FED" | "AIT";
export type InvoiceCurrency = "USD" | "CNY";
export type RateSource = "memory" | "approved_rate" | "default";

export interface ParsedInvoiceItem {
  line_no: number | null;
  description: string;
  quantity: string | null;
  unit: string | null;
  unit_price: string | null;
  line_total: string | null;
}

export interface InvoiceParseResult {
  invoice_currency: string | null;
  freight: string;
  items: ParsedInvoiceItem[];
  disclaimer: string;
}

/** Fractions as strings, e.g. "0.05" == 5%. */
export interface ItemRates {
  cd: string;
  acd: string;
  rd: string;
  st: string;
  ast: string;
  ait: string;
}

export interface InvoiceCalcItemRequest {
  description: string;
  quantity?: string | null;
  unit?: string | null;
  unit_price?: string | null;
  line_total?: string | null;
  hs_code: string;
  rates: ItemRates;
  fed_amount_pkr?: string;
}

export interface InvoiceFees {
  afu_pct: string;
  afu_fixed_pkr: string;
  stamp_fee_pkr: string;
  psw_fee_pkr: string;
}

export interface InvoiceCalcRequest {
  currency: InvoiceCurrency;
  fx_rate: string;
  fx_rate_date?: string | null;
  freight?: string;
  insurance_pct?: string;
  landing_pct?: string;
  items: InvoiceCalcItemRequest[];
  fees?: InvoiceFees;
  save_rates?: boolean;
}

export interface SheetLevyLine {
  levy_type: SheetLevyType;
  label: string;
  rate: string;
  basis_pkr: string;
  amount_pkr: string;
}

export interface InvoiceCalcItemResult {
  description: string;
  hs_code: string;
  quantity: string | null;
  unit_price: string | null;
  line_total: string;
  freight_allocated: string;
  cf_value: string;
  cf_value_pkr: string;
  insurance_pkr: string;
  landing_pkr: string;
  import_value_pkr: string;
  levies: SheetLevyLine[];
  customs_subtotal_pkr: string;
  ait_pkr: string;
  item_duty_total_pkr: string;
}

export interface InvoiceTotals {
  invoice_value: string;
  freight: string;
  cf_value_pkr: string;
  import_value_pkr: string;
  customs_subtotal_pkr: string;
  ait_pkr: string;
  customs_total_pkr: string;
  afu_pkr: string;
  stamp_fee_pkr: string;
  psw_fee_pkr: string;
  total_payable_pkr: string;
  landed_cleared_price_pkr: string;
}

export interface InvoiceCalcResult {
  currency: string;
  fx_rate: string;
  fx_rate_date: string | null;
  items: InvoiceCalcItemResult[];
  totals: InvoiceTotals;
  disclaimer: string;
}

export interface RatePrefill {
  hs_code: string;
  rates: Record<string, string>;
  sources: Record<string, RateSource>;
}

export interface FxRate {
  currency: string;
  quote: string;
  rate: string;
  as_of_date: string;
  source: "live" | "static";
}

export interface SavedFilter {
  id: string;
  name: string;
  criteria: Record<string, unknown>;
}

export interface LlmStatus {
  online: boolean;
  model: string;
  gpu: boolean;
  gpu_name: string | null;
  vram_used: string | null;
  gpu_installed: boolean;
  model_loaded: boolean;
  model_fully_on_gpu: boolean;
  chat_available: boolean;
  reason:
    | "ollama_offline"
    | "no_gpu"
    | "model_not_loaded"
    | "model_on_cpu"
    | "insufficient_vram"
    | null;
}

export interface TenderPullActivity {
  source_id: string;
  source_name: string;
  status: string;
}

export interface ActivitySummary {
  documents_processing: number;
  tender_pulls: TenderPullActivity[];
}

export interface TenderFilter {
  keyword?: string;
  tender_no?: string;
  org_type?: string;
  category?: string;
  sector?: string;
  organization?: string;
  city?: string;
  status?: string;
  closing_from?: string;
  closing_to?: string;
}

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// ---- Chat SSE ----
export interface ChatEvent {
  type: "tool_call" | "tool_result" | "final" | "regenerate";
  action?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  content?: string;
  matrix_changed?: boolean;
  matrix_hash?: string;
  regenerated?: boolean;
  terminated?: boolean;
  tool_calls?: { action: string; args: Record<string, unknown> }[];
}

async function streamChatTo(
  path: string,
  body: { message: string; currency?: string; overrides?: Record<string, number> },
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const token = getToken();
  const controller = new AbortController();
  const timeoutMs = 330 * 1000; // 5.5 min — backend's 5min + buffer for CPU-bound models
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      let detail: unknown = "Chat request failed";
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* ignore */
      }
      const apiError = new ApiError(res.status, formatErrorDetail(detail));
      logClientError(`POST ${path} (chat)`, apiError, res.status);
      throw apiError;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (payload === "[DONE]") return;
        try {
          onEvent(JSON.parse(payload) as ChatEvent);
        } catch {
          /* ignore malformed chunk */
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      const timeoutError = new ApiError(
        0,
        "Request timed out. Please try again or simplify your message.",
      );
      logClientError(`POST ${path} (chat)`, timeoutError);
      throw timeoutError;
    }
    // ApiErrors were already logged where they were thrown.
    if (!(err instanceof ApiError)) logClientError(`POST ${path} (chat)`, err);
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

function streamChat(
  projectId: string,
  body: { message: string; currency?: string; overrides?: Record<string, number> },
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  return streamChatTo(`/projects/${projectId}/chat`, body, onEvent);
}

function streamGlobalChat(
  body: { message: string },
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  return streamChatTo(`/chat`, body, onEvent);
}

// ---- Pull SSE ----
export interface PullEvent {
  phase: "listing" | "fetching" | "notice" | "done";
  source_name?: string;
  index?: number;
  total?: number;
  title?: string;
  step?: "fetching" | "classifying" | "done" | "error";
  action?: string;
  error?: string;
  status?: string;
  created?: number;
  updated?: number;
  skipped?: number;
}

async function streamPullSource(
  sourceId: string,
  onEvent: (event: PullEvent) => void,
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BASE_URL}/tender-sources/${sourceId}/pull`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok || !res.body) {
    throw new ApiError(res.status, "Pull request failed");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") return;
      try {
        onEvent(JSON.parse(payload) as PullEvent);
      } catch {
        /* ignore malformed chunk */
      }
    }
  }
}

// ---- Endpoints ----
export const api = {
  health: () => request<{ status: string }>("/health"),
  llmStatus: () => request<LlmStatus>("/status/llm"),
  startGpu: () => request<LlmStatus>("/gpu/start", { method: "POST" }),

  register: (email: string, password: string, displayName?: string) =>
    request<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: displayName }),
    }),

  login: async (email: string, password: string) => {
    const token = await request<AuthToken>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setToken(token.access_token);
    return token;
  },

  me: () => request<User>("/auth/me"),
  logout: () => setToken(null),

  // Projects
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (name: string) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  updateProject: (id: string, patch: Partial<Project>) =>
    request<Project>(`/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: "DELETE" }),

  // BOM
  listBom: (pid: string) => request<BomItem[]>(`/projects/${pid}/bom`),
  createBom: (pid: string, item: Partial<BomItem>) =>
    request<BomItem>(`/projects/${pid}/bom`, {
      method: "POST",
      body: JSON.stringify(item),
    }),
  pasteBom: (pid: string, text: string, hasHeader?: boolean) =>
    request<BomItem[]>(`/projects/${pid}/bom/paste`, {
      method: "POST",
      body: JSON.stringify({ text, has_header: hasHeader ?? null }),
    }),
  classifyBomHs: (pid: string, itemId: string) =>
    request<HsClassificationResult>(
      `/projects/${pid}/bom/${itemId}/classify-hs`,
      { method: "POST" },
    ),
  updateBom: (itemId: string, patch: Partial<BomItem>) =>
    request<BomItem>(`/bom/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteBom: (itemId: string) =>
    request<void>(`/bom/${itemId}`, { method: "DELETE" }),

  // Quotations (sell-side)
  extractRequirements: (pid: string, sources: QuotationSourceRef[]) =>
    request<BomItem[]>(`/projects/${pid}/quotations/extract-requirements`, {
      method: "POST",
      body: JSON.stringify({ sources }),
    }),
  createQuotation: (pid: string, title?: string) =>
    request<Quotation>(`/projects/${pid}/quotations`, {
      method: "POST",
      body: JSON.stringify({ title: title ?? null, sources: [] }),
    }),
  listQuotations: (pid: string) =>
    request<Quotation[]>(`/projects/${pid}/quotations`),
  getQuotation: (pid: string, qid: string) =>
    request<Quotation>(`/projects/${pid}/quotations/${qid}`),
  updateQuotationVersion: (
    pid: string,
    versionId: string,
    patch: QuotationVersionUpdate,
  ) =>
    request<QuotationVersion>(
      `/projects/${pid}/quotations/versions/${versionId}`,
      { method: "PATCH", body: JSON.stringify(patch) },
    ),
  regenerateQuotationVersion: (pid: string, versionId: string) =>
    request<QuotationVersion>(
      `/projects/${pid}/quotations/versions/${versionId}/regenerate`,
      { method: "POST" },
    ),
  finalizeQuotationVersion: (pid: string, versionId: string) =>
    request<QuotationVersion>(
      `/projects/${pid}/quotations/versions/${versionId}/finalize`,
      { method: "POST" },
    ),
  // Auth'd blob download (a plain <a href> can't carry the Bearer token).
  downloadQuotationFile: async (
    pid: string,
    versionId: string,
    fmt: "docx" | "xlsx",
    filename: string,
  ) => {
    const token = getToken();
    const res = await fetch(
      apiUrl(`/projects/${pid}/quotations/versions/${versionId}/download?fmt=${fmt}`),
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
    if (!res.ok) throw new ApiError(res.status, "Could not generate file");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  },

  // Suppliers
  listSuppliers: (pid: string) =>
    request<Supplier[]>(`/projects/${pid}/suppliers`),
  createSupplier: (pid: string, s: Partial<Supplier>) =>
    request<Supplier>(`/projects/${pid}/suppliers`, {
      method: "POST",
      body: JSON.stringify(s),
    }),
  deleteSupplier: (id: string) =>
    request<void>(`/suppliers/${id}`, { method: "DELETE" }),

  // Documents
  listDocuments: (pid: string) =>
    request<Document[]>(`/projects/${pid}/documents`),
  uploadDocuments: (pid: string, files: File[], kind?: string) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    if (kind) fd.append("kind", kind);
    return request<Document[]>(`/projects/${pid}/documents`, {
      method: "POST",
      body: fd,
    });
  },
  reviewDocument: (docId: string) =>
    request<DocumentReview>(`/documents/${docId}/review`),
  reparseDocument: (docId: string) =>
    request<Document>(`/documents/${docId}/reparse`, { method: "POST" }),
  reparseAllDocuments: (pid: string) =>
    request<Document[]>(`/projects/${pid}/documents/reparse-all`, {
      method: "POST",
    }),
  markReviewed: (docId: string) =>
    request<Document>(`/documents/${docId}/mark-reviewed`, { method: "POST" }),
  pageImageUrl: (docId: string, page: number) =>
    apiUrl(`/documents/${docId}/pages/${page}.png`),
  updateField: (fieldId: string, patch: Partial<ExtractedField>) =>
    request<ExtractedField>(`/fields/${fieldId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  // Matrix
  getMatrix: (pid: string, params: MatrixParams = {}) =>
    request<Matrix>(
      `/projects/${pid}/matrix${qs(params as Record<string, unknown>)}`,
    ),
  matrixExportUrl: (pid: string, params: MatrixParams = {}) =>
    apiUrl(
      `/projects/${pid}/matrix/export${qs(params as Record<string, unknown>)}`,
    ),

  // Chat
  chatHistory: (pid: string) =>
    request<ChatMessage[]>(`/projects/${pid}/chat`),
  streamChat,
  globalChatHistory: () => request<ChatMessage[]>(`/chat`),
  streamGlobalChat,

  // Library ("My Documents")
  libraryQuota: () => request<LibraryQuota>(`/library/quota`),
  listLibraryDocuments: (params?: LibraryListParams) =>
    request<LibraryDocument[]>(
      `/library/documents${qs(params as Record<string, unknown>)}`,
    ),
  // XHR-based so upload progress can be reported (fetch can't).
  uploadLibraryDocuments: (
    files: File[],
    onProgress?: (percent: number) => void,
  ): Promise<LibraryUploadResult> => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const token = getToken();
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE_URL}/library/documents`);
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText) as LibraryUploadResult);
          } catch {
            reject(new ApiError(xhr.status, "Malformed upload response"));
          }
        } else {
          reject(new ApiError(xhr.status, "Upload failed"));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "Upload failed"));
      xhr.send(fd);
    });
  },
  deleteLibraryDocument: (id: string) =>
    request<{ deleted: string }>(`/library/documents/${id}`, {
      method: "DELETE",
    }),
  bulkDeleteLibraryDocuments: (ids: string[]) =>
    request<{ deleted: string[]; not_found: string[]; count: number }>(
      `/library/documents/bulk-delete`,
      { method: "POST", body: JSON.stringify({ ids }) },
    ),
  libraryDocumentUrl: (id: string, inline = false) =>
    apiUrl(`/library/documents/${id}/original${inline ? "?inline=1" : ""}`),
  // Fetch the file with auth and open/save it via a blob URL (plain <a href>
  // can't carry the Bearer token).
  openLibraryDocument: async (id: string, filename: string, inline: boolean) => {
    const token = getToken();
    const res = await fetch(
      apiUrl(`/library/documents/${id}/original${inline ? "?inline=1" : ""}`),
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
    if (!res.ok) throw new ApiError(res.status, "Could not load file");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    if (inline) {
      window.open(url, "_blank");
    } else {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  },

  // Document comments
  listDocumentComments: (docId: string) =>
    request<DocumentComment[]>(`/library/documents/${docId}/comments`),
  addDocumentComment: (docId: string, content: string) =>
    request<DocumentComment>(`/library/documents/${docId}/comments`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  deleteDocumentComment: (docId: string, commentId: string) =>
    request<{ deleted: string }>(
      `/library/documents/${docId}/comments/${commentId}`,
      { method: "DELETE" },
    ),

  // Tender cleanup
  cleanupTenders: (keep?: number) =>
    request<{ removed: number; kept: number }>(`/tenders/cleanup`, {
      method: "POST",
      body: JSON.stringify(keep !== undefined ? { keep } : {}),
    }),

  // Project <-> library links
  listProjectLibraryDocuments: (pid: string) =>
    request<ProjectLibraryDocument[]>(`/projects/${pid}/library-documents`),
  linkLibraryDocument: (pid: string, libraryDocumentId: string) =>
    request<{ linked: boolean }>(`/projects/${pid}/library-documents`, {
      method: "POST",
      body: JSON.stringify({ library_document_id: libraryDocumentId }),
    }),
  unlinkLibraryDocument: (pid: string, linkId: string) =>
    request<{ deleted: boolean }>(
      `/projects/${pid}/library-documents/${linkId}`,
      { method: "DELETE" },
    ),

  // Tenders
  listTenders: (filter: TenderFilter = {}) =>
    request<Tender[]>(`/tenders${qs(filter as Record<string, unknown>)}`),
  getTender: (id: string) => request<Tender>(`/tenders/${id}`),
  tenderMatches: (id: string) =>
    request<{ tender_id: string; count: number; matches: TenderMatch[] }>(
      `/tenders/${id}/matches`,
    ),
  notificationBadge: () =>
    request<{ count: number }>("/tenders/notifications/badge"),

  // Background activity
  getActivity: () => request<ActivitySummary>("/activity"),

  // Tender sources
  listSources: () => request<TenderSource[]>("/tender-sources"),
  createSource: (name: string, baseUrl: string, adapter = "generic") =>
    request<TenderSource>("/tender-sources", {
      method: "POST",
      body: JSON.stringify({ name, base_url: baseUrl, adapter }),
    }),
  updateSource: (id: string, patch: Partial<TenderSource>) =>
    request<TenderSource>(`/tender-sources/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteSource: (id: string) =>
    request<void>(`/tender-sources/${id}`, { method: "DELETE" }),
  pullSource: (id: string) =>
    request<{ status: string; created: number; updated: number; total: number }>(
      `/tender-sources/${id}/pull`,
      { method: "POST" },
    ),
  pullSourceAsync: (id: string) =>
    request<{ job_id: string; status: string }>(
      `/tender-sources/${id}/pull-async`,
      { method: "POST" },
    ),
  streamPullSource,

  // Pakistan duty/tax calculator
  dutyHsCodes: (search?: string) =>
    request<string[]>(`/duty-calc/hs-codes${qs({ q: search })}`),
  dutyCalc: (hsCode: string, params: DutyCalcParams) =>
    request<DutyCalculation>(
      `/duty-calc/${encodeURIComponent(hsCode)}${qs(params as unknown as Record<string, unknown>)}`,
    ),
  classifyHsCode: (params: ClassifyHsCodeParams) =>
    request<HsClassificationResult>(`/duty-calc/classify`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  parseInvoice: (params: ClassifyHsCodeParams) =>
    request<InvoiceParseResult>(`/duty-calc/invoice/parse`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  invoiceDutyCalc: (body: InvoiceCalcRequest) =>
    request<InvoiceCalcResult>(`/duty-calc/invoice/calculate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ratePrefill: (hsCode: string) =>
    request<RatePrefill>(`/duty-calc/rate-prefill/${encodeURIComponent(hsCode)}`),
  fxRate: (currency: InvoiceCurrency) =>
    request<FxRate>(`/duty-calc/fx-rate${qs({ currency })}`),

  // Saved filters
  listSavedFilters: () => request<SavedFilter[]>("/saved-filters"),
  createSavedFilter: (name: string, criteria: Record<string, unknown>) =>
    request<SavedFilter>("/saved-filters", {
      method: "POST",
      body: JSON.stringify({ name, criteria }),
    }),
  deleteSavedFilter: (id: string) =>
    request<void>(`/saved-filters/${id}`, { method: "DELETE" }),
};

// ---- Admin console (compliance) ----
// Separate credential/token pair from the normal user session.

const ADMIN_TOKEN_KEY = "quolate_admin_token";

export function setAdminToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem(ADMIN_TOKEN_KEY, token);
  else localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ADMIN_TOKEN_KEY);
}

export interface AdminUserSummary {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  counts: {
    projects: number;
    documents: number;
    library_documents: number;
    chat_messages: number;
    duty_calculations: number;
    audit_events: number;
  };
}

export interface AdminAuditEvent {
  created_at: string;
  action: string;
  method: string;
  path: string;
  query: string | null;
  status_code: number;
}

export interface AdminUserActivity {
  user: {
    id: string;
    email: string;
    display_name: string | null;
    created_at: string;
  };
  events: AdminAuditEvent[];
  projects: { id: string; name: string; status: string; created_at: string }[];
  documents: {
    id: string;
    filename: string;
    kind: string;
    status: string;
    project: string | null;
    created_at: string;
  }[];
  library_documents: {
    id: string;
    filename: string;
    kind: string;
    status: string;
    created_at: string;
  }[];
  chat_messages: { content: string; created_at: string }[];
}

async function adminRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getAdminToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body) headers.set("Content-Type", "application/json");

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    const apiError = new ApiError(res.status, formatErrorDetail(detail));
    logClientError(`${options.method ?? "GET"} ${path} (admin)`, apiError, res.status);
    throw apiError;
  }
  return (await res.json()) as T;
}

export const adminApi = {
  login: async (username: string, password: string) => {
    const token = await adminRequest<AuthToken>("/admin/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setAdminToken(token.access_token);
    return token;
  },
  logout: () => setAdminToken(null),
  users: () => adminRequest<AdminUserSummary[]>("/admin/users"),
  userActivity: (userId: string) =>
    adminRequest<AdminUserActivity>(`/admin/users/${userId}/activity`),
  downloadActivityCsv: (userId: string, email: string) =>
    adminDownload(`/admin/users/${userId}/activity.csv`, `activity-${email}.csv`),
  downloadDocument: (docId: string, kind: "project" | "library", filename: string) =>
    adminDownload(
      kind === "library"
        ? `/admin/library-documents/${docId}/file`
        : `/admin/documents/${docId}/file`,
      filename,
    ),
};

async function adminDownload(path: string, filename: string) {
  const token = getAdminToken();
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new ApiError(res.status, `Could not download ${filename}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
