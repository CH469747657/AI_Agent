import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState, useCallback } from "react";
import { useDebounce } from "../hooks/useDebounce";
import {
  Users,
  Plus,
  ArrowsClockwise,
  Warning,
  PencilSimple,
  Trash,
  MagnifyingGlass,
  X,
  Key,
  CheckCircle,
  Table,
  Spinner,
  DownloadSimple,
  UploadSimple,
  FileText,
} from "@phosphor-icons/react";
import { employeeApi } from "../api/client";
import type { Employee, EmployeeSyncResult, EmployeeCreate, EmployeeUpdate } from "../types";
import { EmptyState } from "../components/EmptyState";
import { ConfirmModal } from "../components/ConfirmModal";

export function Employees() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const debouncedKeyword = useDebounce(keyword, 300);
  const [statusFilter, setStatusFilter] = useState<number | undefined>(undefined);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<EmployeeSyncResult | null>(null);
  const [form, setForm] = useState({
    wecom_user_id: "",
    name: "",
    employee_no: "",
    department: "",
    position: "",
    mobile: "",
    email: "",
    status: 1,
    password: "",
  });
  const [resetTarget, setResetTarget] = useState<Employee | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  // 批量添加状态
  const [showBatchForm, setShowBatchForm] = useState(false);
  const [batchFile, setBatchFile] = useState<File | null>(null);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchResult, setBatchResult] = useState<{
    total: number;
    success: number;
    failed: number;
    errors: string[];
  } | null>(null);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Employee | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    employeeApi
      .list({ keyword: debouncedKeyword || undefined, status: statusFilter })
      .then(setEmployees)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [debouncedKeyword, statusFilter]);

  useEffect(load, [load]);

  const resetForm = () => {
    setForm({
      wecom_user_id: "",
      name: "",
      employee_no: "",
      department: "",
      position: "",
      mobile: "",
      email: "",
      status: 1,
      password: "",
    });
    setEditing(null);
  };

  const openCreate = () => {
    resetForm();
    setShowForm(true);
  };

  const openEdit = (emp: Employee) => {
    setForm({
      wecom_user_id: emp.wecom_user_id,
      name: emp.name,
      employee_no: emp.employee_no || "",
      department: emp.department || "",
      position: emp.position || "",
      mobile: emp.mobile || "",
      email: emp.email || "",
      status: emp.status,
      password: "",
    });
    setEditing(emp);
    setShowForm(true);
  };

  const handleSubmit = async () => {
    if (!form.name) return;
    try {
      const data = {
        wecom_user_id: form.wecom_user_id,
        name: form.name,
        employee_no: form.employee_no || null,
        department: form.department || null,
        position: form.position || null,
        mobile: form.mobile || null,
        email: form.email || null,
        status: form.status,
      };
      if (editing) {
        const updateData: Record<string, unknown> = { ...data };
        if (form.password) {
          updateData.password = form.password;
        }
        await employeeApi.update(editing.id, updateData as EmployeeUpdate);
      } else {
        const createData: EmployeeCreate = { ...data };
        if (form.password) {
          createData.password = form.password;
        }
        await employeeApi.create(createData);
      }
      setShowForm(false);
      resetForm();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await employeeApi.delete(deleteTarget.id);
      setDeleteTarget(null);
      load();
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  const handleResetPassword = async () => {
    if (!resetTarget || !resetPassword) return;
    setResetting(true);
    setResetError(null);
    try {
      await employeeApi.update(resetTarget.id, { password: resetPassword });
      setResetTarget(null);
      setResetPassword("");
      load();
    } catch (e) {
      setResetError(e instanceof Error ? e.message : "重置失败");
    } finally {
      setResetting(false);
    }
  };

  // 下载批量添加模板
  const handleDownloadTemplate = async () => {
    try {
      await employeeApi.downloadTemplate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "模板下载失败");
    }
  };

  // 批量上传：调用后端 batch API，返回统计结果
  const handleBatchSubmit = async () => {
    if (!batchFile) return;
    setBatchSubmitting(true);
    setBatchResult(null);
    try {
      const result = await employeeApi.batchUpload(batchFile);
      setBatchResult(result);
      if (result.failed === 0 && result.success > 0) {
        load();
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "上传失败";
      setBatchResult({
        total: 0,
        success: 0,
        failed: 1,
        errors: [msg],
      });
    } finally {
      setBatchSubmitting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    setSyncResult(null);
    try {
      const result = await employeeApi.sync();
      setSyncResult(result);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "同步失败");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
            员工管理
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            管理员工信息 — 支持企微通讯录同步和手动维护工号、部门等
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            <ArrowsClockwise size={16} className={syncing ? "animate-spin" : ""} />
            {syncing ? "同步中..." : "企微同步"}
          </button>
          <button
            onClick={() => setShowBatchForm(true)}
            className="flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
          >
            <Table size={16} />
            批量添加
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
          >
            <Plus size={16} />
            添加员工
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
          <Warning size={18} />
          {error}
          <button onClick={() => setError(null)} className="ml-auto">
            <X size={14} />
          </button>
        </div>
      )}

      {syncResult && (
        <div className="rounded-xl bg-primary-50 p-4 text-sm text-primary-800">
          <div className="font-medium">
            企微同步完成：共 {syncResult.total} 人，新增 {syncResult.created} 人，更新 {syncResult.updated} 人
          </div>
          {syncResult.errors.length > 0 && (
            <div className="mt-2 space-y-1 text-xs text-amber-700">
              {syncResult.errors.slice(0, 5).map((err, i) => (
                <div key={i}>{err}</div>
              ))}
            </div>
          )}
          <button onClick={() => setSyncResult(null)} className="mt-2 text-xs text-primary-600 hover:underline">
            关闭
          </button>
        </div>
      )}

      {/* Search bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <MagnifyingGlass
            size={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索姓名 / 工号 / 企微ID / 部门"
            className="w-full rounded-lg border border-border bg-background py-2.5 pl-10 pr-3 text-sm focus:border-primary-400"
          />
        </div>
        <select
          value={statusFilter ?? ""}
          onChange={(e) =>
            setStatusFilter(e.target.value ? Number(e.target.value) : undefined)
          }
          className="rounded-lg border border-border bg-background px-3 py-2.5 text-sm focus:border-primary-400"
        >
          <option value="">全部状态</option>
          <option value="1">在职</option>
          <option value="2">离职</option>
        </select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-14 animate-pulse rounded-xl border border-border bg-background"
            />
          ))}
        </div>
      ) : employees.length === 0 ? (
        <div className="rounded-2xl border border-border bg-background">
          <EmptyState
            icon={<Users size={28} className="text-muted-foreground" />}
            title="还没有员工数据"
            description="点击「企微同步」从企业微信拉取通讯录，或手动添加员工"
          />
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border bg-background">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left text-xs font-medium text-muted-foreground">
                <th className="px-4 py-3">序号</th>
                <th className="px-4 py-3">工号</th>
                <th className="px-4 py-3">姓名</th>
                <th className="px-4 py-3">企微ID</th>
                <th className="px-4 py-3">部门</th>
                <th className="px-4 py-3">职务</th>
                <th className="px-4 py-3">手机号</th>
                <th className="px-4 py-3 text-center">状态</th>
                <th className="px-4 py-3 text-center">登录密码</th>
                <th className="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {employees.map((emp, i) => (
                <motion.tr
                  key={emp.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: i * 0.02 }}
                  className="border-b border-border hover:bg-muted/50"
                >
                  <td className="px-4 py-3 text-muted-foreground">{i + 1}</td>
                  <td className="px-4 py-3 font-mono text-xs text-foreground">
                    {emp.employee_no || "-"}
                  </td>
                  <td className="px-4 py-3 font-medium text-foreground">
                    {emp.name}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                    {emp.wecom_user_id}
                  </td>
                  <td className="px-4 py-3 text-foreground">
                    {emp.department || "-"}
                  </td>
                  <td className="px-4 py-3 text-foreground">
                    {emp.position || "-"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                    {emp.mobile || "-"}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span
                      className={`rounded-md px-2 py-0.5 text-xs font-medium ${
                        emp.status === 1
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {emp.status === 1 ? "在职" : "离职"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    {emp.has_password ? (
                      <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
                        <CheckCircle size={14} weight="fill" />
                        已设置
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">未设置</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <button
                        onClick={() => openEdit(emp)}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                        title="编辑"
                      >
                        <PencilSimple size={16} />
                      </button>
                      <button
                        onClick={() => {
                          setResetTarget(emp);
                          setResetPassword("");
                          setResetError(null);
                        }}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-primary-50 hover:text-primary-600"
                        title="重置密码"
                      >
                        <Key size={16} />
                      </button>
                      <button
                        onClick={() => {
                          setDeleteTarget(emp);
                          setDeleteError(null);
                        }}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-rose-50 hover:text-rose-600"
                        title="删除"
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

      {/* Create / Edit form modal */}
      <AnimatePresence>
        {showForm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            onClick={() => setShowForm(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-lg rounded-2xl bg-background p-6 shadow-xl"
            >
              <div className="mb-4 flex items-center justify-between">
                <h2 className="font-display text-lg font-bold text-foreground">
                  {editing ? "编辑员工" : "添加员工"}
                </h2>
                <button
                  onClick={() => setShowForm(false)}
                  className="rounded-lg p-1 text-muted-foreground hover:bg-muted"
                >
                  <X size={20} />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <FormField
                  label="姓名"
                  required
                  value={form.name}
                  onChange={(v) => setForm({ ...form, name: v })}
                  placeholder="员工姓名"
                />
                <FormField
                  label="企微ID"
                  disabled={!!editing}
                  value={form.wecom_user_id}
                  onChange={(v) => setForm({ ...form, wecom_user_id: v })}
                  placeholder="企微UserID（留空自动生成）"
                />
                <FormField
                  label="工号"
                  value={form.employee_no}
                  onChange={(v) => setForm({ ...form, employee_no: v })}
                  placeholder="如 EMP-001"
                />
                <FormField
                  label="部门"
                  value={form.department}
                  onChange={(v) => setForm({ ...form, department: v })}
                  placeholder="如 技术部"
                />
                <FormField
                  label="职务"
                  value={form.position}
                  onChange={(v) => setForm({ ...form, position: v })}
                  placeholder="如 工程师"
                />
                <FormField
                  label="手机号"
                  value={form.mobile}
                  onChange={(v) => setForm({ ...form, mobile: v })}
                  placeholder="如 138xxxx0000"
                />
                <FormField
                  label="邮箱"
                  value={form.email}
                  onChange={(v) => setForm({ ...form, email: v })}
                  placeholder="如 name@company.com"
                />
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-foreground">
                    状态
                  </label>
                  <select
                    value={form.status}
                    onChange={(e) =>
                      setForm({ ...form, status: Number(e.target.value) })
                    }
                    className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
                  >
                    <option value={1}>在职</option>
                    <option value={2}>离职</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-foreground">
                    {editing ? "重置密码" : "初始密码"}
                    <span className="ml-0.5 text-muted-foreground">(可选)</span>
                  </label>
                  <input
                    type="text"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    placeholder={editing ? "留空则不修改" : "如 Abc@1234"}
                    className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
                  />
                  <p className="text-xs text-muted-foreground">
                    {editing ? "设置后原密码将被覆盖" : "员工可用此密码登录员工端"}
                  </p>
                </div>
              </div>

              <div className="mt-5 flex justify-end gap-2">
                <button
                  onClick={() => setShowForm(false)}
                  className="rounded-lg bg-muted px-4 py-2 text-sm font-medium text-foreground hover:bg-muted"
                >
                  取消
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={!form.name}
                  className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                >
                  {editing ? "保存修改" : "确认添加"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 重置密码弹窗 */}
      <AnimatePresence>
        {resetTarget && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            onClick={() => setResetTarget(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-md rounded-2xl bg-background p-6 shadow-xl"
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Key size={20} className="text-primary-600" />
                  <h2 className="font-display text-lg font-bold text-foreground">
                    重置密码
                  </h2>
                </div>
                <button
                  onClick={() => setResetTarget(null)}
                  className="rounded-lg p-1 text-muted-foreground hover:bg-muted"
                >
                  <X size={20} />
                </button>
              </div>

              <p className="mb-4 text-sm text-muted-foreground">
                为员工「<span className="font-medium text-foreground">{resetTarget.name}</span>
                」<span className="font-mono text-xs">({resetTarget.employee_no || "-"})</span>
                设置新密码，设置后原密码立即失效。
              </p>

              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">
                  新密码
                </label>
                <input
                  type="text"
                  value={resetPassword}
                  onChange={(e) => {
                    setResetPassword(e.target.value);
                    setResetError(null);
                  }}
                  placeholder="请输入新密码"
                  autoFocus
                  className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
                />
                {resetError && (
                  <p className="text-xs text-rose-500">{resetError}</p>
                )}
              </div>

              <div className="mt-5 flex justify-end gap-2">
                <button
                  onClick={() => setResetTarget(null)}
                  className="rounded-lg bg-muted px-4 py-2 text-sm font-medium text-foreground hover:bg-muted"
                >
                  取消
                </button>
                <button
                  onClick={handleResetPassword}
                  disabled={!resetPassword || resetting}
                  className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                >
                  {resetting ? "重置中..." : "确认重置"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 批量添加弹窗 */}
      <AnimatePresence>
        {showBatchForm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
            onClick={() => !batchSubmitting && setShowBatchForm(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-3xl rounded-2xl bg-background p-6 shadow-2xl"
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Table size={20} className="text-primary-600" />
                  <h2 className="font-display text-lg font-bold text-foreground">
                    批量添加员工
                  </h2>
                </div>
                <button
                  onClick={() => !batchSubmitting && setShowBatchForm(false)}
                  disabled={batchSubmitting}
                  className="rounded-lg p-1 text-muted-foreground hover:bg-muted disabled:opacity-50"
                >
                  <X size={20} />
                </button>
              </div>

              <div className="mb-4 flex items-center justify-between rounded-lg bg-muted p-3">
                <div className="flex items-start gap-2 text-sm text-muted-foreground">
                  <FileText size={16} className="mt-0.5 shrink-0" />
                  <div>
                    <div className="font-medium text-foreground">操作流程</div>
                    <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-xs">
                      <li>点击右侧下载模板（.xlsx）</li>
                      <li>按表头字段填写员工信息（仅姓名必填）</li>
                      <li>选择填写好的文件上传</li>
                      <li>点击"批量提交"</li>
                    </ol>
                  </div>
                </div>
                <button
                  onClick={handleDownloadTemplate}
                  disabled={batchSubmitting}
                  className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-primary-600 transition-colors hover:bg-primary-50 disabled:opacity-50"
                >
                  <DownloadSimple size={16} />
                  下载模板
                </button>
              </div>

              {/* 文件上传区 */}
              <label
                className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed py-10 transition-colors ${
                  batchSubmitting
                    ? "border-border bg-muted/50 cursor-not-allowed"
                    : "border-border bg-muted hover:border-primary-400 hover:bg-primary-50/30"
                }`}
              >
                <input
                  type="file"
                  accept=".xlsx,.xls"
                  disabled={batchSubmitting}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) setBatchFile(f);
                    e.target.value = "";
                  }}
                  className="sr-only"
                />
                <UploadSimple size={32} className="text-primary-500" />
                <p className="mt-3 text-sm font-medium text-foreground">
                  {batchFile ? batchFile.name : "点击选择 .xlsx 文件"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {batchFile
                    ? `${(batchFile.size / 1024).toFixed(1)} KB · 已选择`
                    : "支持 .xlsx 格式，请使用模板填写"}
                </p>
              </label>

              {batchFile && !batchSubmitting && (
                <div className="mt-2 flex items-center justify-between rounded-lg bg-muted px-3 py-2 text-xs">
                  <span className="font-mono text-foreground">{batchFile.name}</span>
                  <button
                    onClick={() => setBatchFile(null)}
                    className="rounded p-1 text-muted-foreground hover:bg-background hover:text-foreground"
                  >
                    <X size={14} />
                  </button>
                </div>
              )}

              {batchResult && (
                <div className={`mt-3 rounded-lg p-3 text-sm ${
                  batchResult.failed === 0
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-amber-50 text-amber-700"
                }`}>
                  <div className="flex items-center gap-2 font-medium">
                    <CheckCircle size={16} weight="fill" />
                    共 {batchResult.total} 条，成功 {batchResult.success} 条
                    {batchResult.failed > 0 && `，失败 ${batchResult.failed} 条`}
                  </div>
                  {batchResult.errors.length > 0 && (
                    <ul className="mt-2 space-y-1 text-xs">
                      {batchResult.errors.map((err, i) => (
                        <li key={i} className="font-mono">{err}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="mt-5 flex justify-end gap-2">
                <button
                  onClick={() => setShowBatchForm(false)}
                  disabled={batchSubmitting}
                  className="rounded-lg bg-muted px-4 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
                >
                  关闭
                </button>
                <button
                  onClick={handleBatchSubmit}
                  disabled={batchSubmitting || !batchFile}
                  className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                >
                  {batchSubmitting ? (
                    <Spinner size={16} className="animate-spin" />
                  ) : (
                    <CheckCircle size={16} />
                  )}
                  {batchSubmitting ? `提交中...` : "批量提交"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 删除确认弹窗 */}
      <ConfirmModal
        open={!!deleteTarget}
        title="删除员工"
        description={`确定要删除员工「${deleteTarget?.name ?? ""}」吗？此操作不可撤销。`}
        confirmText="确认删除"
        variant="danger"
        loading={deleting}
        error={deleteError}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

function FormField({
  label,
  value,
  onChange,
  placeholder,
  required,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium text-foreground">
        {label}
        {required && <span className="ml-0.5 text-rose-500">*</span>}
      </label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
      />
    </div>
  );
}
