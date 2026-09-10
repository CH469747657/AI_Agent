import { useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Warning,
  Trash,
  User,
  Building,
  CalendarBlank,
  CurrencyCny,
  NotePencil,
  Clock,
  Spinner,
  PaperPlaneTilt,
  ArrowUUpLeft,
  CheckCircle,
  Check,
  XCircle,
  MoneyWavy,
  FileXls,
  FilePdf,
  FileZip,
  DownloadSimple,
  Receipt,
  Plus,
  Minus,
  Paperclip,
  Lock,
  CalendarStar,
  ListChecks,
  Coins,
} from "@phosphor-icons/react";
import { reimbursementApi, invoiceApi, reportApi } from "../../api/client";
import {
  CategoryBadge,
  VerifyBadge,
  DuplicateBadge,
} from "../../components/StatusBadge";
import {
  ReimbStatusBadge,
  InfoRow,
  hasReportFiles,
  weekdayName,
  dayTypeLabel,
  dayTypeBadge,
  formatCycleRange,
} from "./shared";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import type { ReimbursementsPageState } from "./index";

const reportFileTypes = [
  {
    key: "xlsx",
    label: "Excel 费用清单",
    desc: "按发票/明细行列示的费用清单与金额汇总",
    icon: FileXls,
    color: "text-emerald-600",
    bg: "bg-emerald-50",
  },
  {
    key: "pdf",
    label: "PDF 发票汇总",
    desc: "全部已上传发票的元数据与图片汇总",
    icon: FilePdf,
    color: "text-rose-600",
    bg: "bg-rose-50",
  },
  {
    key: "zip",
    label: "ZIP 完整包",
    desc: "原始发票图片 + Excel 费用清单 + PDF 汇总打包",
    icon: FileZip,
    color: "text-amber-600",
    bg: "bg-amber-50",
  },
];

export function ReimbursementDetail({ state }: { state: ReimbursementsPageState }) {
  const {
    detailId,
    detailReimb: reimb,
    setDetailReimb,
    detailInvoices,
    setDetailInvoices,
    detailLoading,
    detailAttachments,
    setDetailAttachments,
    allInvoices,
    setAllInvoices,
    error,
    setError,
    goToList,
    submitting,
    withdrawing,
    approving,
    rejecting,
    reimbursing,
    handleSubmit,
    handleWithdraw,
    handleApprove,
    handleReject,
    handleReimburse,
    showAddInvoice,
    setShowAddInvoice,
    addInvoiceIds,
    setAddInvoiceIds,
    addingInvoices,
    setAddingInvoices,
    removingInvoiceId,
    setRemovingInvoiceId,
    uploadingAttachment,
    setUploadingAttachment,
    deletingAttachmentId,
    setDeletingAttachmentId,
    detailFileInputRef,
    deleteTarget,
    setDeleteTarget,
    deleting,
    deleteError,
    setDeleteError,
    handleDelete,
  } = state;

  const showReportFiles = hasReportFiles(reimb);

  const [togglingSubsidyDate, setTogglingSubsidyDate] = useState<string | null>(null);
  const [downloadingReportType, setDownloadingReportType] = useState<string | null>(null);

  const handleDownloadReport = async (fileType: string) => {
    if (!reimb) return;
    setDownloadingReportType(fileType);
    setError(null);
    try {
      await reportApi.download(reimb.id, fileType);
    } catch (e) {
      setError(e instanceof Error ? e.message : "下载失败");
    } finally {
      setDownloadingReportType(null);
    }
  };

  const handleToggleSubsidy = async (subsidyDate: string, included: boolean) => {
    if (!reimb) return;
    setTogglingSubsidyDate(subsidyDate);
    setError(null);
    try {
      await reimbursementApi.toggleSubsidy(reimb.id, subsidyDate, included);
      const updated = await reimbursementApi.detail(reimb.id);
      setDetailReimb(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "切换补贴失败");
    } finally {
      setTogglingSubsidyDate(null);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={goToList}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="返回"
        >
          <ArrowLeft size={20} />
        </button>
        <div className="flex-1">
          <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
            报销单 #{reimb?.id ?? detailId}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            查看详情、生成报表并提交
          </p>
        </div>
        {reimb && reimb.status === "DRAFT" && (
          <button
            onClick={() => {
              setDeleteError(null);
              setDeleteTarget(reimb);
            }}
            className="flex items-center gap-2 rounded-xl border border-rose-200 bg-background px-4 py-2 text-sm font-medium text-rose-600 transition-colors hover:bg-rose-50"
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
          <div className="h-48 animate-pulse rounded-2xl bg-muted/50" />
          <div className="h-32 animate-pulse rounded-2xl bg-muted/50" />
        </div>
      ) : (
        <>
          {/* Info card */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-2xl border border-border bg-background p-6"
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ReimbStatusBadge status={reimb.status} />
                {reimb.cycle_key && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">
                    <CalendarStar size={12} />
                    {reimb.cycle_key}
                  </span>
                )}
                {reimb.is_cycle_locked && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-600">
                    <Lock size={12} />
                    已封账
                  </span>
                )}
                {reimb.auto_generated && (
                  <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                    自动生成
                  </span>
                )}
              </div>
              <span className="text-xs text-muted-foreground">
                创建于 {reimb.created_at
                  ? new Date(reimb.created_at).toLocaleString("zh-CN")
                  : "—"}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <InfoRow
                icon={<User size={16} className="text-muted-foreground" />}
                label="申请人"
                value={reimb.applicant_name || reimb.applicant_id}
              />
              <InfoRow
                icon={<Building size={16} className="text-muted-foreground" />}
                label="部门"
                value={reimb.department || "—"}
              />
              <InfoRow
                icon={<CalendarBlank size={16} className="text-muted-foreground" />}
                label="报销期间"
                value={reimb.period || "—"}
              />
              <InfoRow
                icon={<CalendarStar size={16} className="text-muted-foreground" />}
                label="周期范围"
                value={formatCycleRange(reimb.cycle_start, reimb.cycle_end)}
              />
            </div>

            {/* 金额明细 */}
            <div className="mt-4 grid grid-cols-3 gap-3 border-t border-border pt-4">
              <div className="rounded-lg bg-muted p-3">
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Receipt size={14} />
                  费用合计
                </div>
                <p className="mt-1 font-display text-lg font-bold text-foreground">
                  ¥{(reimb.expense_total ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </p>
              </div>
              <div className="rounded-lg bg-amber-50 p-3">
                <div className="flex items-center gap-1 text-xs text-amber-500">
                  <Coins size={14} />
                  补贴合计
                </div>
                <p className="mt-1 font-display text-lg font-bold text-amber-700">
                  ¥{(reimb.subsidy_total ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </p>
              </div>
              <div className="rounded-lg bg-primary-50 p-3 ring-1 ring-primary-200">
                <div className="flex items-center gap-1 text-xs text-primary-500">
                  <CurrencyCny size={14} />
                  报销总额
                </div>
                <p className="mt-1 font-display text-lg font-bold text-primary-700">
                  ¥{(reimb.total_amount ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </p>
              </div>
            </div>
            {reimb.reason && (
              <div className="mt-4 flex items-start gap-3 border-t border-border pt-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                  <NotePencil size={16} className="text-muted-foreground" />
                </div>
                <div className="flex-1">
                  <p className="text-xs text-muted-foreground">报销事由</p>
                  <p className="text-sm font-medium text-foreground whitespace-pre-wrap">{reimb.reason}</p>
                </div>
              </div>
            )}
          </motion.div>

          {/* 费用明细 */}
          {reimb.items && reimb.items.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl border border-border bg-background"
            >
              <div className="border-b border-border px-5 py-4">
                <div className="flex items-center gap-2">
                  <ListChecks size={18} className="text-muted-foreground" />
                  <h2 className="font-display text-base font-semibold text-foreground">
                    费用明细
                  </h2>
                  <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                    {reimb.items.length} 条
                  </span>
                </div>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-5 py-3 font-medium">日期</th>
                    <th className="px-5 py-3 font-medium">星期</th>
                    <th className="px-5 py-3 font-medium">费用分类</th>
                    <th className="px-5 py-3 font-medium">金额</th>
                    <th className="px-5 py-3 font-medium">备注</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {reimb.items.map((item) => (
                    <tr key={item.id} className="hover:bg-muted/50">
                      <td className="px-5 py-3 text-foreground">
                        {item.item_date || "—"}
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">
                        {weekdayName(item.weekday)}
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">
                        {item.fee_subcategory || item.fee_category || "—"}
                      </td>
                      <td className="px-5 py-3 font-medium text-foreground">
                        ¥{item.amount.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">
                        <div className="flex items-center gap-2">
                          <span className="truncate">{item.description || "—"}</span>
                          {item.is_late_charge && (
                            <span
                              title={item.intended_cycle_key ? `原应归属周期：${item.intended_cycle_key}` : "跨期费用"}
                              className="inline-flex items-center gap-0.5 rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-600 ring-1 ring-rose-200 cursor-help"
                            >
                              跨期{item.intended_cycle_key ? `→${item.intended_cycle_key}` : ""}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </motion.div>
          )}

          {/* 出差日 */}
          {reimb.travel_days && reimb.travel_days.length > 0 && (
            <div className="rounded-xl border border-border bg-background p-5 shadow-sm">
              <div className="mb-3 flex items-center gap-2">
                <CalendarBlank size={18} className="text-primary-600" />
                <h3 className="font-display text-sm font-semibold text-foreground/90">出差日</h3>
                <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                  {reimb.travel_days.length} 天
                </span>
              </div>
              <div className="space-y-2">
                {reimb.travel_days.map((td) => {
                  const invoiceCount = (reimb.items || []).filter(
                    (it) => it.item_date === td.travel_date
                  ).length;
                  return (
                    <div
                      key={td.id}
                      className="flex items-center justify-between rounded-lg border border-border p-2.5"
                    >
                      <div>
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
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 日补贴 */}
          {reimb.day_subsidies && reimb.day_subsidies.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl border border-border bg-background"
            >
              <div className="border-b border-border px-5 py-4">
                <div className="flex items-center gap-2">
                  <Coins size={18} className="text-muted-foreground" />
                  <h2 className="font-display text-base font-semibold text-foreground">
                    日补贴
                  </h2>
                  <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                    {reimb.day_subsidies.filter((d) => d.included).length}/{reimb.day_subsidies.length} 天
                  </span>
                </div>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-5 py-3 font-medium">日期</th>
                    <th className="px-5 py-3 font-medium">星期</th>
                    <th className="px-5 py-3 font-medium">日类型</th>
                    <th className="px-5 py-3 font-medium">基准</th>
                    <th className="px-5 py-3 font-medium">实际补贴</th>
                    <th className="px-5 py-3 text-center font-medium">计入</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {reimb.day_subsidies.map((ds) => (
                    <tr key={ds.id} className={`hover:bg-muted/50 ${!ds.included ? "opacity-50" : ""}`}>
                      <td className="px-5 py-3 text-foreground">
                        {ds.subsidy_date}
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">
                        {weekdayName(ds.weekday)}
                      </td>
                      <td className="px-5 py-3">
                        <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${dayTypeBadge(ds.day_type)}`}>
                          {dayTypeLabel(ds.day_type)}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">
                        ¥{(ds.base_rate ?? 0).toFixed(0)}
                      </td>
                      <td className="px-5 py-3 font-medium text-foreground">
                        ¥{ds.subsidy_amount.toFixed(2)}
                      </td>
                      <td className="px-5 py-3 text-center">
                        {reimb.status === "DRAFT" ? (
                          <button
                            onClick={() => handleToggleSubsidy(ds.subsidy_date, !ds.included)}
                            disabled={togglingSubsidyDate === ds.subsidy_date}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                              ds.included ? "bg-emerald-500" : "bg-muted"
                            } disabled:opacity-50`}
                            title={ds.included ? "点击取消补贴" : "点击计入补贴"}
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
            </motion.div>
          )}

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

          {/* Action section: withdraw + approve/reject */}
          {reimb.status === "SUBMITTED" && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-wrap items-center gap-3 rounded-2xl border border-blue-200 bg-blue-50/50 p-4"
            >
              <ArrowUUpLeft size={20} className="text-blue-600" />
              <span className="flex-1 text-sm text-blue-800">
                该报销单已提交，可撤回、审核通过、直接报销或驳回
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
                撤回
              </button>
              <button
                onClick={() => handleApprove(reimb.id)}
                disabled={approving}
                className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-emerald-700 disabled:opacity-50"
              >
                {approving ? (
                  <Spinner size={16} className="animate-spin" />
                ) : (
                  <CheckCircle size={16} weight="bold" />
                )}
                审核通过
              </button>
              <button
                onClick={() => handleReimburse(reimb.id)}
                disabled={reimbursing}
                className="flex items-center gap-2 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-emerald-800 disabled:opacity-50"
              >
                {reimbursing ? (
                  <Spinner size={16} className="animate-spin" />
                ) : (
                  <Check size={16} weight="bold" />
                )}
                直接报销
              </button>
              <button
                onClick={() => handleReject(reimb.id)}
                disabled={rejecting}
                className="flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-rose-700 disabled:opacity-50"
              >
                {rejecting ? (
                  <Spinner size={16} className="animate-spin" />
                ) : (
                  <XCircle size={16} weight="bold" />
                )}
                驳回
              </button>
            </motion.div>
          )}

          {/* Action section: mark reimbursed */}
          {reimb.status === "REVIEWED" && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50/50 p-4"
            >
              <CheckCircle size={20} className="text-emerald-600" />
              <span className="flex-1 text-sm text-emerald-800">
                该报销单已审核通过，确认打款后标记为已报销
              </span>
              <button
                onClick={() => handleReimburse(reimb.id)}
                disabled={reimbursing}
                className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-emerald-700 disabled:opacity-50"
              >
                {reimbursing ? (
                  <Spinner size={16} className="animate-spin" />
                ) : (
                  <MoneyWavy size={16} weight="bold" />
                )}
                确认打款
              </button>
            </motion.div>
          )}

          {/* Report download */}
          <div className="rounded-2xl border border-border bg-background p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-display text-base font-semibold text-foreground">
                报表
              </h2>
            </div>

            {showReportFiles ? (
              <div className="grid gap-3">
                {reportFileTypes.map((ft, i) => {
                  const Icon = ft.icon;
                  return (
                    <motion.button
                      key={ft.key}
                      onClick={() => handleDownloadReport(ft.key)}
                      disabled={downloadingReportType === ft.key}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.08 }}
                      className="group flex w-full items-center gap-4 rounded-xl border border-border p-4 text-left transition-colors hover:border-primary-300 hover:bg-muted disabled:opacity-50"
                    >
                      <div
                        className={`flex h-10 w-10 items-center justify-center rounded-lg ${ft.bg}`}
                      >
                        <Icon size={20} className={ft.color} />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-foreground">
                          {ft.label}
                        </p>
                        <p className="text-xs text-muted-foreground">{ft.desc}</p>
                      </div>
                      {downloadingReportType === ft.key ? (
                        <Spinner size={18} className="animate-spin text-muted-foreground" />
                      ) : (
                        <DownloadSimple
                          size={18}
                          className="text-muted-foreground group-hover:text-primary-600"
                        />
                      )}
                    </motion.button>
                  );
                })}
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                暂无报表
              </p>
            )}
          </div>

          {/* Linked invoices */}
          <div className="rounded-2xl border border-border bg-background">
            <div className="border-b border-border px-5 py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Receipt size={18} className="text-muted-foreground" />
                  <h2 className="font-display text-base font-semibold text-foreground">
                    关联发票
                  </h2>
                  <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                    {detailInvoices.length} 张
                  </span>
                </div>
                {reimb.status === "DRAFT" && !showAddInvoice && (
                  <button
                    onClick={() => {
                      setShowAddInvoice(true);
                      setAddInvoiceIds([]);
                    }}
                    className="flex items-center gap-1.5 rounded-lg bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100"
                  >
                    <Plus size={14} weight="bold" />
                    追加发票
                  </button>
                )}
              </div>
            </div>

            {/* 追加发票面板 */}
            {showAddInvoice && (
              <div className="border-b border-border bg-muted/50 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-sm text-foreground">选择要追加的发票</p>
                  <div className="flex items-center gap-2">
                    {addInvoiceIds.length > 0 && (
                      <span className="text-xs text-primary-600">
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
                      className="flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
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
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
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
                          ? inv.status === "REVIEWED"
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
                              ? "border-primary-300 bg-primary-50"
                              : "border-border bg-background hover:bg-muted"
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
                            className="h-3.5 w-3.5 rounded border-border text-primary-600 focus:ring-primary-500"
                          />
                          <div className="flex-1 min-w-0">
                            <span className="text-sm text-foreground">
                              {inv.seller_name || "未知销方"}
                            </span>
                            <span className="ml-2 text-xs text-muted-foreground">
                              {inv.issue_date || ""}
                            </span>
                          </div>
                          <span className="text-sm font-medium text-foreground">
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
                    <p className="py-4 text-center text-xs text-muted-foreground">
                      没有可追加的发票（标准发票需验真通过、非标票据需审核通过，均需查重唯一且未关联其他报销单）
                    </p>
                  )}
                </div>
              </div>
            )}

            {detailInvoices.length === 0 && !showAddInvoice ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                暂无关联发票
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
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
                    <tr key={inv.id} className="hover:bg-muted/50">
                      <td className="px-5 py-3 font-mono text-xs text-muted-foreground">
                        #{inv.id}
                      </td>
                      <td className="max-w-[200px] truncate px-5 py-3 text-foreground">
                        {inv.seller_name || "—"}
                      </td>
                      <td className="px-5 py-3 font-medium text-foreground">
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
          <div className="rounded-2xl border border-border bg-background">
            <div className="border-b border-border px-5 py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Paperclip size={18} className="text-muted-foreground" />
                  <h2 className="font-display text-base font-semibold text-foreground">
                    附件
                  </h2>
                  <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                    {detailAttachments.length} 个
                  </span>
                </div>
                {reimb.status === "DRAFT" && (
                  <>
                    <button
                      onClick={() => detailFileInputRef.current?.click()}
                      disabled={uploadingAttachment}
                      className="flex items-center gap-1.5 rounded-lg bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100 disabled:opacity-50"
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
              <p className="py-8 text-center text-sm text-muted-foreground">
                暂无附件
              </p>
            ) : (
              <div className="divide-y divide-slate-50">
                {detailAttachments.map((att) => (
                  <div key={att.id} className="flex items-center gap-3 px-5 py-3">
                    <Paperclip size={18} className="shrink-0 text-muted-foreground" />
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">
                        {att.filename}
                      </p>
                      <p className="text-xs text-muted-foreground">
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
                      className="shrink-0 rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-primary-50 hover:text-primary-600"
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
                        className="shrink-0 rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50"
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
