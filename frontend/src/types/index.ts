// ===== 发票相关类型 =====

export type InvoiceStatus =
  | "UPLOADED"
  | "PROCESSING"
  | "REVIEWING"
  | "CONFIRMED"
  | "REIMBURSED"
  | "NOT_REIMBURSED";

export type VerifyStatus = "PENDING" | "VALID" | "INVALID" | "UNABLE_TO_VERIFY";

export type DuplicateStatus = "PENDING" | "UNIQUE" | "DUPLICATE";

export type FeeCategory = "personal" | "company";

export type DiffConflictStatus = "RESOLVED" | "CONFLICT" | "PENDING";

export interface DiffConflict {
  field: string;
  status: DiffConflictStatus;
  ocr_value: string | null;
  llm_value: string | null;
  resolved_by: string | null;
  resolved_reason: string | null;
}

export interface Invoice {
  id: number;
  receipt_type: string;
  status: InvoiceStatus;
  user_id?: string | null;
  uploader_name?: string | null;
  invoice_number: string | null;
  invoice_code: string | null;
  check_code: string | null;
  issue_date: string | null;
  expense_date?: string | null;
  expense_date_source?: string | null;
  buyer_name: string | null;
  seller_name: string | null;
  seller_tax_id: string | null;
  total_with_tax: string | null;
  amount: string | null;
  tax_amount: string | null;
  fee_category: FeeCategory | null;
  fee_subcategory: string | null;
  project_id: number | null;
  diff_confidence: number | null;
  diff_conflicts: DiffConflict[] | null;
  verify_status: VerifyStatus | null;
  verify_message: string | null;
  duplicate_status: DuplicateStatus | null;
  user_description: string | null;
  reimbursement_id?: number | null;
  created_at: string | null;
  // 非标准票据扩展字段
  is_nonstandard?: boolean | null;
  vlm_confidence?: number | null;
  risk_level?: string | null;
  receipt_detail?: Record<string, unknown> | null;
  processing_pipeline?: string | null;
}

export interface InvoiceDetail extends Invoice {
  buyer_tax_id?: string | null;
  item_name?: string | null;
  tax_rate?: string | null;
  file_type?: string | null;
  file_path?: string | null;
}

export interface OnlineVerifyResponse {
  invoice_id: number;
  verify_status: VerifyStatus;
  message: string;
  is_verified: boolean | null;
  invoice_status: string | null;
  verified_fields: Record<string, string> | null;
  invoice: Invoice | null;
}

export interface OcrResult {
  id: number;
  invoice_id: number;
  raw_text: string | null;
  confidence: number | null;
  extracted_fields: Record<string, string | null> | null;
  ocr_lines:
    | { text: string; confidence: number; bbox: number[][] }[]
    | null;
}

export interface Statistics {
  total_invoices: number;
  total_amount: number;
  total_tax: number;
  pending_review: number;
  confirmed: number;
  duplicates: number;
}

// ===== 报销单类型 =====

export type ReimbursementStatus = "DRAFT" | "SUBMITTED" | "REVIEWED" | "REIMBURSED";

export interface Reimbursement {
  id: number;
  applicant_id: string;
  applicant_name: string | null;
  department: string | null;
  period: string | null;
  reason: string | null;
  total_amount: number | null;
  expense_total: number | null;
  subsidy_total: number | null;
  status: ReimbursementStatus;
  cycle_start: string | null;
  cycle_end: string | null;
  cycle_key: string | null;
  auto_generated: boolean;
  is_cycle_locked: boolean;
  locked_at: string | null;
  submitted_at: string | null;
  confirmed_at: string | null;
  excel_path: string | null;
  pdf_path: string | null;
  zip_path: string | null;
  created_at: string | null;
  attachments?: ReimbursementAttachment[];
  items?: ReimbursementItem[];
  day_subsidies?: ReimbursementDaySubsidy[];
  travel_days?: TravelDay[];
}

export interface ReimbursementItem {
  id: number;
  invoice_id: number | null;
  item_date: string | null;
  item_date_source: string | null;
  weekday: number | null;
  fee_category: string | null;
  fee_subcategory: string | null;
  amount: number;
  description: string | null;
  is_late_charge: boolean;
  intended_cycle_key: string | null;
  sort_order: number;
}

export interface ReimbursementDaySubsidy {
  id: number;
  subsidy_date: string;
  weekday: number | null;
  day_type: string | null;
  base_rate: number | null;
  subsidy_amount: number;
  included: boolean;
  exclude_reason: string | null;
  trigger_invoice_count: number;
}

export interface TravelDay {
  id: number;
  reimbursement_id: number;
  travel_date: string;  // ISO date YYYY-MM-DD
  note: string | null;
  weekday: number | null;  // 0=周一…6=周日
  day_type: string | null;  // workday/weekend/holiday
  base_rate: number | null;
  applicant_id: string;
}

export interface ReimbursementCreate {
  applicant_id: string;
  applicant_name?: string | null;
  department?: string | null;
  period?: string | null;
  reason?: string | null;
  invoice_ids?: number[];
}

// ===== 上传请求 =====

export interface UploadParams {
  file: File;
  user_id: string;
  user_description?: string;
  receipt_type?: string;
}

// ===== 更新请求 =====

export interface InvoiceUpdate {
  fee_category?: FeeCategory | null;
  fee_subcategory?: string | null;
  project_id?: number | null;
  status?: InvoiceStatus | null;
  user_description?: string | null;
}

// ===== 员工相关类型 =====

export interface Employee {
  id: number;
  wecom_user_id: string;
  name: string;
  employee_no: string | null;
  department: string | null;
  department_id: number | null;
  position: string | null;
  mobile: string | null;
  email: string | null;
  has_password?: boolean | null;
  status: number; // 1=在职 2=离职
  created_at: string | null;
  updated_at: string | null;
}

export interface EmployeeCreate {
  wecom_user_id?: string | null;
  name: string;
  employee_no?: string | null;
  department?: string | null;
  department_id?: number | null;
  position?: string | null;
  mobile?: string | null;
  email?: string | null;
  status?: number;
  password?: string | null;
}

export interface EmployeeUpdate {
  name?: string | null;
  employee_no?: string | null;
  department?: string | null;
  department_id?: number | null;
  position?: string | null;
  mobile?: string | null;
  email?: string | null;
  status?: number | null;
  password?: string | null;
}

export interface EmployeeSyncResult {
  total: number;
  created: number;
  updated: number;
  errors: string[];
}

// ===== 对话引擎类型 =====

export type DialogRole = "employee" | "admin" | "boss";

export interface DialogMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  timestamp: number;
  /** 附件缩略图（base64 data URL，仅用户消息） */
  attachmentPreview?: string;
  /** 快捷回复选项（仅 assistant 消息） */
  quickReplies?: string[];
  /** 是否正在执行操作 */
  actionTaken?: boolean;
  /** 错误信息 */
  error?: string | null;
  /** 上传成功消息附带的发票 ID（用于显示“撤销”按钮） */
  invoiceId?: number;
  /** 是否已撤销（隐藏撤销按钮） */
  undone?: boolean;
  /** 追问用途时附带的发票摘要列表 */
  batchSummary?: BatchInvoiceSummary[];
  /** 追问状态（如 waiting_purpose） */
  followUpState?: string;
}

export interface BatchInvoiceSummary {
  index: number;
  id: number;
  seller_name: string;
  total_with_tax: string;
  receipt_type: string;
  issue_date: string;
}

export interface DialogAPIResponse {
  text: string;
  state: string;
  intent: string | null;
  action_taken: boolean;
  need_user_input: boolean;
  quick_replies: string[];
  error: string | null;
  data?: Record<string, any> | null;
}

export interface DialogStateInfo {
  user_id: string;
  state: string;
  role: string;
  current_intent: string | null;
  turn_count: number;
}


export interface PortalLoginResponse {
  access_token: string;
  token_type: string;
  employee: {
    id: number;
    employee_no: string;
    name: string;
    department: string | null;
    position: string | null;
  };
}

export interface PortalDashboard {
  invoice_count: number;
  invoice_total: number;
  cycle_key: string;
  cycle_start: string;
  cycle_end: string;
  recent_invoices: {
    id: number;
    seller_name: string | null;
    total_with_tax: string | null;
    fee_subcategory: string | null;
    status: string;
    created_at: string | null;
  }[];
}

export interface PortalProfile {
  id: number;
  employee_no: string;
  name: string;
  department: string | null;
  position: string | null;
  mobile: string | null;
  email: string | null;
  status: number;
  last_login_at: string | null;
}

export interface PortalReimbursement {
  id: number;
  applicant_id: string;
  applicant_name: string | null;
  department: string | null;
  period: string | null;
  reason: string | null;
  total_amount: number | null;
  expense_total: number | null;
  subsidy_total: number | null;
  status: string;
  cycle_start: string | null;
  cycle_end: string | null;
  cycle_key: string | null;
  auto_generated: boolean;
  is_cycle_locked: boolean;
  invoice_count: number;
  created_at: string | null;
}

export interface ReimbursementAttachment {
  id: number;
  filename: string;
  file_size: number;
  file_type: string | null;
  created_at: string | null;
}

export interface PortalReimbursementDetail extends PortalReimbursement {
  locked_at: string | null;
  submitted_at: string | null;
  confirmed_at: string | null;
  excel_path: string | null;
  pdf_path: string | null;
  zip_path: string | null;
  items?: ReimbursementItem[];
  day_subsidies?: ReimbursementDaySubsidy[];
  travel_days?: TravelDay[];
  invoices: {
    id: number;
    seller_name: string | null;
    issue_date: string | null;
    total_with_tax: string | null;
    fee_category: string | null;
    fee_subcategory: string | null;
    invoice_number: string | null;
    verify_status: string | null;
    duplicate_status: string | null;
  }[];
  attachments: ReimbursementAttachment[];
}

// ===== LLM 设置类型 =====

export interface LlmSettings {
  llm_provider: string;
  llm_api_key: string;
  llm_model: string;
  llm_text_model: string;
  llm_base_url: string;
}

export interface LlmTestResult {
  success: boolean;
  message: string;
  latency_ms: number | null;
}

export interface LlmProviderInfo {
  base_url: string;
  models: string[];
  vision_prefixes: string[];
}

export interface VerifySettings {
  verify_provider: string;
  verify_api_key: string;
  verify_secret_key: string;
  aliyun_verify_appcode: string;
  aliyun_verify_appsecret: string;
}
