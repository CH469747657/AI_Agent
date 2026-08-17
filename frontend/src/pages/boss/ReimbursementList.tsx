import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Reimbursement, ReimbursementStatus } from "../../types";
import {
  Stack,
  Spinner,
  WarningCircle,
  Eye,
  X,
} from "@phosphor-icons/react";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "DRAFT", label: "草稿" },
  { value: "SUBMITTED", label: "待审批" },
  { value: "REVIEWED", label: "已批准" },
  { value: "REIMBURSED", label: "已报销" },
];

const statusLabels: Record<ReimbursementStatus, { label: string; color: string }> = {
  DRAFT: { label: "草稿", color: "bg-muted text-muted-foreground" },
  SUBMITTED: { label: "待审批", color: "bg-warning-50 text-warning-700" },
  REVIEWED: { label: "已批准", color: "bg-success-50 text-success-700" },
  REIMBURSED: { label: "已报销", color: "bg-primary-50 text-primary-700" },
};

export function BossReimbursementList() {
  const navigate = useNavigate();
  const [reimbs, setReimbs] = useState<Reimbursement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    bossApi
      .listReimbursements()
      .then(setReimbs)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "加载失败")
      )
      .finally(() => setLoading(false));
  }, []);

  const filtered = statusFilter
    ? reimbs.filter((r) => r.status === statusFilter)
    : reimbs;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size={24} className="animate-spin text-primary-700" />
      </div>
    );
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h1 className="font-display text-lg font-bold text-foreground sm:text-xl">
            全公司报销单
          </h1>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            穿透查看所有部门、所有员工的报销单
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground/70">
          共 {filtered.length} 份
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg bg-error-50 px-4 py-3 text-sm text-error-700">
          <WarningCircle size={18} weight="fill" />
          {error}
          <button
            onClick={() => setError("")}
            className="ml-auto text-error-400 hover:text-error-600"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-background py-16 text-center">
          <Stack size={48} className="text-muted" />
          <p className="mt-3 text-sm text-muted-foreground">暂无报销单</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((r) => {
            const sc = statusLabels[r.status] || statusLabels.DRAFT;
            return (
              <div
                key={r.id}
                onClick={() => navigate(`/boss/reimbursements/${r.id}`)}
                className="cursor-pointer rounded-xl border border-border bg-background p-3 shadow-sm transition-all hover:shadow-md sm:p-5"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="truncate text-sm font-semibold text-foreground">
                      {r.applicant_name || r.applicant_id || "—"}
                      {r.department && (
                        <span className="ml-1 text-xs font-normal text-muted-foreground">
                          · {r.department}
                        </span>
                      )}
                    </p>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={`inline-block whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ${sc.color}`}
                      >
                        {sc.label}
                      </span>
                    </div>
                  </div>
                  <p className="shrink-0 font-display text-sm font-bold text-foreground sm:text-base">
                    ¥{(r.total_amount ?? 0).toFixed(2)}
                  </p>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground sm:gap-4 sm:text-xs">
                  {r.period && <span>{r.period}</span>}
                  {r.cycle_key && <span>{r.cycle_key}</span>}
                  {r.reason && (
                    <span className="truncate">{r.reason}</span>
                  )}
                </div>

                <div className="mt-2.5 flex flex-wrap items-center justify-end gap-1.5 border-t border-border pt-2.5 sm:mt-0 sm:border-0 sm:pt-0">
                  <span className="flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-[11px] font-medium text-foreground/70 sm:px-2.5 sm:py-1.5 sm:text-xs">
                    <Eye size={13} />
                    详情
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
