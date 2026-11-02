import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

export default function App({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">跨项目管理软件 · E1</span>
        <nav>
          <NavLink to="/" end>
            项目
          </NavLink>
          <NavLink to="/imports">导入报告</NavLink>
        </nav>
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
