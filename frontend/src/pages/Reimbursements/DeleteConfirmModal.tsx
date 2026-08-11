import { ConfirmModal } from "../../components/ConfirmModal";
import type { Reimbursement } from "../../types";

export function DeleteConfirmModal({
  target,
  deleting,
  deleteError,
  onCancel,
  onConfirm,
}: {
  target: Reimbursement | null;
  deleting: boolean;
  deleteError: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!target) return null;

  return (
    <ConfirmModal
      open={!!target}
      title="删除报销单"
      description={`确定要删除报销单 #${target.id} 吗？关联的发票将被解除关联（不会被删除），已生成的报表文件将一并清除。`}
      confirmText="确认删除"
      variant="danger"
      loading={deleting}
      error={deleteError}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}
