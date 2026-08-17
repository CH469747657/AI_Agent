import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Reimbursement, ReimbursementStatus } from "../../types";
import {
  ArrowLeft,
  Spinner,
  WarningCircle,
  Link as LinkIcon,
  Stack,
} from "@phosphor-icons/react";

const statusLabels: Record<ReimbursementStatus, { label: string; color: string }> = {
  DRAFT: { label: "草稿", color: "bg-muted text-muted-foreground" },
  SUBMITTED: { label: "待审批", color: "bg-warning-50 text-warning-700" },
  REVIEWED: { label: "已批准", color: "bg-success-50 text-success-700" },
  REIMBURSED: { label: "已报销", color: "bg-primary-50 text-primary-700" },
};

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

  if (!r) return null;

  const sc = statusLabels[r.status] || statusLabels.DRAFT;

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
            报销单 #{r.id}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            {r.applicant_name || r.applicant_id}
            {r.department && ` · ${r.department}`}
          </p>
        </div>
        <p className="shrink-0 font-display text-lg font-bold text-primary-700 sm:text-2xl">
          ¥{(r.total_amount ?? 0).toFixed(2)}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${sc.color}`}
        >
          {sc.label}
        </span>
      </div>

      <Section title="基本信息">
        <Field label="申请人" value={r.applicant_name || r.applicant_id} />
        <Field label="部门" value={r.department} />
        <Field label="周期" value={r.period} />
        <Field label="周期范围" value={r.cycle_start && r.cycle_end ? `${r.cycle_start} ~ ${r.cycle_end}` : null} />
        <Field label="事由" value={r.reason} />
      </Section>

      <Section title="金额">
        <Field
          label="发票总额"
          value={`¥${(r.expense_total ?? 0).toFixed(2)}`}
        />
        <Field
          label="补贴总额"
          value={`¥${(r.subsidy_total ?? 0).toFixed(2)}`}
        />
        <Field
          label="合计"
          value={`¥${(r.total_amount ?? 0).toFixed(2)}`}
          highlight
        />
      </Section>

      <Section title="审批记录">
        <Field label="提交时间" value={r.submitted_at} />
        <Field label="批准时间" value={r.confirmed_at} />
        <Field label="封账时间" value={r.locked_at} />
        <Field label="自动生成" value={r.auto_generated ? "是" : "否"} />
      </Section>

      {r.items && r.items.length > 0 ? (
        <div className="rounded-xl border border-border bg-background p-4 shadow-sm">
          <h3 className="mb-3 flex items-center gap-1.5 font-display text-sm font-semibold text-foreground/70">
            <LinkIcon size={14} className="text-muted" />
            关联发票（{r.items.length}）
          </h3>
          <div className="space-y-2">
            {r.items.map((it) => (
              <button
                key={it.id}
                onClick={() =>
                  it.invoice_id && navigate(`/boss/invoices/${it.invoice_id}`)
                }
                disabled={!it.invoice_id}
                className="flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-background p-2.5 text-left transition-colors hover:bg-muted disabled:cursor-default disabled:opacity-60"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {it.fee_subcategory || it.fee_category || "未分类"}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {it.item_date || "—"} ·{" "}
                    {it.description || "无备注"}
                  </p>
                </div>
                <span className="shrink-0 font-display text-sm font-bold text-foreground">
                  ¥{it.amount.toFixed(2)}
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-background py-12 text-center">
          <Stack size={36} className="text-muted" />
          <p className="mt-2 text-xs text-muted-foreground">无关联发票</p>
        </div>
      )}
    </div>
  );
}
