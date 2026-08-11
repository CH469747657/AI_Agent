import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { portalApi } from "../../api/client";
import type { Invoice } from "../../types";
import {
  MAX_FILE_SIZE,
  ACCEPTED_TYPES,
  receiptTypes,
  NONSTANDARD_TYPES,
  FileDropZone,
  FilePreviewCard,
  ProcessingTimeline,
  UploadResult,
} from "../../components/upload";
import { UploadSimple, Warning, Spinner } from "@phosphor-icons/react";

export function PortalUpload() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [receiptType, setReceiptType] = useState("增值税普通发票");
  const [dragOver, setDragOver] = useState(false);

  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<Invoice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    const isAccepted =
      ACCEPTED_TYPES.includes(f.type) ||
      ["png", "jpg", "jpeg", "gif", "bmp", "webp", "pdf", "ofd"].includes(ext || "");

    if (!isAccepted) {
      setError("不支持的文件格式，请上传 PNG / JPG / GIF / BMP / WEBP / PDF / OFD 文件");
      return;
    }

    if (f.size > MAX_FILE_SIZE) {
      setError(`文件大小不能超过 20MB，当前文件 ${(f.size / (1024 * 1024)).toFixed(1)} MB`);
      return;
    }

    setFile(f);
    setResult(null);
    setError(null);
  }, []);

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

      {/* 上传区域 */}
      {!file && !result && (
        <FileDropZone
          onFile={handleFile}
          dragOver={dragOver}
          setDragOver={setDragOver}
          inputRef={inputRef}
        />
      )}

      {/* 文件信息 + 表单 */}
      {file && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-4"
        >
          <FilePreviewCard
            file={file}
            onRemove={() => {
              setFile(null);
              setError(null);
            }}
          />

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
          <UploadResult
            result={result}
            onViewDetail={() => navigate("/portal/invoices")}
            onReset={reset}
            viewDetailText="查看发票"
          />
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
