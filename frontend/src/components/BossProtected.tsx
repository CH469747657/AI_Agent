import { Navigate, Outlet } from "react-router-dom";
import { bossApi } from "../api/client";

/**
 * 老板端路由守卫
 * 检查 localStorage 中是否有有效的 boss_token，
 * 未登录则重定向到 /boss/login
 */
export function BossProtected() {
  const token = bossApi.getToken();

  if (!token) {
    return <Navigate to="/boss/login" replace />;
  }

  return <Outlet />;
}
