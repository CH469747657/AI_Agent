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

// ===== 项目相关类型 =====

export interface Project {
  id: number;
  name: string;
  code: string | null;
  status: string;
}

export interface ProjectCreate {
  name: string;
  code?: string | null;
  member_ids?: string[];
  supplier_names?: string[];
  description?: string | null;
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
  status: ReimbursementStatus;
  excel_path: string | null;
  pdf_path: string | null;
  zip_path: string | null;
  created_at: string | null;
  attachments?: ReimbursementAttachment[];
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
  wecom_user_id: string;
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

// ===== 员工端 Portal 类型 =====

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
  reimbursement_count: number;
  draft_count: number;
  submitted_count: number;
  recent_invoices: {
    id: number;
    seller_name: string | null;
    total_with_tax: string | null;
    fee_subcategory: string | null;
    status: string;
    created_at: string | null;
  }[];
  recent_reimbursements: {
    id: number;
    total_amount: number | null;
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
  status: string;
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
  excel_path: string | null;
  pdf_path: string | null;
  zip_path: string | null;
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
