import type {
  Employee,
  EmployeeCreate,
  EmployeeSyncResult,
  EmployeeUpdate,
  Invoice,
  InvoiceDetail,
  InvoiceUpdate,
  OnlineVerifyResponse,
  OcrResult,
  PortalDashboard,
  PortalLoginResponse,
  PortalProfile,
  PortalReimbursement,
  PortalReimbursementDetail,
  Project,
  ProjectCreate,
  Reimbursement,
  ReimbursementCreate,
  ReimbursementAttachment,
  Statistics,
  UploadParams,
  VerifyStatus,
} from "../types";

const BASE = "/api";

async function request<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${url}`, options);
  if (!res.ok) {
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
    formData.append("receipt_type", params.receipt_type || "增值税普通发票");
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

// ===== 项目 API =====

export const projectApi = {
  list: () => request<Project[]>("/projects"),
  create: (data: ProjectCreate) =>
    request<Project>("/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
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

  createReimbursement: (data: {
    reason?: string;
    period?: string;
    invoice_ids?: number[];
  }) =>
    portalRequest<{ id: number; status: string; total_amount: number | null; message: string }>(
      "/reimbursements",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }
    ),

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
    formData.append(
      "receipt_type",
      options?.receipt_type || "增值税普通发票"
    );
    formData.append("user_description", options?.description || "");
    return portalRequest<Invoice>("/invoices/upload", {
      method: "POST",
      body: formData,
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
};
