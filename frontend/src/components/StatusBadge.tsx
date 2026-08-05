import {
  InvoiceStatus,
  VerifyStatus,
  DuplicateStatus,
  FeeCategory,
} from "../types";

const statusConfig: Record<
  InvoiceStatus,
  { label: string; className: string }
> = {
  UPLOADED: {
    label: "已上传",
    className: "bg-slate-100 text-slate-600",
  },
  PROCESSING: {
    label: "处理中",
    className: "bg-blue-50 text-blue-700",
  },
  REVIEWING: {
    label: "待审核",
    className: "bg-amber-50 text-amber-700",
  },
  CONFIRMED: {
    label: "已确认",
    className: "bg-emerald-50 text-emerald-700",
  },
  REIMBURSED: {
    label: "已报销",
    className: "bg-brand-50 text-brand-700",
  },
  NOT_REIMBURSED: {
    label: "不予报销",
    className: "bg-rose-50 text-rose-700",
  },
};

export function StatusBadge({
  status,
  linked,
}: {
  status: InvoiceStatus;
  linked?: boolean;
}) {
  // 已关联报销单的发票优先显示「已关联」
  if (linked) {
    return (
      <span className="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium bg-indigo-50 text-indigo-700">
        已关联
      </span>
    );
  }
  const config = statusConfig[status] || statusConfig.UPLOADED;
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  );
}

const verifyConfig: Record<VerifyStatus, { label: string; className: string }> =
  {
    PENDING: { label: "待验真", className: "bg-slate-100 text-slate-500" },
    VALID: { label: "验真通过", className: "bg-emerald-50 text-emerald-700" },
    INVALID: { label: "验真失败", className: "bg-rose-50 text-rose-700" },
    UNABLE_TO_VERIFY: {
      label: "无法验真",
      className: "bg-amber-50 text-amber-700",
    },
  };

export function VerifyBadge({ status }: { status: VerifyStatus | null }) {
  if (!status) return <span className="text-slate-300">—</span>;
  const config = verifyConfig[status];
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  );
}

const dupConfig: Record<
  DuplicateStatus,
  { label: string; className: string }
> = {
  PENDING: { label: "待查重", className: "bg-slate-100 text-slate-500" },
  UNIQUE: { label: "唯一", className: "bg-emerald-50 text-emerald-700" },
  DUPLICATE: { label: "重复", className: "bg-rose-50 text-rose-700" },
};

export function DuplicateBadge({
  status,
}: {
  status: DuplicateStatus | null;
}) {
  if (!status) return <span className="text-slate-300">—</span>;
  const config = dupConfig[status];
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  );
}

export function CategoryBadge({
  category,
  subcategory,
}: {
  category: FeeCategory | null;
  subcategory?: string | null;
}) {
  if (!category) return <span className="text-slate-300">—</span>;
  const isCompany = category === "company";
  const label = subcategory
    ? `${isCompany ? "公司" : "个人"}-${subcategory}`
    : isCompany
      ? "公司"
      : "个人";
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${
        isCompany
          ? "bg-violet-50 text-violet-700"
          : "bg-orange-50 text-orange-700"
      }`}
    >
      {label}
    </span>
  );
}
