import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { useState, useCallback, useRef } from "react";
import { UploadSimple, Warning, Spinner } from "@phosphor-icons/react";
import { invoiceApi } from "../api/client";
import type { Invoice } from "../types";
import {
  receiptTypes,
  NONSTANDARD_TYPES,
  FileDropZone,
  FilePreviewCard,
  ProcessingTimeline,
  UploadResult,
} from "../components/upload";

export function Upload() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [userId] = useState("admin");
  const [description, setDescription] = useState("");
  const [receiptType, setReceiptType] = useState("增值税普通发票");
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<Invoice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File) => {
    setFile(f);
    setResult(null);
    setError(null);
  }, []);

  const handleUpload = async () => {
    if (!file || !userId) return;
    if (!description.trim()) {
      setError("请填写备注说明");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const res = await invoiceApi.upload({
        file,
        user_id: userId,
        user_description: description,
        receipt_type: receiptType,
      });
      setResult(res);
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
      {/* Header */}
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">
          上传发票
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          上传票据图片，系统将自动进行 OCR 识别、费用分类与查重
        </p>
      </div>

      {/* Upload zone */}
      {!file && !result && (
        <FileDropZone
          onFile={handleFile}
          dragOver={dragOver}
          setDragOver={setDragOver}
          inputRef={inputRef}
        />
      )}

      {/* File preview & form */}
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

          {/* Form */}
          <div className="space-y-4 rounded-xl border border-slate-200/60 bg-white p-5">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">
                票据类型
              </label>
              <select
                value={receiptType}
                onChange={(e) => setReceiptType(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white"
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
                备注说明{" "}
                <span className="text-rose-500">*</span>
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white"
                placeholder="例如：2026年产数关键岗位能力实训班培训费"
              />
            </div>
          </div>

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700"
              >
                <Warning size={18} />
                {error}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Submit */}
          <button
            onClick={handleUpload}
            disabled={uploading || !userId || !description.trim()}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white transition-all hover:bg-brand-700 disabled:opacity-50 active:scale-[0.98]"
          >
            {uploading ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                正在识别中...
              </>
            ) : (
              <>
                <UploadSimple size={18} />
                开始上传并识别
              </>
            )}
          </button>

          {/* Processing timeline */}
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

      {/* Result */}
      <AnimatePresence>
        {result && (
          <UploadResult
            result={result}
            onViewDetail={() => navigate(`/invoices?id=${result.id}`)}
            onReset={reset}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
