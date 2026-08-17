import { Routes, Route, useLocation, Link } from "react-router-dom";
import { AdminProtected } from "./components/AdminProtected";
import { AdminLogin } from "./pages/admin/Login";
import { AnimatePresence, motion } from "framer-motion";
import { Sidebar } from "./components/Sidebar";
import { PortalLayout } from "./components/PortalLayout";
import { PortalProtected } from "./components/PortalProtected";
import { BossProtected } from "./components/BossProtected";
import { BossLayout } from "./components/BossLayout";
import { ChatWidget } from "./components/ChatWidget";
import { Dashboard } from "./pages/Dashboard";
import { Invoices } from "./pages/Invoices";
import { Upload } from "./pages/Upload";
import { Reimbursements } from "./pages/Reimbursements";
import { Employees } from "./pages/Employees";
import { Settings } from "./pages/Settings";
import { PortalLogin } from "./pages/portal/Login";
import { PortalHome } from "./pages/portal/Home";
import { PortalUpload } from "./pages/portal/Upload";
import { PortalMyInvoices } from "./pages/portal/MyInvoices";
import { PortalMyReimbursements } from "./pages/portal/MyReimbursements";
import { PortalProfile } from "./pages/portal/Profile";
import { BossLogin } from "./pages/boss/Login";
import { BossChat } from "./pages/boss/Chat";
import { BossInvoiceList } from "./pages/boss/InvoiceList";
import { BossInvoiceDetail } from "./pages/boss/InvoiceDetail";
import { BossReimbursementList } from "./pages/boss/ReimbursementList";
import { BossReimbursementDetail } from "./pages/boss/ReimbursementDetail";

function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <p className="font-display text-6xl font-bold text-muted-foreground">404</p>
      <p className="mt-2 text-sm text-muted-foreground">页面不存在</p>
      <Link
        to="/"
        className="mt-4 rounded-lg bg-primary-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-800"
      >
        返回首页
      </Link>
    </div>
  );
}

function App() {
  const location = useLocation();
  const isPortal = location.pathname.startsWith("/portal");
  const isBoss = location.pathname.startsWith("/boss");

  return (
    <>
      {/* 老板端：独立移动端布局，底部 3 Tab */}
      {isBoss ? (
        <Routes location={location}>
          <Route path="/boss/login" element={<BossLogin />} />
          <Route element={<BossProtected />}>
            <Route element={<BossLayout />}>
              <Route path="/boss/chat" element={<BossChat />} />
              <Route path="/boss/invoices" element={<BossInvoiceList />} />
              <Route
                path="/boss/invoices/:id"
                element={<BossInvoiceDetail />}
              />
              <Route
                path="/boss/reimbursements"
                element={<BossReimbursementList />}
              />
              <Route
                path="/boss/reimbursements/:id"
                element={<BossReimbursementDetail />}
              />
            </Route>
          </Route>
        </Routes>
      ) : isPortal ? (
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ type: "spring", stiffness: 200, damping: 25 }}
          >
            <Routes location={location}>
              <Route path="/portal/login" element={<PortalLogin />} />
              <Route element={<PortalProtected />}>
                <Route element={<PortalLayout />}>
                  <Route path="/portal/home" element={<PortalHome />} />
                  <Route path="/portal/upload" element={<PortalUpload />} />
                  <Route path="/portal/invoices" element={<PortalMyInvoices />} />
                  <Route
                    path="/portal/reimbursements"
                    element={<PortalMyReimbursements />}
                  />
                  <Route path="/portal/profile" element={<PortalProfile />} />
                </Route>
              </Route>
            </Routes>
          </motion.div>
        </AnimatePresence>
      ) : (
        // 管理后台：左 Sidebar + 智能问数悬浮对话框（可拖拽/缩放/隐藏）
        <div className="min-h-[100dvh] bg-background">
          <Routes location={location}>
            <Route path="/admin/login" element={<AdminLogin />} />
            <Route element={<AdminProtected />}>
              <Route path="/*" element={
                <>
                  <Sidebar />
                  {/* Main content area — offset for sidebar width */}
                  <main className="ml-60 min-h-[100dvh]">
                    <div className="mx-auto max-w-[1400px] px-6 py-8 lg:px-8">
                      <AnimatePresence mode="wait">
                        <motion.div
                          key={location.pathname}
                          initial={{ opacity: 0, y: 12 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -8 }}
                          transition={{ type: "spring", stiffness: 200, damping: 25 }}
                        >
                          <Routes location={location}>
                            <Route path="/" element={<Dashboard />} />
                            <Route path="/invoices" element={<Invoices />} />
                            <Route path="/upload" element={<Upload />} />
                            <Route path="/reimbursements" element={<Reimbursements />} />
                            <Route path="/employees" element={<Employees />} />
                            <Route path="/settings" element={<Settings />} />
                            <Route path="*" element={<NotFound />} />
                          </Routes>
                        </motion.div>
                      </AnimatePresence>
                    </div>
                  </main>

                  {/* 智能问数悬浮对话框 — 可拖拽/缩放/隐藏，Cmd/Ctrl+K 切换 */}
                  <ChatWidget mode="floating" />
                </>
              } />
            </Route>
          </Routes>
        </div>
      )}
    </>
  );
}

export default App;
