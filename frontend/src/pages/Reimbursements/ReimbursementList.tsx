import { motion } from "framer-motion";
import { Plus, Stack, Warning, Trash, ArrowUUpLeft, Lock, Check } from "@phosphor-icons/react";
import { EmptyState, TableSkeleton } from "../../components/EmptyState";
import { ReimbStatusBadge, statusTabs, cycleLabel } from "./shared";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import type { ReimbursementsPageState } from "./index";

export function ReimbursementList({ state }: { state: ReimbursementsPageState }) {
  const {
    filteredReimbs,
    loading,
    error,
    statusFilter,
    setStatusFilter,
    goToCreate,
    goToDetail,
    handleWithdraw,
    withdrawing,
    handleReimburse,
    reimbursing,
    deleteTarget,
    setDeleteTarget,
    deleting,
    deleteError,
    setDeleteError,
    handleDelete,
  } = state;

  return (
    <>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
              报销单管理
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              创建报销单、关联发票、生成报表并下载
            </p>
          </div>
          <button
            onClick={goToCreate}
            className="flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white transition-all hover:bg-primary-700 active:scale-[0.98]"
          >
            <Plus size={18} weight="bold" />
            新建报销单
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
            <Warning size={18} />
            {error}
          </div>
        )}

        {/* Status filter tabs */}
        <div className="flex gap-2">
          {statusTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setStatusFilter(tab.key)}
              className={`rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors ${
                statusFilter === tab.key
                  ? "bg-primary-600 text-white"
                  : "bg-background text-foreground ring-1 ring-border hover:bg-muted"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Table */}
        {loading ? (
          <TableSkeleton rows={5} />
        ) : filteredReimbs.length === 0 ? (
          <div className="rounded-2xl border border-border bg-background">
            <EmptyState
              icon={<Stack size={28} className="text-muted-foreground" />}
              title="暂无报销单"
              description="点击「新建报销单」选择发票并创建"
              action={
                <button
                  onClick={goToCreate}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
                >
                  <Plus size={16} weight="bold" />
                  新建报销单
                </button>
              }
            />
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-border bg-background">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-4 py-3 font-medium">序号</th>
                  <th className="px-4 py-3 font-medium">申请人</th>
                  <th className="px-4 py-3 font-medium">部门</th>
                  <th className="px-4 py-3 font-medium">报销周期</th>
                  <th className="px-4 py-3 font-medium">金额</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">创建时间</th>
                  <th className="px-4 py-3 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {filteredReimbs.map((r, i) => (
                  <motion.tr
                    key={r.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      delay: i * 0.04,
                      type: "spring",
                      stiffness: 120,
                      damping: 20,
                    }}
                    onClick={() => goToDetail(r.id)}
                    className="cursor-pointer transition-colors hover:bg-muted"
                  >
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      {i + 1}
                    </td>
                    <td className="px-4 py-3 text-foreground">
                      {r.applicant_name || r.applicant_id}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {r.department || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-mono text-xs text-foreground">
                          {cycleLabel(r.cycle_key)}
                        </span>
                        {r.is_cycle_locked && (
                          <span className="inline-flex w-fit items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-600">
                            <Lock size={10} weight="fill" />
                            已封账
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col">
                        <span className="font-medium text-foreground">
                          {r.total_amount != null
                            ? `¥${r.total_amount.toLocaleString("zh-CN", {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                              })}`
                            : "—"}
                        </span>
                        {r.expense_total != null && r.subsidy_total != null && (
                          <span className="text-[10px] text-muted-foreground">
                            费用 {r.expense_total.toLocaleString("zh-CN", { minimumFractionDigits: 2 })} + 补贴 {r.subsidy_total.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <ReimbStatusBadge status={r.status} />
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {r.created_at
                        ? new Date(r.created_at).toLocaleDateString("zh-CN")
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex items-center justify-center gap-1">
                        {r.status === "SUBMITTED" && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleWithdraw(r.id);
                            }}
                            disabled={withdrawing}
                            className="inline-flex items-center justify-center rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-amber-50 hover:text-amber-600"
                            title="撤回报销单"
                          >
                            <ArrowUUpLeft size={16} />
                          </button>
                        )}
                        {r.status === "SUBMITTED" && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleReimburse(r.id);
                            }}
                            disabled={reimbursing}
                            className="inline-flex items-center justify-center rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-emerald-50 hover:text-emerald-600"
                            title="直接报销"
                          >
                            <Check size={16} />
                          </button>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteError(null);
                            setDeleteTarget(r);
                          }}
                          className="inline-flex items-center justify-center rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-rose-50 hover:text-rose-600"
                          title="删除报销单"
                        >
                          <Trash size={16} />
                        </button>
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <DeleteConfirmModal
        target={deleteTarget}
        deleting={deleting}
        deleteError={deleteError}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </>
  );
}
