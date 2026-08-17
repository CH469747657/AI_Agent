import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { portalApi } from "../../api/client";
import type { Invoice } from "../../types";
import {
  MAX_FILE_SIZE,
  ACCEPTED_TYPES,
  FileDropZone,
  FilePreviewCard,
  ProcessingTimeline,
  UploadResult,
} from "../../components/upload";
import { UploadSimple, Warning, Spinner, Sparkle, ChatCircleDots } from "@phosphor-icons/react";

export function PortalUpload() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [dragOver, setDragOver] = useState(false);

  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<Invoice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  /** 文件选择 → 立即自动上传（无感上传，无需手动选类型） */
  const handleFile = useCallback(async (f: File) => {
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

    // 立即触发自动上传（无 receipt_type，由后端 LLM Vision 自动识别）
    setFile(f);
    setResult(null);
    setError(null);
    setUploading(true);

    try {
      const res = await portalApi.uploadInvoice(f, {
        description: "",  // 无感上传：备注留空，识别后由用户补充
        receipt_type: "", // 留空 → 后端 LLM Vision 自动判断
      });
      setResult(res);
      setFile(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "上传失败";
      // 识别失败的友好提示
      if (msg.includes("识别") || msg.includes("VLM") || msg.includes("vision")) {
        setError("无法识别票据类型，请重新上传清晰的发票图片");
      } else {
        setError(msg);
      }
    } finally {
      setUploading(false);
    }
  }, []);

  /** 识别完成后补充用途说明 */
  const handleAddDescription = async () => {
    if (!result || !description.trim()) return;
    try {
      // 调用更新接口补充用途
      await portalApi.updateInvoice(result.id, { user_description: description.trim() });
      setResult({ ...result, user_description: description.trim() });
      setDescription("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "补充用途失败");
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
        <h1 className="font-display text-xl font-bold tracking-tight text-foreground">
          上传发票
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          拖拽发票图片或 PDF，系统将自动识别票据类型与关键字段
        </p>
      </div>

      {/* 上传区域（无文件、无结果、未在上传中时显示） */}
      {!file && !result && !uploading && (
        <FileDropZone
          onFile={handleFile}
          dragOver={dragOver}
          setDragOver={setDragOver}
          inputRef={inputRef}
        />
      )}

      {/* 上传中：智能识别状态 */}
      <AnimatePresence>
        {uploading && file && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="space-y-4"
          >
            <FilePreviewCard
              file={file}
              onRemove={() => {
                setFile(null);
                setError(null);
                setUploading(false);
              }}
            />

            {/* 智能识别加载状态 */}
            <div className="rounded-lg border border-primary-200 bg-primary-50/30 p-4">
              <div className="flex items-center gap-3">
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-100"
                >
                  <Sparkle size={18} className="text-primary-600" weight="fill" />
                </motion.div>
                <div>
                  <p className="text-sm font-semibold text-primary-700">
                    正在智能识别票据类型...
                  </p>
                  <p className="text-xs text-primary-600/70">
                    大模型视觉分析中，无需手动选择
                  </p>
                </div>
              </div>

              <div className="mt-3">
                <ProcessingTimeline uploading />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 识别结果 + 用途补充 */}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            <UploadResult
              result={result}
              onViewDetail={() => navigate("/portal/invoices")}
              onReset={reset}
              viewDetailText="查看发票"
            />

            {/* 补充费用用途引导 */}
            {!result.user_description && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="rounded-xl border border-primary-200 bg-gradient-to-br from-primary-50 to-background p-4"
              >
                <div className="flex items-center gap-2">
                  <ChatCircleDots size={18} className="text-primary-600" weight="fill" />
                  <h3 className="font-display text-sm font-semibold text-primary-800">
                    补充费用用途
                  </h3>
                </div>
                <p className="mt-1 text-xs text-primary-600/80">
                  识别已完成，请补充该笔费用的用途说明，以便完成报销单生成
                </p>

                <div className="mt-3 flex gap-2">
                  <input
                    type="text"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && description.trim()) handleAddDescription();
                    }}
                    placeholder="请补充说明该笔费用的用途（如：7月团建餐费）"
                    className="flex-1 rounded-md border border-primary-200 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
                    autoFocus
                  />
                  <button
                    onClick={handleAddDescription}
                    disabled={!description.trim()}
                    className="flex items-center gap-1.5 rounded-md bg-primary-600 px-3 py-2 text-sm font-medium text-white transition-all hover:bg-primary-700 disabled:opacity-40 active:scale-[0.98]"
                  >
                    <UploadSimple size={14} />
                    确认
                  </button>
                </div>
              </motion.div>
            )}

            {/* 已有用途时显示 */}
            {result.user_description && (
              <div className="rounded-lg border border-success-200 bg-success-50/50 p-3">
                <p className="text-xs text-success-700/70">费用用途</p>
                <p className="mt-0.5 text-sm font-medium text-success-900">
                  {result.user_description}
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* 错误提示 */}
      <AnimatePresence>
        {error && !uploading && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2 rounded-lg bg-error-50 p-4 text-sm text-error-700"
          >
            <Warning size={18} weight="fill" />
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-auto text-xs text-error-500 hover:text-error-700"
            >
              重试
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
