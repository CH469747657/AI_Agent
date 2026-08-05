import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  SquaresFour,
  Receipt,
  UploadSimple,
  Stack,
  UserCircle,
  SignOut,
} from "@phosphor-icons/react";
import { portalApi } from "../api/client";

const navItems = [
  { to: "/portal/home", label: "工作台", icon: SquaresFour },
  { to: "/portal/upload", label: "上传发票", icon: UploadSimple },
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
    <div className="min-h-[100dvh] bg-slate-50">
      {/* 顶部导航栏 */}
      <header className="fixed left-0 right-0 top-0 z-30 flex h-14 items-center justify-between border-b border-slate-200/60 bg-white px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600">
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
          <span className="font-display text-sm font-bold tracking-tight text-slate-900">
            发票报销智能助手
          </span>
          <span className="ml-1 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
            员工端
          </span>
        </div>

        {/* 顶部导航 */}
        <nav className="flex items-center gap-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-brand-50 text-brand-700"
                      : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
                  }`
                }
              >
                <Icon size={16} />
                <span className="hidden sm:inline">{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        {/* 用户信息和退出 */}
        <div className="flex items-center gap-3">
          {employee && (
            <span className="text-sm text-slate-500">
              {employee.name}
              <span className="ml-1 text-xs text-slate-400">
                ({employee.employee_no})
              </span>
            </span>
          )}
          <button
            onClick={handleLogout}
            className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
          >
            <SignOut size={16} />
          </button>
        </div>
      </header>

      {/* 主内容区域 */}
      <main className="pt-14">
        <div className="mx-auto max-w-[1200px] px-6 py-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 200, damping: 25 }}
          >
            <Outlet />
          </motion.div>
        </div>
      </main>
    </div>
  );
}
