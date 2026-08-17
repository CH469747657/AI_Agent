import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { useEffect, useState, useMemo } from "react";
import {
  Receipt,
  CurrencyCny,
  Clock,
  ShieldCheck,
  Warning,
  UploadSimple,
  CheckCircle,
  TrendUp,
  Stack,
} from "@phosphor-icons/react";
import { invoiceApi } from "../api/client";
import type { Invoice, Statistics } from "../types";
import { StatCard } from "../components/StatCard";
import {
  StatusBadge,
  DuplicateBadge,
  CategoryBadge,
} from "../components/StatusBadge";
import { EmptyState, CardSkeleton, TableSkeleton } from "../components/EmptyState";

export function Dashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<Statistics | null>(null);
  const [recent, setRecent] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([invoiceApi.statistics(), invoiceApi.list()])
      .then(([s, list]) => {
        setStats(s);
        setRecent(list.slice(0, 8));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Group invoices by month for trend chart
  const monthlyData = useMemo(() => {
    const groups = new Map<string, { total: number; count: number }>();
    recent.concat().forEach((inv) => {
      if (!inv.issue_date) return;
      const month = inv.issue_date.slice(0, 7); // YYYY-MM
      if (!groups.has(month)) groups.set(month, { total: 0, count: 0 });
      const g = groups.get(month)!;
      g.total += parseFloat(inv.total_with_tax || "0");
      g.count += 1;
    });
    // Sort by month and take last 6
    const sorted = Array.from(groups.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .slice(-6);
    return sorted;
  }, [recent]);

  const maxMonthlyTotal = useMemo(
    () => Math.max(1, ...monthlyData.map(([, v]) => v.total)),
    [monthlyData]
  );

  // Duplicate invoices for warning panel
  const duplicates = useMemo(
    () => recent.filter((inv) => inv.duplicate_status === "DUPLICATE"),
    [recent]
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
          仪表板
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          AI 报销智能体系统概览 — 发票识别、分类与查重状态一览
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-error-50 p-4 text-sm text-error-700">
          <Warning size={18} />
          {error}
        </div>
      )}

      {/* Stat cards — 6 cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {loading ? (
          Array.from({ length: 6 }).map((_, i) => <CardSkeleton key={i} />)
        ) : stats ? (
          <>
            <StatCard
              label="发票总数"
              value={stats.total_invoices}
              icon={<Receipt size={20} className="text-primary-600" />}
              iconBg="bg-primary-50"
              delay={0}
            />
            <StatCard
              label="价税合计"
              value={stats.total_amount}
              prefix="¥"
              icon={<CurrencyCny size={20} className="text-accent-600" />}
              iconBg="bg-accent-50"
              delay={0.06}
            />
            <StatCard
              label="税额合计"
              value={stats.total_tax}
              prefix="¥"
              icon={<CurrencyCny size={20} className="text-primary-600" />}
              iconBg="bg-primary-50"
              delay={0.12}
            />
            <StatCard
              label="已确认"
              value={stats.confirmed}
              icon={<CheckCircle size={20} className="text-success-600" />}
              iconBg="bg-success-50"
              delay={0.18}
            />
            <StatCard
              label="待审核"
              value={stats.pending_review}
              icon={<Clock size={20} className="text-warning-600" />}
              iconBg="bg-warning-50"
              delay={0.24}
            />
            <StatCard
              label="重复发票"
              value={stats.duplicates}
              icon={<ShieldCheck size={20} className="text-error-600" />}
              iconBg="bg-error-50"
              delay={0.30}
            />
          </>
        ) : null}
      </div>

      {/* Trend chart + warning panel */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Monthly trend */}
        <div className="rounded-xl border border-border bg-background p-4 col-span-1 lg:col-span-2">
          <div className="mb-3 flex items-center gap-2">
            <TrendUp size={18} className="text-primary-600" />
            <h2 className="font-display text-base font-semibold text-foreground">
              月度金额趋势
            </h2>
          </div>

          {monthlyData.length === 0 ? (
            <div className="flex h-[140px] items-center justify-center text-sm text-muted-foreground">
              暂无可分析的数据
            </div>
          ) : (
            <div className="flex h-[140px] items-end justify-between gap-2">
              {monthlyData.map(([month, val], i) => (
                <div
                  key={month}
                  className="flex flex-1 flex-col items-center gap-1"
                >
                  <div className="flex w-full flex-1 items-end">
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{
                        height: `${Math.max(
                          (val.total / maxMonthlyTotal) * 100,
                          4
                        )}px`,
                      }}
                      transition={{
                        delay: 0.3 + i * 0.08,
                        type: "spring",
                        stiffness: 120,
                        damping: 20,
                      }}
                      className="w-full rounded-t bg-gradient-to-t from-primary-400 to-primary-500"
                    >
                      <div className="mb-1 text-center text-[10px] font-medium text-primary-800">
                        ¥{val.total >= 10000
                          ? `${(val.total / 10000).toFixed(1)}万`
                          : val.total.toFixed(0)}
                      </div>
                    </motion.div>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {month.slice(5)}月
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Warning panel */}
        <div className="rounded-xl border border-border bg-background p-4">
          <div className="mb-2 flex items-center gap-2">
            <Warning size={18} className="text-error-500" />
            <h2 className="font-display text-base font-semibold text-foreground">
              重复预警
            </h2>
          </div>

          {duplicates.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-6">
              <CheckCircle size={24} className="text-success-400" />
              <p className="mt-1 text-sm text-muted-foreground">暂无重复发票</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {duplicates.slice(0, 4).map((inv, i) => (
                <motion.div
                  key={inv.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.06 }}
                  onClick={() => navigate(`/invoices?id=${inv.id}`)}
                  className="flex cursor-pointer items-center gap-2 rounded-lg bg-error-50/50 p-2 transition-colors hover:bg-error-50"
                >
                  <span className="font-mono text-[10px] text-error-400">
                    #{inv.id}
                  </span>
                  <span className="flex-1 truncate text-xs text-foreground">
                    {inv.seller_name || "未知"}
                  </span>
                  <span className="text-xs font-medium text-foreground">
                    {inv.total_with_tax
                      ? `¥${inv.total_with_tax}`
                      : "—"}
                  </span>
                </motion.div>
              ))}
              {duplicates.length > 4 && (
                <button
                  onClick={() => navigate("/invoices?dup=DUPLICATE")}
                  className="w-full pt-1 text-center text-xs text-primary-600 hover:text-primary-700"
                >
                  查看全部 {duplicates.length} 条 →
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Recent invoices */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-base font-semibold text-foreground">
            最近发票
          </h2>
          <div className="flex gap-2">
            <button
              onClick={() => navigate("/reimbursements")}
              className="flex items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700"
            >
              <Stack size={14} />
              报销单 →
            </button>
            <button
              onClick={() => navigate("/invoices")}
              className="text-sm font-medium text-primary-600 hover:text-primary-700"
            >
              查看全部发票 →
            </button>
          </div>
        </div>

        {loading ? (
          <TableSkeleton rows={5} />
        ) : recent.length === 0 ? (
          <div className="rounded-xl border border-border bg-background">
            <EmptyState
              icon={<Receipt size={24} className="text-muted-foreground" />}
              title="暂无发票记录"
              description="上传第一张发票开始使用 AI 报销智能体"
              action={
                <button
                  onClick={() => navigate("/upload")}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-primary-700"
                >
                  <UploadSimple size={14} />
                  上传发票
                </button>
              }
            />
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border bg-background">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2.5 font-medium">ID</th>
                  <th className="px-3 py-2.5 font-medium">销方名称</th>
                  <th className="px-3 py-2.5 font-medium">金额</th>
                  <th className="px-3 py-2.5 font-medium">分类</th>
                  <th className="px-3 py-2.5 font-medium">状态</th>
                  <th className="px-3 py-2.5 font-medium">查重</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {recent.map((inv, i) => (
                  <motion.tr
                    key={inv.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05, type: "spring", stiffness: 120, damping: 20 }}
                    onClick={() => navigate(`/invoices?id=${inv.id}`)}
                    className="cursor-pointer transition-colors hover:bg-muted"
                  >
                    <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                      #{inv.id}
                    </td>
                    <td className="max-w-[180px] truncate px-3 py-2.5 text-foreground">
                      {inv.seller_name || "—"}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-foreground">
                      {inv.total_with_tax
                        ? `¥${inv.total_with_tax}`
                        : "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <CategoryBadge category={inv.fee_category} subcategory={inv.fee_subcategory} />
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusBadge status={inv.status} linked={!!inv.reimbursement_id} />
                    </td>
                    <td className="px-3 py-2.5">
                      <DuplicateBadge status={inv.duplicate_status} />
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
