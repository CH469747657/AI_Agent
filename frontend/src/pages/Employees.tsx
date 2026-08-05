import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState, useCallback } from "react";
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
} from "@phosphor-icons/react";
import { employeeApi } from "../api/client";
import type { Employee, EmployeeSyncResult, EmployeeCreate, EmployeeUpdate } from "../types";
import { EmptyState } from "../components/EmptyState";

export function Employees() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
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
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    employeeApi
      .list({ keyword: keyword || undefined, status: statusFilter })
      .then(setEmployees)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [keyword, statusFilter]);

  useEffect(load, [load]);

  // 防抖搜索
  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [keyword, statusFilter, load]);

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
    if (!form.wecom_user_id || !form.name) return;
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

  const handleDelete = async (emp: Employee) => {
    if (!confirm(`确认删除员工「${emp.name}」吗？`)) return;
    try {
      await employeeApi.delete(emp.id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
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
          <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">
            员工管理
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            管理员工信息 — 支持企微通讯录同步和手动维护工号、部门等
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50"
          >
            <ArrowsClockwise size={16} className={syncing ? "animate-spin" : ""} />
            {syncing ? "同步中..." : "企微同步"}
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700"
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
        <div className="rounded-xl bg-brand-50 p-4 text-sm text-brand-800">
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
          <button onClick={() => setSyncResult(null)} className="mt-2 text-xs text-brand-600 hover:underline">
            关闭
          </button>
        </div>
      )}

      {/* Search bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <MagnifyingGlass
            size={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索姓名 / 工号 / 企微ID / 部门"
            className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-3 text-sm focus:border-brand-400"
          />
        </div>
        <select
          value={statusFilter ?? ""}
          onChange={(e) =>
            setStatusFilter(e.target.value ? Number(e.target.value) : undefined)
          }
          className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:border-brand-400"
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
              className="h-14 animate-pulse rounded-xl border border-slate-200/60 bg-white"
            />
          ))}
        </div>
      ) : employees.length === 0 ? (
        <div className="rounded-2xl border border-slate-200/60 bg-white">
          <EmptyState
            icon={<Users size={28} className="text-slate-300" />}
            title="还没有员工数据"
            description="点击「企微同步」从企业微信拉取通讯录，或手动添加员工"
          />
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200/60 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/50 text-left text-xs font-medium text-slate-500">
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
                  className="border-b border-slate-50 hover:bg-slate-50/50"
                >
                  <td className="px-4 py-3 text-slate-400">{i + 1}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">
                    {emp.employee_no || "-"}
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-800">
                    {emp.name}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">
                    {emp.wecom_user_id}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {emp.department || "-"}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {emp.position || "-"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {emp.mobile || "-"}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span
                      className={`rounded-md px-2 py-0.5 text-xs font-medium ${
                        emp.status === 1
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-slate-100 text-slate-500"
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
                      <span className="text-xs text-slate-400">未设置</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <button
                        onClick={() => openEdit(emp)}
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
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
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-brand-50 hover:text-brand-600"
                        title="重置密码"
                      >
                        <Key size={16} />
                      </button>
                      <button
                        onClick={() => handleDelete(emp)}
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
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
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm"
            onClick={() => setShowForm(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl"
            >
              <div className="mb-4 flex items-center justify-between">
                <h2 className="font-display text-lg font-bold text-slate-900">
                  {editing ? "编辑员工" : "添加员工"}
                </h2>
                <button
                  onClick={() => setShowForm(false)}
                  className="rounded-lg p-1 text-slate-400 hover:bg-slate-100"
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
                  required
                  disabled={!!editing}
                  value={form.wecom_user_id}
                  onChange={(v) => setForm({ ...form, wecom_user_id: v })}
                  placeholder="企微UserID"
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
                  <label className="text-sm font-medium text-slate-700">
                    状态
                  </label>
                  <select
                    value={form.status}
                    onChange={(e) =>
                      setForm({ ...form, status: Number(e.target.value) })
                    }
                    className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white"
                  >
                    <option value={1}>在职</option>
                    <option value={2}>离职</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-slate-700">
                    {editing ? "重置密码" : "初始密码"}
                    <span className="ml-0.5 text-slate-400">(可选)</span>
                  </label>
                  <input
                    type="text"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    placeholder={editing ? "留空则不修改" : "如 Abc@1234"}
                    className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white"
                  />
                  <p className="text-xs text-slate-400">
                    {editing ? "设置后原密码将被覆盖" : "员工可用此密码登录员工端"}
                  </p>
                </div>
              </div>

              <div className="mt-5 flex justify-end gap-2">
                <button
                  onClick={() => setShowForm(false)}
                  className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-200"
                >
                  取消
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={!form.wecom_user_id || !form.name}
                  className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
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
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm"
            onClick={() => setResetTarget(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Key size={20} className="text-brand-600" />
                  <h2 className="font-display text-lg font-bold text-slate-900">
                    重置密码
                  </h2>
                </div>
                <button
                  onClick={() => setResetTarget(null)}
                  className="rounded-lg p-1 text-slate-400 hover:bg-slate-100"
                >
                  <X size={20} />
                </button>
              </div>

              <p className="mb-4 text-sm text-slate-500">
                为员工「<span className="font-medium text-slate-700">{resetTarget.name}</span>
                」<span className="font-mono text-xs">({resetTarget.employee_no || "-"})</span>
                设置新密码，设置后原密码立即失效。
              </p>

              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">
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
                  className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white"
                />
                {resetError && (
                  <p className="text-xs text-rose-500">{resetError}</p>
                )}
              </div>

              <div className="mt-5 flex justify-end gap-2">
                <button
                  onClick={() => setResetTarget(null)}
                  className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-200"
                >
                  取消
                </button>
                <button
                  onClick={handleResetPassword}
                  disabled={!resetPassword || resetting}
                  className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                >
                  {resetting ? "重置中..." : "确认重置"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
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
      <label className="text-sm font-medium text-slate-700">
        {label}
        {required && <span className="ml-0.5 text-rose-500">*</span>}
      </label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
      />
    </div>
  );
}
