import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import {
  SquaresFour,
  Receipt,
  UploadSimple,
  Stack,
  FileText,
  FolderOpen,
  Users,
} from "@phosphor-icons/react";

const navItems = [
  { to: "/", label: "仪表板", icon: SquaresFour },
  { to: "/invoices", label: "发票列表", icon: Receipt },
  { to: "/upload", label: "上传发票", icon: UploadSimple },
  { to: "/reimbursements", label: "报销单管理", icon: Stack },
  { to: "/reports", label: "报表下载", icon: FileText },
  { to: "/projects", label: "项目管理", icon: FolderOpen },
  { to: "/employees", label: "员工管理", icon: Users },
];

export function Sidebar() {
  const location = useLocation();

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-[100dvh] w-60 flex-col border-r border-slate-200/60 bg-white">
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600">
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
          <span className="font-display text-sm font-bold tracking-tight text-slate-900">
            发票报销智能助手
          </span>
          <span className="text-xs text-slate-400">管理后台 v1.0</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1 px-3 py-2">
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
              className="group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors"
            >
              {isActive && (
                <motion.div
                  layoutId="nav-active"
                  className="absolute inset-0 rounded-xl bg-brand-50"
                  transition={{ type: "spring", stiffness: 300, damping: 30 }}
                />
              )}
              <Icon
                size={20}
                weight={isActive ? "fill" : "regular"}
                className={`relative z-10 transition-colors ${
                  isActive
                    ? "text-brand-700"
                    : "text-slate-400 group-hover:text-slate-600"
                }`}
              />
              <span
                className={`relative z-10 transition-colors ${
                  isActive
                    ? "text-brand-700"
                    : "text-slate-600 group-hover:text-slate-900"
                }`}
              >
                {item.label}
              </span>
            </NavLink>
          );
        })}
      </nav>

      {/* Footer status */}
      <div className="border-t border-slate-200/60 px-4 py-4">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          <span className="text-xs text-slate-500">OCR 引擎运行中</span>
        </div>
      </div>
    </aside>
  );
}
