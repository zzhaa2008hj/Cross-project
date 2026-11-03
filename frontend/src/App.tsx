import { NavLink, Route, Routes } from "react-router-dom";
import PersonPage from "./pages/PersonPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import ProjectListPage from "./pages/ProjectListPage";
import WorkbenchPage from "./pages/WorkbenchPage";

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">跨项目管理软件 · E2</span>
        <nav>
          <NavLink to="/" end>
            项目
          </NavLink>
          <NavLink to="/workbench">工作台</NavLink>
          <NavLink to="/persons">人员</NavLink>
        </nav>
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<ProjectListPage />} />
          <Route path="/workbench" element={<WorkbenchPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/persons" element={<PersonPage />} />
        </Routes>
      </main>
    </div>
  );
}
