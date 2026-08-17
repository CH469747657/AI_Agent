import type {
  DialogAPIResponse,
  DialogRole,
  DialogStateInfo,
  Employee,
  EmployeeCreate,
  EmployeeSyncResult,
  EmployeeUpdate,
  Invoice,
  InvoiceDetail,
  InvoiceUpdate,
  LlmProviderInfo,
  LlmSettings,
  LlmTestResult,
  VerifySettings,
  OnlineVerifyResponse,
  OcrResult,
  PortalDashboard,
  PortalLoginResponse,
  PortalProfile,
  PortalReimbursement,
  PortalReimbursementDetail,
  Reimbursement,
  ReimbursementCreate,
  ReimbursementAttachment,
  Statistics,
  TravelDay,
  UploadParams,
  VerifyStatus,
} from "../types";

const BASE = "/api";

/** 获取管理端 token */
function getAdminToken(): string | null {
  return localStorage.getItem("admin_token");
}

/** 保存管理端 token */
function setAdminToken(token: string) {
  localStorage.setItem("admin_token", token);
}

/** 清除管理端 token */
function clearAdminToken() {
  localStorage.removeItem("admin_token");
}

async function request<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  // 管理端接口自动注入 admin token（与员工端 portal_token 物理隔离）
  const token = getAdminToken();
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${BASE}${url}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    if (res.status === 401) {
      clearAdminToken();
      // 避免在登录页跳转自身造成循环
      if (!window.location.pathname.startsWith("/admin/login")) {
        window.location.href = "/admin/login";
      }
      throw new Error("登录已过期，请重新登录");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `请求失败 (${res.status})`);
  }
  return res.json();
}

// ===== 发票 API =====

export const invoiceApi = {
  list: (params?: { user_id?: string; status?: string }) => {
    const qs = new URLSearchParams();
    if (params?.user_id) qs.set("user_id", params.user_id);
    if (params?.status) qs.set("status", params.status);
    const q = qs.toString();
    return request<Invoice[]>(`/invoices${q ? "?" + q : ""}`);
  },

  statistics: () => request<Statistics>("/invoices/statistics"),

  detail: (id: number) => request<InvoiceDetail>(`/invoices/${id}`),

  ocrResult: async (id: number): Promise<OcrResult | null> => {
    try {
      const detail = await request<{ ocr_text?: string }>(
        `/wecom/invoices/${id}/detail`
      );
      return {
        id: 0,
        invoice_id: id,
        raw_text: detail.ocr_text || null,
        confidence: null,
        extracted_fields: null,
        ocr_lines: null,
      };
    } catch {
      return null;
    }
  },

  upload: (params: UploadParams) => {
    const formData = new FormData();
    formData.append("file", params.file);
    formData.append("user_id", params.user_id);
    // 无感上传：receipt_type 留空时，后端 LLM Vision 自动识别
    formData.append("receipt_type", params.receipt_type ?? "");
    formData.append("user_description", params.user_description || "");
    return request<Invoice>("/invoices/upload", {
      method: "POST",
      body: formData,
    });
  },

  update: (id: number, data: InvoiceUpdate) =>
    request<Invoice>(`/invoices/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  verify: (id: number, verifyStatus: VerifyStatus) =>
    request<Invoice>(`/invoices/${id}/verify`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verify_status: verifyStatus }),
    }),

  onlineVerify: (id: number) =>
    request<OnlineVerifyResponse>(`/invoices/${id}/online-verify`, {
      method: "POST",
    }),

  delete: (id: number) =>
    request<{ message: string; deleted: boolean }>(`/invoices/${id}`, {
      method: "DELETE",
    }),

  approve: (id: number) =>
    request<Invoice>(`/invoices/${id}/approve`, {
      method: "POST",
    }),

  reject: (id: number) =>
    request<Invoice>(`/invoices/${id}/reject`, {
      method: "POST",
    }),

  fileUrl: (id: number) => `${BASE}/invoices/${id}/file`,

  exportInvoices: async (userId?: string) => {
    const qs = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
    const res = await fetch(`${BASE}/invoices/export${qs}`);
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "导出失败");
    }
    // 从 Content-Disposition 提取文件名
    let filename = "发票清单.xlsx";
    const disposition = res.headers.get("Content-Disposition");
    if (disposition) {
      const utf8Match = disposition.match(/filename\*=UTF-8''(.+)/i);
      const asciiMatch = disposition.match(/filename="?([^";\n]+)"?/i);
      if (utf8Match) filename = decodeURIComponent(utf8Match[1]);
      else if (asciiMatch) filename = asciiMatch[1];
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  },
};

// ===== 报销单 API =====

export const reimbursementApi = {
  list: (params?: { applicant_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.applicant_id) qs.set("applicant_id", params.applicant_id);
    const q = qs.toString();
    return request<Reimbursement[]>(`/reimbursements${q ? "?" + q : ""}`);
  },

  detail: (id: number) => request<Reimbursement>(`/reimbursements/${id}`),

  toggleSubsidy: (id: number, subsidyDate: string, included: boolean, excludeReason?: string) =>
    request<{
      subsidy_date: string;
      included: boolean;
      subsidy_amount: number;
      subsidy_total: number;
      total_amount: number;
    }>(`/reimbursements/${id}/subsidy/toggle`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subsidy_date: subsidyDate, included, exclude_reason: excludeReason || null }),
    }),

  lockCycle: (cycleKey: string, autoSubmit: boolean = true) =>
    request<{
      cycle_key: string;
      locked: boolean;
      locked_at: string;
      submitted_count: number;
      total_locked: number;
    }>(`/reimbursements/cycle/lock/${cycleKey}?auto_submit=${autoSubmit}`, {
      method: "POST",
    }),

  cycleStatus: (cycleKey: string) =>
    request<{
      cycle_key: string;
      is_locked: boolean;
      locked_at: string | null;
      draft_count: number;
      submitted_count: number;
    }>(`/reimbursements/cycle/status/${cycleKey}`),

  create: (data: ReimbursementCreate) =>
    request<Reimbursement>("/reimbursements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  linkInvoices: (id: number, invoiceIds: number[]) =>
    request<Reimbursement>(`/reimbursements/${id}/invoices`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ invoice_ids: invoiceIds }),
    }),

  unlinkInvoice: (reimbursementId: number, invoiceId: number) =>
    request<Reimbursement>(`/reimbursements/${reimbursementId}/unlink/${invoiceId}`, {
      method: "PUT",
    }),

  submit: (id: number) =>
    request<Reimbursement>(`/reimbursements/${id}/submit`, {
      method: "PUT",
    }),

  withdraw: (id: number) =>
    request<Reimbursement>(`/reimbursements/${id}/withdraw`, {
      method: "PUT",
    }),

  approve: (id: number) =>
    request<Reimbursement>(`/reimbursements/${id}/approve`, {
      method: "PUT",
    }),

  reject: (id: number, reason?: string) =>
    request<Reimbursement>(`/reimbursements/${id}/reject${reason ? `?reason=${encodeURIComponent(reason)}` : ""}`, {
      method: "PUT",
    }),

  reimburse: (id: number) =>
    request<Reimbursement>(`/reimbursements/${id}/reimburse`, {
      method: "PUT",
    }),

  // 节假日
  syncHolidays: (year: number) =>
    request<{ year: number; holidays_added: number; workdays_added: number; total: number }>(
      `/holidays/sync/${year}`,
      { method: "POST" }
    ),

  listHolidays: (year: number) =>
    request<{ id: number; holiday_date: string; holiday_name: string | null; day_type: string; year: number | null; source: string | null }[]>(
      `/holidays/${year}`
    ),

  delete: (id: number) =>
    request<{ message: string; deleted: boolean }>(`/reimbursements/${id}`, {
      method: "DELETE",
    }),

  // 附件
  uploadAttachment: async (
    reimbursementId: number,
    file: File
  ): Promise<ReimbursementAttachment & { message: string }> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(
      `${BASE}/reimbursements/${reimbursementId}/attachments`,
      { method: "POST", body: formData }
    );
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "附件上传失败");
    }
    return res.json();
  },

  deleteAttachment: (reimbursementId: number, attachmentId: number) =>
    request<{ message: string; deleted: boolean }>(
      `/reimbursements/${reimbursementId}/attachments/${attachmentId}`,
      { method: "DELETE" }
    ),

  downloadAttachment: async (
    reimbursementId: number,
    attachmentId: number,
    filename?: string
  ): Promise<void> => {
    const res = await fetch(
      `${BASE}/reimbursements/${reimbursementId}/attachments/${attachmentId}/download`
    );
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "下载失败");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "附件";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};

// ===== 报表 API =====

export const reportApi = {
  generate: (reimbursementId: number) =>
    request<{ status: string; files: Record<string, string> }>(
      `/reports/generate/${reimbursementId}`,
      { method: "POST" }
    ),

  downloadUrl: (reimbursementId: number, fileType: string) =>
    `${BASE}/reports/download/${reimbursementId}/${fileType}`,

  download: async (reimbursementId: number, fileType: string): Promise<void> => {
    const token = getAdminToken();
    const res = await fetch(
      `${BASE}/reports/download/${reimbursementId}/${fileType}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} }
    );
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "下载失败");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `reimbursement_${reimbursementId}.${fileType}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};

// ===== 员工 API =====

export const employeeApi = {
  list: (params?: { keyword?: string; status?: number }) => {
    const qs = new URLSearchParams();
    if (params?.keyword) qs.set("keyword", params.keyword);
    if (params?.status !== undefined) qs.set("status", String(params.status));
    const q = qs.toString();
    return request<Employee[]>(`/employees${q ? "?" + q : ""}`);
  },

  detail: (id: number) => request<Employee>(`/employees/${id}`),

  create: (data: EmployeeCreate) =>
    request<Employee>("/employees", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  update: (id: number, data: EmployeeUpdate) =>
    request<Employee>(`/employees/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    request<{ message: string; deleted: boolean }>(`/employees/${id}`, {
      method: "DELETE",
    }),

  sync: () =>
    request<EmployeeSyncResult>("/employees/sync", { method: "POST" }),

  /** 下载批量添加模板（.xlsx） */
  downloadTemplate: async (): Promise<void> => {
    const token = getAdminToken();
    const res = await fetch("/api/employees/batch/template", {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      throw new Error("模板下载失败");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "employee_batch_template.xlsx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /** 批量上传 Excel 添加员工 */
  batchUpload: async (
    file: File
  ): Promise<{
    total: number;
    success: number;
    failed: number;
    errors: string[];
  }> => {
    const token = getAdminToken();
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/employees/batch/upload", {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `上传失败 (${res.status})`);
    }
    return res.json();
  },
};

// ===== 员工端 Portal API =====

const PORTAL_BASE = "/api/portal";

/** 获取存储的 portal token */
function getPortalToken(): string | null {
  return localStorage.getItem("portal_token");
}

/** 保存 portal token */
function setPortalToken(token: string) {
  localStorage.setItem("portal_token", token);
}

/** 清除 portal token */
function clearPortalToken() {
  localStorage.removeItem("portal_token");
  localStorage.removeItem("portal_employee");
}

/** portal 请求封装（自动携带 Authorization） */
async function portalRequest<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const token = getPortalToken();
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${PORTAL_BASE}${url}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    if (res.status === 401) {
      clearPortalToken();
      window.location.href = "/portal/login";
      throw new Error("登录已过期，请重新登录");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `请求失败 (${res.status})`);
  }
  return res.json();
}

export const portalApi = {
  // 认证
  login: async (
    employee_no: string,
    password: string
  ): Promise<PortalLoginResponse> => {
    const res = await fetch(`${PORTAL_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee_no, password }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "登录失败");
    }
    const data: PortalLoginResponse = await res.json();
    setPortalToken(data.access_token);
    localStorage.setItem("portal_employee", JSON.stringify(data.employee));
    return data;
  },

  changePassword: (oldPassword: string, newPassword: string) => {
    const employee = JSON.parse(
      localStorage.getItem("portal_employee") || "{}"
    );
    return portalRequest<{ status: string; message: string }>(
      "/auth/change-password",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          employee_no: employee.employee_no,
          old_password: oldPassword,
          new_password: newPassword,
        }),
      }
    );
  },

  logout: () => {
    clearPortalToken();
  },

  getStoredEmployee: (): PortalLoginResponse["employee"] | null => {
    const raw = localStorage.getItem("portal_employee");
    return raw ? JSON.parse(raw) : null;
  },

  getToken: getPortalToken,

  // 仪表板
  dashboard: () => portalRequest<PortalDashboard>("/dashboard"),

  // 个人信息
  profile: () => portalRequest<PortalProfile>("/profile"),

  // 我的发票
  myInvoices: () => portalRequest<Invoice[]>("/invoices"),

  myInvoiceDetail: (id: number) => portalRequest<InvoiceDetail>(`/invoices/${id}`),

  deleteInvoice: (id: number) =>
    portalRequest<{ message: string; deleted: boolean }>(
      `/invoices/${id}`,
      { method: "DELETE" }
    ),

  // 我的报销单
  myReimbursements: () => portalRequest<PortalReimbursement[]>("/reimbursements"),

  myReimbursementDetail: (id: number) =>
    portalRequest<PortalReimbursementDetail>(`/reimbursements/${id}`),

  updateReimbursement: (id: number, data: { reason?: string; period?: string }) =>
    portalRequest<{
      id: number;
      reason: string | null;
      period: string | null;
      status: string;
      message: string;
    }>(`/reimbursements/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  linkInvoices: (id: number, invoiceIds: number[]) =>
    portalRequest<{
      status: string;
      linked: number;
      total_amount: number;
      message: string;
    }>(`/reimbursements/${id}/invoices`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ invoice_ids: invoiceIds }),
    }),

  unlinkInvoice: (reimbursementId: number, invoiceId: number) =>
    portalRequest<{
      status: string;
      total_amount: number;
      message: string;
    }>(`/reimbursements/${reimbursementId}/unlink/${invoiceId}`, {
      method: "PUT",
    }),

  submitReimbursement: (id: number) =>
    portalRequest<{ status: string; message: string }>(
      `/reimbursements/${id}/submit`,
      { method: "POST" }
    ),

  withdrawReimbursement: (id: number) =>
    portalRequest<{ status: string; message: string }>(
      `/reimbursements/${id}/withdraw`,
      { method: "POST" }
    ),

  toggleSubsidy: (id: number, subsidyDate: string, included: boolean, excludeReason?: string) =>
    portalRequest<{
      subsidy_date: string;
      included: boolean;
      subsidy_amount: number;
      subsidy_total: number;
      total_amount: number;
    }>(`/reimbursements/${id}/subsidy/toggle`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subsidy_date: subsidyDate, included, exclude_reason: excludeReason || null }),
    }),

  deleteReimbursement: (id: number) =>
    portalRequest<{ message: string; deleted: boolean }>(
      `/reimbursements/${id}`,
      { method: "DELETE" }
    ),

  // 报销单附件
  uploadAttachment: async (
    reimbursementId: number,
    file: File
  ): Promise<ReimbursementAttachment & { message: string }> => {
    const token = getPortalToken();
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(
      `${PORTAL_BASE}/reimbursements/${reimbursementId}/attachments`,
      {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      }
    );
    if (!res.ok) {
      if (res.status === 401) {
        clearPortalToken();
        window.location.href = "/portal/login";
        throw new Error("登录已过期，请重新登录");
      }
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "附件上传失败");
    }
    return res.json();
  },

  deleteAttachment: (
    reimbursementId: number,
    attachmentId: number
  ) =>
    portalRequest<{ message: string; deleted: boolean }>(
      `/reimbursements/${reimbursementId}/attachments/${attachmentId}`,
      { method: "DELETE" }
    ),

  attachmentDownloadUrl: (
    reimbursementId: number,
    attachmentId: number
  ): string =>
    `${PORTAL_BASE}/reimbursements/${reimbursementId}/attachments/${attachmentId}/download`,

  downloadAttachment: async (
    reimbursementId: number,
    attachmentId: number,
    filename?: string
  ): Promise<void> => {
    const token = getPortalToken();
    const res = await fetch(
      `${PORTAL_BASE}/reimbursements/${reimbursementId}/attachments/${attachmentId}/download`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} }
    );
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "下载失败");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "附件";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  // 上传发票（员工端专属鉴权接口，user_id 由服务端从 JWT token 推导）
  uploadInvoice: (
    file: File,
    options?: {
      description?: string;
      receipt_type?: string;
    }
  ) => {
    const formData = new FormData();
    formData.append("file", file);
    // 无感上传：receipt_type 留空时，后端 LLM Vision 自动识别
    formData.append("receipt_type", options?.receipt_type ?? "");
    formData.append("user_description", options?.description || "");
    return portalRequest<Invoice>("/invoices/upload", {
      method: "POST",
      body: formData,
    });
  },

  /** 更新发票字段（补充用途等） */
  updateInvoice: async (id: number, data: { user_description?: string }) => {
    return portalRequest<Invoice>(`/invoices/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  },

  downloadInvoiceFile: async (id: number) => {
    const token = localStorage.getItem("portal_token");
    const resp = await fetch(`${PORTAL_BASE}/invoices/${id}/file`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) throw new Error("下载失败");
    // 从 Content-Disposition 提取服务端返回的文件名（含扩展名）
    let filename = `发票_${id}`;
    const disposition = resp.headers.get("Content-Disposition");
    if (disposition) {
      // 支持 filename*=UTF-8''xxx 和 filename="xxx" 两种格式
      const utf8Match = disposition.match(/filename\*=UTF-8''(.+)/i);
      const asciiMatch = disposition.match(/filename="?([^";\n]+)"?/i);
      if (utf8Match) filename = decodeURIComponent(utf8Match[1]);
      else if (asciiMatch) filename = asciiMatch[1];
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // 延迟释放，确保浏览器完成读取
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  },

  // 出差日（员工标记）
  listTravelDays: (): Promise<TravelDay[]> =>
    portalRequest<TravelDay[]>("/travel-days"),

  createTravelDay: async (
    travel_date: string,
    note?: string
  ): Promise<TravelDay> => {
    return portalRequest<TravelDay>("/travel-days", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ travel_date, note: note || null }),
    });
  },

  deleteTravelDayByDate: async (travel_date: string): Promise<void> => {
    await portalRequest<{ deleted: boolean }>(
      `/travel-days/by-date/${encodeURIComponent(travel_date)}`,
      { method: "DELETE" }
    );
  },
};

// ===== 对话引擎 API =====

export const dialogApi = {
  /**
   * 发送消息
   * employee → JWT 鉴权端点 /api/portal/dialog/message（user_id 从 token 推导）
   * admin/boss → 通用端点 /api/dialog/message
   */
  sendMessage: (params: {
    user_id: string;
    text: string;
    role: DialogRole;
    has_attachment?: boolean;
    attachment_base64?: string | null;
    attachment_file_type?: string | null;
    receipt_type?: string | null;
    user_description?: string | null;
    no_receipt_amount?: string | null;
  }) => {
    const body = {
      user_id: params.user_id,
      text: params.text,
      role: params.role,
      has_attachment: params.has_attachment ?? false,
      attachment_base64: params.attachment_base64 ?? null,
      attachment_file_type: params.attachment_file_type ?? null,
      receipt_type: params.receipt_type ?? null,
      user_description: params.user_description ?? null,
      no_receipt_amount: params.no_receipt_amount ?? null,
    };
    if (params.role === "employee") {
      return portalRequest<DialogAPIResponse>("/dialog/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }
    return request<DialogAPIResponse>("/dialog/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  /**
   * 流式发送消息（SSE）
   * 通过 POST + ReadableStream 解析 SSE 事件流（EventSource 仅支持 GET，无法用）。
   *
   * 回调约定：
   * - onProgress(text): 收到 {"phase":"progress","text":"..."} 事件
   * - onDone(response): 收到 {"phase":"done","response":<DialogAPIResponse>} 事件
   * - onError(message): 收到 {"phase":"error","message":"..."} 事件或网络异常
   *
   * 兼容性：若服务端不支持 SSE（返回非 text/event-stream），降级为一次性 JSON 响应。
   */
  streamMessage: async (
    params: {
      user_id: string;
      text: string;
      role: DialogRole;
      has_attachment?: boolean;
      attachment_base64?: string | null;
      attachment_file_type?: string | null;
      receipt_type?: string | null;
      user_description?: string | null;
      no_receipt_amount?: string | null;
    },
    handlers: {
      onProgress?: (text: string) => void;
      onDone?: (response: DialogAPIResponse) => void;
      onError?: (message: string) => void;
    }
  ): Promise<void> => {
    const body = {
      user_id: params.user_id,
      text: params.text,
      role: params.role,
      has_attachment: params.has_attachment ?? false,
      attachment_base64: params.attachment_base64 ?? null,
      attachment_file_type: params.attachment_file_type ?? null,
      receipt_type: params.receipt_type ?? null,
      user_description: params.user_description ?? null,
      no_receipt_amount: params.no_receipt_amount ?? null,
    };

    // 构造请求头：admin/boss 走通用端点（带 admin token），employee 走 portal 端点（带 JWT）
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    const url = params.role === "employee" ? `${PORTAL_BASE}/dialog/message/stream` : `${BASE}/dialog/message/stream`;
    if (params.role === "employee") {
      const token = getPortalToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    } else {
      const adminToken = getAdminToken();
      if (adminToken) headers["Authorization"] = `Bearer ${adminToken}`;
    }

    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
    } catch (err) {
      handlers.onError?.(err instanceof Error ? err.message : "网络请求失败");
      return;
    }

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({ detail: res.statusText }));
      handlers.onError?.(errBody.detail || `请求失败 (${res.status})`);
      return;
    }

    // 兼容降级：服务端返回 JSON 而非 SSE
    const contentType = res.headers.get("content-type") || "";
    if (!contentType.includes("text/event-stream")) {
      try {
        const data = await res.json();
        handlers.onDone?.(data as DialogAPIResponse);
      } catch (err) {
        handlers.onError?.(err instanceof Error ? err.message : "响应解析失败");
      }
      return;
    }

    // 解析 SSE 事件流
    const reader = res.body?.getReader();
    if (!reader) {
      handlers.onError?.("无法读取响应流");
      return;
    }

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // 按 "data: <json>\n\n" 分割事件
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const eventChunk = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);

          // 提取 data: 行
          const lines = eventChunk.split("\n");
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data:")) continue;
            const jsonStr = trimmed.slice(5).trim();
            if (!jsonStr) continue;

            try {
              const event = JSON.parse(jsonStr);
              if (event.phase === "progress" && event.text) {
                handlers.onProgress?.(event.text);
              } else if (event.phase === "done" && event.response) {
                handlers.onDone?.(event.response as DialogAPIResponse);
              } else if (event.phase === "error") {
                handlers.onError?.(event.message || "服务端处理失败");
              }
            } catch {
              // 单个事件解析失败不中断整体流
            }
          }
        }
      }
    } catch (err) {
      handlers.onError?.(err instanceof Error ? err.message : "响应流读取失败");
    }
  },

  /**
   * 重置对话上下文
   * employee → JWT 鉴权端点 /api/portal/dialog/reset
   */
  reset: (userId: string, role?: DialogRole) => {
    if (role === "employee") {
      return portalRequest<{ status: string; message: string }>(
        "/dialog/reset",
        { method: "POST" }
      );
    }
    return request<{ status: string; message: string }>(
      `/dialog/reset/${encodeURIComponent(userId)}`,
      { method: "POST" }
    );
  },

  /**
   * 查询对话状态
   * employee → JWT 鉴权端点 /api/portal/dialog/state
   */
  state: (userId: string, role?: DialogRole) => {
    if (role === "employee") {
      return portalRequest<DialogStateInfo>("/dialog/state");
    }
    return request<DialogStateInfo>(
      `/dialog/state/${encodeURIComponent(userId)}`
    );
  },
};

// ===== 系统设置 API =====

export const settingsApi = {
  /** 获取当前 LLM 配置 */
  getLlmSettings: () => request<LlmSettings>("/settings/llm"),

  /** 保存 LLM 配置 */
  updateLlmSettings: (data: Partial<LlmSettings>) =>
    request<LlmSettings>("/settings/llm", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  /** 测试 LLM 连通性 */
  testLlmConnection: (data?: Partial<LlmSettings>) =>
    request<LlmTestResult>("/settings/llm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data ?? {}),
    }),

  /** 获取所有服务商信息 */
  getProviders: () =>
    request<Record<string, LlmProviderInfo>>("/settings/llm/providers"),

  /** 获取验真 API 配置 */
  getVerifySettings: () => request<VerifySettings>("/settings/verify"),

  /** 保存验真 API 配置 */
  updateVerifySettings: (data: Partial<VerifySettings>) =>
    request<VerifySettings>("/settings/verify", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
};

// ===== 管理端 Admin API =====

export interface AdminLoginResponse {
  access_token: string;
  token_type: string;
  admin: {
    username: string;
    name: string;
    role: string;
  };
}

export const adminApi = {
  login: async (
    username: string,
    password: string
  ): Promise<AdminLoginResponse> => {
    const res = await fetch(`/api/admin/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "登录失败");
    }
    const data: AdminLoginResponse = await res.json();
    setAdminToken(data.access_token);
    localStorage.setItem("admin_user", JSON.stringify(data.admin));
    return data;
  },

  logout: () => {
    clearAdminToken();
    localStorage.removeItem("admin_user");
  },

  getToken: getAdminToken,

  getStoredAdmin: (): AdminLoginResponse["admin"] | null => {
    const raw = localStorage.getItem("admin_user");
    return raw ? JSON.parse(raw) : null;
  },

  /** 修改管理员密码（需当前登录态） */
  changePassword: async (oldPassword: string, newPassword: string) => {
    const token = getAdminToken();
    const res = await fetch(`/api/admin/auth/change-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
      }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `修改失败 (${res.status})`);
    }
    return res.json();
  },
};

// ===== 超级管理员端 API（BOSS） — token 与 admin_token / portal_token 物理隔离 =====

/** 获取超级管理员端 token */
function getBossToken(): string | null {
  return localStorage.getItem("boss_token");
}

/** 保存超级管理员端 token */
function setBossToken(token: string) {
  localStorage.setItem("boss_token", token);
}

/** 清除超级管理员端 token */
function clearBossToken() {
  localStorage.removeItem("boss_token");
  localStorage.removeItem("boss_profile");
}

/** 超级管理员端专用请求函数 — 自动注入 boss_token，401 清 token + 跳 /boss/login */
async function bossRequest<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const token = getBossToken();
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${BASE}${url}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    if (res.status === 401) {
      clearBossToken();
      if (!window.location.pathname.startsWith("/boss/login")) {
        window.location.href = "/boss/login";
      }
      throw new Error("登录已过期，请重新登录");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `请求失败 (${res.status})`);
  }
  return res.json();
}

export interface BossLoginResponse {
  access_token: string;
  token_type: string;
  profile: {
    username: string;
    name: string;
    role: "boss";
  };
}

export interface BossDialogResponse {
  text: string;
  state: string;
  intent: string | null;
  action_taken: boolean;
  need_user_input: boolean;
  quick_replies: string[];
  error: string | null;
  data: unknown;
}

export const bossApi = {
  login: async (
    username: string,
    password: string
  ): Promise<BossLoginResponse> => {
    const res = await fetch(`/api/boss/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "登录失败");
    }
    const data: BossLoginResponse = await res.json();
    setBossToken(data.access_token);
    localStorage.setItem("boss_profile", JSON.stringify(data.profile));
    return data;
  },

  logout: () => {
    clearBossToken();
  },

  getToken: getBossToken,

  getProfile: (): BossLoginResponse["profile"] | null => {
    const raw = localStorage.getItem("boss_profile");
    return raw ? JSON.parse(raw) : null;
  },

  /** 智能问数 — POST /api/dialog/message，body 带 role=boss */
  ask: async (message: string, userId = "boss"): Promise<BossDialogResponse> => {
    return bossRequest<BossDialogResponse>(`/dialog/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, role: "boss", user_id: userId }),
    });
  },

  /** 发票列表（穿透全公司） */
  listInvoices: (params?: {
    user_id?: string;
    status?: string;
  }): Promise<Invoice[]> => {
    const qs = new URLSearchParams();
    if (params?.user_id) qs.set("user_id", params.user_id);
    if (params?.status) qs.set("status", params.status);
    const q = qs.toString();
    return bossRequest<Invoice[]>(`/invoices${q ? "?" + q : ""}`);
  },

  /** 发票详情 */
  getInvoice: (id: number): Promise<InvoiceDetail> =>
    bossRequest<InvoiceDetail>(`/invoices/${id}`),

  /** 报销单列表（穿透全公司） */
  listReimbursements: (params?: { applicant_id?: string }): Promise<Reimbursement[]> => {
    const qs = new URLSearchParams();
    if (params?.applicant_id) qs.set("applicant_id", params.applicant_id);
    const q = qs.toString();
    return bossRequest<Reimbursement[]>(`/reimbursements${q ? "?" + q : ""}`);
  },

  /** 报销单详情 */
  getReimbursement: (id: number): Promise<Reimbursement> =>
    bossRequest<Reimbursement>(`/reimbursements/${id}`),

  /** 员工列表（用于问数下钻） */
  listEmployees: (): Promise<unknown[]> => bossRequest<unknown[]>(`/employees`),

  /** 项目列表 */
  listProjects: (): Promise<unknown[]> => bossRequest<unknown[]>(`/projects`),

  /** 发票图片下载 URL — fetch 时仍需带 token，浏览器原生 img src 无法带 header，
   * 故由调用方 fetch blob 后转 objectURL */
  getInvoiceFileUrl: (id: number): string => `/api/invoices/${id}/file`,

  /** 拉取发票图片为 blob URL（带 boss_token） */
  fetchInvoiceFile: async (id: number): Promise<string | null> => {
    try {
      const res = await fetch(`/api/invoices/${id}/file`, {
        headers: { Authorization: `Bearer ${getBossToken()}` },
      });
      if (!res.ok) return null;
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    } catch {
      return null;
    }
  },
};
