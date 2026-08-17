import { NavLink, Outlet, useNavigate, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ChatCircle,
  Receipt,
  Stack,
  SignOut,
} from "@phosphor-icons/react";
import { bossApi } from "../api/client";

const navItems = [
  { to: "/boss/chat", label: "智能问数", icon: ChatCircle },
  { to: "/boss/invoices", label: "发票", icon: Receipt },
  { to: "/boss/reimbursements", label: "报销单", icon: Stack },
];

/**
 * 超级管理员端布局 — 复用员工端的设计语言（顶部 header + 底部 Tab Bar + design-system 配色）
 * 详情页（含 /:id）隐藏底部 Tab，由详情页自身提供返回按钮
 */
export function BossLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const profile = bossApi.getProfile();
  const isDetail =
    /\/boss\/(invoices|reimbursements)\/\d+/.test(location.pathname);

  const handleLogout = () => {
    bossApi.logout();
    navigate("/boss/login");
  };

  return (
    <div className="min-h-[100dvh] bg-background">
      <header className="fixed left-0 right-0 top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background px-4 sm:px-6">
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-700">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
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
          <span className="font-display text-sm font-bold tracking-tight text-foreground">
            发票报销智能助手
          </span>
          <span className="ml-1 hidden rounded-full bg-primary-50 px-2 py-0.5 text-xs font-medium text-primary-700 sm:inline">
            超级管理员
          </span>
        </div>

        <nav className="hidden items-center gap-1 sm:flex">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-primary-50 text-primary-700"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`
                }
              >
                <Icon size={16} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="flex items-center gap-2 sm:gap-3">
          {profile && (
            <span className="text-sm text-foreground">
              {profile.name}
              <span className="ml-1 hidden text-xs text-muted-foreground sm:inline">
                ({profile.username})
              </span>
            </span>
          )}
          <button
            onClick={handleLogout}
            className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-error-50 hover:text-error-600"
            title="退出登录"
          >
            <SignOut size={16} />
          </button>
        </div>
      </header>

      <main className="min-h-[100dvh] pt-14 pb-14 sm:pb-0">
        <div className="mx-auto max-w-[1200px] px-4 py-6 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 200, damping: 25 }}
          >
            <Outlet />
          </motion.div>
        </div>
      </main>

      {!isDetail && (
        <nav className="fixed bottom-0 left-0 right-0 z-30 flex h-14 items-stretch justify-around border-t border-border bg-background sm:hidden">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex flex-1 flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors ${
                    isActive ? "text-primary-700" : "text-muted-foreground"
                  }`
                }
              >
                <Icon size={20} weight={undefined} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      )}
    </div>
  );
}
