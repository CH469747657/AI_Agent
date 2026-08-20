import { useEffect, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { adminApi } from "../../api/client";
import { Eye, EyeSlash, WarningCircle } from "@phosphor-icons/react";

export function AdminLogin() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // 已登录则跳转
  useEffect(() => {
    if (adminApi.getToken()) {
      const redirect = searchParams.get("redirect") || "/";
      navigate(redirect, { replace: true });
    }
  }, [navigate, searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await adminApi.login(username, password);
      const redirect = searchParams.get("redirect") || "/";
      navigate(redirect, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-primary-900/30">
      <div className="w-full max-w-md px-4">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-primary-700 shadow-lg shadow-primary-700/40">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 2L2 7V17L12 22L22 17V7L12 2Z"
                stroke="white"
                strokeWidth="2"
                strokeLinejoin="round"
              />
              <path
                d="M2 7L12 12L22 7M12 12V22"
                stroke="white"
                strokeWidth="1.5"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <h1 className="font-display text-3xl font-extrabold tracking-tight text-white">
            发票报销智能助手
          </h1>
          <p className="mt-1.5 text-sm font-medium text-slate-300">管理后台登录</p>
        </div>

        {/* 登录表单 */}
        <div className="rounded-xl border border-slate-700 bg-slate-800/80 p-6 shadow-xl backdrop-blur">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div
                role="alert"
                aria-live="polite"
                className="flex items-center gap-2 rounded-lg bg-red-500/20 px-4 py-3 text-sm text-red-200"
              >
                <WarningCircle size={18} weight="fill" />
                {error}
              </div>
            )}

            <div>
              <label htmlFor="login-username" className="mb-1.5 block text-sm font-medium text-slate-200">
                用户名
              </label>
              <input
                id="login-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoComplete="username"
                className="min-h-[44px] w-full rounded-md border border-slate-600 bg-slate-900/60 px-3 py-2.5 text-sm text-white placeholder:text-slate-500 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
                required
                autoFocus
              />
            </div>

            <div>
              <label htmlFor="login-password" className="mb-1.5 block text-sm font-medium text-slate-200">
                密码
              </label>
              <div className="relative">
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                  className="min-h-[44px] w-full rounded-md border border-slate-600 bg-slate-900/60 px-3 py-2.5 pr-12 text-sm text-white placeholder:text-slate-500 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/30"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                  className="absolute right-2 top-1/2 flex min-h-[40px] min-w-[40px] -translate-y-1/2 items-center justify-center rounded text-slate-400 transition-colors hover:text-slate-200"
                >
                  {showPassword ? <EyeSlash size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="min-h-[44px] w-full rounded-md bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white transition-all duration-200 hover:bg-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-400 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "登录中..." : "登录"}
            </button>
          </form>

          <div className="mt-4 flex items-center justify-between text-sm text-slate-400">
            <Link
              to="/portal/login"
              className="inline-block rounded py-1 transition-colors hover:text-slate-200 hover:underline"
            >
              员工登录入口 →
            </Link>
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          管理员账户由系统配置，如忘记密码请联系系统管理员
        </p>
      </div>
    </div>
  );
}
