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
    className: "bg-muted text-muted-foreground",
  },
  PROCESSING: {
    label: "处理中",
    className: "bg-primary-50 text-primary-700",
  },
  REVIEWING: {
    label: "待审核",
    className: "bg-warning-50 text-warning-700",
  },
  CONFIRMED: {
    label: "已确认",
    className: "bg-success-50 text-success-700",
  },
  REIMBURSED: {
    label: "已报销",
    className: "bg-primary-50 text-primary-700",
  },
  NOT_REIMBURSED: {
    label: "不予报销",
    className: "bg-error-50 text-error-700",
  },
};

export function StatusBadge({
  status,
  linked,
}: {
  status: InvoiceStatus;
  linked?: boolean;
}) {
  if (linked) {
    return (
      <span className="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium bg-primary-50 text-primary-700">
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
    PENDING: { label: "待验真", className: "bg-muted text-muted-foreground" },
    VALID: { label: "验真通过", className: "bg-success-50 text-success-700" },
    INVALID: { label: "验真失败", className: "bg-error-50 text-error-700" },
    UNABLE_TO_VERIFY: {
      label: "无法验真",
      className: "bg-warning-50 text-warning-700",
    },
  };

export function VerifyBadge({ status }: { status: VerifyStatus | null }) {
  if (!status) return <span className="text-muted-foreground">—</span>;
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
  PENDING: { label: "待查重", className: "bg-muted text-muted-foreground" },
  UNIQUE: { label: "唯一", className: "bg-success-50 text-success-700" },
  DUPLICATE: { label: "重复", className: "bg-error-50 text-error-700" },
};

export function DuplicateBadge({
  status,
}: {
  status: DuplicateStatus | null;
}) {
  if (!status) return <span className="text-muted-foreground">—</span>;
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
  if (!category) return <span className="text-muted-foreground">—</span>;
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
          ? "bg-primary-50 text-primary-700"
          : "bg-accent-50 text-accent-700"
      }`}
    >
      {label}
    </span>
  );
}
