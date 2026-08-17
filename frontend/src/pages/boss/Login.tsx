import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";

export function BossLogin() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await bossApi.login(username.trim(), password);
      navigate("/boss/chat", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="boss-login">
      <div className="boss-login__logo">👔</div>
      <div className="boss-login__title">老板端</div>
      <div className="boss-login__subtitle">公司报销数据 · 智能问数</div>
      <form className="boss-login__form" onSubmit={handleSubmit}>
        <input
          className="boss-input"
          type="text"
          placeholder="账号"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
        <input
          className="boss-input"
          type="password"
          placeholder="密码"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button className="boss-button" type="submit" disabled={loading}>
          {loading ? "登录中…" : "登录"}
        </button>
        <div className="boss-login__error">{error}</div>
      </form>
    </div>
  );
}
