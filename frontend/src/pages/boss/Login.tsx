import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import { Eye, EyeSlash, WarningCircle } from "@phosphor-icons/react";

export function BossLogin() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (bossApi.getToken()) {
      navigate("/boss/chat", { replace: true });
    }
  }, [navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await bossApi.login(username.trim(), password);
      navigate("/boss/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-gradient-to-br from-background via-background to-primary-50/20">
      <div className="w-full max-w-md px-4">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-primary-700 shadow-lg shadow-primary-700/25">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
              <path
                d="M4 7C4 5.9 4.9 5 6 5H18C19.1 5 20 5.9 20 7V19C20 20.1 19.1 21 18 21H6C4.9 21 4 20.1 4 19V7Z"
                stroke="white"
                strokeWidth="2"
              />
              <path
                d="M8 10H16M8 14H16M8 18H13"
                stroke="white"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </div>
          <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
            发票报销智能助手
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">老板端登录</p>
        </div>

        <div className="rounded-xl border border-border bg-background p-6 shadow-lg">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="flex items-center gap-2 rounded-lg bg-error-50 px-4 py-3 text-sm text-error-700">
                <WarningCircle size={18} weight="fill" />
                {error}
              </div>
            )}

            <div>
              <label className="mb-1.5 block text-sm font-medium text-foreground">
                账号
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入账号"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
                required
                autoFocus
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-medium text-foreground">
                密码
              </label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="w-full rounded-md border border-border bg-background px-3 py-2 pr-10 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? (
                    <EyeSlash size={16} />
                  ) : (
                    <Eye size={16} />
                  )}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-md bg-primary-700 px-4 py-2 text-sm font-medium text-white transition-all hover:bg-primary-800 focus:outline-none focus:ring-2 focus:ring-primary-300 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "登录中..." : "登录"}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          可穿透查看全公司发票与报销单明细
        </p>
      </div>
    </div>
  );
}
