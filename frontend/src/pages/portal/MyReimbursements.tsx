import { useEffect, useState, useCallback, useRef } from "react";
import { portalApi, reimbursementApi } from "../../api/client";
import { ConfirmModal } from "../../components/ConfirmModal";
import type {
  PortalReimbursement,
  PortalReimbursementDetail,
  Invoice,
} from "../../types";
import {
  Stack,
  Spinner,
  PaperPlaneRight,
  Plus,
  WarningCircle,
  Trash,
  X,
  Warning,
  ArrowLeft,
  PencilSimple,
  Check,
  LinkBreak,
  Link as LinkIcon,
  CaretDown,
  CalendarBlank,
  FileText,
  Receipt,
  Paperclip,
  DownloadSimple,
  ArrowUUpLeft,
  Lock,
  CalendarStar,
  ListChecks,
  Coins,
  CurrencyCny,
  Sparkle,
} from "@phosphor-icons/react";
import {
  weekdayName,
  dayTypeLabel,
  dayTypeBadge,
  formatCycleRange,
} from "../Reimbursements/shared";

const statusLabels: Record<string, { label: string; color: string }> = {
  DRAFT: { label: "已关联", color: "bg-success-100 text-success-700" },
  SUBMITTED: { label: "已关联", color: "bg-success-100 text-success-700" },
  REVIEWED: { label: "已关联", color: "bg-success-100 text-success-700" },
  REIMBURSED: { label: "已报销", color: "bg-emerald-100 text-emerald-700" },
};

type View = "list" | "detail";

export function PortalMyReimbursements() {
  const [view, setView] = useState<View>("list");
  const [reimbursements, setReimbursements] = useState<PortalReimbursement[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<number | null>(null);
  const [withdrawing, setWithdrawing] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<PortalReimbursement | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [detailId, setDetailId] = useState<number | null>(null);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    portalApi
      .myReimbursements()
      .then(setReimbursements)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, []);

  const handleSubmit = async (id: number) => {
    setSubmitting(id);
   setError("");
    try {
      await portalApi.submitReimbursement(id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setSubmitting(null);
    }
  };

  const handleWithdraw = async (id: number) => {
    if (!window.confirm("确定要撤回该报销单吗？撤回后将恢复为草稿状态，可继续编辑。")) return;
    setWithdrawing(id);
    setError("");
    try {
      await portalApi.withdrawReimbursement(id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "撤回失败");
    } finally {
      setWithdrawing(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await portalApi.deleteReimbursement(deleteTarget.id);
      setDeleteTarget(null);
      load();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  const goDetail = (id: number) => {
    setDetailId(id);
    setView("detail");
  };

  // 生成我的报销单（同一周期已有则后端返回原单，幂等）
  const handleGenerate = async () => {
    setGenerating(true);
    setError("");
    try {
      const res = await reimbursementApi.generate();
      // 跳转到该报销单的详情视图（页面内部用 state 切换 view，无独立路由）
      goDetail(res.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  };

  // ===== 列表视图 =====
  if (view === "list") {
    if (loading) {
      return (
        <div className="flex items-center justify-center py-20">
          <Spinner size={24} className="animate-spin text-primary-700" />
        </div>
      );
    }

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-xl font-bold text-foreground">
              我的报销单
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              查看您的报销单，报销单由系统按周期自动生成与归集
            </p>
          </div>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="flex items-center gap-1.5 rounded-lg bg-primary-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-800 disabled:opacity-50"
          >
            {generating ? (
              <Spinner size={16} className="animate-spin" />
            ) : (
              <Sparkle size={16} weight="fill" />
            )}
            {generating ? "生成中..." : "生成我的报销单"}
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl bg-error-50 px-4 py-3 text-sm text-error-700">
            <WarningCircle size={18} weight="fill" />
            {error}
            <button onClick={() => setError("")} className="ml-auto text-error-500 hover:text-error-700">
              <X size={16} />
            </button>
          </div>
        )}

        {reimbursements.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-border bg-background py-16 text-center">
            <Stack size={48} className="text-muted" />
            <p className="mt-3 text-sm text-muted-foreground">暂无报销单</p>
          </div>
        ) : (
          <div className="space-y-3">
            {reimbursements.map((r) => {
              const st = statusLabels[r.status] || { label: r.status, color: "bg-muted text-foreground/70" };
              return (
                <div
                  key={r.id}
                  className="cursor-pointer rounded-2xl border border-border bg-background p-4 shadow-sm transition-all hover:shadow-md hover:border-primary-200 sm:p-5"
                  onClick={() => goDetail(r.id)}
                >
                  {/* 第一行：编号 + 状态 + 金额（手机端换行） */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-foreground">
                        报销单 #{r.id}
                      </p>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${st.color}`}>
                        {st.label}
                      </span>
                      {r.is_cycle_locked && (
                        <span className="inline-flex shrink-0 items-center gap-0.5 text-xs text-error-600">
                          <Lock size={10} />
                          已封账
                        </span>
                      )}
                    </div>
                    <p className="shrink-0 font-display text-base font-bold text-foreground">
                      ¥{r.total_amount?.toLocaleString("zh-CN", { minimumFractionDigits: 2 }) ?? "0.00"}
                    </p>
                  </div>

                  {/* 第二行：事由 + 周期范围（手机端换行） */}
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span className="truncate">{r.reason || "未填写"}</span>
                    {r.cycle_start && r.cycle_end && (
                      <span className="text-gray-600">
                        {r.cycle_start} ~ {r.cycle_end}
                      </span>
                    )}
                    {r.cycle_key && <span className="text-primary-600">{r.cycle_key}</span>}
                    <span>{r.invoice_count} 张发票</span>
                  </div>

                  {/* 第三行：操作按钮（手机端右对齐） */}
                  <div className="mt-3 flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                    {r.status === "SUBMITTED" && (
                      <button
                        onClick={() => handleWithdraw(r.id)}
                        disabled={withdrawing === r.id}
                        className="flex items-center gap-1 rounded-lg bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100 disabled:opacity-50"
                      >
                        {withdrawing === r.id ? <Spinner size={14} className="animate-spin" /> : <ArrowUUpLeft size={14} />}
                        撤回
                      </button>
                    )}
                    {r.status === "DRAFT" && !r.is_cycle_locked && (
                      <button
                        onClick={() => handleSubmit(r.id)}
                        disabled={submitting === r.id}
                        className="flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
                        title="提交报销单（提交后仍可撤回至草稿）"
                      >
                        {submitting === r.id ? <Spinner size={14} className="animate-spin" /> : <PaperPlaneRight size={14} />}
                        提交
                      </button>
                    )}
                    {r.status === "DRAFT" && !r.is_cycle_locked && (
                      <button
                        onClick={() => setDeleteTarget(r)}
                        className="flex items-center gap-1 rounded-lg bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-100"
                        title="删除报销单（仅草稿状态可删）"
                      >
                        <Trash size={14} />
                        删除
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* 删除确认弹窗 */}
        {deleteTarget && (
          <DeleteConfirmModal
            target={deleteTarget}
            deleting={deleting}
            deleteError={deleteError}
            onCancel={() => setDeleteTarget(null)}
            onConfirm={handleDelete}
          />
        )}
      </div>
    );
  }

  // ===== 详情视图 =====
  if (view === "detail" && detailId) {
    return (
      <ReimbursementDetail
        reimbursementId={detailId}
        onBack={() => { setView("list"); setDetailId(null); load(); }}
        onUpdate={() => load()}
      />
    );
  }

  return null;
}

// ===== 删除确认弹窗 =====

function DeleteConfirmModal({
  target,
  deleting,
  deleteError,
  onCancel,
  onConfirm,
}: {
  target: PortalReimbursement;
  deleting: boolean;
  deleteError: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <ConfirmModal
      open
      title="删除报销单"
      description="确定要删除以下报销单吗？已关联的发票将被解除关联（发票本身不删除）。此操作不可撤销。"
      confirmText="确认删除"
      variant="danger"
      loading={deleting}
      error={deleteError}
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      <div className="rounded-xl bg-muted p-3">
        <div className="text-sm font-medium text-foreground">报销单 #{target.id}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {target.reason || "未填写"}
          {target.period && ` · ${target.period}`}
          {` · ${target.invoice_count} 张发票`}
          {target.total_amount && ` · ¥${target.total_amount.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`}
        </div>
      </div>
    </ConfirmModal>
  );
}

// ===== 报销单详情组件 =====

function ReimbursementDetail({
  reimbursementId,
  onBack,
  onUpdate,
}: {
  reimbursementId: number;
  onBack: () => void;
  onUpdate: () => void;
}) {
  const [detail, setDetail] = useState<PortalReimbursementDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [editReason, setEditReason] = useState("");
  const [editPeriod, setEditPeriod] = useState("");
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  // 报表下载相关
  const [generatingReports, setGeneratingReports] = useState(false);
  const [downloadingReport, setDownloadingReport] = useState<"xlsx" | "pdf" | "zip" | null>(null);
  const [reportError, setReportError] = useState("");

  // 关联发票相关
  const [showLinkPanel, setShowLinkPanel] = useState(false);
  const [availableInvoices, setAvailableInvoices] = useState<Invoice[]>([]);
  const [linkSelectedIds, setLinkSelectedIds] = useState<Set<number>>(new Set());
  const [linking, setLinking] = useState(false);
  const [unlinking, setUnlinking] = useState<number | null>(null);
  // 发票验真开关（False 时放宽过滤：标准发票无需 verify_status=VALID 也可关联）
  const [verifyEnabled, setVerifyEnabled] = useState(true);

  // 附件相关
  const attachmentInputRef = useRef<HTMLInputElement>(null);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [deletingAttachment, setDeletingAttachment] = useState<number | null>(null);

  const [togglingSubsidyDate, setTogglingSubsidyDate] = useState<string | null>(null);

  const loadDetail = useCallback(() => {
    setLoading(true);
    setError("");
    portalApi
      .myReimbursementDetail(reimbursementId)
      .then(setDetail)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [reimbursementId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const isDraft = detail?.status === "DRAFT";
  const isSubmitted = detail?.status === "SUBMITTED";

  const handleStartEdit = () => {
    if (!detail) return;
    setEditReason(detail.reason || "");
    setEditPeriod(detail.period || "");
    setEditMode(true);
  };

  const handleSaveEdit = async () => {
    setSaving(true);
    setError("");
    try {
      await portalApi.updateReimbursement(reimbursementId, {
        reason: editReason,
        period: editPeriod,
      });
      setEditMode(false);
      loadDetail();
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError("");
    try {
      await portalApi.submitReimbursement(reimbursementId);
      loadDetail();
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleWithdraw = async () => {
    if (!window.confirm("确定要撤回该报销单吗？撤回后将恢复为草稿状态，可继续编辑。")) return;
    setWithdrawing(true);
    setError("");
    try {
      await portalApi.withdrawReimbursement(reimbursementId);
      loadDetail();
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "撤回失败");
    } finally {
      setWithdrawing(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    setDeleteError("");
    try {
      await portalApi.deleteReimbursement(reimbursementId);
      onBack();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  const handleGenerateReports = async () => {
    setGeneratingReports(true);
    setReportError("");
    try {
      await portalApi.generateReports(reimbursementId);
      // 刷新详情以更新 excel_path/pdf_path/zip_path
      const updated = await portalApi.myReimbursementDetail(reimbursementId);
      setDetail(updated);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : "报表生成失败");
    } finally {
      setGeneratingReports(false);
    }
  };

  const handleDownloadReport = async (fileType: "xlsx" | "pdf" | "zip") => {
    setDownloadingReport(fileType);
    setReportError("");
    try {
      const token = localStorage.getItem("portal_token");
      const url = portalApi.downloadReportUrl(reimbursementId, fileType);
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => null);
        throw new Error(data?.detail || `下载失败（HTTP ${resp.status}）`);
      }
      const blob = await resp.blob();
      const downloadUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = `reimbursement_${reimbursementId}.${fileType}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(downloadUrl);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : "下载失败");
    } finally {
      setDownloadingReport(null);
    }
  };

  const loadAvailableInvoices = async () => {
    try {
      // 先读验真开关状态（失败时默认 true，按严格规则过滤）
      let verifyEnabledNow = true;
      try {
        const r = await portalApi.getVerifyEnabled();
        verifyEnabledNow = r.verify_enabled;
        setVerifyEnabled(verifyEnabledNow);
      } catch {
        // 接口不可用时保持原行为
      }
      const all = await portalApi.myInvoices();
      // 可关联条件：
      // - 标准发票：
      //   - 验真开关开启：verify_status=VALID（验真通过）+ 查重唯一 + 未关联其他报销单
      //   - 验真开关关闭（账户欠费等场景）：放宽 verify_status 检查，全部非 processing 均可关联，
      //     由管理员人工审核；与后端 _assert_invoice_linkable 规则一致
      // - 非标票据（支付截图/收据等）：已处理完成（非 processing）+ 查重唯一 + 未关联其他报销单
      //   与归集任务规则一致：reviewing/reviewed 都允许关联
      setAvailableInvoices(
        all.filter(
          (inv) =>
            (inv.is_nonstandard
              ? inv.status && inv.status !== "PROCESSING"
              : verifyEnabledNow
                ? inv.verify_status === "VALID"
                : inv.status && inv.status !== "PROCESSING") &&
            inv.duplicate_status === "UNIQUE" &&
            !inv.reimbursement_id
        )
      );
    } catch {
      // ignore
    }
  };

  const toggleLinkInvoice = (id: number) => {
    setLinkSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleLinkInvoices = async () => {
    if (linkSelectedIds.size === 0) return;
    setLinking(true);
    setError("");
    try {
      await portalApi.linkInvoices(reimbursementId, Array.from(linkSelectedIds));
      setLinkSelectedIds(new Set());
      setShowLinkPanel(false);
      loadDetail();
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "关联失败");
    } finally {
      setLinking(false);
    }
  };

  const handleUnlink = async (invoiceId: number) => {
    setUnlinking(invoiceId);
    setError("");
    try {
      await portalApi.unlinkInvoice(reimbursementId, invoiceId);
      loadDetail();
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "移除失败");
    } finally {
      setUnlinking(null);
    }
  };

  const handleUploadAttachment = async (files: FileList) => {
    setUploadingAttachment(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        await portalApi.uploadAttachment(reimbursementId, file);
      }
      loadDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "附件上传失败");
    } finally {
      setUploadingAttachment(false);
    }
  };

  const handleDeleteAttachment = async (attachmentId: number) => {
    setDeletingAttachment(attachmentId);
    setError("");
    try {
      await portalApi.deleteAttachment(reimbursementId, attachmentId);
      loadDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "附件删除失败");
    } finally {
      setDeletingAttachment(null);
    }
  };

  const handleDownloadAttachment = async (attachmentId: number, filename: string) => {
    try {
      await portalApi.downloadAttachment(reimbursementId, attachmentId, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "下载失败");
    }
  };

  const handleToggleSubsidy = async (subsidyDate: string, included: boolean) => {
    setTogglingSubsidyDate(subsidyDate);
    setError("");
    try {
      await portalApi.toggleSubsidy(reimbursementId, subsidyDate, included);
      loadDetail();
      onUpdate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换补贴失败");
    } finally {
      setTogglingSubsidyDate(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size={24} className="animate-spin text-primary-700" />
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="space-y-4">
        <button onClick={onBack} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft size={18} /> 返回列表
        </button>
        <div className="flex items-center gap-2 rounded-xl bg-error-50 px-4 py-3 text-sm text-error-700">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      </div>
    );
  }

  if (!detail) return null;

  const st = statusLabels[detail.status] || { label: detail.status, color: "bg-muted text-foreground/70" };
  const cycleLocked = detail.is_cycle_locked;
  const lockTitle = cycleLocked ? "周期已封账，无法操作" : "";

  return (
    <div className="space-y-6">
      {detail.cycle_start && detail.cycle_end && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg bg-gray-50 p-3">
          <span className="text-sm">周期范围：{detail.cycle_start} ~ {detail.cycle_end}</span>
          {cycleLocked && (
            <span className="inline-flex items-center gap-1 text-sm font-medium text-red-600">
              <Lock size={12} />
              已封账
            </span>
          )}
        </div>
      )}

      {/* 顶部导航 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button onClick={onBack} className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground">
          <ArrowLeft size={18} />
          返回列表
        </button>
        <div className="flex flex-wrap items-center gap-2">
          {isDraft && !editMode && !cycleLocked && (
            <button
              onClick={handleSubmit}
              disabled={submitting}
              title="提交报销单（提交后仍可撤回至草稿）"
              className="flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
            >
              {submitting ? <Spinner size={14} className="animate-spin" /> : <PaperPlaneRight size={14} />}
              提交报销单
            </button>
          )}
          {isDraft && !editMode && (
            <button
              onClick={handleStartEdit}
              disabled={cycleLocked}
              title={lockTitle}
              className="flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground/70 transition-colors hover:bg-muted disabled:opacity-50"
            >
              <PencilSimple size={14} />
              编辑
            </button>
          )}
          {isDraft && !editMode && !cycleLocked && (
            <button
              onClick={() => setDeleteTarget(true)}
              disabled={deleting}
              title="删除报销单（仅草稿状态可删）"
              className="flex items-center gap-1 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
            >
              <Trash size={14} />
              删除
            </button>
          )}
          {isSubmitted && !editMode && (
            <button
              onClick={handleWithdraw}
              disabled={withdrawing || cycleLocked}
              title={lockTitle}
              className="flex items-center gap-1 rounded-lg bg-primary-700 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-800 disabled:opacity-50"
            >
              {withdrawing ? <Spinner size={14} className="animate-spin" /> : <ArrowUUpLeft size={14} />}
              撤回报销单
            </button>
          )}
          {editMode && (
            <>
              <button
                onClick={() => setEditMode(false)}
                disabled={saving || cycleLocked}
                title={lockTitle}
                className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={saving || cycleLocked}
                title={lockTitle}
                className="flex items-center gap-1 rounded-lg bg-primary-700 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-800 disabled:opacity-50"
              >
                {saving ? <Spinner size={14} className="animate-spin" /> : <Check size={14} />}
                保存
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-error-50 px-4 py-3 text-sm text-error-700">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}

      {/* 报销单信息卡片 */}
      <div className="rounded-2xl border border-border/60 bg-background p-4 shadow-sm sm:p-6">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h2 className="font-display text-base font-semibold text-foreground">
            报销单 #{detail.id}
          </h2>
          <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${st.color}`}>
            {st.label}
          </span>
          {detail.cycle_key && (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">
              <CalendarStar size={12} />
              {detail.cycle_key}
            </span>
          )}
          {detail.is_cycle_locked && (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-600">
              <Lock size={12} />
              已封账
            </span>
          )}
          {detail.auto_generated && (
            <span className="shrink-0 rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              自动生成
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
          {/* 报销期间 */}
          <div className="rounded-xl bg-muted p-3">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <CalendarBlank size={14} />
              报销期间
            </div>
            {editMode ? (
              <input
                type="month"
                value={editPeriod}
                onChange={(e) => setEditPeriod(e.target.value)}
                className="mt-1 w-full rounded-lg border border-border bg-background px-2 py-1 text-sm text-foreground/90 outline-none focus:border-primary-400"
              />
            ) : (
              <p className="mt-1 text-sm font-medium text-foreground">{detail.period || "未设置"}</p>
            )}
          </div>

          {/* 报销事由 */}
          <div className="rounded-xl bg-muted p-3 sm:col-span-2">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <FileText size={14} />
              报销事由
            </div>
            {editMode ? (
              <input
                type="text"
                value={editReason}
                onChange={(e) => setEditReason(e.target.value)}
                placeholder="如：7月差旅费报销"
                className="mt-1 w-full rounded-lg border border-border bg-background px-2 py-1 text-sm text-foreground/90 outline-none focus:border-primary-400"
              />
            ) : (
              <p className="mt-1 break-words text-sm font-medium text-foreground">{detail.reason || "未填写"}</p>
            )}
          </div>

          {/* 申请人 */}
          <div className="rounded-xl bg-muted p-3">
            <div className="text-xs text-muted-foreground">申请人</div>
            <p className="mt-1 truncate text-sm font-medium text-foreground">{detail.applicant_name || "—"}</p>
          </div>

          {/* 部门 */}
          <div className="rounded-xl bg-muted p-3">
            <div className="text-xs text-muted-foreground">部门</div>
            <p className="mt-1 truncate text-sm font-medium text-foreground">{detail.department || "—"}</p>
          </div>

          {/* 周期范围 */}
          <div className="rounded-xl bg-muted p-3">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <CalendarStar size={14} />
              周期范围
            </div>
            <p className="mt-1 break-words text-sm font-medium text-foreground">
              {formatCycleRange(detail.cycle_start, detail.cycle_end)}
            </p>
          </div>
        </div>

        {/* 金额明细 */}
        <div className="mt-4 grid grid-cols-1 gap-3 border-t border-border pt-4 sm:grid-cols-3 sm:gap-4">
          <div className="rounded-xl bg-muted p-3">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Receipt size={14} />
              费用合计
            </div>
            <p className="mt-1 font-display text-lg font-bold text-foreground">
              ¥{(detail.expense_total ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="rounded-xl bg-warning-50 p-3">
            <div className="flex items-center gap-1 text-xs text-warning-500">
              <Coins size={14} />
              补贴合计
            </div>
            <p className="mt-1 font-display text-lg font-bold text-warning-700">
              ¥{(detail.subsidy_total ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="rounded-xl bg-primary-50 p-3 ring-1 ring-primary-200">
            <div className="flex items-center gap-1 text-xs text-primary-400">
              <CurrencyCny size={14} />
              报销总额
            </div>
            <p className="mt-1 font-display text-lg font-bold text-primary-700">
              ¥{(detail.total_amount ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>

        {/* 报表下载 */}
        <div className="mt-4 rounded-xl border border-border bg-muted/30 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <FileText size={16} className="shrink-0 text-primary-600" />
              <span className="text-sm font-medium text-foreground">报销单报表</span>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                （Excel 费用清单 / PDF 发票汇总 / ZIP 完整包）
              </span>
            </div>
            <button
              onClick={handleGenerateReports}
              disabled={generatingReports}
              className="flex shrink-0 items-center gap-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground/70 transition-colors hover:bg-muted disabled:opacity-50"
              title="生成或刷新报表包"
            >
              {generatingReports ? <Spinner size={14} className="animate-spin" /> : <Sparkle size={14} />}
              生成报表
            </button>
          </div>
          <p className="mt-1 text-xs text-muted-foreground sm:hidden">
            Excel 费用清单 / PDF 发票汇总 / ZIP 完整包
          </p>
          {reportError && (
            <p className="mt-2 text-xs text-red-600">{reportError}</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={() => handleDownloadReport("xlsx")}
              disabled={!detail.excel_path || downloadingReport === "xlsx"}
              title={detail.excel_path ? "下载 Excel 费用清单" : "尚未生成，请先点「生成报表」"}
              className="flex items-center gap-1 rounded-lg bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {downloadingReport === "xlsx" ? <Spinner size={14} className="animate-spin" /> : <DownloadSimple size={14} />}
              下载 Excel
            </button>
            <button
              onClick={() => handleDownloadReport("pdf")}
              disabled={!detail.pdf_path || downloadingReport === "pdf"}
              title={detail.pdf_path ? "下载 PDF 发票汇总" : "尚未生成，请先点「生成报表」"}
              className="flex items-center gap-1 rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {downloadingReport === "pdf" ? <Spinner size={14} className="animate-spin" /> : <DownloadSimple size={14} />}
              下载 PDF
            </button>
            <button
              onClick={() => handleDownloadReport("zip")}
              disabled={!detail.zip_path || downloadingReport === "zip"}
              title={detail.zip_path ? "下载 ZIP 完整包" : "尚未生成，请先点「生成报表」"}
              className="flex items-center gap-1 rounded-lg bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {downloadingReport === "zip" ? <Spinner size={14} className="animate-spin" /> : <DownloadSimple size={14} />}
              下载 ZIP
            </button>
          </div>
          {!detail.excel_path && !detail.pdf_path && !detail.zip_path && (
            <p className="mt-2 text-xs text-muted-foreground">
              尚未生成报表，请先点上方「生成报表」按钮
            </p>
          )}
        </div>
      </div>

      {/* 费用明细 */}
      {detail.items && detail.items.length > 0 && (
        <div className="rounded-2xl border border-border/60 bg-background p-4 shadow-sm sm:p-6">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <ListChecks size={18} className="text-primary-600" />
            <h2 className="font-display text-sm font-semibold text-foreground/90">费用明细</h2>
            <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              {detail.items.length} 条
            </span>
          </div>
          {/* 移动端卡片列表 */}
          <div className="space-y-2 sm:hidden">
            {detail.items.map((item) => (
              <div key={item.id} className="rounded-lg border border-border/60 bg-muted/30 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-foreground/90">{item.item_date || "—"}</span>
                  <span className="font-display text-sm font-bold text-foreground">
                    ¥{item.amount.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  <span>{weekdayName(item.weekday)}</span>
                  <span>·</span>
                  <span>{item.fee_subcategory || item.fee_category || "—"}</span>
                  {item.is_late_charge && (
                    <span className="inline-flex items-center gap-0.5 rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-600">
                      跨期
                    </span>
                  )}
                </div>
                {item.description && (
                  <p className="mt-1 break-words text-xs text-muted-foreground">{item.description}</p>
                )}
              </div>
            ))}
          </div>
          {/* 桌面端表格 */}
          <div className="hidden overflow-x-auto sm:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">日期</th>
                  <th className="px-3 py-2 font-medium">星期</th>
                  <th className="px-3 py-2 font-medium">费用分类</th>
                  <th className="px-3 py-2 font-medium">金额</th>
                  <th className="px-3 py-2 font-medium">备注</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {detail.items.map((item) => (
                  <tr key={item.id}>
                    <td className="px-3 py-2.5 text-foreground/90">{item.item_date || "—"}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{weekdayName(item.weekday)}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {item.fee_subcategory || item.fee_category || "—"}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-foreground">
                      ¥{item.amount.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">
                      <div className="flex items-center gap-2">
                        <span className="truncate">{item.description || "—"}</span>
                        {item.is_late_charge && (
                          <span className="inline-flex items-center gap-0.5 rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-600">
                            跨期
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 出差日 */}
      {detail.travel_days && detail.travel_days.length > 0 && (
        <div className="rounded-2xl border border-border/60 bg-background p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <CalendarBlank size={18} className="text-primary-600" />
            <h2 className="font-display text-sm font-semibold text-foreground/90">出差日</h2>
            <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              {detail.travel_days.length} 天
            </span>
          </div>
          <div className="space-y-2">
            {detail.travel_days.map((td) => {
              const invoiceCount = (detail.items || []).filter(
                (it) => it.item_date === td.travel_date
              ).length;
              return (
                <div
                  key={td.id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-background p-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground/90">
                      {td.travel_date}
                      {td.day_type && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          · {dayTypeLabel(td.day_type)}
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {td.note || "—"} · 当日发票 {invoiceCount} 张
                    </p>
                  </div>
                  {isDraft && (
                    <button
                      onClick={async () => {
                        try {
                          await portalApi.deleteTravelDayByDate(td.travel_date);
                          loadDetail();
                          window.dispatchEvent(new CustomEvent("chat-invoices-changed"));
                        } catch (err) {
                          setError(err instanceof Error ? err.message : "删除失败");
                        }
                      }}
                      disabled={cycleLocked}
                      title={cycleLocked ? lockTitle : "删除出差日"}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-error-50 hover:text-error-600 disabled:opacity-50"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 日补贴 */}
      {detail.day_subsidies && detail.day_subsidies.length > 0 && (
        <div className="rounded-2xl border border-border/60 bg-background p-4 shadow-sm sm:p-6">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Coins size={18} className="text-primary-600" />
            <h2 className="font-display text-sm font-semibold text-foreground/90">日补贴</h2>
            <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              {detail.day_subsidies.filter((d) => d.included).length}/{detail.day_subsidies.length} 天
            </span>
          </div>
          {/* 移动端卡片列表 */}
          <div className="space-y-2 sm:hidden">
            {detail.day_subsidies.map((ds) => (
              <div key={ds.id} className={`rounded-lg border border-border/60 bg-muted/30 p-3 ${!ds.included ? "opacity-50" : ""}`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="text-sm font-medium text-foreground/90">{ds.subsidy_date}</span>
                    <span className="text-xs text-muted-foreground">{weekdayName(ds.weekday)}</span>
                    <span className={`inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-xs font-medium ${dayTypeBadge(ds.day_type)}`}>
                      {dayTypeLabel(ds.day_type)}
                    </span>
                  </div>
                  <span className="shrink-0 font-display text-sm font-bold text-foreground">
                    ¥{ds.subsidy_amount.toFixed(2)}
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>基准 ¥{(ds.base_rate ?? 0).toFixed(0)}</span>
                  {isDraft ? (
                    <button
                      onClick={() => handleToggleSubsidy(ds.subsidy_date, !ds.included)}
                      disabled={togglingSubsidyDate === ds.subsidy_date || cycleLocked}
                      title={cycleLocked ? lockTitle : ds.included ? "点击取消补贴" : "点击计入补贴"}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                        ds.included ? "bg-emerald-500" : "bg-border"
                      } disabled:opacity-50`}
                    >
                      {togglingSubsidyDate === ds.subsidy_date ? (
                        <Spinner size={12} className="absolute left-1 animate-spin text-white" />
                      ) : (
                        <span
                          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-background transition-transform ${
                            ds.included ? "translate-x-4" : "translate-x-1"
                          }`}
                        />
                      )}
                    </button>
                  ) : (
                    <span className={`text-xs font-medium ${ds.included ? "text-emerald-600" : "text-muted-foreground"}`}>
                      {ds.included ? "计入" : "不计入"}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
          {/* 桌面端表格 */}
          <div className="hidden overflow-x-auto sm:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">日期</th>
                  <th className="px-3 py-2 font-medium">星期</th>
                  <th className="px-3 py-2 font-medium">日类型</th>
                  <th className="px-3 py-2 font-medium">基准</th>
                  <th className="px-3 py-2 font-medium">实际补贴</th>
                  <th className="px-3 py-2 text-center font-medium">计入</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {detail.day_subsidies.map((ds) => (
                  <tr key={ds.id} className={!ds.included ? "opacity-50" : ""}>
                    <td className="px-3 py-2.5 text-foreground/90">{ds.subsidy_date}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{weekdayName(ds.weekday)}</td>
                    <td className="px-3 py-2.5">
                      <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${dayTypeBadge(ds.day_type)}`}>
                        {dayTypeLabel(ds.day_type)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">¥{(ds.base_rate ?? 0).toFixed(0)}</td>
                    <td className="px-3 py-2.5 font-medium text-foreground">¥{ds.subsidy_amount.toFixed(2)}</td>
                    <td className="px-3 py-2.5 text-center">
                      {isDraft ? (
                        <button
                          onClick={() => handleToggleSubsidy(ds.subsidy_date, !ds.included)}
                          disabled={togglingSubsidyDate === ds.subsidy_date || cycleLocked}
                          title={cycleLocked ? lockTitle : ds.included ? "点击取消补贴" : "点击计入补贴"}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                            ds.included ? "bg-emerald-500" : "bg-border"
                          } disabled:opacity-50`}
                        >
                          {togglingSubsidyDate === ds.subsidy_date ? (
                            <Spinner size={12} className="absolute left-1 animate-spin text-white" />
                          ) : (
                            <span
                              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-background transition-transform ${
                                ds.included ? "translate-x-4" : "translate-x-1"
                              }`}
                            />
                          )}
                        </button>
                      ) : (
                        <span className={`text-xs font-medium ${ds.included ? "text-emerald-600" : "text-muted-foreground"}`}>
                          {ds.included ? "是" : "否"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 关联发票 */}
      <div className="rounded-2xl border border-border/60 bg-background p-4 shadow-sm sm:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-1.5 font-display text-sm font-semibold text-foreground/90">
            <Receipt size={18} className="text-primary-600" />
            关联发票
            <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              {detail.invoices?.length || 0} 张
            </span>
          </h2>
          {isDraft && !showLinkPanel && (
            <button
              onClick={() => { setShowLinkPanel(true); loadAvailableInvoices(); }}
              disabled={cycleLocked}
              title={lockTitle}
              className="flex items-center gap-1 rounded-lg bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100 disabled:opacity-50"
            >
              <LinkIcon size={14} />
              添加发票
            </button>
          )}
        </div>

        {/* 已关联发票列表 */}
        {detail.invoices && detail.invoices.length > 0 ? (
          <div className="space-y-2">
            {detail.invoices.map((inv) => (
              <div
                key={inv.id}
                className="rounded-xl border border-border p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                    {inv.seller_name || "未识别"}
                  </p>
                  <span className="shrink-0 font-display text-sm font-bold text-foreground">
                    ¥{inv.total_with_tax || "-"}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  {inv.verify_status === "VALID" && (
                    <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600">验真通过</span>
                  )}
                  {inv.verify_status === "INVALID" && (
                    <span className="rounded-full bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-600">验真失败</span>
                  )}
                  {inv.duplicate_status === "DUPLICATE" && (
                    <span className="rounded-full bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-600">重复</span>
                  )}
                  <span>{inv.fee_subcategory || inv.fee_category || "未分类"}</span>
                  {inv.invoice_number && <span>· {inv.invoice_number}</span>}
                  {inv.issue_date && <span>· {inv.issue_date}</span>}
                </div>
                {isDraft && (
                  <div className="mt-2 flex justify-end">
                    <button
                      onClick={() => handleUnlink(inv.id)}
                      disabled={unlinking === inv.id || cycleLocked}
                      title={cycleLocked ? lockTitle : "移除发票"}
                      className="flex items-center gap-1 rounded-lg bg-muted px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                    >
                      {unlinking === inv.id ? <Spinner size={12} className="animate-spin" /> : <LinkBreak size={14} />}
                      移除
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Receipt size={36} className="text-muted" />
            <p className="mt-2 text-sm text-muted-foreground">暂无关联发票</p>
            {isDraft && !showLinkPanel && (
              <button
                onClick={() => { setShowLinkPanel(true); loadAvailableInvoices(); }}
                disabled={cycleLocked}
                title={lockTitle}
                className="mt-2 text-sm font-medium text-primary-600 hover:text-primary-700 disabled:opacity-50"
              >
                添加发票
              </button>
            )}
          </div>
        )}

        {/* 添加发票面板 */}
        {showLinkPanel && (
          <div className="mt-4 rounded-xl border border-primary-200 bg-primary-50/30 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-foreground/90">选择要添加的发票</h3>
              <div className="flex items-center gap-2">
                {linkSelectedIds.size > 0 && (
                  <button
                    onClick={handleLinkInvoices}
                    disabled={linking || cycleLocked}
                    title={cycleLocked ? lockTitle : ""}
                    className="flex items-center gap-1 rounded-lg bg-primary-700 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-800 disabled:opacity-50"
                  >
                    {linking ? <Spinner size={12} className="animate-spin" /> : <Check size={12} />}
                    确认添加 ({linkSelectedIds.size})
                  </button>
                )}
                <button
                  onClick={() => { setShowLinkPanel(false); setLinkSelectedIds(new Set()); }}
                  className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
                >
                  取消
                </button>
              </div>
            </div>
            {availableInvoices.length === 0 ? (
              <div className="py-4 text-center text-sm text-muted-foreground">
                没有可添加的发票（标准发票需验真通过、非标票据需审核通过，均需查重唯一且未关联其他报销单）
              </div>
            ) : (
              <div className="max-h-60 space-y-2 overflow-y-auto">
                {availableInvoices.map((inv) => {
                  const checked = linkSelectedIds.has(inv.id);
                  return (
                    <label
                      key={inv.id}
                      className={`flex cursor-pointer items-center gap-3 rounded-lg border bg-background p-3 transition-all ${
                        checked ? "border-primary-300 bg-primary-50/50" : "border-border hover:border-border"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleLinkInvoice(inv.id)}
                        className="h-4 w-4 shrink-0 rounded border-border text-primary-600 focus:ring-primary-500"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-foreground">
                          {inv.seller_name || "未识别"}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {inv.fee_subcategory || inv.fee_category || "未分类"}
                          {inv.invoice_number && ` · ${inv.invoice_number}`}
                          {inv.issue_date && ` · ${inv.issue_date}`}
                        </p>
                      </div>
                      <span className="shrink-0 text-sm font-bold text-foreground">
                        ¥{inv.total_with_tax || "-"}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 附件 */}
      <div className="rounded-2xl border border-border/60 bg-background p-4 shadow-sm sm:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-1.5 font-display text-sm font-semibold text-foreground/90">
            <Paperclip size={18} className="text-primary-600" />
            附件
            <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              {detail.attachments?.length || 0} 个
            </span>
          </h2>
          {isDraft && (
            <button
              onClick={() => attachmentInputRef.current?.click()}
              disabled={uploadingAttachment || cycleLocked}
              title={lockTitle}
              className="flex items-center gap-1 rounded-lg bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100 disabled:opacity-50"
            >
              {uploadingAttachment ? <Spinner size={14} className="animate-spin" /> : <Plus size={14} />}
              上传附件
            </button>
          )}
        </div>
        <input
          ref={attachmentInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              handleUploadAttachment(e.target.files);
            }
            e.target.value = "";
          }}
        />

        {detail.attachments && detail.attachments.length > 0 ? (
          <div className="space-y-2">
            {detail.attachments.map((att) => (
              <div
                key={att.id}
                className="flex items-center gap-3 rounded-xl border border-border p-3"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-50">
                  <Paperclip size={16} className="text-primary-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">{att.filename}</p>
                  <p className="text-xs text-muted-foreground">
                    {(att.file_size / 1024).toFixed(1)} KB
                    {att.created_at && ` · ${new Date(att.created_at).toLocaleString("zh-CN")}`}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleDownloadAttachment(att.id, att.filename)}
                    className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground/70"
                    title="下载"
                  >
                    <DownloadSimple size={16} />
                  </button>
                  {isDraft && (
                    <button
                      onClick={() => handleDeleteAttachment(att.id)}
                      disabled={deletingAttachment === att.id || cycleLocked}
                      title={cycleLocked ? lockTitle : "删除"}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                    >
                      {deletingAttachment === att.id ? <Spinner size={14} className="animate-spin" /> : <Trash size={16} />}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Paperclip size={36} className="text-muted" />
            <p className="mt-2 text-sm text-muted-foreground">暂无附件</p>
            {isDraft && (
              <button
                onClick={() => attachmentInputRef.current?.click()}
                disabled={uploadingAttachment || cycleLocked}
                title={lockTitle}
                className="mt-2 text-sm font-medium text-primary-600 hover:text-primary-700 disabled:opacity-50"
              >
                上传附件
              </button>
            )}
          </div>
        )}
      </div>

      {/* 删除确认弹窗 */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-background p-6 shadow-xl">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-50">
                <Warning size={20} className="text-red-600" weight="fill" />
              </div>
              <div>
                <h3 className="font-display text-base font-semibold text-foreground">删除报销单</h3>
                <p className="text-sm text-muted-foreground">此操作不可撤销</p>
              </div>
              <button
                onClick={() => setDeleteTarget(false)}
                className="ml-auto rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground/70"
              >
                <X size={18} />
              </button>
            </div>
            <p className="mb-2 text-sm text-foreground/70">
              确定要删除报销单 #{detail.id} 吗？已关联的发票将被解除关联（发票本身不删除）。
            </p>
            {deleteError && (
              <div className="mb-3 flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
                <WarningCircle size={14} weight="fill" />
                {deleteError}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteTarget(false)}
                disabled={deleting}
                className="rounded-xl px-4 py-2 text-sm font-medium text-foreground/70 transition-colors hover:bg-muted disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="flex items-center gap-1.5 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-red-700 disabled:opacity-50"
              >
                {deleting && <Spinner size={14} className="animate-spin" />}
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
