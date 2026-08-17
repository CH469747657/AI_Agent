import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Reimbursement, ReimbursementStatus } from "../../types";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "DRAFT", label: "草稿" },
  { value: "SUBMITTED", label: "待审批" },
  { value: "REVIEWED", label: "已批准" },
  { value: "REIMBURSED", label: "已报销" },
];

const STATUS_BADGE: Record<ReimbursementStatus, string> = {
  DRAFT: "boss-badge boss-badge--draft",
  SUBMITTED: "boss-badge boss-badge--pending",
  REVIEWED: "boss-badge boss-badge--approved",
  REIMBURSED: "boss-badge boss-badge--reimbursed",
};

const STATUS_LABEL: Record<ReimbursementStatus, string> = {
  DRAFT: "草稿",
  SUBMITTED: "待审批",
  REVIEWED: "已批准",
  REIMBURSED: "已报销",
};

export function BossReimbursementList() {
  const navigate = useNavigate();
  const [reimbs, setReimbs] = useState<Reimbursement[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const data = await bossApi.listReimbursements();
        setReimbs(data);
      } catch {
        setReimbs([]);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const filtered = statusFilter
    ? reimbs.filter((r) => r.status === statusFilter)
    : reimbs;

  return (
    <div className="boss-list">
      <div className="boss-list__header">
        <div className="boss-list__title">报销单</div>
        <div className="boss-filter-bar">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {loading ? (
        <div className="boss-empty">加载中…</div>
      ) : filtered.length === 0 ? (
        <div className="boss-empty">没有报销单</div>
      ) : (
        filtered.map((r) => (
          <div
            key={r.id}
            className="boss-card"
            onClick={() => navigate(`/boss/reimbursements/${r.id}`)}
          >
            <div className="boss-card__top">
              <span className="boss-card__title">
                {r.applicant_name || r.applicant_id || "—"} ·{" "}
                {r.department || "—"}
              </span>
              <span className="boss-card__amount">
                ¥{(r.total_amount ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="boss-card__meta">
              <span>
                {r.period || "—"}
                {r.cycle_key ? ` · ${r.cycle_key}` : ""}
              </span>
              <span className={STATUS_BADGE[r.status]}>
                {STATUS_LABEL[r.status]}
              </span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
