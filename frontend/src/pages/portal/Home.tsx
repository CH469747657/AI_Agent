import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { portalApi } from "../../api/client";
import type { PortalDashboard } from "../../types";
import {
  Receipt,
  Stack,
  UploadSimple,
  ArrowRight,
  Spinner,
} from "@phosphor-icons/react";

const invoiceStatusLabels: Record<string, string> = {
  UPLOADED: "已上传",
  PROCESSING: "处理中",
  REVIEWING: "待审核",
  CONFIRMED: "已确认",
  REIMBURSED: "已报销",
  NOT_REIMBURSED: "不予报销",
};

const reimbursementStatusLabels: Record<string, string> = {
  DRAFT: "草稿",
  SUBMITTED: "已提交",
  REVIEWED: "已审核",
  REIMBURSED: "已报销",
};

export function PortalHome() {
  const [dashboard, setDashboard] = useState<PortalDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    portalApi.dashboard().then(setDashboard).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size={24} className="animate-spin text-brand-600" />
      </div>
    );
  }

  if (!dashboard) return null;

  const employee = portalApi.getStoredEmployee();

  return (
    <div className="space-y-6">
      {/* 欢迎语 */}
      <div>
        <h1 className="font-display text-2xl font-bold text-slate-900">
          你好，{employee?.name}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          欢迎使用 AI 报销智能体，您可以在此上传发票、创建报销单。
        </p>
      </div>

      {/* 快捷操作 */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Link
          to="/portal/upload"
          className="group flex flex-col items-center gap-2 rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm transition-all hover:border-brand-200 hover:shadow-md"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition-colors group-hover:bg-brand-100">
            <UploadSimple size={22} />
          </div>
          <span className="text-sm font-medium text-slate-700">
            上传发票
          </span>
        </Link>
        <Link
          to="/portal/invoices"
          className="group flex flex-col items-center gap-2 rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm transition-all hover:border-brand-200 hover:shadow-md"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600 transition-colors group-hover:bg-blue-100">
            <Receipt size={22} />
          </div>
          <span className="text-sm font-medium text-slate-700">
            我的发票
          </span>
        </Link>
        <Link
          to="/portal/reimbursements"
          className="group flex flex-col items-center gap-2 rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm transition-all hover:border-brand-200 hover:shadow-md"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50 text-amber-600 transition-colors group-hover:bg-amber-100">
            <Stack size={22} />
          </div>
          <span className="text-sm font-medium text-slate-700">
            我的报销
          </span>
        </Link>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-2xl border border-slate-200/60 bg-white p-4 shadow-sm">
          <p className="text-xs font-medium text-slate-400">发票总数</p>
          <p className="mt-1 font-display text-2xl font-bold text-slate-900">
            {dashboard.invoice_count}
          </p>
        </div>
        <div className="rounded-2xl border border-slate-200/60 bg-white p-4 shadow-sm">
          <p className="text-xs font-medium text-slate-400">发票总金额</p>
          <p className="mt-1 font-display text-2xl font-bold text-slate-900">
            ¥{dashboard.invoice_total.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
          </p>
        </div>
        <div className="rounded-2xl border border-slate-200/60 bg-white p-4 shadow-sm">
          <p className="text-xs font-medium text-slate-400">报销单数</p>
          <p className="mt-1 font-display text-2xl font-bold text-slate-900">
            {dashboard.reimbursement_count}
          </p>
        </div>
        <div className="rounded-2xl border border-slate-200/60 bg-white p-4 shadow-sm">
          <p className="text-xs font-medium text-slate-400">待提交草稿</p>
          <p className="mt-1 font-display text-2xl font-bold text-amber-600">
            {dashboard.draft_count}
          </p>
        </div>
      </div>

      {/* 最近发票 */}
      <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-base font-semibold text-slate-900">
            最近发票
          </h2>
          <Link
            to="/portal/invoices"
            className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
          >
            查看全部 <ArrowRight size={12} />
          </Link>
        </div>
        {dashboard.recent_invoices.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-400">
            暂无发票，去上传一张吧
          </p>
        ) : (
          <div className="space-y-2">
            {dashboard.recent_invoices.map((inv) => (
              <div
                key={inv.id}
                className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-slate-700">
                    {inv.seller_name || "未识别"}
                  </p>
                  <p className="text-xs text-slate-400">
                    {inv.fee_subcategory || "未分类"}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold text-slate-900">
                    ¥{inv.total_with_tax || "-"}
                  </p>
                  <p className="text-xs text-slate-400">{invoiceStatusLabels[inv.status] || inv.status}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 最近报销单 */}
      <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-base font-semibold text-slate-900">
            最近报销单
          </h2>
          <Link
            to="/portal/reimbursements"
            className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
          >
            查看全部 <ArrowRight size={12} />
          </Link>
        </div>
        {dashboard.recent_reimbursements.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-400">
            暂无报销单
          </p>
        ) : (
          <div className="space-y-2">
            {dashboard.recent_reimbursements.map((r) => (
              <div
                key={r.id}
                className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-slate-700">
                    报销单 #{r.id}
                  </p>
                  <p className="text-xs text-slate-400">{reimbursementStatusLabels[r.status] || r.status}</p>
                </div>
                <p className="text-sm font-semibold text-slate-900">
                  ¥{r.total_amount?.toLocaleString("zh-CN", { minimumFractionDigits: 2 }) ?? "-"}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
