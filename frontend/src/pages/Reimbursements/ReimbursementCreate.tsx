import {
  ArrowLeft,
  Warning,
  CheckCircle,
  Spinner,
  Paperclip,
  XCircle,
} from "@phosphor-icons/react";
import {
  StatusBadge,
  CategoryBadge,
  DuplicateBadge,
  VerifyBadge,
} from "../../components/StatusBadge";
import type { ReimbursementsPageState } from "./index";

export function ReimbursementCreate({ state }: { state: ReimbursementsPageState }) {
  const {
    goToList,
    error,
    allInvoices,
    availableInvoices,
    selectedIds,
    toggleInvoice,
    selectedTotal,
    applicantId,
    setApplicantId,
    applicantName,
    setApplicantName,
    department,
    setDepartment,
    period,
    setPeriod,
    reason,
    setReason,
    pendingFiles,
    setPendingFiles,
    fileInputRef,
    creating,
    uploadingAttachments,
    handleCreate,
  } = state;

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
