import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  SquaresFour,
  Receipt,
  Stack,
  UserCircle,
  SignOut,
} from "@phosphor-icons/react";
import { portalApi } from "../api/client";

const navItems = [
  { to: "/portal/home", label: "智能问数", icon: SquaresFour },
  { to: "/portal/invoices", label: "我的发票", icon: Receipt },
  { to: "/portal/reimbursements", label: "我的报销", icon: Stack },
  { to: "/portal/profile", label: "个人中心", icon: UserCircle },
];

export function PortalLayout() {
  const navigate = useNavigate();
  const employee = portalApi.getStoredEmployee();

  const handleLogout = () => {
    portalApi.logout();
    navigate("/portal/login");
  };

  return (
    <div className="min-h-[100dvh] bg-background">
      {/* 顶部导航栏 */}
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
            员工端
          </span>
        </div>

        {/* 桌面端顶部导航（sm 及以上显示） */}
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

        {/* 用户信息和退出（窄屏隐藏工号） */}
        <div className="flex items-center gap-2 sm:gap-3">
          {employee && (
            <span className="text-sm text-foreground">
              {employee.name}
              <span className="ml-1 hidden text-xs text-muted-foreground sm:inline">
                ({employee.employee_no})
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

      {/* 主内容区域 — 底部留出 tab bar 高度（手机端 pb-14） */}
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

      {/* 手机端底部 Tab Bar（sm 以下显示） */}
      <nav className="fixed bottom-0 left-0 right-0 z-30 flex h-14 items-stretch justify-around border-t border-border bg-background sm:hidden">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors ${
                  isActive
                    ? "text-primary-700"
                    : "text-muted-foreground"
                }`
              }
            >
              <Icon size={20} weight={undefined} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
}
