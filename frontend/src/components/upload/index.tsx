import { motion } from "framer-motion";
import {
  UploadSimple,
  FileImage,
  FilePdf,
  X,
  CheckCircle,
  Spinner,
  ArrowRight,
} from "@phosphor-icons/react";
import type { Invoice } from "../../types";
import type { ReactNode } from "react";

/* ---------- Constants ---------- */

export const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB

export const ACCEPTED_TYPES = [
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/gif",
  "image/bmp",
  "image/webp",
  "application/pdf",
  "application/ofd",
];

export const ACCEPT_ATTR = "image/*,.pdf,.ofd";

export const receiptTypes = [
  "增值税普通发票",
  "增值税专用发票",
  "火车票",
  "机票",
  "收据",
  "支付截图",
  "交易流水单",
];

export const NONSTANDARD_TYPES = new Set(["收据", "支付截图", "交易流水单"]);

/* ---------- Utils ---------- */

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function getFileIcon(file: File): ReactNode {
  if (file.type === "application/pdf" || file.name.endsWith(".pdf")) {
    return <FilePdf size={20} className="text-red-500" weight="fill" />;
  }
  if (file.type === "application/ofd" || file.name.endsWith(".ofd")) {
    return <FilePdf size={20} className="text-orange-500" weight="fill" />;
  }
  return <FileImage size={20} className="text-blue-500" />;
}

/* ---------- FileDropZone ---------- */

export function FileDropZone({
  onFile,
  dragOver,
  setDragOver,
  inputRef,
}: {
  onFile: (f: File) => void;
  dragOver: boolean;
  setDragOver: (v: boolean) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const f = e.dataTransfer.files[0];
        if (f) onFile(f);
      }}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed py-12 transition-colors sm:py-16 ${
        dragOver
          ? "border-primary-500 bg-primary-50"
          : "border-border bg-background hover:border-primary-400 hover:bg-muted"
      }`}
    >
      {/* 单一 file input：accept 含图片+PDF+OFD
          手机端点击弹出系统菜单（拍照/相册/文件），桌面端打开文件选择器
          不用 capture 属性——它会强制只调相机，丢失 PDF/OFD 上传能力 */}
      <input
        ref={inputRef as React.RefObject<HTMLInputElement>}
        type="file"
        accept={ACCEPT_ATTR}
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      <motion.div
        animate={{ y: dragOver ? -4 : 0 }}
        className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-50"
      >
        <UploadSimple size={28} className="text-primary-600" />
      </motion.div>
      <p className="mt-4 font-display text-base font-semibold text-foreground">
        点击拍照或选择文件
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        支持 PNG / JPG / GIF / BMP / WEBP / PDF / OFD 格式，单文件最大 20MB
      </p>
    </label>
  );
}

/* ---------- FilePreviewCard ---------- */

export function FilePreviewCard({
  file,
  onRemove,
}: {
  file: File;
  onRemove: () => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-background p-4">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
        {getFileIcon(file)}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">
          {file.name}
        </p>
        <p className="text-xs text-muted-foreground">
          {formatFileSize(file.size)} · {file.type || "未知类型"}
        </p>
      </div>
      <button
        onClick={onRemove}
        className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted"
        aria-label="移除文件"
      >
        <X size={16} />
      </button>
    </div>
  );
}

/* ---------- ProcessingTimeline ---------- */

export function ProcessingTimeline({
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
          <div className="flex flex-col items-center">
            {step.done ? (
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500">
                <CheckCircle
                  size={14}
                  className="text-white"
                  weight="fill"
                />
              </div>
            ) : step.processing ? (
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary-100">
                <Spinner size={14} className="animate-spin text-primary-600" />
              </div>
            ) : (
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-muted">
                <span className="h-2 w-2 rounded-full bg-muted" />
              </div>
            )}
            {index < steps.length - 1 && (
              <div
                className={`my-0.5 h-6 w-0.5 ${
                  step.done ? "bg-emerald-300" : "bg-muted"
                }`}
              />
            )}
          </div>
          <div className="pb-3">
            <p
              className={`text-sm font-medium ${
                step.done ? "text-foreground" : "text-muted-foreground"
              }`}
            >
              {step.label}
            </p>
            <p
              className={`text-xs ${
                step.warning
                  ? "text-rose-500"
                  : step.done
                    ? "text-muted-foreground"
                    : "text-muted-foreground"
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

/* ---------- ResultField ---------- */

export function ResultField({
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
      <dd className="mt-0.5 truncate text-sm font-medium text-foreground">
        {value || <span className="text-muted-foreground">未提取到</span>}
      </dd>
    </div>
  );
}

/* ---------- UploadResult ---------- */

export function UploadResult({
  result,
  onViewDetail,
  onReset,
  viewDetailText = "查看详情",
}: {
  result: Invoice;
  onViewDetail: () => void;
  onReset: () => void;
  viewDetailText?: string;
}) {
  return (
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

      <div className="mt-4">
        <ProcessingTimeline result={result} />
      </div>

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

      <div className="mt-4 flex gap-3">
        <button
          onClick={onViewDetail}
          className="flex items-center gap-1.5 rounded-lg bg-background px-4 py-2 text-sm font-medium text-primary-600 ring-1 ring-primary-200 transition-colors hover:bg-primary-50"
        >
          {viewDetailText}
          <ArrowRight size={14} />
        </button>
        <button
          onClick={onReset}
          className="flex items-center gap-1.5 rounded-lg bg-background px-4 py-2 text-sm font-medium text-foreground ring-1 ring-border transition-colors hover:bg-muted"
        >
          <UploadSimple size={14} />
          继续上传
        </button>
      </div>
    </motion.div>
  );
}
