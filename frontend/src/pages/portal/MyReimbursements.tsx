import { useEffect, useState, useCallback, useRef } from "react";
import { portalApi } from "../../api/client";
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
} from "@phosphor-icons/react";
import {
  weekdayName,
  dayTypeLabel,
  dayTypeBadge,
  formatCycleRange,
} from "../Reimbursements/shared";

const statusLabels: Record<string, { label: string; color: string }> = {
  DRAFT: { label: "已关联", color: "bg-green-100 text-green-600" },
  SUBMITTED: { label: "已关联", color: "bg-green-100 text-green-600" },
  REVIEWED: { label: "已关联", color: "bg-green-100 text-green-600" },
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

  // ===== 列表视图 =====
  if (view === "list") {
    if (loading) {
      return (
        <div className="flex items-center justify-center py-20">
          <Spinner size={24} className="animate-spin text-brand-600" />
        </div>
      );
    }

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-xl font-bold text-slate-900">
              我的报销单
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              查看您的报销单，报销单由系统按周期自动生成与归集
            </p>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600">
            <WarningCircle size={18} weight="fill" />
            {error}
            <button onClick={() => setError("")} className="ml-auto text-red-400 hover:text-red-600">
              <X size={16} />
            </button>
          </div>
        )}

        {reimbursements.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-slate-200/60 bg-white py-16 text-center">
            <Stack size={48} className="text-slate-200" />
            <p className="mt-3 text-sm text-slate-400">暂无报销单</p>
          </div>
        ) : (
          <div className="space-y-3">
            {reimbursements.map((r) => {
              const st = statusLabels[r.status] || { label: r.status, color: "bg-slate-100 text-slate-600" };
              return (
                <div
                  key={r.id}
                  className="flex cursor-pointer items-center justify-between rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm transition-all hover:shadow-md hover:border-brand-200"
                  onClick={() => goDetail(r.id)}
                >
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-slate-900">
                        报销单 #{r.id}
                      </p>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${st.color}`}>
                        {st.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-slate-400">
                      <span>{r.reason || "未填写"}</span>
                      {r.cycle_key && <span className="text-indigo-500">{r.cycle_key}</span>}
                      {r.is_cycle_locked && (
                        <span className="inline-flex items-center gap-0.5 text-rose-500">
                          <Lock size={10} />
                          已封账
                        </span>
                      )}
                      <span>{r.invoice_count} 张发票</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
                    <p className="font-display text-base font-bold text-slate-900">
                      ¥{r.total_amount?.toLocaleString("zh-CN", { minimumFractionDigits: 2 }) ?? "0.00"}
                    </p>
                    {r.status === "SUBMITTED" && (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleWithdraw(r.id)}
                          disabled={withdrawing === r.id}
                          className="flex items-center gap-1 rounded-lg bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-100 disabled:opacity-50"
                        >
                          {withdrawing === r.id ? <Spinner size={14} className="animate-spin" /> : <ArrowUUpLeft size={14} />}
                          撤回
                        </button>
                      </div>
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
      <div className="rounded-xl bg-slate-50 p-3">
        <div className="text-sm font-medium text-slate-800">报销单 #{target.id}</div>
        <div className="mt-0.5 text-xs text-slate-400">
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

  // 关联发票相关
  const [showLinkPanel, setShowLinkPanel] = useState(false);
  const [availableInvoices, setAvailableInvoices] = useState<Invoice[]>([]);
  const [linkSelectedIds, setLinkSelectedIds] = useState<Set<number>>(new Set());
  const [linking, setLinking] = useState(false);
  const [unlinking, setUnlinking] = useState<number | null>(null);

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

  const loadAvailableInvoices = async () => {
    try {
      const all = await portalApi.myInvoices();
      // 可关联：标准发票需验真通过，非标票据需审核通过，均需查重唯一且未关联报销单
      setAvailableInvoices(
        all.filter(
          (inv) =>
            (inv.is_nonstandard
              ? inv.status === "CONFIRMED"
              : inv.verify_status === "VALID") &&
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
        <Spinner size={24} className="animate-spin text-brand-600" />
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="space-y-4">
        <button onClick={onBack} className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
          <ArrowLeft size={18} /> 返回列表
        </button>
        <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      </div>
    );
  }

  if (!detail) return null;

  const st = statusLabels[detail.status] || { label: detail.status, color: "bg-slate-100 text-slate-600" };

  return (
    <div className="space-y-6">
      {/* 顶部导航 */}
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="flex items-center gap-1 text-sm text-slate-500 transition-colors hover:text-slate-700">
          <ArrowLeft size={18} />
          返回列表
        </button>
        <div className="flex items-center gap-2">
          {isDraft && !editMode && (
            <button
              onClick={handleStartEdit}
              className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
            >
              <PencilSimple size={14} />
              编辑
            </button>
          )}
          {isSubmitted && !editMode && (
            <button
              onClick={handleWithdraw}
              disabled={withdrawing}
              className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
            >
              {withdrawing ? <Spinner size={14} className="animate-spin" /> : <ArrowUUpLeft size={14} />}
              撤回报销单
            </button>
          )}
          {editMode && (
            <>
              <button
                onClick={() => setEditMode(false)}
                disabled={saving}
                className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100"
              >
                取消
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={saving}
                className="flex items-center gap-1 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
              >
                {saving ? <Spinner size={14} className="animate-spin" /> : <Check size={14} />}
                保存
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}

      {/* 报销单信息卡片 */}
      <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <h2 className="font-display text-base font-semibold text-slate-900">
            报销单 #{detail.id}
          </h2>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${st.color}`}>
            {st.label}
          </span>
          {detail.cycle_key && (
            <span className="inline-flex items-center gap-1 rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">
              <CalendarStar size={12} />
              {detail.cycle_key}
            </span>
          )}
          {detail.is_cycle_locked && (
            <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-600">
              <Lock size={12} />
              已封账
            </span>
          )}
          {detail.auto_generated && (
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              自动生成
            </span>
          )}
        </div>

        <div className="grid grid-cols-3 gap-4">
          {/* 报销期间 */}
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="flex items-center gap-1 text-xs text-slate-400">
              <CalendarBlank size={14} />
              报销期间
            </div>
            {editMode ? (
              <input
                type="month"
                value={editPeriod}
                onChange={(e) => setEditPeriod(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm text-slate-700 outline-none focus:border-brand-400"
              />
            ) : (
              <p className="mt-1 text-sm font-medium text-slate-800">{detail.period || "未设置"}</p>
            )}
          </div>

          {/* 报销事由 */}
          <div className="col-span-2 rounded-xl bg-slate-50 p-3">
            <div className="flex items-center gap-1 text-xs text-slate-400">
              <FileText size={14} />
              报销事由
            </div>
            {editMode ? (
              <input
                type="text"
                value={editReason}
                onChange={(e) => setEditReason(e.target.value)}
                placeholder="如：7月差旅费报销"
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm text-slate-700 outline-none focus:border-brand-400"
              />
            ) : (
              <p className="mt-1 text-sm font-medium text-slate-800">{detail.reason || "未填写"}</p>
            )}
          </div>

          {/* 申请人 */}
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-xs text-slate-400">申请人</div>
            <p className="mt-1 text-sm font-medium text-slate-800">{detail.applicant_name || "—"}</p>
          </div>

          {/* 部门 */}
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-xs text-slate-400">部门</div>
            <p className="mt-1 text-sm font-medium text-slate-800">{detail.department || "—"}</p>
          </div>

          {/* 周期范围 */}
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="flex items-center gap-1 text-xs text-slate-400">
              <CalendarStar size={14} />
              周期范围
            </div>
            <p className="mt-1 text-sm font-medium text-slate-800">
              {formatCycleRange(detail.cycle_start, detail.cycle_end)}
            </p>
          </div>
        </div>

        {/* 金额明细 */}
        <div className="mt-4 grid grid-cols-3 gap-4 border-t border-slate-100 pt-4">
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="flex items-center gap-1 text-xs text-slate-400">
              <Receipt size={14} />
              费用合计
            </div>
            <p className="mt-1 font-display text-lg font-bold text-slate-800">
              ¥{(detail.expense_total ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="rounded-xl bg-amber-50 p-3">
            <div className="flex items-center gap-1 text-xs text-amber-500">
              <Coins size={14} />
              补贴合计
            </div>
            <p className="mt-1 font-display text-lg font-bold text-amber-700">
              ¥{(detail.subsidy_total ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="rounded-xl bg-brand-50 p-3 ring-1 ring-brand-200">
            <div className="flex items-center gap-1 text-xs text-brand-400">
              <CurrencyCny size={14} />
              报销总额
            </div>
            <p className="mt-1 font-display text-lg font-bold text-brand-700">
              ¥{(detail.total_amount ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>
      </div>

      {/* 费用明细 */}
      {detail.items && detail.items.length > 0 && (
        <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <ListChecks size={18} className="text-brand-600" />
            <h2 className="font-display text-sm font-semibold text-slate-700">费用明细</h2>
            <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              {detail.items.length} 条
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
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
                    <td className="px-3 py-2.5 text-slate-700">{item.item_date || "—"}</td>
                    <td className="px-3 py-2.5 text-slate-500">{weekdayName(item.weekday)}</td>
                    <td className="px-3 py-2.5 text-slate-500">
                      {item.fee_subcategory || item.fee_category || "—"}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-slate-900">
                      ¥{item.amount.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-3 py-2.5 text-slate-500">
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

      {/* 日补贴 */}
      {detail.day_subsidies && detail.day_subsidies.length > 0 && (
        <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Coins size={18} className="text-brand-600" />
            <h2 className="font-display text-sm font-semibold text-slate-700">日补贴</h2>
            <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              {detail.day_subsidies.filter((d) => d.included).length}/{detail.day_subsidies.length} 天
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
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
                    <td className="px-3 py-2.5 text-slate-700">{ds.subsidy_date}</td>
                    <td className="px-3 py-2.5 text-slate-500">{weekdayName(ds.weekday)}</td>
                    <td className="px-3 py-2.5">
                      <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${dayTypeBadge(ds.day_type)}`}>
                        {dayTypeLabel(ds.day_type)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-slate-500">¥{(ds.base_rate ?? 0).toFixed(0)}</td>
                    <td className="px-3 py-2.5 font-medium text-slate-900">¥{ds.subsidy_amount.toFixed(2)}</td>
                    <td className="px-3 py-2.5 text-center">
                      {isDraft ? (
                        <button
                          onClick={() => handleToggleSubsidy(ds.subsidy_date, !ds.included)}
                          disabled={togglingSubsidyDate === ds.subsidy_date}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                            ds.included ? "bg-emerald-500" : "bg-slate-300"
                          } disabled:opacity-50`}
                          title={ds.included ? "点击取消补贴" : "点击计入补贴"}
                        >
                          {togglingSubsidyDate === ds.subsidy_date ? (
                            <Spinner size={12} className="absolute left-1 animate-spin text-white" />
                          ) : (
                            <span
                              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                                ds.included ? "translate-x-4" : "translate-x-1"
                              }`}
                            />
                          )}
                        </button>
                      ) : (
                        <span className={`text-xs font-medium ${ds.included ? "text-emerald-600" : "text-slate-400"}`}>
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
      <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-1.5 font-display text-sm font-semibold text-slate-700">
            <Receipt size={18} className="text-brand-600" />
            关联发票
            <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              {detail.invoices?.length || 0} 张
            </span>
          </h2>
          {isDraft && !showLinkPanel && (
            <button
              onClick={() => { setShowLinkPanel(true); loadAvailableInvoices(); }}
              className="flex items-center gap-1 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-600 transition-colors hover:bg-brand-100"
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
                className="flex items-center justify-between rounded-xl border border-slate-200 p-3"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-slate-800">
                      {inv.seller_name || "未识别"}
                    </p>
                    {inv.verify_status === "VALID" && (
                      <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600">验真通过</span>
                    )}
                    {inv.verify_status === "INVALID" && (
                      <span className="rounded-full bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-600">验真失败</span>
                    )}
                    {inv.duplicate_status === "DUPLICATE" && (
                      <span className="rounded-full bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-600">重复</span>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-slate-400">
                    {inv.fee_subcategory || inv.fee_category || "未分类"}
                    {inv.invoice_number && ` · ${inv.invoice_number}`}
                    {inv.issue_date && ` · ${inv.issue_date}`}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-display text-sm font-bold text-slate-900">
                    ¥{inv.total_with_tax || "-"}
                  </span>
                  {isDraft && (
                    <button
                      onClick={() => handleUnlink(inv.id)}
                      disabled={unlinking === inv.id}
                      className="flex items-center gap-1 rounded-lg bg-slate-50 px-2 py-1 text-xs text-slate-500 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                      title="移除发票"
                    >
                      {unlinking === inv.id ? <Spinner size={12} className="animate-spin" /> : <LinkBreak size={14} />}
                      移除
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Receipt size={36} className="text-slate-200" />
            <p className="mt-2 text-sm text-slate-400">暂无关联发票</p>
            {isDraft && !showLinkPanel && (
              <button
                onClick={() => { setShowLinkPanel(true); loadAvailableInvoices(); }}
                className="mt-2 text-sm font-medium text-brand-600 hover:text-brand-700"
              >
                添加发票
              </button>
            )}
          </div>
        )}

        {/* 添加发票面板 */}
        {showLinkPanel && (
          <div className="mt-4 rounded-xl border border-brand-200 bg-brand-50/30 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-medium text-slate-700">选择要添加的发票</h3>
              <div className="flex items-center gap-2">
                {linkSelectedIds.size > 0 && (
                  <button
                    onClick={handleLinkInvoices}
                    disabled={linking}
                    className="flex items-center gap-1 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
                  >
                    {linking ? <Spinner size={12} className="animate-spin" /> : <Check size={12} />}
                    确认添加 ({linkSelectedIds.size})
                  </button>
                )}
                <button
                  onClick={() => { setShowLinkPanel(false); setLinkSelectedIds(new Set()); }}
                  className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100"
                >
                  取消
                </button>
              </div>
            </div>
            {availableInvoices.length === 0 ? (
              <div className="py-4 text-center text-sm text-slate-400">
                没有可添加的发票（标准发票需验真通过、非标票据需审核通过，均需查重唯一且未关联其他报销单）
              </div>
            ) : (
              <div className="max-h-60 space-y-2 overflow-y-auto">
                {availableInvoices.map((inv) => {
                  const checked = linkSelectedIds.has(inv.id);
                  return (
                    <label
                      key={inv.id}
                      className={`flex cursor-pointer items-center gap-3 rounded-lg border bg-white p-3 transition-all ${
                        checked ? "border-brand-300 bg-brand-50/50" : "border-slate-200 hover:border-slate-300"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleLinkInvoice(inv.id)}
                        className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                      />
                      <div className="flex-1">
                        <p className="text-sm font-medium text-slate-800">
                          {inv.seller_name || "未识别"}
                        </p>
                        <p className="text-xs text-slate-400">
                          {inv.fee_subcategory || inv.fee_category || "未分类"}
                          {inv.invoice_number && ` · ${inv.invoice_number}`}
                          {inv.issue_date && ` · ${inv.issue_date}`}
                        </p>
                      </div>
                      <span className="text-sm font-bold text-slate-900">
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
      <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-1.5 font-display text-sm font-semibold text-slate-700">
            <Paperclip size={18} className="text-brand-600" />
            附件
            <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              {detail.attachments?.length || 0} 个
            </span>
          </h2>
          {isDraft && (
            <button
              onClick={() => attachmentInputRef.current?.click()}
              disabled={uploadingAttachment}
              className="flex items-center gap-1 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-600 transition-colors hover:bg-brand-100 disabled:opacity-50"
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
                className="flex items-center gap-3 rounded-xl border border-slate-200 p-3"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50">
                  <Paperclip size={16} className="text-brand-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="truncate text-sm font-medium text-slate-800">{att.filename}</p>
                  <p className="text-xs text-slate-400">
                    {(att.file_size / 1024).toFixed(1)} KB
                    {att.created_at && ` · ${new Date(att.created_at).toLocaleString("zh-CN")}`}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleDownloadAttachment(att.id, att.filename)}
                    className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                    title="下载"
                  >
                    <DownloadSimple size={16} />
                  </button>
                  {isDraft && (
                    <button
                      onClick={() => handleDeleteAttachment(att.id)}
                      disabled={deletingAttachment === att.id}
                      className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                      title="删除"
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
            <Paperclip size={36} className="text-slate-200" />
            <p className="mt-2 text-sm text-slate-400">暂无附件</p>
            {isDraft && (
              <button
                onClick={() => attachmentInputRef.current?.click()}
                disabled={uploadingAttachment}
                className="mt-2 text-sm font-medium text-brand-600 hover:text-brand-700 disabled:opacity-50"
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
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-50">
                <Warning size={20} className="text-red-600" weight="fill" />
              </div>
              <div>
                <h3 className="font-display text-base font-semibold text-slate-900">删除报销单</h3>
                <p className="text-sm text-slate-500">此操作不可撤销</p>
              </div>
              <button
                onClick={() => setDeleteTarget(false)}
                className="ml-auto rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X size={18} />
              </button>
            </div>
            <p className="mb-2 text-sm text-slate-600">
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
                className="rounded-xl px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 disabled:opacity-50"
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
