import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import {
  SquaresFour,
  Receipt,
  UploadSimple,
  Stack,
  Users,
  GearSix,
} from "@phosphor-icons/react";

const navItems = [
  { to: "/", label: "仪表板", icon: SquaresFour },
  { to: "/invoices", label: "发票列表", icon: Receipt },
  { to: "/upload", label: "上传发票", icon: UploadSimple },
  { to: "/reimbursements", label: "报销单管理", icon: Stack },
  { to: "/employees", label: "员工管理", icon: Users },
  { to: "/settings", label: "设置", icon: GearSix },
];

export function Sidebar() {
  const location = useLocation();

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-[100dvh] w-60 flex-col bg-sidebar-bg">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary-600 shadow-sm">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
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
        <div className="flex flex-col">
          <span className="font-display text-sm font-semibold tracking-tight text-white">
            发票报销助手
          </span>
          <span className="text-xs text-sidebar-muted">管理后台 v2.0</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 px-3 py-3">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.to === "/"
              ? location.pathname === "/"
              : location.pathname.startsWith(item.to);
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className="group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors"
            >
              {isActive && (
                <motion.div
                  layoutId="nav-active"
                  className="absolute inset-0 rounded-lg bg-sidebar-active/80"
                  transition={{ type: "spring", stiffness: 350, damping: 32 }}
                />
              )}
              {!isActive && (
                <div className="absolute inset-0 rounded-lg opacity-0 transition-opacity group-hover:opacity-100 bg-sidebar-hover" />
              )}
              <Icon
                size={19}
                weight={isActive ? "fill" : "regular"}
                className={`relative z-10 transition-colors ${
                  isActive ? "text-primary-300" : "text-sidebar-muted group-hover:text-sidebar-text"
                }`}
              />
              <span
                className={`relative z-10 transition-colors ${
                  isActive ? "text-white" : "text-sidebar-text group-hover:text-white"
                }`}
              >
                {item.label}
              </span>
            </NavLink>
          );
        })}
      </nav>

      {/* Footer status */}
      <div className="border-t border-white/5 px-5 py-4 space-y-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
          </span>
          <span className="text-xs text-sidebar-muted">OCR 引擎运行中</span>
        </div>
        <button
          onClick={() => {
            import("../api/client").then(({ adminApi }) => {
              adminApi.logout();
              window.location.href = "/admin/login";
            });
          }}
          className="w-full rounded-md bg-white/5 px-3 py-1.5 text-xs text-sidebar-muted transition-colors hover:bg-white/10 hover:text-white"
        >
          退出登录
        </button>
      </div>
    </aside>
  );
}
