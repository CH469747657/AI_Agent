import { Navigate, Outlet, useLocation } from "react-router-dom";
import { adminApi } from "../api/client";

/**
 * 管理端路由守卫
 * 检查 localStorage 中是否有有效的 admin_token，
 * 未登录则重定向到 /admin/login（并携带 redirect 参数）
 */
export function AdminProtected() {
  const token = adminApi.getToken();
  const location = useLocation();

  if (!token) {
    const redirect = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/admin/login?redirect=${redirect}`} replace />;
  }

  return <Outlet />;
}
