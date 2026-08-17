import type { ReimbursementStatus, Reimbursement } from "../../types";

export type View = "list" | "create" | "detail";

/* ---------- Status badge ---------- */

export const reimbStatusConfig: Record<
  ReimbursementStatus,
  { label: string; className: string }
> = {
  DRAFT: { label: "草稿", className: "bg-muted text-foreground" },
  SUBMITTED: { label: "已提交", className: "bg-blue-50 text-blue-700" },
  REVIEWED: { label: "已审核", className: "bg-amber-50 text-amber-700" },
  REIMBURSED: { label: "已报销", className: "bg-emerald-50 text-emerald-700" },
};

export function ReimbStatusBadge({ status }: { status: ReimbursementStatus }) {
  const config = reimbStatusConfig[status] || reimbStatusConfig.DRAFT;
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  );
}

/* ---------- Info row for detail ---------- */

export function InfoRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted">
        {icon}
      </div>
      <div className="flex-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-medium text-foreground">{value ?? "—"}</p>
      </div>
    </div>
  );
}

/* ---------- Status filter tabs ---------- */

export const statusTabs: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "DRAFT", label: "草稿" },
  { key: "SUBMITTED", label: "已提交" },
  { key: "REVIEWED", label: "已审核" },
  { key: "REIMBURSED", label: "已报销" },
];

/* ---------- Report file helpers ---------- */

export function hasReportFiles(r: Reimbursement | null): boolean {
  return !!r && !!(r.excel_path || r.pdf_path || r.zip_path);
}

/* ---------- Cycle & subsidy helpers ---------- */

const _weekdayNames = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export function weekdayName(n: number | null): string {
  if (n == null || n < 0 || n > 6) return "—";
  return _weekdayNames[n];
}

const _dayTypeConfig: Record<string, { label: string; badge: string }> = {
  workday: { label: "工作日", badge: "bg-muted text-foreground" },
  rest_day: { label: "休息日", badge: "bg-blue-50 text-blue-600" },
  holiday: { label: "法定节假日", badge: "bg-rose-50 text-rose-600" },
  adjusted_workday: { label: "调休补班", badge: "bg-amber-50 text-amber-600" },
};

export function dayTypeLabel(type: string | null): string {
  if (!type) return "—";
  return _dayTypeConfig[type]?.label ?? type;
}

export function dayTypeBadge(type: string | null): string {
  if (!type) return "bg-muted text-foreground";
  return _dayTypeConfig[type]?.badge ?? "bg-muted text-foreground";
}

export function formatCycleRange(start: string | null, end: string | null): string {
  if (!start || !end) return "—";
  return `${start} ~ ${end}`;
}

export function cycleLabel(key: string | null): string {
  if (!key) return "—";
  // key format: "2026-08"
  return key;
}
