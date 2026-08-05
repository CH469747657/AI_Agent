import { motion, AnimatePresence } from "framer-motion";
import { useSearchParams } from "react-router-dom";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import {
  Plus,
  ArrowLeft,
  CurrencyCny,
  CalendarBlank,
  User,
  Building,
  FileText,
  FileXls,
  FileZip,
  DownloadSimple,
  CheckCircle,
  Warning,
  Spinner,
  PaperPlaneTilt,
  Stack,
  Receipt,
  Clock,
  Trash,
  XCircle,
  NotePencil,
  Minus,
  Paperclip,
  ArrowUUpLeft,
} from "@phosphor-icons/react";
import { reimbursementApi, invoiceApi, reportApi } from "../api/client";
import type {
  Reimbursement,
  ReimbursementStatus,
  Invoice,
  ReimbursementAttachment,
} from "../types";
import { StatusBadge, CategoryBadge, DuplicateBadge, VerifyBadge } from "../components/StatusBadge";
import { EmptyState, TableSkeleton } from "../components/EmptyState";

/* ---------- Status badge ---------- */

const reimbStatusConfig: Record<
  ReimbursementStatus,
  { label: string; className: string }
> = {
  DRAFT: { label: "草稿", className: "bg-slate-100 text-slate-600" },
  SUBMITTED: { label: "已提交", className: "bg-blue-50 text-blue-700" },
  REVIEWED: { label: "已审核", className: "bg-amber-50 text-amber-700" },
  REIMBURSED: { label: "已报销", className: "bg-emerald-50 text-emerald-700" },
};

function ReimbStatusBadge({ status }: { status: ReimbursementStatus }) {
  const config = reimbStatusConfig[status] || reimbStatusConfig.DRAFT;
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  );
}

/* ---------- Info row for detail ---------- */

function InfoRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100">
        {icon}
      </div>
      <div className="flex-1">
        <p className="text-xs text-slate-400">{label}</p>
        <p className="text-sm font-medium text-slate-800">{value ?? "—"}</p>
      </div>
    </div>
  );
}

/* ---------- Main component ---------- */

type View = "list" | "create" | "detail";

const statusTabs: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "DRAFT", label: "草稿" },
  { key: "SUBMITTED", label: "已提交" },
  { key: "REVIEWED", label: "已审核" },
  { key: "REIMBURSED", label: "已报销" },
];

export function Reimbursements() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Determine initial view from URL
  const idsParam = searchParams.get("ids");
  const detailParam = searchParams.get("detail");
  const initialView: View = idsParam
    ? "create"
    : detailParam
      ? "detail"
      : "list";

  const [view, setView] = useState<View>(initialView);
  const [statusFilter, setStatusFilter] = useState("all");

  // Data
  const [reimbursements, setReimbursements] = useState<Reimbursement[]>([]);
  const [allInvoices, setAllInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail state
  const [detailId, setDetailId] = useState<number | null>(
    initialView === "detail" ? Number(detailParam) : null
  );
  const [detailReimb, setDetailReimb] = useState<Reimbursement | null>(null);
  const [detailInvoices, setDetailInvoices] = useState<Invoice[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [showAddInvoice, setShowAddInvoice] = useState(false);
  const [addInvoiceIds, setAddInvoiceIds] = useState<number[]>([]);
  const [addingInvoices, setAddingInvoices] = useState(false);
  const [removingInvoiceId, setRemovingInvoiceId] = useState<number | null>(null);
  const [detailAttachments, setDetailAttachments] = useState<ReimbursementAttachment[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [deletingAttachmentId, setDeletingAttachmentId] = useState<number | null>(null);
  const detailFileInputRef = useRef<HTMLInputElement>(null);

  // Create form
  const [selectedIds, setSelectedIds] = useState<number[]>(
    idsParam
      ? idsParam
          .split(",")
          .map(Number)
          .filter((n) => !isNaN(n) && n > 0)
      : []
  );
  const [applicantId, setApplicantId] = useState("test_user_001");
  const [applicantName, setApplicantName] = useState("");
  const [department, setDepartment] = useState("");
  const [period, setPeriod] = useState(
    new Date().toISOString().slice(0, 7)
  );
  const [reason, setReason] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);

  // 删除状态
  const [deleteTarget, setDeleteTarget] = useState<Reimbursement | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  /* ---------- Effects ---------- */

  // Fetch reimbursements
  const fetchReimbursements = useCallback(() => {
    return reimbursementApi
      .list()
      .then(setReimbursements)
      .catch((e) => setError(e.message));
  }, []);

  // Initial fetch
  useEffect(() => {
    Promise.all([reimbursementApi.list(), invoiceApi.list()])
      .then(([reimb, invs]) => {
        setReimbursements(reimb);
        setAllInvoices(invs);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Fetch detail when switching to detail view
  useEffect(() => {
    if (view !== "detail" || !detailId) return;
    setDetailLoading(true);
    setError(null);
    Promise.all([reimbursementApi.detail(detailId), invoiceApi.list()])
      .then(([reimb, invs]) => {
        setDetailReimb(reimb);
        setDetailAttachments(reimb.attachments || []);
        setDetailInvoices(invs.filter((inv) => inv.reimbursement_id === detailId));
      })
      .catch((e) => setError(e.message))
      .finally(() => setDetailLoading(false));
  }, [view, detailId]);

  /* ---------- Handlers ---------- */

  const goToCreate = useCallback(() => {
    setView("create");
    setSearchParams({});
  }, [setSearchParams]);

  const goToList = useCallback(() => {
    setView("list");
    setDetailId(null);
    setDetailReimb(null);
    setDetailInvoices([]);
    setDetailAttachments([]);
    setSearchParams({});
    // Refresh list
    reimbursementApi.list().then(setReimbursements).catch(() => {});
  }, [setSearchParams]);

  const goToDetail = useCallback(
    (id: number) => {
      setDetailId(id);
      setView("detail");
      setSearchParams({ detail: String(id) });
    },
    [setSearchParams]
  );

  const toggleInvoice = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleCreate = async () => {
    if (!applicantId) return;
    if (!reason.trim()) {
      setError("报销事由为必填项");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await reimbursementApi.create({
        applicant_id: applicantId,
        applicant_name: applicantName || undefined,
        department: department || undefined,
        period: period || undefined,
        reason: reason.trim(),
        invoice_ids: selectedIds.length > 0 ? selectedIds : undefined,
      });

      // 创建成功后上传待传附件
      if (pendingFiles.length > 0) {
        setUploadingAttachments(true);
        for (const file of pendingFiles) {
          try {
            await reimbursementApi.uploadAttachment(created.id, file);
          } catch (e) {
            console.error("附件上传失败:", file.name, e);
          }
        }
        setUploadingAttachments(false);
        setPendingFiles([]);
      }

      const list = await reimbursementApi.list();
      setReimbursements(list);
      goToDetail(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const handleSubmit = async (id: number) => {
    setSubmitting(true);
    setError(null);
    try {
      await reimbursementApi.submit(id);
      const updated = await reimbursementApi.detail(id);
      setDetailReimb(updated);
      const list = await reimbursementApi.list();
      setReimbursements(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleWithdraw = async (id: number) => {
    if (!window.confirm("确定要撤回该报销单吗？撤回后将恢复为草稿状态，可继续编辑。")) return;
    setWithdrawing(true);
    setError(null);
    try {
      await reimbursementApi.withdraw(id);
      const updated = await reimbursementApi.detail(id);
      setDetailReimb(updated);
      const list = await reimbursementApi.list();
      setReimbursements(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "撤回失败");
    } finally {
      setWithdrawing(false);
    }
  };

  const handleGenerateReport = async (id: number) => {
    setGeneratingReport(true);
    setError(null);
    try {
      await reportApi.generate(id);
      const updated = await reimbursementApi.detail(id);
      setDetailReimb(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setGeneratingReport(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await reimbursementApi.delete(deleteTarget.id);
      const list = await reimbursementApi.list();
      setReimbursements(list);
      // 如果在详情视图删除，返回列表
      if (view === "detail" && detailId === deleteTarget.id) {
        goToList();
      }
      setDeleteTarget(null);
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "删除失败，请稍后重试");
    } finally {
      setDeleting(false);
    }
  };

  const availableInvoices = useMemo(() => {
    return allInvoices.filter(
      (inv) =>
        (inv.is_nonstandard
          ? inv.status === "CONFIRMED"
          : inv.verify_status === "VALID") &&
        inv.duplicate_status === "UNIQUE" &&
        !inv.reimbursement_id
    );
  }, [allInvoices]);

  const selectedTotal = useMemo(() => {
    return availableInvoices
      .filter((inv) => selectedIds.includes(inv.id))
      .reduce(
        (sum, inv) => sum + parseFloat(inv.total_with_tax || "0"),
        0
      );
  }, [availableInvoices, selectedIds]);

  const filteredReimbs = useMemo(() => {
    if (statusFilter === "all") return reimbursements;
    return reimbursements.filter((r) => r.status === statusFilter);
  }, [reimbursements, statusFilter]);

  const hasReportFiles = (r: Reimbursement | null) =>
    !!r && !!(r.excel_path || r.pdf_path || r.zip_path);

  const reportFileTypes = [
    {
      key: "xlsx",
      label: "Excel 明细表",
      desc: "发票明细、金额汇总、分类统计",
      icon: FileXls,
      color: "text-emerald-600",
      bg: "bg-emerald-50",
    },
    {
      key: "pdf",
      label: "PDF 报销单",
      desc: "格式化报销申请单，含发票明细",
      icon: FileText,
      color: "text-rose-600",
      bg: "bg-rose-50",
    },
    {
      key: "zip",
      label: "ZIP 完整包",
      desc: "原始发票图片 + Excel + PDF 打包",
      icon: FileZip,
      color: "text-amber-600",
      bg: "bg-amber-50",
    },
  ];

  /* ---------- LIST VIEW ---------- */

  if (view === "list") {
    return (
      <>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">
              报销单管理
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              创建报销单、关联发票、生成报表并下载
            </p>
          </div>
          <button
            onClick={goToCreate}
            className="flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white transition-all hover:bg-brand-700 active:scale-[0.98]"
          >
            <Plus size={18} weight="bold" />
            新建报销单
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
            <Warning size={18} />
            {error}
          </div>
        )}

        {/* Status filter tabs */}
        <div className="flex gap-2">
          {statusTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setStatusFilter(tab.key)}
              className={`rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors ${
                statusFilter === tab.key
                  ? "bg-brand-600 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Table */}
        {loading ? (
          <TableSkeleton rows={5} />
        ) : filteredReimbs.length === 0 ? (
          <div className="rounded-2xl border border-slate-200/60 bg-white">
            <EmptyState
              icon={<Stack size={28} className="text-slate-300" />}
              title="暂无报销单"
              description="点击「新建报销单」选择发票并创建"
              action={
                <button
                  onClick={goToCreate}
                  className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700"
                >
                  <Plus size={16} weight="bold" />
                  新建报销单
                </button>
              }
            />
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-slate-200/60 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
                  <th className="px-4 py-3 font-medium">序号</th>
                  <th className="px-4 py-3 font-medium">申请人</th>
                  <th className="px-4 py-3 font-medium">部门</th>
                  <th className="px-4 py-3 font-medium">期间</th>
                  <th className="px-4 py-3 font-medium">金额</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">创建时间</th>
                  <th className="px-4 py-3 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {filteredReimbs.map((r, i) => (
                  <motion.tr
                    key={r.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      delay: i * 0.04,
                      type: "spring",
                      stiffness: 120,
                      damping: 20,
                    }}
                    onClick={() => goToDetail(r.id)}
                    className="cursor-pointer transition-colors hover:bg-slate-50"
                  >
                    <td className="px-4 py-3 font-mono text-xs text-slate-400">
                      {i + 1}
                    </td>
                    <td className="px-4 py-3 text-slate-700">
                      {r.applicant_name || r.applicant_id}
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {r.department || "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {r.period || "—"}
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-900">
                      {r.total_amount != null
                        ? `¥${r.total_amount.toLocaleString("zh-CN", {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <ReimbStatusBadge status={r.status} />
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">
                      {r.created_at
                        ? new Date(r.created_at).toLocaleDateString("zh-CN")
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex items-center justify-center gap-1">
                        {r.status === "SUBMITTED" && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleWithdraw(r.id);
                            }}
                            disabled={withdrawing}
                            className="inline-flex items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-amber-50 hover:text-amber-600"
                            title="撤回报销单"
                          >
                            <ArrowUUpLeft size={16} />
                          </button>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteError(null);
                            setDeleteTarget(r);
                          }}
                          className="inline-flex items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-600"
                          title="删除报销单"
                        >
                          <Trash size={16} />
                        </button>
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <DeleteConfirmModal
        target={deleteTarget}
        deleting={deleting}
        deleteError={deleteError}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </>
  );
  }

  /* ---------- CREATE VIEW ---------- */

  if (view === "create") {
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <button
            onClick={goToList}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            aria-label="返回"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">
              新建报销单
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              选择发票并填写申请人信息，系统将自动汇总金额
            </p>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
            <Warning size={18} />
            {error}
          </div>
        )}

        {/* Invoice selection */}
        <div className="rounded-2xl border border-slate-200/60 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-base font-semibold text-slate-700">
              选择发票
            </h2>
            {selectedIds.length > 0 && (
              <span className="text-sm text-slate-500">
                已选 {selectedIds.length} 张 · 合计 ¥
                {selectedTotal.toLocaleString("zh-CN", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            )}
          </div>

          {allInvoices.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
              暂无发票记录
            </p>
          ) : availableInvoices.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
              没有可关联的发票（标准发票需验真通过、非标票据需审核通过，均需查重唯一且未关联其他报销单）
            </p>
          ) : (
            <div className="max-h-[360px] space-y-1.5 overflow-y-auto">
              {availableInvoices.map((inv) => {
                const isSelected = selectedIds.includes(inv.id);
                return (
                  <label
                    key={inv.id}
                    className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition-colors ${
                      isSelected
                        ? "border-brand-300 bg-brand-50"
                        : "border-slate-100 hover:bg-slate-50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleInvoice(inv.id)}
                      className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-slate-400">
                          #{inv.id}
                        </span>
                        <span className="truncate text-sm font-medium text-slate-700">
                          {inv.seller_name || "未知销方"}
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-3">
                        <span className="text-xs text-slate-400">
                          {inv.issue_date || "—"}
                        </span>
                        <CategoryBadge category={inv.fee_category} subcategory={inv.fee_subcategory} />
                        <StatusBadge status={inv.status} />
                        <VerifyBadge status={inv.verify_status} />
                        <DuplicateBadge status={inv.duplicate_status} />
                      </div>
                    </div>
                    <span className="font-medium text-slate-900">
                      {inv.total_with_tax
                        ? `¥${inv.total_with_tax}`
                        : "—"}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        {/* Applicant form */}
        <div className="space-y-4 rounded-2xl border border-slate-200/60 bg-white p-5">
          <h2 className="font-display text-base font-semibold text-slate-700">
            申请人信息
          </h2>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">
                申请人 ID
              </label>
              <input
                type="text"
                value={applicantId}
                onChange={(e) => setApplicantId(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white"
                placeholder="企业微信 UserID"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">
                申请人姓名
              </label>
              <input
                type="text"
                value={applicantName}
                onChange={(e) => setApplicantName(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white"
                placeholder="选填"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">
                部门
              </label>
              <input
                type="text"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white"
                placeholder="选填"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">
                报销期间
              </label>
              <input
                type="month"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white"
              />
            </div>
          </div>
        </div>

        {/* Reimbursement reason */}
        <div className="space-y-2 rounded-2xl border border-slate-200/60 bg-white p-5">
          <label className="text-sm font-medium text-slate-700">
            报销事由 <span className="text-rose-500">*</span>
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white"
            placeholder="例如：XX项目差旅费、部门日常办公采购等"
          />
          <p className="text-xs text-slate-400">
            简要说明本次报销的事由及补充说明，将显示在报表中
          </p>
        </div>

        {/* Attachments */}
        <div className="space-y-3 rounded-2xl border border-slate-200/60 bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-base font-semibold text-slate-700">
              附件
            </h2>
            {pendingFiles.length > 0 && (
              <span className="text-sm text-slate-500">
                已选 {pendingFiles.length} 个文件
              </span>
            )}
          </div>
          <div
            onClick={() => fileInputRef.current?.click()}
            className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-200 bg-slate-50/50 py-8 transition-colors hover:border-brand-300 hover:bg-brand-50/30"
          >
            <Paperclip size={28} className="text-slate-300" />
            <p className="text-sm text-slate-500">
              点击选择附件文件
            </p>
            <p className="text-xs text-slate-400">
              支持图片/PDF/Office/压缩包，单文件最大 20MB
            </p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files || []);
                setPendingFiles((prev) => [...prev, ...files]);
                e.target.value = "";
              }}
            />
          </div>
          {pendingFiles.length > 0 && (
            <div className="space-y-1.5">
              {pendingFiles.map((file, i) => (
                <div
                  key={`${file.name}-${i}`}
                  className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2"
                >
                  <Paperclip size={16} className="shrink-0 text-slate-400" />
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-sm text-slate-700">{file.name}</p>
                    <p className="text-xs text-slate-400">
                      {(file.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setPendingFiles((prev) => prev.filter((_, idx) => idx !== i));
                    }}
                    className="shrink-0 rounded-md p-1 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-600"
                  >
                    <XCircle size={16} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Summary & submit */}
        <div className="flex items-center justify-between rounded-2xl border border-brand-200 bg-brand-50/50 p-5">
          <div>
            <p className="text-sm text-slate-500">报销总金额</p>
            <p className="font-display text-2xl font-bold text-slate-900">
              ¥
              {selectedTotal.toLocaleString("zh-CN", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </p>
          </div>
          <button
            onClick={handleCreate}
            disabled={creating || uploadingAttachments || !applicantId || !reason.trim()}
            className="flex items-center gap-2 rounded-xl bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition-all hover:bg-brand-700 disabled:opacity-50 active:scale-[0.98]"
          >
            {creating || uploadingAttachments ? (
              <>
                <Spinner size={18} className="animate-spin" />
                {uploadingAttachments ? "上传附件中..." : "创建中..."}
              </>
            ) : (
              <>
                <CheckCircle size={18} weight="bold" />
                创建报销单
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  /* ---------- DETAIL VIEW ---------- */

  const reimb = detailReimb;
  const showReportFiles = hasReportFiles(reimb);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={goToList}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          aria-label="返回"
        >
          <ArrowLeft size={20} />
        </button>
        <div className="flex-1">
          <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">
            报销单 #{reimb?.id ?? detailId}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            查看详情、生成报表并提交
          </p>
        </div>
        {reimb && reimb.status === "DRAFT" && (
          <button
            onClick={() => {
              setDeleteError(null);
              setDeleteTarget(reimb);
            }}
            className="flex items-center gap-2 rounded-xl border border-rose-200 bg-white px-4 py-2 text-sm font-medium text-rose-600 transition-colors hover:bg-rose-50"
          >
            <Trash size={16} />
            删除报销单
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
          <Warning size={18} />
          {error}
        </div>
      )}

      {detailLoading || !reimb ? (
        <div className="space-y-4">
          <div className="h-48 animate-pulse rounded-2xl bg-slate-200/50" />
          <div className="h-32 animate-pulse rounded-2xl bg-slate-200/50" />
        </div>
      ) : (
        <>
          {/* Info card */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-2xl border border-slate-200/60 bg-white p-6"
          >
            <div className="mb-4 flex items-center justify-between">
              <ReimbStatusBadge status={reimb.status} />
              <span className="text-xs text-slate-400">
                创建于 {reimb.created_at
                  ? new Date(reimb.created_at).toLocaleString("zh-CN")
                  : "—"}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <InfoRow
                icon={<User size={16} className="text-slate-500" />}
                label="申请人"
                value={reimb.applicant_name || reimb.applicant_id}
              />
              <InfoRow
                icon={<Building size={16} className="text-slate-500" />}
                label="部门"
                value={reimb.department || "—"}
              />
              <InfoRow
                icon={<CalendarBlank size={16} className="text-slate-500" />}
                label="报销期间"
                value={reimb.period || "—"}
              />
              <InfoRow
                icon={<CurrencyCny size={16} className="text-slate-500" />}
                label="报销总金额"
                value={
                  reimb.total_amount != null
                    ? `¥${reimb.total_amount.toLocaleString("zh-CN", {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}`
                    : "—"
                }
              />
            </div>
            {reimb.reason && (
              <div className="mt-4 flex items-start gap-3 border-t border-slate-100 pt-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100">
                  <NotePencil size={16} className="text-slate-500" />
                </div>
                <div className="flex-1">
                  <p className="text-xs text-slate-400">报销事由</p>
                  <p className="text-sm font-medium text-slate-800 whitespace-pre-wrap">{reimb.reason}</p>
                </div>
              </div>
            )}
          </motion.div>

          {/* Action section: submit */}
          {reimb.status === "DRAFT" && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50/50 p-4"
            >
              <Clock size={20} className="text-amber-600" />
              <span className="flex-1 text-sm text-amber-800">
                该报销单为草稿状态，可生成报表确认无误后提交
              </span>
              <button
                onClick={() => handleSubmit(reimb.id)}
                disabled={submitting}
                className="flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-amber-700 disabled:opacity-50"
              >
                {submitting ? (
                  <Spinner size={16} className="animate-spin" />
                ) : (
                  <PaperPlaneTilt size={16} weight="bold" />
                )}
                提交报销单
              </button>
            </motion.div>
          )}

          {/* Action section: withdraw */}
          {reimb.status === "SUBMITTED" && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3 rounded-2xl border border-blue-200 bg-blue-50/50 p-4"
            >
              <ArrowUUpLeft size={20} className="text-blue-600" />
              <span className="flex-1 text-sm text-blue-800">
                该报销单已提交，可撤回为草稿继续编辑
              </span>
              <button
                onClick={() => handleWithdraw(reimb.id)}
                disabled={withdrawing}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-blue-700 disabled:opacity-50"
              >
                {withdrawing ? (
                  <Spinner size={16} className="animate-spin" />
                ) : (
                  <ArrowUUpLeft size={16} weight="bold" />
                )}
                撤回报销单
              </button>
            </motion.div>
          )}

          {/* Report generation & download */}
          <div className="rounded-2xl border border-slate-200/60 bg-white p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-display text-base font-semibold text-slate-700">
                报表
              </h2>
              {!showReportFiles && (
                <button
                  onClick={() => handleGenerateReport(reimb.id)}
                  disabled={generatingReport}
                  className="flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
                >
                  {generatingReport ? (
                    <>
                      <Spinner size={16} className="animate-spin" />
                      生成中...
                    </>
                  ) : (
                    <>
                      <FileText size={16} />
                      生成报表
                    </>
                  )}
                </button>
              )}
            </div>

            {showReportFiles ? (
              <div className="grid gap-3">
                {reportFileTypes.map((ft, i) => {
                  const Icon = ft.icon;
                  const url = reportApi.downloadUrl(reimb.id, ft.key);
                  return (
                    <motion.a
                      key={ft.key}
                      href={url}
                      download
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.08 }}
                      className="group flex items-center gap-4 rounded-xl border border-slate-200/60 p-4 transition-colors hover:border-brand-300 hover:bg-slate-50"
                    >
                      <div
                        className={`flex h-10 w-10 items-center justify-center rounded-lg ${ft.bg}`}
                      >
                        <Icon size={20} className={ft.color} />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-slate-800">
                          {ft.label}
                        </p>
                        <p className="text-xs text-slate-400">{ft.desc}</p>
                      </div>
                      <DownloadSimple
                        size={18}
                        className="text-slate-300 group-hover:text-brand-600"
                      />
                    </motion.a>
                  );
                })}
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-slate-400">
                {generatingReport
                  ? "正在生成报表..."
                  : "暂无报表，点击「生成报表」创建"}
              </p>
            )}
          </div>

          {/* Linked invoices */}
          <div className="rounded-2xl border border-slate-200/60 bg-white">
            <div className="border-b border-slate-100 px-5 py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Receipt size={18} className="text-slate-400" />
                  <h2 className="font-display text-base font-semibold text-slate-700">
                    关联发票
                  </h2>
                  <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                    {detailInvoices.length} 张
                  </span>
                </div>
                {reimb.status === "DRAFT" && !showAddInvoice && (
                  <button
                    onClick={() => {
                      setShowAddInvoice(true);
                      setAddInvoiceIds([]);
                    }}
                    className="flex items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 transition-colors hover:bg-brand-100"
                  >
                    <Plus size={14} weight="bold" />
                    追加发票
                  </button>
                )}
              </div>
            </div>

            {/* 追加发票面板 */}
            {showAddInvoice && (
              <div className="border-b border-slate-100 bg-slate-50/50 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-sm text-slate-600">选择要追加的发票</p>
                  <div className="flex items-center gap-2">
                    {addInvoiceIds.length > 0 && (
                      <span className="text-xs text-brand-600">
                        已选 {addInvoiceIds.length} 张
                      </span>
                    )}
                    <button
                      onClick={async () => {
                        if (addInvoiceIds.length === 0) {
                          setShowAddInvoice(false);
                          return;
                        }
                        setAddingInvoices(true);
                        try {
                          await reimbursementApi.linkInvoices(reimb.id, addInvoiceIds);
                          const [updated, invs] = await Promise.all([
                            reimbursementApi.detail(reimb.id),
                            invoiceApi.list(),
                          ]);
                          setDetailReimb(updated);
                          setDetailInvoices(invs.filter((i) => i.reimbursement_id === reimb.id));
                          setAllInvoices(invs);
                          setShowAddInvoice(false);
                        } catch (e) {
                          setError(e instanceof Error ? e.message : "追加发票失败");
                        } finally {
                          setAddingInvoices(false);
                        }
                      }}
                      disabled={addingInvoices}
                      className="flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
                    >
                      {addingInvoices ? (
                        <Spinner size={14} className="animate-spin" />
                      ) : (
                        <Plus size={14} weight="bold" />
                      )}
                      {addingInvoices ? "追加中..." : "确认追加"}
                    </button>
                    <button
                      onClick={() => setShowAddInvoice(false)}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-200"
                    >
                      取消
                    </button>
                  </div>
                </div>
                <div className="max-h-[240px] space-y-1.5 overflow-y-auto">
                  {allInvoices
                    .filter(
                      (inv) =>
                        (inv.is_nonstandard
                          ? inv.status === "CONFIRMED"
                          : inv.verify_status === "VALID") &&
                        inv.duplicate_status === "UNIQUE" &&
                        (!inv.reimbursement_id ||
                          inv.reimbursement_id === reimb.id)
                    )
                    .filter((inv) => !detailInvoices.some((di) => di.id === inv.id))
                    .map((inv) => {
                      const isSelected = addInvoiceIds.includes(inv.id);
                      return (
                        <label
                          key={inv.id}
                          className={`flex cursor-pointer items-center gap-3 rounded-lg border p-2.5 transition-colors ${
                            isSelected
                              ? "border-brand-300 bg-brand-50"
                              : "border-slate-200 bg-white hover:bg-slate-50"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() =>
                              setAddInvoiceIds((prev) =>
                                prev.includes(inv.id)
                                  ? prev.filter((x) => x !== inv.id)
                                  : [...prev, inv.id]
                              )
                            }
                            className="h-3.5 w-3.5 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                          />
                          <div className="flex-1 min-w-0">
                            <span className="text-sm text-slate-700">
                              {inv.seller_name || "未知销方"}
                            </span>
                            <span className="ml-2 text-xs text-slate-400">
                              {inv.issue_date || ""}
                            </span>
                          </div>
                          <span className="text-sm font-medium text-slate-900">
                            {inv.total_with_tax ? `¥${inv.total_with_tax}` : "—"}
                          </span>
                        </label>
                      );
                    })}
                  {allInvoices.filter(
                    (inv) =>
                      inv.verify_status === "VALID" &&
                      inv.duplicate_status === "UNIQUE" &&
                      (!inv.reimbursement_id || inv.reimbursement_id === reimb.id) &&
                      !detailInvoices.some((di) => di.id === inv.id),
                  ).length === 0 && (
                    <p className="py-4 text-center text-xs text-slate-400">
                      没有可追加的发票（标准发票需验真通过、非标票据需审核通过，均需查重唯一且未关联其他报销单）
                    </p>
                  )}
                </div>
              </div>
            )}

            {detailInvoices.length === 0 && !showAddInvoice ? (
              <p className="py-8 text-center text-sm text-slate-400">
                暂无关联发票
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-50 text-left text-xs text-slate-400">
                    <th className="px-5 py-3 font-medium">编号</th>
                    <th className="px-5 py-3 font-medium">销方</th>
                    <th className="px-5 py-3 font-medium">金额</th>
                    <th className="px-5 py-3 font-medium">分类</th>
                    <th className="px-5 py-3 font-medium">查重</th>
                    {reimb.status === "DRAFT" && (
                      <th className="px-5 py-3 text-center font-medium">操作</th>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {detailInvoices.map((inv) => (
                    <tr key={inv.id} className="hover:bg-slate-50/50">
                      <td className="px-5 py-3 font-mono text-xs text-slate-400">
                        #{inv.id}
                      </td>
                      <td className="max-w-[200px] truncate px-5 py-3 text-slate-700">
                        {inv.seller_name || "—"}
                      </td>
                      <td className="px-5 py-3 font-medium text-slate-900">
                        {inv.total_with_tax
                          ? `¥${inv.total_with_tax}`
                          : "—"}
                      </td>
                      <td className="px-5 py-3">
                        <CategoryBadge category={inv.fee_category} subcategory={inv.fee_subcategory} />
                      </td>
                      <td className="px-5 py-3">
                        <VerifyBadge status={inv.verify_status} />
                      </td>
                      <td className="px-5 py-3">
                        <DuplicateBadge status={inv.duplicate_status} />
                      </td>
                      {reimb.status === "DRAFT" && (
                        <td className="px-5 py-3 text-center">
                          <button
                            onClick={async () => {
                              setRemovingInvoiceId(inv.id);
                              try {
                                await reimbursementApi.unlinkInvoice(reimb.id, inv.id);
                                const [updated, invs] = await Promise.all([
                                  reimbursementApi.detail(reimb.id),
                                  invoiceApi.list(),
                                ]);
                                setDetailReimb(updated);
                                setDetailInvoices(invs.filter((i) => i.reimbursement_id === reimb.id));
                                setAllInvoices(invs);
                              } catch (e) {
                                setError(e instanceof Error ? e.message : "移除失败");
                              } finally {
                                setRemovingInvoiceId(null);
                              }
                            }}
                            disabled={removingInvoiceId === inv.id}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-rose-600 transition-colors hover:bg-rose-50 disabled:opacity-50"
                            title="移除关联"
                          >
                            {removingInvoiceId === inv.id ? (
                              <Spinner size={12} className="animate-spin" />
                            ) : (
                              <Minus size={12} />
                            )}
                            移除
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Attachments */}
          <div className="rounded-2xl border border-slate-200/60 bg-white">
            <div className="border-b border-slate-100 px-5 py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Paperclip size={18} className="text-slate-400" />
                  <h2 className="font-display text-base font-semibold text-slate-700">
                    附件
                  </h2>
                  <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                    {detailAttachments.length} 个
                  </span>
                </div>
                {reimb.status === "DRAFT" && (
                  <>
                    <button
                      onClick={() => detailFileInputRef.current?.click()}
                      disabled={uploadingAttachment}
                      className="flex items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 transition-colors hover:bg-brand-100 disabled:opacity-50"
                    >
                      {uploadingAttachment ? (
                        <Spinner size={14} className="animate-spin" />
                      ) : (
                        <Plus size={14} weight="bold" />
                      )}
                      上传附件
                    </button>
                    <input
                      ref={detailFileInputRef}
                      type="file"
                      className="hidden"
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        setUploadingAttachment(true);
                        try {
                          await reimbursementApi.uploadAttachment(reimb.id, file);
                          const updated = await reimbursementApi.detail(reimb.id);
                          setDetailReimb(updated);
                          setDetailAttachments(updated.attachments || []);
                        } catch (err) {
                          setError(err instanceof Error ? err.message : "附件上传失败");
                        } finally {
                          setUploadingAttachment(false);
                          e.target.value = "";
                        }
                      }}
                    />
                  </>
                )}
              </div>
            </div>
            {detailAttachments.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-400">
                暂无附件
              </p>
            ) : (
              <div className="divide-y divide-slate-50">
                {detailAttachments.map((att) => (
                  <div key={att.id} className="flex items-center gap-3 px-5 py-3">
                    <Paperclip size={18} className="shrink-0 text-slate-400" />
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-sm font-medium text-slate-700">
                        {att.filename}
                      </p>
                      <p className="text-xs text-slate-400">
                        {(att.file_size / 1024).toFixed(1)} KB
                        {att.created_at && (
                          <span className="ml-2">
                            {new Date(att.created_at).toLocaleString("zh-CN")}
                          </span>
                        )}
                      </p>
                    </div>
                    <button
                      onClick={() => {
                        reimbursementApi.downloadAttachment(
                          reimb.id,
                          att.id,
                          att.filename
                        );
                      }}
                      className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-brand-50 hover:text-brand-600"
                      title="下载"
                    >
                      <DownloadSimple size={18} />
                    </button>
                    {reimb.status === "DRAFT" && (
                      <button
                        onClick={async () => {
                          setDeletingAttachmentId(att.id);
                          try {
                            await reimbursementApi.deleteAttachment(reimb.id, att.id);
                            const updated = await reimbursementApi.detail(reimb.id);
                            setDetailReimb(updated);
                            setDetailAttachments(updated.attachments || []);
                          } catch (err) {
                            setError(err instanceof Error ? err.message : "删除附件失败");
                          } finally {
                            setDeletingAttachmentId(null);
                          }
                        }}
                        disabled={deletingAttachmentId === att.id}
                        className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50"
                        title="删除"
                      >
                        {deletingAttachmentId === att.id ? (
                          <Spinner size={16} className="animate-spin" />
                        ) : (
                          <Trash size={16} />
                        )}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
      <DeleteConfirmModal
        target={deleteTarget}
        deleting={deleting}
        deleteError={deleteError}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}

/* ---------- Delete confirmation modal ---------- */

function DeleteConfirmModal({
  target,
  deleting,
  deleteError,
  onCancel,
  onConfirm,
}: {
  target: Reimbursement | null;
  deleting: boolean;
  deleteError: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!target) return null;

  return (
    <AnimatePresence>
      {target && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm"
          onClick={() => !deleting && onCancel()}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ type: "spring", damping: 25, stiffness: 400 }}
            className="mx-4 w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-rose-50">
                <Warning size={22} className="text-rose-600" />
              </div>
              <div className="flex-1">
                <h3 className="font-display text-lg font-semibold text-slate-900">
                  删除报销单
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  确定要删除报销单{" "}
                  <span className="font-mono font-medium text-slate-700">
                    #{target.id}
                  </span>{" "}
                  吗？关联的发票将被解除关联（不会被删除），已生成的报表文件将一并清除。
                </p>
              </div>
            </div>

            {deleteError && (
              <div className="mt-4 flex items-start gap-2 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">
                <XCircle size={18} className="mt-0.5 shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                onClick={() => !deleting && onCancel()}
                disabled={deleting}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={onConfirm}
                disabled={deleting}
                className="flex items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {deleting ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    删除中...
                  </>
                ) : (
                  <>
                    <Trash size={16} />
                    确认删除
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
