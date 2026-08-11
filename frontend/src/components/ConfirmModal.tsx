import { motion, AnimatePresence } from "framer-motion";
import { Warning, XCircle, Trash } from "@phosphor-icons/react";
import type { ReactNode } from "react";

export function ConfirmModal({
  open,
  title,
  description,
  confirmText = "确认",
  cancelText = "取消",
  variant = "danger",
  loading = false,
  error = null,
  onConfirm,
  onCancel,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "danger" | "primary" | "warning";
  loading?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  const colorMap = {
    danger: {
      iconBg: "bg-rose-50",
      iconColor: "text-rose-600",
      btnBg: "bg-rose-600 hover:bg-rose-700",
    },
    primary: {
      iconBg: "bg-brand-50",
      iconColor: "text-brand-600",
      btnBg: "bg-brand-600 hover:bg-brand-700",
    },
    warning: {
      iconBg: "bg-amber-50",
      iconColor: "text-amber-600",
      btnBg: "bg-amber-600 hover:bg-amber-700",
    },
  };
  const colors = colorMap[variant];

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm"
          onClick={() => !loading && onCancel()}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ type: "spring", damping: 25, stiffness: 400 }}
            className="mx-4 w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start gap-4">
              <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${colors.iconBg}`}>
                {variant === "danger" ? (
                  <Warning size={22} className={colors.iconColor} />
                ) : (
                  <Warning size={22} className={colors.iconColor} />
                )}
              </div>
              <div className="flex-1">
                <h3 className="font-display text-lg font-semibold text-slate-900">
                  {title}
                </h3>
                {description && (
                  <p className="mt-1 text-sm text-slate-500">
                    {description}
                  </p>
                )}
              </div>
            </div>

            {/* Optional detail content */}
            {children && (
              <div className="mt-4">{children}</div>
            )}

            {/* Error */}
            {error && (
              <div className="mt-4 flex items-start gap-2 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">
                <XCircle size={18} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* Actions */}
            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                onClick={() => !loading && onCancel()}
                disabled={loading}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {cancelText}
              </button>
              <button
                onClick={onConfirm}
                disabled={loading}
                className={`flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${colors.btnBg}`}
              >
                {loading ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    {confirmText}中...
                  </>
                ) : (
                  <>
                    {variant === "danger" && <Trash size={16} />}
                    {confirmText}
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
