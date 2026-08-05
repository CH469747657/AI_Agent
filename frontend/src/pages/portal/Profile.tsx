import { useEffect, useState } from "react";
import { portalApi } from "../../api/client";
import type { PortalProfile } from "../../types";
import {
  UserCircle,
  Spinner,
  LockKey,
  CheckCircle,
  WarningCircle,
} from "@phosphor-icons/react";

export function PortalProfile() {
  const [profile, setProfile] = useState<PortalProfile | null>(null);
  const [loading, setLoading] = useState(true);

  // 修改密码
  const [oldPwd, setOldPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [changing, setChanging] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(
    null
  );

  useEffect(() => {
    portalApi.profile().then(setProfile).finally(() => setLoading(false));
  }, []);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);

    if (newPwd !== confirmPwd) {
      setMsg({ type: "err", text: "两次输入的新密码不一致" });
      return;
    }
    if (newPwd.length < 6) {
      setMsg({ type: "err", text: "新密码长度不能少于6位" });
      return;
    }

    setChanging(true);
    try {
      await portalApi.changePassword(oldPwd, newPwd);
      setMsg({ type: "ok", text: "密码修改成功" });
      setOldPwd("");
      setNewPwd("");
      setConfirmPwd("");
    } catch (err) {
      setMsg({
        type: "err",
        text: err instanceof Error ? err.message : "修改失败",
      });
    } finally {
      setChanging(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size={24} className="animate-spin text-brand-600" />
      </div>
    );
  }

  if (!profile) return null;

  return (
    <div className="mx-auto max-w-lg space-y-6">
      {/* 个人信息 */}
      <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-600">
            <UserCircle size={28} />
          </div>
          <div>
            <h2 className="font-display text-lg font-bold text-slate-900">
              {profile.name}
            </h2>
            <p className="text-sm text-slate-500">{profile.employee_no}</p>
          </div>
        </div>

        <div className="space-y-3 text-sm">
          <div className="flex justify-between border-t border-slate-100 pt-3">
            <span className="text-slate-400">部门</span>
            <span className="font-medium text-slate-700">
              {profile.department || "-"}
            </span>
          </div>
          <div className="flex justify-between border-t border-slate-100 pt-3">
            <span className="text-slate-400">职务</span>
            <span className="font-medium text-slate-700">
              {profile.position || "-"}
            </span>
          </div>
          <div className="flex justify-between border-t border-slate-100 pt-3">
            <span className="text-slate-400">手机</span>
            <span className="font-medium text-slate-700">
              {profile.mobile || "-"}
            </span>
          </div>
          <div className="flex justify-between border-t border-slate-100 pt-3">
            <span className="text-slate-400">邮箱</span>
            <span className="font-medium text-slate-700">
              {profile.email || "-"}
            </span>
          </div>
          <div className="flex justify-between border-t border-slate-100 pt-3">
            <span className="text-slate-400">最后登录</span>
            <span className="font-medium text-slate-700">
              {profile.last_login_at
                ? new Date(profile.last_login_at).toLocaleString("zh-CN")
                : "-"}
            </span>
          </div>
        </div>
      </div>

      {/* 修改密码 */}
      <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
        <h3 className="mb-4 flex items-center gap-2 font-display text-base font-semibold text-slate-900">
          <LockKey size={18} className="text-slate-400" />
          修改密码
        </h3>

        <form onSubmit={handleChangePassword} className="space-y-3">
          {msg && (
            <div
              className={`flex items-center gap-2 rounded-xl px-4 py-3 text-sm ${
                msg.type === "ok"
                  ? "bg-green-50 text-green-600"
                  : "bg-red-50 text-red-600"
              }`}
            >
              {msg.type === "ok" ? (
                <CheckCircle size={18} weight="fill" />
              ) : (
                <WarningCircle size={18} weight="fill" />
              )}
              {msg.text}
            </div>
          )}

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              旧密码
            </label>
            <input
              type="password"
              value={oldPwd}
              onChange={(e) => setOldPwd(e.target.value)}
              className="w-full rounded-xl border border-slate-200 px-4 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              新密码
            </label>
            <input
              type="password"
              value={newPwd}
              onChange={(e) => setNewPwd(e.target.value)}
              className="w-full rounded-xl border border-slate-200 px-4 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              required
              minLength={6}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              确认新密码
            </label>
            <input
              type="password"
              value={confirmPwd}
              onChange={(e) => setConfirmPwd(e.target.value)}
              className="w-full rounded-xl border border-slate-200 px-4 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              required
              minLength={6}
            />
          </div>
          <button
            type="submit"
            disabled={changing}
            className="flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
          >
            {changing && <Spinner size={16} className="animate-spin" />}
            确认修改
          </button>
        </form>
      </div>
    </div>
  );
}
