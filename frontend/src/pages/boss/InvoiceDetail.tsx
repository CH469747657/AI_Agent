import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { InvoiceDetail } from "../../types";

export function BossInvoiceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [imgUrl, setImgUrl] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await bossApi.getInvoice(Number(id));
        setInv(data);
        const url = await bossApi.fetchInvoiceFile(Number(id));
        setImgUrl(url);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    };
    load();
    return () => {
      if (imgUrl) URL.revokeObjectURL(imgUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
          发票详情 #{id}
        </span>
      </div>
      {loading ? (
        <div className="boss-empty">加载中…</div>
      ) : error ? (
        <div className="boss-empty">{error}</div>
      ) : inv ? (
        <>
          <div className="boss-detail__section">
            <div className="boss-detail__section-title">基本信息</div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">发票号</span>
              <span className="boss-detail__field-value">
                {inv.invoice_number || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">状态</span>
              <span className="boss-detail__field-value">{inv.status}</span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">开票日期</span>
              <span className="boss-detail__field-value">
                {inv.issue_date || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">费用发生日</span>
              <span className="boss-detail__field-value">
                {inv.expense_date || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">上传人</span>
              <span className="boss-detail__field-value">
                {inv.uploader_name || inv.user_id || "—"}
              </span>
            </div>
          </div>
          <div className="boss-detail__section">
            <div className="boss-detail__section-title">金额</div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">金额（不含税）</span>
              <span className="boss-detail__field-value">
                ¥{inv.amount || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">税额</span>
              <span className="boss-detail__field-value">
                ¥{inv.tax_amount || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">价税合计</span>
              <span className="boss-detail__field-value">
                ¥{inv.total_with_tax || "—"}
              </span>
            </div>
          </div>
          <div className="boss-detail__section">
            <div className="boss-detail__section-title">销售方 / 购买方</div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">销售方</span>
              <span className="boss-detail__field-value">
                {inv.seller_name || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">销售方税号</span>
              <span className="boss-detail__field-value">
                {inv.seller_tax_id || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">购买方</span>
              <span className="boss-detail__field-value">
                {inv.buyer_name || "—"}
              </span>
            </div>
          </div>
          <div className="boss-detail__section">
            <div className="boss-detail__section-title">分类</div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">费用分类</span>
              <span className="boss-detail__field-value">
                {inv.fee_category || "—"}
              </span>
            </div>
            <div className="boss-detail__field">
              <span className="boss-detail__field-label">明细子类</span>
              <span className="boss-detail__field-value">
                {inv.fee_subcategory || "—"}
              </span>
            </div>
          </div>
          {inv.reimbursement_id && (
            <div className="boss-detail__section">
              <div className="boss-detail__section-title">关联报销单</div>
              <a
                className="boss-link-card"
                href={`#/boss/reimbursements/${inv.reimbursement_id}`}
                onClick={(e) => {
                  e.preventDefault();
                  navigate(`/boss/reimbursements/${inv.reimbursement_id}`);
                }}
              >
                报销单 #{inv.reimbursement_id} →
              </a>
            </div>
          )}
          {imgUrl && (
            <div className="boss-detail__section">
              <div className="boss-detail__section-title">发票图片</div>
              <img
                className="boss-image-preview"
                src={imgUrl}
                alt="发票图片"
              />
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
