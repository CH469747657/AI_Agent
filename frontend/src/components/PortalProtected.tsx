import { Navigate, Outlet } from "react-router-dom";
import { portalApi } from "../api/client";

/**
 * Portal 路由守卫
 * 检查 localStorage 中是否有有效的 portal_token，
 * 未登录则重定向到 /portal/login
 */
export function PortalProtected() {
  const token = portalApi.getToken();

  if (!token) {
    return <Navigate to="/portal/login" replace />;
  }

  return <Outlet />;
}
