import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  BookOpen, Command, FolderOpen, Library, Maximize2, Minimize2,
  Moon, Network, PanelLeft, PanelRight, Route, Settings, Sun, Type,
} from "lucide-react";
import { useApp } from "../core/store";
import { READING_SCALE_LABEL } from "../core/prefs";
import { stageFromPath, trackPath } from "../core/routes";
import type { Stage } from "../types";
import { ProjectModal } from "./ProjectModal";
import { SettingsModal } from "./SettingsModal";

const STAGES: { id: Stage; label: string; num: string; icon: typeof Network }[] = [
  { id: "architecture", label: "骨架", num: "01", icon: Network },
  { id: "plan", label: "计划", num: "02", icon: Route },
  { id: "read", label: "阅读", num: "03", icon: BookOpen },
  { id: "library", label: "切片库", num: "04", icon: Library },
];

export function TopBar() {
  const navigate = useNavigate();
  const location = useLocation();
  const workspace = useApp((s) => s.workspace);
  const activeTrackId = useApp((s) => s.activeTrackId);
  const activeSliceId = useApp((s) => s.activeSliceId);
  const setStage = useApp((s) => s.setStage);
  const setCommandOpen = useApp((s) => s.setCommandOpen);
  const railOpen = useApp((s) => s.railOpen);
  const dockOpen = useApp((s) => s.dockOpen);
  const focusMode = useApp((s) => s.focusMode);
  const toggleRail = useApp((s) => s.toggleRail);
  const toggleDock = useApp((s) => s.toggleDock);
  const toggleFocusMode = useApp((s) => s.toggleFocusMode);
  const readingScale = useApp((s) => s.readingScale);
  const cycleReadingScale = useApp((s) => s.cycleReadingScale);
  const codeTheme = useApp((s) => s.codeTheme);
  const toggleCodeTheme = useApp((s) => s.toggleCodeTheme);
  const [projectOpen, setProjectOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const stage = stageFromPath(location.pathname);

  function go(next: Stage) {
    if (!activeTrackId) return;
    setStage(next);
    navigate(trackPath(activeTrackId, next, next === "read" ? activeSliceId : null));
  }

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">QT</div>
          <div>
            <div className="brand-name">Quick-TakeApart</div>
            <div className="brand-sub">Reading observatory</div>
          </div>
        </div>

        <div className="top-divider" />

        <button className="project-switch" onClick={() => setProjectOpen(true)} title="切换项目">
          <span className="project-dot" />
          <span className="truncate">
            <span className="project-name">{workspace?.name || "未打开项目"}</span>
          </span>
          <span className="project-caret">▾</span>
        </button>

        <div className="stage-tabs">
          {STAGES.map(({ id, label, num, icon: Icon }) => (
            <button
              key={id}
              className={`stage-tab${stage === id ? " active" : ""}`}
              onClick={() => go(id)}
              disabled={!activeTrackId}
              title={label}
              aria-label={label}
            >
              <span className="num">{num}</span>
              <Icon size={13} />
              <span className="lbl">{label}</span>
            </button>
          ))}
        </div>

        <div className="top-spacer" />

        <div className="top-stats">
          <span><b>{workspace?.stats.files ?? 0}</b> 文件</span>
          <span><b>{workspace?.stats.callables ?? 0}</b> 函数</span>
          <span><b>{workspace?.stats.edges ?? 0}</b> 边</span>
        </div>

        <button
          className={`icon-btn top-toggle-rail${railOpen && !focusMode ? " is-on" : ""}`}
          title={railOpen ? "隐藏左栏" : "显示左栏"}
          onClick={toggleRail}
        >
          <PanelLeft size={15} />
        </button>
        <button
          className={`icon-btn top-toggle-dock${dockOpen && !focusMode ? " is-on" : ""}`}
          title={dockOpen ? "隐藏右栏" : "显示右栏"}
          onClick={toggleDock}
        >
          <PanelRight size={15} />
        </button>
        <button
          className={`icon-btn top-toggle-focus${focusMode ? " is-on" : ""}`}
          title={focusMode ? "退出全屏阅读" : "全屏阅读"}
          onClick={toggleFocusMode}
        >
          {focusMode ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
        <button
          className="icon-btn"
          title={`阅读字号：${READING_SCALE_LABEL[readingScale]}（点击切换）`}
          aria-label="切换阅读字号"
          onClick={cycleReadingScale}
        >
          <Type size={15} />
        </button>
        <button
          className="icon-btn"
          title={codeTheme === "dark" ? "切换为浅色代码底" : "切换为深色代码底"}
          aria-label="切换代码配色"
          onClick={toggleCodeTheme}
        >
          {codeTheme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
        <button className="icon-btn" title="API 设置" onClick={() => setSettingsOpen(true)}>
          <Settings size={15} />
        </button>
        <button className="icon-btn" title="命令面板 (Ctrl/Cmd+K)" onClick={() => setCommandOpen(true)}>
          <Command size={15} />
        </button>
        <button className="icon-btn" title="打开项目" onClick={() => setProjectOpen(true)}>
          <FolderOpen size={15} />
        </button>
      </header>
      {projectOpen ? <ProjectModal onClose={() => setProjectOpen(false)} /> : null}
      {settingsOpen ? <SettingsModal onClose={() => setSettingsOpen(false)} /> : null}
    </>
  );
}
