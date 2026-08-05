import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { portalApi } from "../../api/client";
import type { Invoice, InvoiceDetail } from "../../types";
import {
  Receipt,
  Spinner,
  Eye,
  WarningCircle,
  Trash,
  X,
  Warning,
  ShieldCheck,
  CopySimple,
  DownloadSimple,
} from "@phosphor-icons/react";
import { StatusBadge, VerifyBadge, DuplicateBadge, CategoryBadge } from "../../components/StatusBadge";



export function PortalMyInvoices() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Invoice | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [detailId, setDetailId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    setError("");
    portalApi
      .myInvoices()
      .then(setInvoices)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "加载失败")
      )
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await portalApi.deleteInvoice(deleteTarget.id);
      setDeleteTarget(null);
      load();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

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
            我的发票
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            查看您上传的所有发票，管理员审核通过后可关联至报销单
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          共 {invoices.length} 张
        </span>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600">
          <WarningCircle size={18} weight="fill" />
          {error}
          <button
            onClick={() => setError("")}
            className="ml-auto text-red-400 hover:text-red-600"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {invoices.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-slate-200/60 bg-white py-16 text-center">
          <Receipt size={48} className="text-slate-200" />
          <p className="mt-3 text-sm text-slate-400">暂无发票</p>
          <a
            href="/portal/upload"
            className="mt-3 text-sm font-medium text-brand-600 hover:text-brand-700"
          >
            去上传
          </a>
        </div>
      ) : (
        <div className="space-y-3">
          {invoices.map((inv) => (
            <div
              key={inv.id}
              className="flex items-center justify-between rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm transition-all hover:shadow-md"
            >
              <div className="flex-1 space-y-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold text-slate-900">
                    {inv.seller_name || "未识别"}
                  </p>
                  {inv.receipt_type && (
                    <span
                      className={`inline-block whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ${
                        inv.is_nonstandard
                          ? "bg-violet-100 text-violet-700"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {inv.receipt_type}
                    </span>
                  )}
                  <StatusBadge status={inv.status} linked={!!inv.reimbursement_id} />
                  {inv.duplicate_status === "DUPLICATE" && (
                    <span className="flex items-center gap-0.5 rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-600">
                      <Warning size={11} weight="fill" />
                      重复
                    </span>
                  )}
                  </div>
                  <div className="flex items-center gap-4 text-xs text-slate-400">
                    <span>
                      {inv.fee_subcategory || inv.fee_category || "未分类"}
                    </span>
                    {inv.invoice_number && <span>{inv.invoice_number}</span>}
                    {inv.issue_date && <span>{inv.issue_date}</span>}
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <p className="font-display text-base font-bold text-slate-900">
                    ¥{inv.total_with_tax || "-"}
                  </p>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setDetailId(inv.id)}
                      className="flex items-center gap-1 rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100"
                    >
                      <Eye size={14} />
                      详情
                    </button>
                    <button
                      onClick={() => portalApi.downloadInvoiceFile(inv.id)}
                      className="flex items-center gap-1 rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100"
                    >
                      <DownloadSimple size={14} />
                      下载
                    </button>

                    {inv.reimbursement_id ? (
                      <span className="flex items-center gap-1 rounded-lg bg-brand-50 px-2.5 py-1.5 text-xs font-medium text-brand-600">
                        <Eye size={14} />
                        已关联
                      </span>
                    ) : (
                      <button
                        onClick={() => {
                          setDeleteTarget(inv);
                          setDeleteError("");
                        }}
                        className="flex items-center gap-1 rounded-lg bg-red-50 px-2.5 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-100"
                      >
                        <Trash size={14} />
                        删除
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
        </div>
      )}

      {/* 发票详情抽屉 */}
      <MyInvoiceDetailDrawer
        invoiceId={detailId}
        onClose={() => setDetailId(null)}
      />

      {/* 删除确认弹窗 */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-50">
                <Warning size={20} className="text-red-600" weight="fill" />
              </div>
              <div>
                <h3 className="font-display text-base font-semibold text-slate-900">
                  删除发票
                </h3>
                <p className="text-sm text-slate-500">此操作不可撤销</p>
              </div>
              <button
                onClick={() => setDeleteTarget(null)}
                className="ml-auto rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X size={18} />
              </button>
            </div>

            <p className="mb-2 text-sm text-slate-600">
              确定要删除以下发票吗？发票数据及原始文件将被永久删除。
            </p>
            <div className="mb-4 rounded-xl bg-slate-50 p-3">
              <div className="text-sm font-medium text-slate-800">
                {deleteTarget.seller_name || "未识别"}
              </div>
              <div className="mt-0.5 text-xs text-slate-400">
                {deleteTarget.fee_subcategory ||
                  deleteTarget.fee_category ||
                  "未分类"}
                {deleteTarget.invoice_number &&
                  ` · ${deleteTarget.invoice_number}`}
                {deleteTarget.total_with_tax &&
                  ` · ¥${deleteTarget.total_with_tax}`}
              </div>
            </div>

            {deleteError && (
              <div className="mb-3 flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
                <WarningCircle size={14} weight="fill" />
                {deleteError}
              </div>
            )}

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteTarget(null)}
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

// ===== 发票详情抽屉 =====

function MyInvoiceDetailDrawer({
  invoiceId,
  onClose,
}: {
  invoiceId: number | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<InvoiceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!invoiceId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setError(null);
    portalApi
      .myInvoiceDetail(invoiceId)
      .then((d) => setDetail(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [invoiceId]);

  return (
    <AnimatePresence>
      {invoiceId && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-slate-900/30 backdrop-blur-sm"
          />
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="fixed right-0 top-0 z-50 flex h-[100dvh] w-full max-w-xl flex-col bg-white shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-200/60 px-6 py-4">
              <div className="flex items-center gap-2">
                <Receipt size={20} className="text-brand-600" />
                <h2 className="font-display text-base font-semibold text-slate-900">
                  发票详情
                </h2>
              </div>
              <button
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                aria-label="关闭"
              >
                <X size={18} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5">
              {loading && (
                <div className="space-y-4">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="flex gap-4">
                      <div className="h-4 w-20 animate-pulse rounded bg-slate-200" />
                      <div className="h-4 flex-1 animate-pulse rounded bg-slate-100" />
                    </div>
                  ))}
                </div>
              )}

              {error && (
                <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
                  <Warning size={18} />
                  {error}
                </div>
              )}

              {detail && !loading && <DetailContent detail={detail} />}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function DetailContent({ detail }: { detail: InvoiceDetail }) {
  const fields = [
    { label: "发票号码", value: detail.invoice_number },
    { label: "发票代码", value: detail.invoice_code },
    { label: "校验码", value: detail.check_code },
    { label: "开票日期", value: detail.issue_date },
    { label: "票据类型", value: detail.receipt_type },
    { label: "购方名称", value: detail.buyer_name },
    { label: "购方税号", value: detail.buyer_tax_id },
    { label: "销方名称", value: detail.seller_name },
    { label: "销方税号", value: detail.seller_tax_id },
    { label: "商品名称", value: detail.item_name },
    { label: "金额(不含税)", value: detail.amount ? `¥${detail.amount}` : null },
    { label: "税额", value: detail.tax_amount ? `¥${detail.tax_amount}` : null },
    { label: "税率", value: detail.tax_rate },
    {
      label: "价税合计",
      value: detail.total_with_tax ? `¥${detail.total_with_tax}` : null,
      highlight: true,
    },
  ];

  return (
    <div className="space-y-6">
      {/* 状态徽章行 */}
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={detail.status} linked={!!detail.reimbursement_id} />
        <VerifyBadge status={detail.verify_status} />
        <DuplicateBadge status={detail.duplicate_status} />
        <CategoryBadge category={detail.fee_category} subcategory={detail.fee_subcategory} />
      </div>

      {/* 双源比对置信度 */}
      {detail.diff_confidence !== null && detail.diff_confidence !== undefined && (
        <div className="rounded-xl border border-slate-200/60 bg-slate-50 p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600">双源比对置信度</span>
            <span className="font-display text-lg font-bold text-slate-900">
              {(detail.diff_confidence * 100).toFixed(1)}%
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${detail.diff_confidence * 100}%` }}
              transition={{ type: "spring", stiffness: 60, damping: 15 }}
              className={`h-full rounded-full ${
                detail.diff_confidence >= 0.9
                  ? "bg-emerald-500"
                  : detail.diff_confidence >= 0.7
                    ? "bg-amber-400"
                    : "bg-rose-500"
              }`}
            />
          </div>
          {/* 比对差异 */}
          {detail.diff_conflicts && detail.diff_conflicts.length > 0 && (
            <div className="mt-3 space-y-1.5">
              <p className="text-xs font-medium text-slate-500">
                OCR / LLM 比对差异（{detail.diff_conflicts.length} 项）
              </p>
              {detail.diff_conflicts.map((c, i) => (
                <div
                  key={i}
                  className={`rounded-lg border p-2.5 text-xs ${
                    c.status === "RESOLVED"
                      ? "border-emerald-200 bg-emerald-50/50"
                      : c.status === "CONFLICT"
                        ? "border-amber-200 bg-amber-50/50"
                        : "border-slate-200 bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-slate-700">
                      {c.field || "—"}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        c.status === "RESOLVED"
                          ? "bg-emerald-100 text-emerald-700"
                          : c.status === "CONFLICT"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {c.status === "RESOLVED"
                        ? "已解决"
                        : c.status === "CONFLICT"
                          ? "待确认"
                          : c.status
                        ? "已解决"
                        : c.status === "CONFLICT"
                          ? "待确认"
                          : c.status}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-1 text-slate-500">
                    <span className="truncate" title={c.ocr_value || ""}>
                      OCR: {c.ocr_value || "—"}
                    </span>
                    <span className="text-slate-300">/</span>
                    <span className="truncate" title={c.llm_value || ""}>
                      LLM: {c.llm_value || "—"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 重复预警 */}
      {detail.duplicate_status === "DUPLICATE" && (
        <div className="flex items-start gap-2 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">
          <Warning size={18} className="mt-0.5 shrink-0" />
          <span>该发票与已有记录重复，请确认是否为重复提交。</span>
        </div>
      )}

      {/* 验真失败预警 */}
      {detail.verify_status === "INVALID" && (
        <div className="flex items-start gap-2 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">
          <Warning size={18} className="mt-0.5 shrink-0" />
          <span>{detail.verify_message || "该发票在线验真未通过，请核实发票信息。"}</span>
        </div>
      )}
      {/* 验真通过提示 */}
      {detail.verify_status === "VALID" && detail.verify_message && (
        <div className="flex items-start gap-2 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-700">
          <ShieldCheck size={18} className="mt-0.5 shrink-0" />
          <span>{detail.verify_message}</span>
        </div>
      )}

      {/* OCR 提取字段 */}
      <div>
        <h3 className="mb-3 flex items-center gap-1.5 font-display text-sm font-semibold text-slate-700">
          <CopySimple size={16} className="text-slate-400" />
          票面信息
        </h3>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3">
          {fields.map((field) => (
            <div
              key={field.label}
              className={`rounded-lg p-2.5 ${
                field.highlight
                  ? "bg-brand-50 ring-1 ring-brand-200"
                  : "bg-slate-50"
              }`}
            >
              <dt className="text-xs text-slate-400">{field.label}</dt>
              <dd
                className={`mt-0.5 truncate text-sm font-medium ${
                  field.highlight ? "text-brand-700" : "text-slate-800"
                }`}
                title={field.value || ""}
              >
                {field.value || (
                  <span className="text-slate-300">未提取到</span>
                )}
              </dd>
            </div>
          ))}
        </div>
      </div>

      {/* 费用分类 */}
      <div>
        <h3 className="mb-3 font-display text-sm font-semibold text-slate-700">
          费用分类
        </h3>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3">
          <div className="rounded-lg bg-slate-50 p-2.5">
            <dt className="text-xs text-slate-400">费用大类</dt>
            <dd className="mt-0.5 text-sm font-medium text-slate-800">
              {detail.fee_category === "company"
                ? "公司"
                : detail.fee_category === "personal"
                  ? "个人"
                  : "未分类"}
            </dd>
          </div>
          <div className="rounded-lg bg-slate-50 p-2.5">
            <dt className="text-xs text-slate-400">费用子类</dt>
            <dd className="mt-0.5 text-sm font-medium text-slate-800">
              {detail.fee_subcategory || (
                <span className="text-slate-300">未分类</span>
              )}
            </dd>
          </div>
        </div>
      </div>

      {/* 用户描述 */}
      {detail.user_description && (
        <div>
          <h3 className="mb-2 font-display text-sm font-semibold text-slate-700">
            用户描述
          </h3>
          <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
            {detail.user_description}
          </p>
        </div>
      )}

      {/* 元信息 */}
      <div className="border-t border-slate-200/60 pt-4">
        <dl className="space-y-2 text-sm">
          {detail.reimbursement_id && (
            <div className="flex justify-between">
              <dt className="text-slate-400">所属报销单</dt>
              <dd className="font-mono text-brand-600">
                #{detail.reimbursement_id}
              </dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-slate-400">发票 ID</dt>
            <dd className="font-mono text-slate-600">#{detail.id}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-400">提交时间</dt>
            <dd className="text-slate-600">
              {detail.created_at
                ? new Date(detail.created_at).toLocaleString("zh-CN")
                : "—"}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}


