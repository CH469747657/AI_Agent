import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { InvoiceDetail } from "../../types";
import {
  ArrowLeft,
  Spinner,
  WarningCircle,
  Link as LinkIcon,
  Receipt,
} from "@phosphor-icons/react";
import {
  StatusBadge,
  VerifyBadge,
  DuplicateBadge,
  CategoryBadge,
} from "../../components/StatusBadge";

function Field({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number | null | undefined;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <span className="text-xs text-muted-foreground sm:text-sm">{label}</span>
      <span
        className={`text-right text-sm ${
          highlight
            ? "font-display text-base font-bold text-foreground"
            : "font-medium text-foreground"
        }`}
      >
        {value ?? "—"}
      </span>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border bg-background p-4 shadow-sm">
      <h3 className="mb-2 font-display text-sm font-semibold text-foreground/70">
        {title}
      </h3>
      <div className="divide-y divide-border">{children}</div>
    </div>
  );
}

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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size={24} className="animate-spin text-primary-700" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft size={16} />
          返回
        </button>
        <div className="flex items-center gap-2 rounded-xl bg-error-50 p-4 text-sm text-error-700">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      </div>
    );
  }

  if (!inv) return null;

  return (
    <div className="space-y-4 sm:space-y-6">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft size={16} />
        返回
      </button>

      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h1 className="font-display text-lg font-bold text-foreground sm:text-xl">
            发票详情 #{inv.id}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            {inv.seller_name || "未识别销售方"}
          </p>
        </div>
        <p className="shrink-0 font-display text-lg font-bold text-primary-700 sm:text-2xl">
          ¥{inv.total_with_tax || inv.amount || "-"}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={inv.status} linked={!!inv.reimbursement_id} />
        <VerifyBadge status={inv.verify_status} />
        <DuplicateBadge status={inv.duplicate_status} />
        <CategoryBadge
          category={inv.fee_category}
          subcategory={inv.fee_subcategory}
        />
      </div>

      <Section title="基本信息">
        <Field label="发票号码" value={inv.invoice_number} />
        <Field label="发票代码" value={inv.invoice_code} />
        <Field label="开票日期" value={inv.issue_date} />
        <Field label="费用发生日" value={inv.expense_date} />
        <Field label="上传人" value={inv.uploader_name || inv.user_id} />
      </Section>

      <Section title="金额">
        <Field label="金额（不含税）" value={inv.amount ? `¥${inv.amount}` : null} />
        <Field label="税额" value={inv.tax_amount ? `¥${inv.tax_amount}` : null} />
        <Field
          label="价税合计"
          value={inv.total_with_tax ? `¥${inv.total_with_tax}` : null}
          highlight
        />
      </Section>

      <Section title="销售方 / 购买方">
        <Field label="销售方名称" value={inv.seller_name} />
        <Field label="销售方税号" value={inv.seller_tax_id} />
        <Field label="购买方名称" value={inv.buyer_name} />
        <Field label="购买方税号" value={inv.buyer_tax_id} />
      </Section>

      <Section title="分类与用途">
        <Field label="票据类型" value={inv.receipt_type} />
        <Field
          label="费用分类"
          value={
            inv.fee_subcategory
              ? `${inv.fee_category === "company" ? "公司" : "个人"}-${inv.fee_subcategory}`
              : inv.fee_category
          }
        />
        <Field label="备注" value={inv.user_description} />
      </Section>

      {inv.reimbursement_id && (
        <button
          onClick={() => navigate(`/boss/reimbursements/${inv.reimbursement_id}`)}
          className="flex w-full items-center justify-between rounded-xl border border-primary-200 bg-primary-50 p-4 text-left transition-colors hover:bg-primary-100"
        >
          <div className="flex items-center gap-2">
            <LinkIcon size={18} className="text-primary-700" />
            <div>
              <p className="text-xs text-primary-600">关联报销单</p>
              <p className="font-display text-sm font-bold text-primary-700">
                报销单 #{inv.reimbursement_id}
              </p>
            </div>
          </div>
          <ArrowLeft size={16} className="rotate-180 text-primary-700" />
        </button>
      )}

      {imgUrl ? (
        <div className="rounded-xl border border-border bg-background p-4 shadow-sm">
          <h3 className="mb-3 font-display text-sm font-semibold text-foreground/70">
            发票图片
          </h3>
          <img
            src={imgUrl}
            alt="发票图片"
            className="w-full rounded-lg border border-border"
          />
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-background py-12 text-center">
          <Receipt size={36} className="text-muted" />
          <p className="mt-2 text-xs text-muted-foreground">无发票图片</p>
        </div>
      )}
    </div>
  );
}
