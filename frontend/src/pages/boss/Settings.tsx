import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import { Lock, Warning, CheckCircle } from "@phosphor-icons/react";

export function BossSettings() {
  const navigate = useNavigate();
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessMsg("");

    if (!oldPassword || !newPassword || !confirmPassword) {
      setError("请填写所有字段");
      return;
    }
    if (newPassword.length < 6) {
      setError("新密码至少 6 位");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    if (oldPassword === newPassword) {
      setError("新密码不能与当前密码相同");
      return;
    }

    setSaving(true);
    try {
      await bossApi.changePassword(oldPassword, newPassword);
      setSuccessMsg("密码修改成功，下次登录请使用新密码");
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
          账号设置
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">修改老板端登录密码</p>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
          <Warning size={18} />
          {error}
        </div>
      )}
      {successMsg && (
        <div className="flex items-center gap-2 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-700">
          <CheckCircle size={18} />
          {successMsg}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-border bg-background p-6 shadow-card">
        <div>
          <label htmlFor="old-pwd" className="mb-1.5 block text-sm font-medium text-foreground">
            当前密码
          </label>
          <div className="relative">
            <input
              id="old-pwd"
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              autoComplete="current-password"
              className="min-h-[44px] w-full rounded-md border border-border bg-background px-3 py-2.5 pr-10 text-sm text-foreground focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
              required
            />
            <Lock size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          </div>
        </div>

        <div>
          <label htmlFor="new-pwd" className="mb-1.5 block text-sm font-medium text-foreground">
            新密码 <span className="text-muted-foreground">（至少 6 位）</span>
          </label>
          <div className="relative">
            <input
              id="new-pwd"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              className="min-h-[44px] w-full rounded-md border border-border bg-background px-3 py-2.5 pr-10 text-sm text-foreground focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
              required
            />
            <Lock size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          </div>
        </div>

        <div>
          <label htmlFor="confirm-pwd" className="mb-1.5 block text-sm font-medium text-foreground">
            确认新密码
          </label>
          <div className="relative">
            <input
              id="confirm-pwd"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              className="min-h-[44px] w-full rounded-md border border-border bg-background px-3 py-2.5 pr-10 text-sm text-foreground focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
              required
            />
            <Lock size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          </div>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="min-h-[44px] w-full rounded-md bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white transition-all duration-200 hover:bg-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-400 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "保存中..." : "修改密码"}
        </button>
      </form>

      <button
        type="button"
        onClick={() => navigate("/boss/chat")}
        className="w-full text-center text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        ← 返回
      </button>
    </div>
  );
}
