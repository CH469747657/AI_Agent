import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Reimbursement } from "../../types";

export function BossReimbursementDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [r, setR] = useState<Reimbursement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await bossApi.getReimbursement(Number(id));
        setR(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  return (
    <div className="boss-detail">
      <div className="boss-detail__header">
        <button
          className="boss-detail__back"
          onClick={() => navigate(-1)}
        >
          ←
        </button>
        <span className="boss-detail__title">
          报销单 #{id}
        </span>
      </div>
      {loading ? (
        <div className="boss-empty">加载中…</div>
      ) : error ? (
        <div className="boss-empty">{error}</div>
      ) : r ? (
        <>
          <div className="boss-detail__section">
            <div className="boss-detail__section-title">基本信息</div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">状态</span>
              <span className="boss-detail__field-value">{r.status}</span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">申请人</span>
              <span className="boss-detail__field-value">
                {r.applicant_name || r.applicant_id || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">部门</span>
              <span className="boss-detail__field-value">
                {r.department || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">周期</span>
              <span className="boss-detail__field-value">
                {r.period || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">事由</span>
              <span className="boss-detail__field-value">
                {r.reason || "—"}
              </span>
            </div>
          </div>
          <div className="boss-detail__section">
            <div className="boss-detail__section-title">金额</div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">发票总额</span>
              <span className="boss-detail__field-value">
                ¥{(r.expense_total ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">补贴总额</span>
              <span className="boss-detail__field-value">
                ¥{(r.subsidy_total ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">合计</span>
              <span className="boss-detail__field-value">
                ¥{(r.total_amount ?? 0).toFixed(2)}
              </span>
            </div>
          </div>
          <div className="boss-detail__section">
            <div className="boss-detail__section-title">时间</div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">周期起</span>
              <span className="boss-detail__field-value">
                {r.cycle_start || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">周期止</span>
              <span className="boss-detail__field-value">
                {r.cycle_end || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">提交时间</span>
              <span className="boss-detail__field-value">
                {r.submitted_at || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">批准时间</span>
              <span className="boss-detail__field-value">
                {r.confirmed_at || "—"}
              </span>
            </div>
          </div>
          {r.items && r.items.length > 0 && (
            <div className="boss-detail__section">
              <div className="boss-detail__section-title">关联发票</div>
              {r.items.map((it) => (
                <a
                  key={it.id}
                  className="boss-link-card"
                  href={`#/boss/invoices/${it.invoice_id}`}
                  onClick={(e) => {
                    e.preventDefault();
                    if (it.invoice_id) {
                      navigate(`/boss/invoices/${it.invoice_id}`);
                    }
                  }}
                >
                  {it.fee_subcategory || it.fee_category || "—"} · ¥
                  {it.amount.toFixed(2)} · {it.item_date || "—"}
                </a>
              ))}
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
