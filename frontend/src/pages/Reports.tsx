import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import {
  FileText,
  FileXls,
  FileZip,
  Warning,
  CheckCircle,
  Spinner,
  DownloadSimple,
} from "@phosphor-icons/react";
import { reportApi } from "../api/client";

export function Reports() {
  const [reimbursementId, setReimbursementId] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    const id = Number(reimbursementId);
    if (!id) return;
    setGenerating(true);
    setError(null);
    setGenerated(false);
    try {
      await reportApi.generate(id);
      setGenerated(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  };

  const fileTypes = [
    {
      key: "xlsx",
      label: "Excel 明细表",
      desc: "发票明细、金额汇总、分类统计",
      icon: FileXls,
      color: "text-emerald-600",
      bg: "bg-emerald-50",
    },
    {
      key: "pdf",
      label: "PDF 报销单",
      desc: "格式化报销申请单，含发票明细",
      icon: FileText,
      color: "text-rose-600",
      bg: "bg-rose-50",
    },
    {
      key: "zip",
      label: "ZIP 完整包",
      desc: "原始发票图片 + Excel + PDF 打包",
      icon: FileZip,
      color: "text-amber-600",
      bg: "bg-amber-50",
    },
  ];

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">
          报表下载
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          输入报销单 ID，生成并下载 Excel、PDF 或 ZIP 报表包
        </p>
      </div>

      {/* Input */}
      <div className="rounded-2xl border border-slate-200/60 bg-white p-5">
        <label className="text-sm font-medium text-slate-700">
          报销单 ID
        </label>
        <div className="mt-2 flex gap-2">
          <input
            type="number"
            value={reimbursementId}
            onChange={(e) => setReimbursementId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleGenerate()}
            className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-brand-400 focus:bg-white"
            placeholder="输入报销单 ID（数字）"
          />
          <button
            onClick={handleGenerate}
            disabled={!reimbursementId || generating}
            className="flex items-center gap-2 rounded-lg bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white transition-all hover:bg-brand-700 disabled:opacity-50 active:scale-[0.98]"
          >
            {generating ? (
              <>
                <Spinner size={16} className="animate-spin" />
                生成中...
              </>
            ) : (
              "生成报表"
            )}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          报销单 ID 由后端创建报销单时分配，可在发票详情中查看关联。
        </p>
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

      {/* Success */}
      <AnimatePresence>
        {generated && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-3"
          >
            <div className="flex items-center gap-2 rounded-xl bg-emerald-50 p-4">
              <CheckCircle size={20} className="text-emerald-600" />
              <span className="text-sm font-medium text-emerald-800">
                报表已生成，请选择需要下载的格式：
              </span>
            </div>

            {/* Download options */}
            <div className="grid gap-3">
              {fileTypes.map((ft, i) => {
                const Icon = ft.icon;
                const url = reportApi.downloadUrl(
                  Number(reimbursementId),
                  ft.key
                );
                return (
                  <motion.a
                    key={ft.key}
                    href={url}
                    download
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.08 }}
                    className="group flex items-center gap-4 rounded-xl border border-slate-200/60 bg-white p-4 transition-colors hover:border-brand-300 hover:bg-slate-50"
                  >
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-lg ${ft.bg}`}
                    >
                      <Icon size={20} className={ft.color} />
                    </div>
                    <div className="flex-1">
                      <p className="text-sm font-medium text-slate-800">
                        {ft.label}
                      </p>
                      <p className="text-xs text-slate-400">{ft.desc}</p>
                    </div>
                    <DownloadSimple
                      size={18}
                      className="text-slate-300 group-hover:text-brand-600"
                    />
                  </motion.a>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
