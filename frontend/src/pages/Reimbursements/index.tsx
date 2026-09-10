import { useSearchParams } from "react-router-dom";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { reimbursementApi, invoiceApi } from "../../api/client";
import type {
  Reimbursement,
  Invoice,
  ReimbursementAttachment,
} from "../../types";
import { ReimbursementList } from "./ReimbursementList";
import { ReimbursementCreate } from "./ReimbursementCreate";
import { ReimbursementDetail } from "./ReimbursementDetail";
import type { View } from "./shared";

function useReimbursementsPageState() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Determine initial view from URL
  const idsParam = searchParams.get("ids");
  const detailParam = searchParams.get("detail");
  const initialView: View = idsParam
    ? "create"
    : detailParam
      ? "detail"
      : "list";

  const [view, setView] = useState<View>(initialView);
  const [statusFilter, setStatusFilter] = useState("all");

  // Data
  const [reimbursements, setReimbursements] = useState<Reimbursement[]>([]);
  const [allInvoices, setAllInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail state
  const [detailId, setDetailId] = useState<number | null>(
    initialView === "detail" ? Number(detailParam) : null
  );
  const [detailReimb, setDetailReimb] = useState<Reimbursement | null>(null);
  const [detailInvoices, setDetailInvoices] = useState<Invoice[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reimbursing, setReimbursing] = useState(false);
  const [showAddInvoice, setShowAddInvoice] = useState(false);
  const [addInvoiceIds, setAddInvoiceIds] = useState<number[]>([]);
  const [addingInvoices, setAddingInvoices] = useState(false);
  const [removingInvoiceId, setRemovingInvoiceId] = useState<number | null>(null);
  const [detailAttachments, setDetailAttachments] = useState<ReimbursementAttachment[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [deletingAttachmentId, setDeletingAttachmentId] = useState<number | null>(null);
  const detailFileInputRef = useRef<HTMLInputElement>(null);

  // Create form
  const [selectedIds, setSelectedIds] = useState<number[]>(
    idsParam
      ? idsParam
          .split(",")
          .map(Number)
          .filter((n) => !isNaN(n) && n > 0)
      : []
  );
  const [applicantId, setApplicantId] = useState("test_user_001");
  const [applicantName, setApplicantName] = useState("");
  const [department, setDepartment] = useState("");
  const [period, setPeriod] = useState(
    new Date().toISOString().slice(0, 7)
  );
  const [reason, setReason] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);

  // 删除状态
  const [deleteTarget, setDeleteTarget] = useState<Reimbursement | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  /* ---------- Effects ---------- */

  // Initial fetch
  useEffect(() => {
    Promise.all([reimbursementApi.list(), invoiceApi.list()])
      .then(([reimb, invs]) => {
        setReimbursements(reimb);
        setAllInvoices(invs);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Fetch detail when switching to detail view
  useEffect(() => {
    if (view !== "detail" || !detailId) return;
    setDetailLoading(true);
    setError(null);
    Promise.all([reimbursementApi.detail(detailId), invoiceApi.list()])
      .then(([reimb, invs]) => {
        setDetailReimb(reimb);
        setDetailAttachments(reimb.attachments || []);
        setDetailInvoices(invs.filter((inv) => inv.reimbursement_id === detailId));
      })
      .catch((e) => setError(e.message))
      .finally(() => setDetailLoading(false));
  }, [view, detailId]);

  /* ---------- Handlers ---------- */

  const goToCreate = useCallback(() => {
    setView("create");
    setSearchParams({});
  }, [setSearchParams]);

  const goToList = useCallback(() => {
    setView("list");
    setDetailId(null);
    setDetailReimb(null);
    setDetailInvoices([]);
    setDetailAttachments([]);
    setSearchParams({});
    // Refresh list
    reimbursementApi.list().then(setReimbursements).catch(() => {});
  }, [setSearchParams]);

  const goToDetail = useCallback(
    (id: number) => {
      setDetailId(id);
      setView("detail");
      setSearchParams({ detail: String(id) });
    },
    [setSearchParams]
  );

  const toggleInvoice = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleCreate = async () => {
    if (!applicantId) return;
    if (!reason.trim()) {
      setError("报销事由为必填项");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await reimbursementApi.create({
        applicant_id: applicantId,
        applicant_name: applicantName || undefined,
        department: department || undefined,
        period: period || undefined,
        reason: reason.trim(),
        invoice_ids: selectedIds.length > 0 ? selectedIds : undefined,
      });

      // 创建成功后上传待传附件
      if (pendingFiles.length > 0) {
        setUploadingAttachments(true);
        for (const file of pendingFiles) {
          try {
            await reimbursementApi.uploadAttachment(created.id, file);
          } catch (e) {
            console.error("附件上传失败:", file.name, e);
          }
        }
        setUploadingAttachments(false);
        setPendingFiles([]);
      }

      const list = await reimbursementApi.list();
      setReimbursements(list);
      goToDetail(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const handleSubmit = async (id: number) => {
    setSubmitting(true);
    setError(null);
    try {
      await reimbursementApi.submit(id);
      const updated = await reimbursementApi.detail(id);
      setDetailReimb(updated);
      const list = await reimbursementApi.list();
      setReimbursements(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleWithdraw = async (id: number) => {
    if (!window.confirm("确定要撤回该报销单吗？撤回后将恢复为草稿状态，可继续编辑。")) return;
    setWithdrawing(true);
    setError(null);
    try {
      await reimbursementApi.withdraw(id);
      const updated = await reimbursementApi.detail(id);
      setDetailReimb(updated);
      const list = await reimbursementApi.list();
      setReimbursements(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "撤回失败");
    } finally {
      setWithdrawing(false);
    }
  };

  const handleApprove = async (id: number) => {
    if (!window.confirm("确定审核通过该报销单吗？")) return;
    setApproving(true);
    setError(null);
    try {
      await reimbursementApi.approve(id);
      const updated = await reimbursementApi.detail(id);
      setDetailReimb(updated);
      const list = await reimbursementApi.list();
      setReimbursements(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "审核失败");
    } finally {
      setApproving(false);
    }
  };

  const handleReject = async (id: number) => {
    const reason = window.prompt("请输入驳回原因（可选）：", "");
    if (reason === null) return; // 用户点了取消
    setRejecting(true);
    setError(null);
    try {
      await reimbursementApi.reject(id, reason || undefined);
      const updated = await reimbursementApi.detail(id);
      setDetailReimb(updated);
      const list = await reimbursementApi.list();
      setReimbursements(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "驳回失败");
    } finally {
      setRejecting(false);
    }
  };

  const handleReimburse = async (id: number) => {
    if (!window.confirm("确认该报销单已打款吗？标记后将变为「已报销」状态。")) return;
    setReimbursing(true);
    setError(null);
    try {
      await reimbursementApi.reimburse(id);
      const updated = await reimbursementApi.detail(id);
      setDetailReimb(updated);
      const list = await reimbursementApi.list();
      setReimbursements(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "标记打款失败");
    } finally {
      setReimbursing(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await reimbursementApi.delete(deleteTarget.id);
      const list = await reimbursementApi.list();
      setReimbursements(list);
      // 如果在详情视图删除，返回列表
      if (view === "detail" && detailId === deleteTarget.id) {
        goToList();
      }
      setDeleteTarget(null);
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "删除失败，请稍后重试");
    } finally {
      setDeleting(false);
    }
  };

  /* ---------- Computed values ---------- */

  const availableInvoices = useMemo(() => {
    return allInvoices.filter(
      (inv) =>
        (inv.is_nonstandard
          ? inv.status === "REVIEWED"
          : inv.verify_status === "VALID") &&
        inv.duplicate_status === "UNIQUE" &&
        !inv.reimbursement_id
    );
  }, [allInvoices]);

  const selectedTotal = useMemo(() => {
    return availableInvoices
      .filter((inv) => selectedIds.includes(inv.id))
      .reduce(
        (sum, inv) => sum + parseFloat(inv.total_with_tax || "0"),
        0
      );
  }, [availableInvoices, selectedIds]);

  const filteredReimbs = useMemo(() => {
    if (statusFilter === "all") return reimbursements;
    return reimbursements.filter((r) => r.status === statusFilter);
  }, [reimbursements, statusFilter]);

  return {
    // View routing
    view,

    // List data
    reimbursements,
    filteredReimbs,
    loading,
    error,
    setError,
    statusFilter,
    setStatusFilter,

    // Navigation
    goToCreate,
    goToList,
    goToDetail,

    // Create form
    allInvoices,
    setAllInvoices,
    availableInvoices,
    selectedIds,
    toggleInvoice,
    selectedTotal,
    applicantId,
    setApplicantId,
    applicantName,
    setApplicantName,
    department,
    setDepartment,
    period,
    setPeriod,
    reason,
    setReason,
    pendingFiles,
    setPendingFiles,
    fileInputRef,
    creating,
    uploadingAttachments,
    handleCreate,

    // Detail state
    detailId,
    detailReimb,
    setDetailReimb,
    detailInvoices,
    setDetailInvoices,
    detailLoading,
    detailAttachments,
    setDetailAttachments,
    submitting,
    withdrawing,
    approving,
    rejecting,
    reimbursing,
    handleSubmit,
    handleWithdraw,
    handleApprove,
    handleReject,
    handleReimburse,
    showAddInvoice,
    setShowAddInvoice,
    addInvoiceIds,
    setAddInvoiceIds,
    addingInvoices,
    setAddingInvoices,
    removingInvoiceId,
    setRemovingInvoiceId,
    uploadingAttachment,
    setUploadingAttachment,
    deletingAttachmentId,
    setDeletingAttachmentId,
    detailFileInputRef,

    // Delete
    deleteTarget,
    setDeleteTarget,
    deleting,
    deleteError,
    setDeleteError,
    handleDelete,
  };
}

export type ReimbursementsPageState = ReturnType<typeof useReimbursementsPageState>;

export function Reimbursements() {
  const state = useReimbursementsPageState();
  if (state.view === "list") return <ReimbursementList state={state} />;
  if (state.view === "create") return <ReimbursementCreate state={state} />;
  return <ReimbursementDetail state={state} />;
}
