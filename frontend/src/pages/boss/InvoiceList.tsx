import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Invoice } from "../../types";
import {
  Receipt,
  Spinner,
  WarningCircle,
  Eye,
  X,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import { StatusBadge } from "../../components/StatusBadge";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "REVIEWING", label: "待审核" },
  { value: "REVIEWED", label: "已确认" },
  { value: "REJECTED", label: "已驳回" },
];

export function BossInvoiceList() {
  const navigate = useNavigate();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [department, setDepartment] = useState("");
  const [keyword, setKeyword] = useState("");
  const [searchInput, setSearchInput] = useState("");

  // 加载部门列表
  useEffect(() => {
    bossApi.listDepartments().then(setDepartments).catch(() => {});
  }, []);

  // 防抖搜索
  useEffect(() => {
    const t = setTimeout(() => setKeyword(searchInput.trim()), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    setLoading(true);
    setError("");
    bossApi
      .listInvoices({
        status: status || undefined,
        department: department || undefined,
        keyword: keyword || undefined,
      })
      .then(setInvoices)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "加载失败")
      )
      .finally(() => setLoading(false));
  }, [status, department, keyword]);

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
            全公司发票
          </h1>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            穿透查看所有部门、所有员工的发票明细
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground/70">
          共 {invoices.length} 张
        </span>
      </div>

      {/* 筛选条 */}
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="min-h-[36px] rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          className="min-h-[36px] rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
        >
          <option value="">全部部门</option>
          {departments.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <div className="relative min-w-[180px] flex-1">
          <MagnifyingGlass
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            type="text"
            placeholder="搜索姓名 / 工号"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="min-h-[36px] w-full rounded-md border border-border bg-background py-1.5 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
        </div>
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

      {invoices.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-background py-16 text-center">
          <Receipt size={48} className="text-muted" />
          <p className="mt-3 text-sm text-muted-foreground">暂无发票</p>
        </div>
      ) : (
        <div className="space-y-3">
          {invoices.map((inv) => (
            <div
              key={inv.id}
              onClick={() => navigate(`/boss/invoices/${inv.id}`)}
              className="cursor-pointer rounded-xl border border-border bg-background p-3 shadow-sm transition-all hover:shadow-md sm:p-5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="truncate text-sm font-semibold text-foreground">
                    {inv.seller_name || "未识别"}
                  </p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {inv.receipt_type && (
                      <span
                        className={`inline-block whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                          inv.is_nonstandard
                            ? "bg-violet-100 text-violet-700"
                            : "bg-muted text-foreground/70"
                        }`}
                      >
                        {inv.receipt_type}
                      </span>
                    )}
                    <StatusBadge
                      status={inv.status}
                      linked={!!inv.reimbursement_id}
                    />
                  </div>
                </div>
                <p className="shrink-0 font-display text-sm font-bold text-foreground sm:text-base">
                  ¥{inv.total_with_tax || "-"}
                </p>
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground sm:gap-4 sm:text-xs">
                <span>
                  {inv.fee_subcategory || inv.fee_category || "未分类"}
                </span>
                {inv.invoice_number && (
                  <span className="truncate">#{inv.invoice_number}</span>
                )}
                {inv.issue_date && <span>{inv.issue_date}</span>}
                {inv.uploader_name && (
                  <span className="truncate">{inv.uploader_name}</span>
                )}
              </div>

              <div className="mt-2.5 flex flex-wrap items-center justify-end gap-1.5 border-t border-border pt-2.5 sm:mt-0 sm:border-0 sm:pt-0">
                <span className="flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-[11px] font-medium text-foreground/70 sm:px-2.5 sm:py-1.5 sm:text-xs">
                  <Eye size={13} />
                  详情
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
