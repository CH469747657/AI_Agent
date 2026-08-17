import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Invoice, InvoiceStatus } from "../../types";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "CONFIRMED", label: "已确认" },
  { value: "REVIEWING", label: "待复核" },
  { value: "REIMBURSED", label: "已报销" },
  { value: "NOT_REIMBURSED", label: "未报销" },
];

const STATUS_BADGE: Record<InvoiceStatus, string> = {
  UPLOADED: "boss-badge boss-badge--draft",
  PROCESSING: "boss-badge boss-badge--pending",
  REVIEWING: "boss-badge boss-badge--pending",
  CONFIRMED: "boss-badge boss-badge--confirmed",
  REIMBURSED: "boss-badge boss-badge--reimbursed",
  NOT_REIMBURSED: "boss-badge boss-badge--draft",
};

const STATUS_LABEL: Record<InvoiceStatus, string> = {
  UPLOADED: "已上传",
  PROCESSING: "识别中",
  REVIEWING: "待复核",
  CONFIRMED: "已确认",
  REIMBURSED: "已报销",
  NOT_REIMBURSED: "未报销",
};

export function BossInvoiceList() {
  const navigate = useNavigate();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const data = await bossApi.listInvoices({
          status: status || undefined,
        });
        setInvoices(data);
      } catch {
        setInvoices([]);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [status]);

  const filtered = keyword
    ? invoices.filter(
        (inv) =>
          inv.seller_name?.toLowerCase().includes(keyword.toLowerCase()) ||
          inv.invoice_number?.includes(keyword)
      )
    : invoices;

  return (
    <div className="boss-list">
      <div className="boss-list__header">
        <div className="boss-list__title">发票</div>
        <div className="boss-filter-bar">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="搜索销售方/发票号"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ flex: 1, minWidth: 120 }}
          />
        </div>
      </div>
      {loading ? (
        <div className="boss-empty">加载中…</div>
      ) : filtered.length === 0 ? (
        <div className="boss-empty">没有发票</div>
      ) : (
        filtered.map((inv) => (
          <div
            key={inv.id}
            className="boss-card"
            onClick={() => navigate(`/boss/invoices/${inv.id}`)}
          >
            <div className="boss-card__top">
              <span className="boss-card__title">
                {inv.seller_name || "（无销售方）"}
              </span>
              <span className="boss-card__amount">
                ¥{inv.total_with_tax || inv.amount || "0.00"}
              </span>
            </div>
            <div className="boss-card__meta">
              <span>
                {inv.expense_date || inv.issue_date || "—"} ·{" "}
                {inv.uploader_name || inv.user_id || "—"}
              </span>
              <span className={STATUS_BADGE[inv.status]}>
                {STATUS_LABEL[inv.status]}
              </span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
