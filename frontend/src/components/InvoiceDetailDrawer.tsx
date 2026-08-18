import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Receipt,
  Warning,
  PencilSimple,
  Check,
  ShieldCheck,
  Globe,
  Info,
  CheckCircle,
  XCircle,
  Spinner,
} from "@phosphor-icons/react";
import { useState, useEffect } from "react";
import type { InvoiceDetail, InvoiceUpdate, VerifyStatus } from "../types";
import { invoiceApi } from "../api/client";
import {
  StatusBadge,
  VerifyBadge,
  DuplicateBadge,
  CategoryBadge,
} from "./StatusBadge";

interface DetailDrawerProps {
  invoiceId: number | null;
  onClose: () => void;
}

export function InvoiceDetailDrawer({ invoiceId, onClose }: DetailDrawerProps) {
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
    invoiceApi
      .detail(invoiceId)
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
            className="fixed inset-0 z-40 bg-sidebar-bg/30 backdrop-blur-sm"
          />

          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="fixed right-0 top-0 z-50 flex h-[100dvh] w-full max-w-xl flex-col bg-white shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border/60 px-6 py-4">
              <div className="flex items-center gap-2">
                <Receipt size={20} className="text-primary-600" />
                <h2 className="font-display text-base font-semibold text-foreground">
                  发票详情
                </h2>
              </div>
              <button
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground/70"
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
                      <div className="h-4 w-20 animate-pulse rounded bg-muted" />
                      <div className="h-4 flex-1 animate-pulse rounded bg-muted" />
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

              {detail && !loading && (
                <DetailContent
                  detail={detail}
                  onUpdate={(updated) => setDetail(updated)}
                />
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function DetailContent({
  detail,
  onUpdate,
}: {
  detail: InvoiceDetail;
  onUpdate: (updated: InvoiceDetail) => void;
}) {
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editForm, setEditForm] = useState<InvoiceUpdate>({});
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [onlineVerifyLoading, setOnlineVerifyLoading] = useState(false);
  const [verifyMessage, setVerifyMessage] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);

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

  const isNonstandard = detail.is_nonstandard === true;

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await invoiceApi.update(detail.id, editForm);
      onUpdate(updated);
      setEditMode(false);
    } catch (e) {
      // Keep edit mode on error
    } finally {
      setSaving(false);
    }
  };

  const handleVerify = async (status: VerifyStatus) => {
    setVerifyLoading(true);
    try {
      const updated = await invoiceApi.verify(detail.id, status);
      onUpdate(updated);
      setVerifyMessage(null);
    } finally {
      setVerifyLoading(false);
    }
  };

  const handleOnlineVerify = async () => {
    setOnlineVerifyLoading(true);
    setVerifyMessage(null);
    try {
      const result = await invoiceApi.onlineVerify(detail.id);
      setVerifyMessage(result.message);
      if (result.invoice) {
        onUpdate(result.invoice);
      }
    } catch (e) {
      setVerifyMessage(e instanceof Error ? e.message : "在线验真失败");
    } finally {
      setOnlineVerifyLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Status row + edit toggle */}
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={detail.status} linked={!!detail.reimbursement_id} />
        <VerifyBadge status={detail.verify_status} />
        <DuplicateBadge status={detail.duplicate_status} />
        <CategoryBadge category={detail.fee_category} subcategory={detail.fee_subcategory} />
        <button
          onClick={() => {
            if (editMode) {
              setEditForm({});
              setEditMode(false);
            } else {
              setEditForm({
                fee_category: detail.fee_category,
                fee_subcategory: detail.fee_subcategory,
                status: detail.status,
                user_description: detail.user_description,
              });
              setEditMode(true);
            }
          }}
          className="ml-auto flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-foreground/70 transition-colors hover:bg-muted"
        >
          <PencilSimple size={14} />
          {editMode ? "取消" : "编辑"}
        </button>
        {editMode && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1 rounded-lg bg-primary-600 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
          >
            <Check size={14} />
            {saving ? "保存中..." : "保存"}
          </button>
        )}
        {/* 审核操作：仅待审核状态显示 */}
        {detail.status === "REVIEWING" && !editMode && (
          <>
            <button
              onClick={async () => {
                setApproving(true);
                try {
                  const updated = await invoiceApi.approve(detail.id);
                  onUpdate(updated);
                } catch (e) {
                  /* ignore */
                } finally {
                  setApproving(false);
                }
              }}
              disabled={approving}
              className="flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
            >
              {approving ? <Spinner size={14} className="animate-spin" /> : <CheckCircle size={14} />}
              审核通过
            </button>
            <button
              onClick={async () => {
                setRejecting(true);
                try {
                  const updated = await invoiceApi.reject(detail.id);
                  onUpdate(updated);
                } catch (e) {
                  /* ignore */
                } finally {
                  setRejecting(false);
                }
              }}
              disabled={rejecting}
              className="flex items-center gap-1 rounded-lg bg-rose-600 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-rose-700 disabled:opacity-50"
            >
              {rejecting ? <Spinner size={14} className="animate-spin" /> : <XCircle size={14} />}
              驳回
            </button>
          </>
        )}
      </div>

      {/* Confidence */}
      {(detail.diff_confidence !== null && detail.diff_confidence !== undefined) && !isNonstandard && (
        <div className="rounded-xl border border-border/60 bg-muted p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-foreground/70">双源比对置信度</span>
            <span className="font-display text-lg font-bold text-foreground">
              {(detail.diff_confidence * 100).toFixed(1)}%
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
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
          {/* Diff conflicts — 仅 PDF/OFD 双源场景展示，图片发票走单源 LLM 无 OCR 比对 */}
          {detail.diff_conflicts && detail.diff_conflicts.length > 0
            && detail.file_type
            && !["jpg", "jpeg", "png", "gif", "bmp", "webp"].includes(detail.file_type.toLowerCase()) && (
            <div className="mt-3 space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">
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
                        : "border-border bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-foreground/80">{c.field}</span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        c.status === "RESOLVED"
                          ? "bg-emerald-100 text-emerald-700"
                          : c.status === "CONFLICT"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-muted text-foreground/70"
                      }`}
                    >
                      {c.status === "RESOLVED"
                        ? "已解决"
                        : c.status === "CONFLICT"
                          ? "待确认"
                          : c.status}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-1 text-muted-foreground">
                    <span className="truncate" title={String(c.ocr_value || "")}>
                      OCR: {c.ocr_value || "—"}
                    </span>
                    <span className="text-muted-foreground">/</span>
                    <span className="truncate" title={String(c.llm_value || "")}>
                      LLM: {c.llm_value || "—"}
                    </span>
                  </div>
                  {c.resolved_reason && (
                    <p className="mt-1 text-[10px] text-emerald-600">
                      {c.resolved_by === "cross_validation"
                        ? "交叉验证"
                        : c.resolved_by === "llm"
                          ? "文本优先LLM"
                          : c.resolved_by === "ocr"
                            ? "数字优先OCR"
                            : c.resolved_by}
                      ：{c.resolved_reason}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* VLM Confidence (nonstandard) */}
      {isNonstandard && detail.vlm_confidence !== null && detail.vlm_confidence !== undefined && (
        <div className="rounded-xl border border-amber-200/60 bg-amber-50/50 p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-foreground/70">VLM 识别置信度</span>
            <span className="font-display text-lg font-bold text-foreground">
              {(detail.vlm_confidence * 100).toFixed(1)}%
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full ${
                detail.vlm_confidence >= 0.8
                  ? "bg-emerald-500"
                  : detail.vlm_confidence >= 0.5
                    ? "bg-amber-400"
                    : "bg-rose-500"
              }`}
              style={{ width: `${detail.vlm_confidence * 100}%` }}
            />
          </div>
          {detail.risk_level && (
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs text-muted-foreground">风险等级:</span>
              <span
                className={`rounded-md px-2 py-0.5 text-xs font-medium ${
                  detail.risk_level === "high"
                    ? "bg-rose-100 text-rose-700"
                    : detail.risk_level === "medium"
                      ? "bg-amber-100 text-amber-700"
                      : "bg-emerald-100 text-emerald-700"
                }`}
              >
                {detail.risk_level === "high" ? "高风险" : detail.risk_level === "medium" ? "中风险" : "低风险"}
              </span>
            </div>
          )}
          {detail.receipt_detail && Object.keys(detail.receipt_detail).length > 0 && (
            <div className="mt-3 space-y-1">
              <p className="text-xs font-medium text-muted-foreground">VLM 提取详情</p>
              <div className="grid grid-cols-2 gap-1.5">
                {Object.entries(detail.receipt_detail)
                  .filter(([_, v]) => v !== null && v !== undefined && v !== "")
                  .map(([key, val]) => (
                    <div key={key} className="rounded-md bg-white px-2 py-1.5 text-xs">
                      <dt className="text-muted-foreground">{key}</dt>
                      <dd className="mt-0.5 truncate font-medium text-foreground/80">{String(val)}</dd>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Nonstandard badge */}
      {isNonstandard && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-200/60 bg-amber-50/50 p-3">
          <Info size={16} className="text-amber-600" />
          <span className="text-xs text-amber-700">
            此票据为非标准票据，由 AI 视觉识别提取信息，不支持在线验真。请结合风险等级和备注信息进行审核。
          </span>
        </div>
      )}

      {/* Duplicate warning */}
      {detail.duplicate_status === "DUPLICATE" && (
        <div className="flex items-start gap-2 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">
          <Warning size={18} className="mt-0.5 shrink-0" />
          <span>该发票与已有记录重复，请确认是否为重复提交。</span>
        </div>
      )}

      {/* Verify action (non-edit mode, standard invoices only) */}
      {!editMode && !isNonstandard && (
        <div className="rounded-xl border border-border/60 p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldCheck size={16} className="text-muted-foreground" />
              <span className="text-sm text-foreground/70">发票验真</span>
            </div>
            <button
              onClick={handleOnlineVerify}
              disabled={onlineVerifyLoading}
              className="flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
            >
              <Globe size={14} />
              {onlineVerifyLoading ? "验真中..." : "在线验真"}
            </button>
          </div>

          {/* Verify message — persistent from backend + transient from current action */}
          {(detail.verify_message || verifyMessage) && (
            <div
              className={`mt-2 flex items-start gap-2 rounded-lg p-2.5 text-xs ${
                detail.verify_status === "VALID"
                  ? "bg-emerald-50 text-emerald-700"
                  : detail.verify_status === "INVALID"
                    ? "bg-rose-50 text-rose-700"
                    : "bg-amber-50 text-amber-700"
              }`}
            >
              <Info size={14} className="mt-0.5 shrink-0" />
              <span>{verifyMessage || detail.verify_message}</span>
            </div>
          )}

          {/* Divider */}
          <div className="my-2 border-t border-border" />

          {/* Manual verify buttons */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">手动标记:</span>
            <button
              onClick={() => handleVerify("VALID")}
              disabled={verifyLoading || detail.verify_status === "VALID"}
              className="rounded-lg bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-100 disabled:opacity-40"
            >
              有效
            </button>
            <button
              onClick={() => handleVerify("INVALID")}
              disabled={verifyLoading || detail.verify_status === "INVALID"}
              className="rounded-lg bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-100 disabled:opacity-40"
            >
              无效
            </button>
            <button
              onClick={() => handleVerify("UNABLE_TO_VERIFY")}
              disabled={verifyLoading || detail.verify_status === "UNABLE_TO_VERIFY"}
              className="rounded-lg bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-100 disabled:opacity-40"
            >
              无法验真
            </button>
          </div>
        </div>
      )}

      {/* OCR Fields */}
      <div>
        <h3 className="mb-3 font-display text-sm font-semibold text-foreground/80">
          {isNonstandard ? "VLM 提取字段" : "OCR 提取字段"}
        </h3>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3">
          {fields.map((field) => (
            <div
              key={field.label}
              className={`rounded-lg p-2.5 ${
                field.highlight
                  ? "bg-primary-50 ring-1 ring-primary-200"
                  : "bg-muted"
              }`}
            >
              <dt className="text-xs text-muted-foreground">{field.label}</dt>
              <dd
                className={`mt-0.5 truncate text-sm font-medium ${
                  field.highlight ? "text-primary-700" : "text-foreground"
                }`}
                title={field.value || ""}
              >
                {field.value || (
                  <span className="text-muted-foreground">未提取到</span>
                )}
              </dd>
            </div>
          ))}
        </div>
      </div>

      {/* Classification — editable */}
      <div>
        <h3 className="mb-3 font-display text-sm font-semibold text-foreground/80">
          费用分类 & 状态
        </h3>
        {editMode ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <div className="rounded-lg bg-muted p-2.5">
                <label className="text-xs text-muted-foreground">费用大类</label>
                <select
                  value={editForm.fee_category || ""}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      fee_category: e.target.value as InvoiceUpdate["fee_category"],
                    })
                  }
                  className="mt-1 w-full rounded-lg border border-border bg-white px-2 py-1.5 text-sm text-foreground/80 outline-none focus:border-primary-400"
                >
                  <option value="">未分类</option>
                  <option value="company">公司</option>
                  <option value="personal">个人</option>
                </select>
              </div>
              <div className="rounded-lg bg-muted p-2.5">
                <label className="text-xs text-muted-foreground">费用子类</label>
                <input
                  type="text"
                  value={editForm.fee_subcategory || ""}
                  onChange={(e) =>
                    setEditForm({ ...editForm, fee_subcategory: e.target.value })
                  }
                  placeholder="如: 交通费"
                  className="mt-1 w-full rounded-lg border border-border bg-white px-2 py-1.5 text-sm text-foreground/80 outline-none focus:border-primary-400"
                />
              </div>
              <div className="rounded-lg bg-muted p-2.5">
                <label className="text-xs text-muted-foreground">发票状态</label>
                <select
                  value={editForm.status || ""}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      status: e.target.value as InvoiceUpdate["status"],
                    })
                  }
                  className="mt-1 w-full rounded-lg border border-border bg-white px-2 py-1.5 text-sm text-foreground/80 outline-none focus:border-primary-400"
                >
                  <option value="UPLOADED">已上传</option>
                  <option value="PROCESSING">处理中</option>
                  <option value="REVIEWING">待审核</option>
                  <option value="CONFIRMED">已确认</option>
                  <option value="REIMBURSED">已报销</option>
                  <option value="NOT_REIMBURSED">不予报销</option>
                </select>
              </div>
            </div>
            <div className="rounded-lg bg-muted p-2.5">
              <label className="text-xs text-muted-foreground">备注说明</label>
              <textarea
                value={editForm.user_description || ""}
                onChange={(e) =>
                  setEditForm({ ...editForm, user_description: e.target.value })
                }
                rows={2}
                placeholder="补充说明..."
                className="mt-1 w-full rounded-lg border border-border bg-white px-2 py-1.5 text-sm text-foreground/80 outline-none focus:border-primary-400"
              />
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            <div className="rounded-lg bg-muted p-2.5">
              <dt className="text-xs text-muted-foreground">费用大类</dt>
              <dd className="mt-0.5 text-sm font-medium text-foreground">
                {detail.fee_category === "company"
                  ? "公司"
                  : detail.fee_category === "personal"
                    ? "个人"
                    : "未分类"}
              </dd>
            </div>
            <div className="rounded-lg bg-muted p-2.5">
              <dt className="text-xs text-muted-foreground">费用子类</dt>
              <dd className="mt-0.5 text-sm font-medium text-foreground">
                {detail.fee_subcategory || (
                  <span className="text-muted-foreground">未分类</span>
                )}
              </dd>
            </div>
          </div>
        )}
      </div>

      {/* User description (read mode) */}
      {!editMode && detail.user_description && (
        <div>
          <h3 className="mb-2 font-display text-sm font-semibold text-foreground/80">
            备注说明
          </h3>
          <p className="rounded-lg bg-muted p-3 text-sm text-foreground/70">
            {detail.user_description}
          </p>
        </div>
      )}

      {/* Meta */}
      <div className="border-t border-border/60 pt-4">
        <dl className="space-y-2 text-sm">
          {detail.reimbursement_id && (
            <div className="flex justify-between">
              <dt className="text-muted-foreground">所属报销单</dt>
              <dd className="font-mono text-primary-600">
                #{detail.reimbursement_id}
              </dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-muted-foreground">发票 ID</dt>
            <dd className="font-mono text-foreground/70">#{detail.id}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">提交时间</dt>
            <dd className="text-foreground/70">
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
