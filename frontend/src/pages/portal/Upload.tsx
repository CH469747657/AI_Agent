import { useState, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { portalApi } from "../../api/client";
import type { Invoice } from "../../types";
import {
  UploadSimple,
  FileImage,
  FilePdf,
  CheckCircle,
  Warning,
  X,
  ArrowRight,
  Spinner,
  Receipt,
} from "@phosphor-icons/react";

const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB

const ACCEPTED_TYPES = [
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/gif",
  "image/bmp",
  "image/webp",
  "application/pdf",
  "application/ofd",
];

const ACCEPT_ATTR = "image/*,.pdf,.ofd";

const receiptTypes = [
  "增值税普通发票",
  "增值税专用发票",
  "火车票",
  "机票",
  "收据",
  "支付截图",
  "交易流水单",
];

const NONSTANDARD_TYPES = new Set(["收据", "支付截图", "交易流水单"]);

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileIcon(file: File) {
  if (file.type === "application/pdf" || file.name.endsWith(".pdf")) {
    return <FilePdf size={20} className="text-red-500" weight="fill" />;
  }
  if (file.type === "application/ofd" || file.name.endsWith(".ofd")) {
    return <FilePdf size={20} className="text-orange-500" weight="fill" />;
  }
  return <FileImage size={20} className="text-blue-500" />;
}

export function PortalUpload() {
  // 表单状态
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [receiptType, setReceiptType] = useState("增值税普通发票");
  const [dragOver, setDragOver] = useState(false);

  // 请求状态
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<Invoice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (f: File) => {
      // 格式校验
      const ext = f.name.split(".").pop()?.toLowerCase();
      const isAccepted =
        ACCEPTED_TYPES.includes(f.type) ||
        ["png", "jpg", "jpeg", "gif", "bmp", "webp", "pdf", "ofd"].includes(ext || "");

      if (!isAccepted) {
        setError("不支持的文件格式，请上传 PNG / JPG / GIF / BMP / WEBP / PDF / OFD 文件");
        return;
      }

      // 大小校验
      if (f.size > MAX_FILE_SIZE) {
        setError(`文件大小不能超过 20MB，当前文件 ${formatFileSize(f.size)}`);
        return;
      }

      setFile(f);
      setResult(null);
      setError(null);
    },
    []
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile]
  );

  const handleUpload = async () => {
    if (!file) return;
    if (!description.trim()) {
      setError("请填写备注说明");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const res = await portalApi.uploadInvoice(file, {
        description,
        receipt_type: receiptType,
      });
      setResult(res);
      setFile(null);
      setDescription("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const reset = () => {
    setFile(null);
    setResult(null);
    setError(null);
    setDescription("");
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {/* 标题 */}
      <div>
        <h1 className="font-display text-xl font-bold tracking-tight text-slate-900">
          上传发票
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          上传发票图片或 PDF，系统将自动进行 OCR 识别、费用分类与查重
        </p>
      </div>

      {/* 上传区域 / 文件预览 */}
      {!file && !result && (
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed py-16 transition-colors ${
            dragOver
              ? "border-brand-500 bg-brand-50"
              : "border-slate-300 bg-white hover:border-brand-400 hover:bg-slate-50"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT_ATTR}
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
              // 重置 value 以便同一文件可重复选择
              e.target.value = "";
            }}
          />
          <motion.div
            animate={{ y: dragOver ? -4 : 0 }}
            className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50"
          >
            <UploadSimple size={28} className="text-brand-600" />
          </motion.div>
          <p className="mt-4 font-display text-base font-semibold text-slate-700">
            拖拽发票到此处，或点击选择文件
          </p>
          <p className="mt-1 text-sm text-slate-400">
            支持 PNG / JPG / GIF / BMP / WEBP / PDF / OFD 格式，单文件最大 20MB
          </p>
        </label>
      )}

      {/* 文件信息 + 表单 */}
      {file && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-4"
        >
          {/* 文件卡片 */}
          <div className="flex items-center gap-3 rounded-xl border border-slate-200/60 bg-white p-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100">
              {getFileIcon(file)}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-800">
                {file.name}
              </p>
              <p className="text-xs text-slate-400">
                {formatFileSize(file.size)} · {file.type || "未知类型"}
              </p>
            </div>
            <button
              onClick={() => {
                setFile(null);
                setError(null);
              }}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100"
              aria-label="移除文件"
            >
              <X size={16} />
            </button>
          </div>

          {/* 票据类型 + 描述 */}
          <div className="space-y-4 rounded-xl border border-slate-200/60 bg-white p-5">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">
                票据类型
              </label>
              <select
                value={receiptType}
                onChange={(e) => setReceiptType(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              >
                {receiptTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              {NONSTANDARD_TYPES.has(receiptType) && (
                <p className="mt-1.5 text-xs text-amber-600">
                  非标准票据将使用 AI 视觉识别提取信息，不支持在线验真，建议填写详细备注以便审核。
                </p>
              )}
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">
                备注说明 <span className="text-rose-500">*</span>
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                placeholder="例如：7月份差旅住宿费"
              />
            </div>
          </div>

          {/* 错误提示 */}
          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700"
              >
                <Warning size={18} weight="fill" />
                {error}
              </motion.div>
            )}
          </AnimatePresence>

          {/* 上传按钮 */}
          <button
            onClick={handleUpload}
            disabled={uploading || !description.trim()}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white transition-all hover:bg-brand-700 disabled:opacity-50 active:scale-[0.98]"
          >
            {uploading ? (
              <>
                <Spinner size={18} className="animate-spin" />
                正在识别中...
              </>
            ) : (
              <>
                <UploadSimple size={18} />
                开始上传并识别
              </>
            )}
          </button>

          {/* 处理时间线 */}
          <AnimatePresence>
            {uploading && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <div className="rounded-xl border border-brand-200 bg-brand-50/30 p-4">
                  <ProcessingTimeline uploading />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {/* 上传结果 */}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-2xl border border-emerald-200 bg-emerald-50/50 p-5"
          >
            <div className="flex items-center gap-2">
              <CheckCircle size={20} className="text-emerald-600" weight="fill" />
              <h3 className="font-display text-base font-semibold text-emerald-800">
                识别完成
              </h3>
            </div>

            {/* 处理时间线（完成状态） */}
            <div className="mt-4">
              <ProcessingTimeline result={result} />
            </div>

            {/* 识别字段 */}
            <div className="mt-4 grid grid-cols-2 gap-3">
              <ResultField label="发票号码" value={result.invoice_number} />
              <ResultField label="开票日期" value={result.issue_date} />
              <ResultField label="销方名称" value={result.seller_name} span />
              <ResultField
                label="价税合计"
                value={result.total_with_tax ? `¥${result.total_with_tax}` : null}
              />
              <ResultField
                label="费用分类"
                value={
                  result.fee_category === "company"
                    ? `公司 / ${result.fee_subcategory}`
                    : result.fee_category === "personal"
                      ? `个人 / ${result.fee_subcategory}`
                      : null
                }
              />
              <ResultField
                label={result.is_nonstandard ? "VLM置信度" : "置信度"}
                value={
                  result.is_nonstandard && result.vlm_confidence !== null && result.vlm_confidence !== undefined
                    ? `${(result.vlm_confidence * 100).toFixed(1)}%`
                    : result.diff_confidence !== null && result.diff_confidence !== undefined
                      ? `${(result.diff_confidence * 100).toFixed(1)}%`
                      : null
                }
              />
              {result.is_nonstandard && result.risk_level && (
                <ResultField
                  label="风险等级"
                  value={
                    result.risk_level === "high"
                      ? "高风险"
                      : result.risk_level === "medium"
                        ? "中风险"
                        : result.risk_level === "low"
                          ? "低风险"
                          : null
                  }
                />
              )}
              <ResultField
                label="查重状态"
                value={
                  result.duplicate_status === "DUPLICATE"
                    ? "重复"
                    : result.duplicate_status === "UNIQUE"
                      ? "唯一"
                      : "待查重"
                }
              />
              <ResultField
                label="验真状态"
                value={
                  result.verify_status === "VALID"
                    ? "验真通过"
                    : result.verify_status === "INVALID"
                      ? "验真失败"
                      : result.verify_status === "UNABLE_TO_VERIFY"
                        ? "无法验真"
                        : result.verify_status === "PENDING"
                          ? "待验真"
                          : null
                }
              />
            </div>

            {/* 操作按钮 */}
            <div className="mt-4 flex gap-3">
              <Link
                to="/portal/invoices"
                className="flex items-center gap-1.5 rounded-lg bg-white px-4 py-2 text-sm font-medium text-brand-600 ring-1 ring-brand-200 transition-colors hover:bg-brand-50"
              >
                查看发票
                <ArrowRight size={14} />
              </Link>
              <button
                onClick={reset}
                className="flex items-center gap-1.5 rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-600 ring-1 ring-slate-200 transition-colors hover:bg-slate-50"
              >
                <UploadSimple size={14} />
                继续上传
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 独立错误提示（无文件时） */}
      {error && !file && (
        <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
          <Warning size={18} weight="fill" />
          {error}
        </div>
      )}
    </div>
  );
}

/* ---------- 处理时间线 ---------- */

function ProcessingTimeline({
  uploading,
  result,
}: {
  uploading?: boolean;
  result?: Invoice | null;
}) {
  const steps: {
    label: string;
    detail: string;
    done: boolean;
    processing: boolean;
    warning: boolean;
  }[] = [
    {
      label: "文件上传",
      detail: "已完成",
      done: true,
      processing: false,
      warning: false,
    },
    {
      label: "OCR 识别",
      detail: result
        ? "已提取发票字段"
        : uploading
          ? "正在识别..."
          : "等待中",
      done: !!result,
      processing: !!uploading && !result,
      warning: false,
    },
    {
      label: "费用分类",
      detail: result
        ? `${result.fee_category === "company" ? "公司" : "个人"}${
            result.fee_subcategory ? ` / ${result.fee_subcategory}` : ""
          }`
        : "等待中",
      done: !!result,
      processing: false,
      warning: false,
    },
    {
      label: "查重检测",
      detail: result
        ? result.duplicate_status === "DUPLICATE"
          ? "检测到重复"
          : result.duplicate_status === "UNIQUE"
            ? "唯一"
            : "待查重"
        : "等待中",
      done: !!result,
      processing: false,
      warning: result?.duplicate_status === "DUPLICATE",
    },
    {
      label: "发票验真",
      detail: result
        ? result.verify_status === "VALID"
          ? "验真通过"
          : result.verify_status === "INVALID"
            ? "验真失败"
            : result.verify_status === "UNABLE_TO_VERIFY"
              ? "无法验真"
              : "待验真"
        : "等待中",
      done: !!result,
      processing: false,
      warning: result?.verify_status === "INVALID",
    },
  ];

  return (
    <div>
      {steps.map((step, index) => (
        <div key={step.label} className="flex gap-3">
          {/* 左侧：图标 + 连线 */}
          <div className="flex flex-col items-center">
            {step.done ? (
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500">
                <CheckCircle size={14} className="text-white" weight="fill" />
              </div>
            ) : step.processing ? (
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-100">
                <Spinner size={14} className="animate-spin text-brand-600" />
              </div>
            ) : (
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-100">
                <span className="h-2 w-2 rounded-full bg-slate-300" />
              </div>
            )}
            {index < steps.length - 1 && (
              <div
                className={`my-0.5 h-6 w-0.5 ${
                  step.done ? "bg-emerald-300" : "bg-slate-200"
                }`}
              />
            )}
          </div>
          {/* 右侧：标签 + 详情 */}
          <div className="pb-3">
            <p
              className={`text-sm font-medium ${
                step.done ? "text-slate-700" : "text-slate-400"
              }`}
            >
              {step.label}
            </p>
            <p
              className={`text-xs ${
                step.warning
                  ? "text-rose-500"
                  : step.done
                    ? "text-slate-500"
                    : "text-slate-400"
              }`}
            >
              {step.detail}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------- 结果字段组件 ---------- */

function ResultField({
  label,
  value,
  span,
}: {
  label: string;
  value: string | null;
  span?: boolean;
}) {
  return (
    <div className={span ? "col-span-2" : ""}>
      <dt className="text-xs text-emerald-600/70">{label}</dt>
      <dd className="mt-0.5 truncate text-sm font-medium text-slate-800">
        {value || <span className="text-slate-300">未提取到</span>}
      </dd>
    </div>
  );
}
