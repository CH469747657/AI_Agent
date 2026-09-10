import { motion, AnimatePresence } from "framer-motion";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useEffect, useState, useMemo, useCallback } from "react";
import { useDebounce } from "../hooks/useDebounce";
import {
  Receipt,
  Warning,
  MagnifyingGlass,
  CaretLeft,
  CaretRight,
  Checks,
  Trash,
  XCircle,
  UploadSimple,
  DownloadSimple,
  FileXls,
} from "@phosphor-icons/react";
import { invoiceApi } from "../api/client";
import type { Invoice, InvoiceStatus } from "../types";
import {
  StatusBadge,
  DuplicateBadge,
  CategoryBadge,
  VerifyBadge,
} from "../components/StatusBadge";
import { EmptyState, TableSkeleton } from "../components/EmptyState";
import { InvoiceDetailDrawer } from "../components/InvoiceDetailDrawer";

const statusOptions: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "UPLOADED", label: "已上传" },
  { value: "PROCESSING", label: "处理中" },
  { value: "REVIEWING", label: "待审核" },
  { value: "REVIEWED", label: "已审核" },
  { value: "REJECTED", label: "审核不通过" },
];

const verifyOptions: { value: string; label: string }[] = [
  { value: "", label: "全部验真" },
  { value: "VALID", label: "验真通过" },
  { value: "PENDING", label: "待验真" },
  { value: "INVALID", label: "验真失败" },
  { value: "UNABLE_TO_VERIFY", label: "无法验真" },
];

const dupOptions: { value: string; label: string }[] = [
  { value: "", label: "全部查重" },
  { value: "UNIQUE", label: "唯一" },
  { value: "DUPLICATE", label: "重复" },
];

const receiptTypeOptions: { value: string; label: string }[] = [
  { value: "", label: "全部类型" },
  { value: "standard", label: "标准票据" },
  { value: "nonstandard", label: "非标票据" },
];

const PAGE_SIZE = 15;

export function Invoices() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [verifyFilter, setVerifyFilter] = useState("");
  const [dupFilter, setDupFilter] = useState("");
  const [receiptTypeFilter, setReceiptTypeFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearch = useDebounce(searchQuery, 300);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // 删除确认弹窗状态
  const [deleteTarget, setDeleteTarget] = useState<Invoice | null>(null);
  const [batchDeleteIds, setBatchDeleteIds] = useState<Set<number> | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportUploader, setExportUploader] = useState<string>("");
  const [exporting, setExporting] = useState(false);

  const idFromUrl = searchParams.get("id");
  useEffect(() => {
    if (idFromUrl) setSelectedId(Number(idFromUrl));
  }, [idFromUrl]);

  const fetchInvoices = useCallback(() => {
    setLoading(true);
    invoiceApi
      .list(statusFilter ? { status: statusFilter } : undefined)
      .then(setInvoices)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [statusFilter]);

  useEffect(() => {
    fetchInvoices();
  }, [fetchInvoices]);

// Client-side search + filter
const filtered = useMemo(() => {
  return invoices.filter((inv) => {
    if (debouncedSearch) {
      const q = debouncedSearch.toLowerCase();
      const matchNum = inv.invoice_number?.toLowerCase().includes(q) ?? false;
      const matchSeller = inv.seller_name?.toLowerCase().includes(q) ?? false;
      const matchDate = inv.issue_date?.includes(debouncedSearch) ?? false;
      if (!matchNum && !matchSeller && !matchDate) return false;
    }
    if (verifyFilter && inv.verify_status !== verifyFilter) return false;
    if (dupFilter && inv.duplicate_status !== dupFilter) return false;
    if (receiptTypeFilter === "standard" && inv.is_nonstandard) return false;
    if (receiptTypeFilter === "nonstandard" && !inv.is_nonstandard) return false;
    return true;
  });
}, [invoices, debouncedSearch, verifyFilter, dupFilter, receiptTypeFilter]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paged = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  useEffect(() => {
  setCurrentPage(1);
}, [statusFilter, verifyFilter, dupFilter, receiptTypeFilter, debouncedSearch]);

  const toggleSelect = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (prev.size === paged.length) return new Set();
      return new Set(paged.map((i) => i.id));
    });
  }, [paged]);

  const clearSelection = () => setSelectedIds(new Set());

  // 提取所有上传者（去重）— 按 user_id 去重，显示名来自后端 uploader_name
  const uploaderOptions = useMemo(() => {
    const map = new Map<string, string>();
    invoices.forEach((inv) => {
      const uid = inv.user_id;
      if (!uid) return; // 跳过无 user_id 的记录
      if (!map.has(uid)) {
        map.set(uid, inv.uploader_name || uid);
      }
    });
    return Array.from(map.entries()).map(([uid, name]) => ({ value: uid, label: name }));
  }, [invoices]);

  // 导出清单
  const handleExport = async () => {
    setExporting(true);
    try {
      await invoiceApi.exportInvoices(exportUploader || undefined);
      setShowExportModal(false);
      setExportUploader("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExporting(false);
    }
  };

  // 单条删除
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await invoiceApi.delete(deleteTarget.id);
      if (selectedId === deleteTarget.id) {
        setSelectedId(null);
        if (searchParams.get("id")) setSearchParams({});
      }
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(deleteTarget.id);
        return next;
      });
      fetchInvoices();
      setDeleteTarget(null);
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "删除失败，请稍后重试");
    } finally {
      setDeleting(false);
    }
  };

  // 批量删除
  const handleBatchDelete = async () => {
    if (!batchDeleteIds) return;
    setDeleting(true);
    setDeleteError(null);
    let failCount = 0;
    for (const id of batchDeleteIds) {
      try {
        await invoiceApi.delete(id);
        if (selectedId === id) {
          setSelectedId(null);
          if (searchParams.get("id")) setSearchParams({});
        }
      } catch {
        failCount++;
      }
    }
    clearSelection();
    fetchInvoices();
    setBatchDeleteIds(null);
    if (failCount > 0) {
      setDeleteError(`${failCount} 张发票删除失败，可能已关联报销单`);
    }
    setDeleting(false);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
            发票列表
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            共 {filtered.length} 张发票
            {selectedIds.size > 0 && (
              <span className="ml-2 text-primary-600">
                已选 {selectedIds.size} 张
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setExportUploader(""); setShowExportModal(true); }}
            className="flex items-center gap-2 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm font-medium text-primary-700 transition-all hover:bg-primary-100 active:scale-[0.98]"
          >
            <FileXls size={18} weight="bold" />
            导出清单
          </button>
          <button
            onClick={() => navigate("/upload")}
            className="flex items-center gap-2 rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white transition-all hover:bg-primary-700 active:scale-[0.98]"
          >
            <UploadSimple size={18} weight="bold" />
            上传发票
          </button>
        </div>
      </div>

      {/* Search bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <MagnifyingGlass
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索发票号、销售方、日期..."
            className="w-full rounded-lg border border-border bg-background py-2 pl-9 pr-4 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary-400"
          />
        </div>
      </div>

      {/* Filter bars — 分行展示，标签区分 */}
      <div className="space-y-3">
        {/* 状态筛选 */}
        <div className="flex items-center gap-3">
          <span className="w-14 shrink-0 text-xs font-medium text-muted-foreground">状态</span>
          <div className="flex flex-wrap gap-1.5">
            {statusOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setStatusFilter(opt.value)}
                className={`rounded-md px-2.5 py-1 text-sm font-medium transition-colors ${
                  statusFilter === opt.value
                    ? "bg-primary-600 text-white"
                    : "bg-background text-foreground hover:bg-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        {/* 验真筛选 */}
        <div className="flex items-center gap-3">
          <span className="w-14 shrink-0 text-xs font-medium text-muted-foreground">验真</span>
          <div className="flex flex-wrap gap-1.5">
            {verifyOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setVerifyFilter(opt.value)}
                className={`rounded-md px-2.5 py-1 text-sm font-medium transition-colors ${
                  verifyFilter === opt.value
                    ? "bg-primary-600 text-white"
                    : "bg-background text-foreground hover:bg-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        {/* 查重筛选 */}
        <div className="flex items-center gap-3">
          <span className="w-14 shrink-0 text-xs font-medium text-muted-foreground">查重</span>
          <div className="flex flex-wrap gap-1.5">
            {dupOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setDupFilter(opt.value)}
                className={`rounded-md px-2.5 py-1 text-sm font-medium transition-colors ${
                  dupFilter === opt.value
                    ? "bg-primary-600 text-white"
                    : "bg-background text-foreground hover:bg-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        {/* 票据类型筛选 */}
        <div className="flex items-center gap-3">
          <span className="w-14 shrink-0 text-xs font-medium text-muted-foreground">类型</span>
          <div className="flex flex-wrap gap-1.5">
            {receiptTypeOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setReceiptTypeFilter(opt.value)}
                className={`rounded-md px-2.5 py-1 text-sm font-medium transition-colors ${
                  receiptTypeFilter === opt.value
                    ? "bg-primary-600 text-white"
                    : "bg-background text-foreground hover:bg-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Batch action bar */}
      <AnimatePresence>
        {selectedIds.size > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="flex items-center gap-4 rounded-lg border border-primary-200 bg-primary-50 px-4 py-3"
          >
            <Checks size={18} className="text-primary-600" />
            <span className="text-sm font-medium text-primary-700">
              已选中 {selectedIds.size} 张发票
            </span>
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={() => {
                  navigate(`/reimbursements?ids=${[...selectedIds].join(",")}`);
                  clearSelection();
                }}
                className="rounded-md bg-primary-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-700"
              >
                创建报销单
              </button>
              <button
                onClick={() => {
                  const linked = filtered.filter(
                    (inv) => selectedIds.has(inv.id) && inv.reimbursement_id
                  );
                  if (linked.length > 0) {
                    setBatchDeleteIds(null);
                    setError(
                      `选中的 ${linked.length} 张发票已关联报销单，无法删除。请先从报销单中移除后再操作。`
                    );
                  } else {
                    setBatchDeleteIds(new Set(selectedIds));
                    setDeleteError(null);
                  }
                }}
                className="rounded-md bg-error-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-error-700"
              >
                批量删除
              </button>
              <button
                onClick={clearSelection}
                className="rounded-md bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
              >
                取消选择
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <div className="flex items-center gap-2 rounded-lg bg-error-50 p-4 text-sm text-error-700">
          <Warning size={18} />
          {error}
        </div>
      )}

      {/* Table */}
      {loading ? (
        <TableSkeleton rows={8} />
      ) : paged.length === 0 ? (
        <div className="rounded-xl border border-border bg-background">
          <EmptyState
            icon={<Receipt size={28} className="text-muted-foreground" />}
            title="没有匹配的发票"
            description="尝试更换筛选条件，或上传新的发票"
          />
        </div>
      ) : (
        <>
          <div className="overflow-hidden rounded-xl border border-border bg-background">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-3 py-2.5 w-10">
                      <input
                        type="checkbox"
                        checked={selectedIds.size === paged.length && paged.length > 0}
                        onChange={toggleSelectAll}
                        className="h-4 w-4 rounded border-border text-primary-600 focus:ring-primary-500"
                      />
                    </th>
                    <th className="px-3 py-2.5 w-12 whitespace-nowrap text-center font-medium">序号</th>
                    <th className="px-3 py-2.5 w-28 whitespace-nowrap font-medium">发票类型</th>
                    <th className="px-3 py-2.5 w-36 whitespace-nowrap font-medium">发票号码</th>
                    <th className="px-3 py-2.5 min-w-[120px] font-medium">销方名称</th>
                    <th className="px-3 py-2.5 w-20 whitespace-nowrap font-medium">金额</th>
                    <th className="px-3 py-2.5 w-24 whitespace-nowrap font-medium">分类</th>
                    <th className="px-3 py-2.5 w-20 whitespace-nowrap font-medium">验真</th>
                    <th className="px-3 py-2.5 w-20 whitespace-nowrap font-medium">查重</th>
                    <th className="px-3 py-2.5 w-16 whitespace-nowrap text-center font-medium">风险</th>
                    <th className="px-3 py-2.5 w-24 whitespace-nowrap font-medium">状态</th>
                    <th className="px-3 py-2.5 w-24 whitespace-nowrap font-medium">上传者</th>
                    <th className="px-3 py-2.5 w-28 whitespace-nowrap font-medium">上传日期</th>
                    <th className="px-3 py-2.5 w-20 whitespace-nowrap text-center font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {paged.map((inv, i) => (
                    <motion.tr
                      key={inv.id}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: i * 0.02 }}
                      className={`cursor-pointer transition-colors hover:bg-muted ${
                        selectedIds.has(inv.id) ? "bg-primary-50/50" : ""
                      }`}
                    >
                      <td
                        className="px-3 py-2.5"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleSelect(inv.id);
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={selectedIds.has(inv.id)}
                          onChange={() => toggleSelect(inv.id)}
                          onClick={(e) => e.stopPropagation()}
                          className="h-4 w-4 rounded border-border text-primary-600 focus:ring-primary-500"
                        />
                      </td>
                      <td
                        className="px-3 py-2.5 text-center font-mono text-xs text-muted-foreground"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        {(currentPage - 1) * PAGE_SIZE + i + 1}
                      </td>
                      <td
                        className="px-3 py-2.5"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        {inv.receipt_type ? (
                          <span
                            className={`inline-block whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ${
                              inv.is_nonstandard
                                ? "bg-accent-100 text-accent-700"
                                : "bg-muted text-foreground"
                            }`}
                          >
                            {inv.receipt_type}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td
                        className="px-3 py-2.5 whitespace-nowrap font-mono text-xs text-foreground"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        {inv.invoice_number || "—"}
                      </td>
                      <td
                        className="max-w-[180px] truncate px-3 py-2.5 text-foreground"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        {inv.seller_name || "—"}
                      </td>
                      <td
                        className="px-3 py-2.5 whitespace-nowrap font-medium text-foreground"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        {inv.total_with_tax ? `¥${inv.total_with_tax}` : "—"}
                      </td>
                      <td
                        className="px-3 py-2.5"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        <CategoryBadge category={inv.fee_category} subcategory={inv.fee_subcategory} />
                      </td>
                      <td
                        className="px-3 py-2.5"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        <VerifyBadge status={inv.verify_status} />
                      </td>
                      <td
                        className="px-3 py-2.5"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        <DuplicateBadge status={inv.duplicate_status} />
                      </td>
                      <td
                        className="px-3 py-2.5 text-center"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        {inv.is_nonstandard && inv.risk_level ? (
                          <span
                            className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${
                              inv.risk_level === "high"
                                ? "bg-error-100 text-error-700"
                                : inv.risk_level === "medium"
                                  ? "bg-warning-100 text-warning-700"
                                  : "bg-success-100 text-success-700"
                            }`}
                          >
                            {inv.risk_level === "high" ? "高" : inv.risk_level === "medium" ? "中" : "低"}
                          </span>
                        ) : inv.is_nonstandard ? (
                          <span className="text-xs text-muted-foreground">—</span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td
                        className="px-4 py-3"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        <StatusBadge status={inv.status} linked={!!inv.reimbursement_id} />
                      </td>
                      <td
                        className="px-3 py-2.5 whitespace-nowrap text-foreground"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        {inv.uploader_name || "—"}
                      </td>
                      <td
                        className="px-3 py-2.5 whitespace-nowrap text-muted-foreground"
                        onClick={() => setSelectedId(inv.id)}
                      >
                        {inv.created_at
                          ? new Date(inv.created_at).toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" })
                          : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <div className="flex items-center justify-center gap-1">
                          {inv.status === "REVIEWING" && (
                            <button
                              onClick={async (e) => {
                                e.stopPropagation();
                                try {
                                  const updated = await invoiceApi.approve(inv.id);
                                  setInvoices((prev) => prev.map((i) => i.id === updated.id ? updated : i));
                                } catch { /* ignore */ }
                              }}
                              className="inline-flex items-center justify-center rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-success-50 hover:text-success-600"
                              title="审核通过"
                            >
                              <Checks size={16} />
                            </button>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              window.open(invoiceApi.fileUrl(inv.id), "_blank");
                            }}
                            className="inline-flex items-center justify-center rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-primary-50 hover:text-primary-600"
                            title="下载原始发票"
                          >
                            <DownloadSimple size={16} />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              if (inv.reimbursement_id) {
                                setDeleteTarget(null);
                                setError("该发票已关联报销单，无法删除。请先从报销单中移除后再操作。");
                              } else {
                                setDeleteError(null);
                                setDeleteTarget(inv);
                              }
                            }}
                            className="inline-flex items-center justify-center rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-error-50 hover:text-error-600"
                            title="删除发票"
                          >
                            <Trash size={16} />
                          </button>
                        </div>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                第 {currentPage} / {totalPages} 页，共 {filtered.length} 条
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <CaretLeft size={14} /> 上一页
                </button>
                {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                  let page: number;
                  if (totalPages <= 7) {
                    page = i + 1;
                  } else if (currentPage <= 4) {
                    page = i + 1;
                  } else if (currentPage >= totalPages - 3) {
                    page = totalPages - 6 + i;
                  } else {
                    page = currentPage - 3 + i;
                  }
                  return (
                    <button
                      key={page}
                      onClick={() => setCurrentPage(page)}
                      className={`h-8 w-8 rounded-md text-sm font-medium transition-colors ${
                        currentPage === page
                          ? "bg-primary-600 text-white"
                          : "border border-border bg-background text-foreground hover:bg-muted"
                      }`}
                    >
                      {page}
                    </button>
                  );
                })}
                <button
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                  className="flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                >
                  下一页 <CaretRight size={14} />
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Detail Drawer */}
      <InvoiceDetailDrawer
        invoiceId={selectedId}
        onClose={() => {
          setSelectedId(null);
          if (searchParams.get("id")) {
            setSearchParams({});
          }
        }}
      />

      {/* Delete Confirmation Modal（单条 / 批量） */}
      <AnimatePresence>
        {(deleteTarget || batchDeleteIds) && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-background/40 backdrop-blur-sm"
            onClick={() => { if (!deleting) { setDeleteTarget(null); setBatchDeleteIds(null); setDeleteError(null); } }}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ type: "spring", damping: 25, stiffness: 400 }}
              className="mx-4 w-full max-w-md rounded-xl bg-background p-6 shadow-lg"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-error-50">
                  <Warning size={20} className="text-error-600" />
                </div>
                <div className="flex-1">
                  <h3 className="font-display text-base font-semibold text-foreground">
                    {batchDeleteIds ? "批量删除发票" : "删除发票"}
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {batchDeleteIds ? (
                      <>确定要删除选中的 <span className="font-mono font-medium text-foreground">{batchDeleteIds.size}</span> 张发票吗？</>
                    ) : (
                      <>确定要删除发票{" "}<span className="font-mono font-medium text-foreground">{deleteTarget?.invoice_number || `#${deleteTarget?.id}`}</span>{" "}吗？</>
                    )}
                    删除后不可恢复，关联的识别结果和原始文件将一并删除。
                  </p>
                </div>
              </div>

              {deleteError && (
                <div className="mt-4 flex items-start gap-2 rounded-lg bg-error-50 px-4 py-3 text-sm text-error-700">
                  <XCircle size={18} className="mt-0.5 shrink-0" />
                  <span>{deleteError}</span>
                </div>
              )}

              <div className="mt-6 flex items-center justify-end gap-3">
                <button
                  onClick={() => { if (!deleting) { setDeleteTarget(null); setBatchDeleteIds(null); setDeleteError(null); } }}
                  disabled={deleting}
                  className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                >
                  取消
                </button>
                <button
                  onClick={batchDeleteIds ? handleBatchDelete : handleDelete}
                  disabled={deleting}
                  className="flex items-center gap-2 rounded-md bg-error-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-error-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {deleting ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                      删除中...
                    </>
                  ) : (
                    <>
                      <Trash size={16} />
                      确认删除
                    </>
                  )}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Export Modal */}
      <AnimatePresence>
        {showExportModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-background/40 backdrop-blur-sm"
            onClick={() => !exporting && setShowExportModal(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ type: "spring", damping: 25, stiffness: 400 }}
              className="mx-4 w-full max-w-md rounded-xl bg-background p-6 shadow-lg"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-50">
                  <FileXls size={20} className="text-primary-600" />
                </div>
                <div className="flex-1">
                  <h3 className="font-display text-base font-semibold text-foreground">
                    导出发票清单
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    选择要导出的上传者范围，将生成 xlsx 文件下载。
                  </p>
                </div>
              </div>

              <div className="mt-4">
                <select
                  value={exportUploader}
                  onChange={(e) => setExportUploader(e.target.value)}
                  className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-primary-400"
                >
                  <option value="">全部上传者</option>
                  {uploaderOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              <div className="mt-6 flex items-center justify-end gap-3">
                <button
                  onClick={() => { if (!exporting) { setShowExportModal(false); setExportUploader(""); } }}
                  disabled={exporting}
                  className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                >
                  取消
                </button>
                <button
                  onClick={handleExport}
                  disabled={exporting}
                  className="flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {exporting ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                      导出中...
                    </>
                  ) : (
                    <>
                      <FileXls size={16} />
                      确认导出
                    </>
                  )}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
