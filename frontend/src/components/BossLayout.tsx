import { NavLink, Outlet, useLocation } from "react-router-dom";

/**
 * 老板端移动端布局 — 底部 3 Tab：问数 / 发票 / 报销单
 * 详情页（路径含 /:id）不显示 Tab Bar，由详情页自身提供返回按钮
 */
export function BossLayout() {
  const location = useLocation();
  const isDetail =
    /\/boss\/(invoices|reimbursements)\/\d+/.test(location.pathname);

  return (
    <div className="boss-layout">
      <main className="boss-layout__main">
        <Outlet />
      </main>
      {!isDetail && (
        <nav className="boss-tabbar">
          <NavLink
            to="/boss/chat"
            className={({ isActive }) =>
              `boss-tabbar__item ${isActive ? "boss-tabbar__item--active" : ""}`
            }
          >
            <span className="boss-tabbar__icon">💬</span>
            <span className="boss-tabbar__label">问数</span>
          </NavLink>
          <NavLink
            to="/boss/invoices"
            className={({ isActive }) =>
              `boss-tabbar__item ${isActive ? "boss-tabbar__item--active" : ""}`
            }
          >
            <span className="boss-tabbar__icon">📄</span>
            <span className="boss-tabbar__label">发票</span>
          </NavLink>
          <NavLink
            to="/boss/reimbursements"
            className={({ isActive }) =>
              `boss-tabbar__item ${isActive ? "boss-tabbar__item--active" : ""}`
            }
          >
            <span className="boss-tabbar__icon">🧾</span>
            <span className="boss-tabbar__label">报销单</span>
          </NavLink>
        </nav>
      )}
    </div>
  );
}
