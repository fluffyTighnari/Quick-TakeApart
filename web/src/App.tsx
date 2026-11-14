import { useEffect, type ReactNode } from "react";
import {
  HashRouter, Navigate, Route, Routes, useLocation, useNavigate, useParams,
} from "react-router-dom";
import { useApp } from "./core/store";
import { Shell } from "./app/Shell";
import { ProjectPicker } from "./app/ProjectPicker";
import { WorkspaceHome } from "./features/workspace/WorkspaceHome";
import { SkeletonView } from "./features/skeleton/SkeletonView";
import { PlanView } from "./features/plan/PlanView";
import { ReadView } from "./features/read/ReadView";
import { LibraryView } from "./features/library/LibraryView";

function TrackGate({ stage, children }: { stage: string; children: ReactNode }) {
  const { trackId } = useParams();
  const activeTrackId = useApp((s) => s.activeTrackId);
  const track = useApp((s) => s.track);
  const error = useApp((s) => s.error);
  const selectTrack = useApp((s) => s.selectTrack);
  const navigate = useNavigate();

  useEffect(() => {
    if (trackId && trackId !== activeTrackId) {
      void selectTrack(trackId);
    }
  }, [trackId, activeTrackId, selectTrack]);

  useEffect(() => {
    if (!trackId && activeTrackId) {
      navigate(`/track/${activeTrackId}/${stage}`, { replace: true });
    }
  }, [trackId, activeTrackId, stage, navigate]);

  if (trackId && track?.track.id !== trackId) {
    if (error) {
      return (
        <div className="stage">
          <div className="empty" style={{ marginTop: 30 }}>
            <strong>这条轨道打不开</strong>
            {error}
            <div style={{ marginTop: 12 }}>
              <button className="btn btn-sm" onClick={() => navigate("/")}>回到工作区</button>
            </div>
          </div>
        </div>
      );
    }
    return <div className="stage"><div className="loading">正在打开轨道…</div></div>;
  }
  return <>{children}</>;
}

function ShellRoutes() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<WorkspaceHome />} />
        <Route
          path="/track/:trackId/architecture"
          element={<TrackGate stage="architecture"><SkeletonView /></TrackGate>}
        />
        <Route
          path="/track/:trackId/plan"
          element={<TrackGate stage="plan"><PlanView /></TrackGate>}
        />
        <Route
          path="/track/:trackId/read/:sliceId?"
          element={<TrackGate stage="read"><ReadView /></TrackGate>}
        />
        <Route
          path="/track/:trackId/library"
          element={<TrackGate stage="library"><LibraryView /></TrackGate>}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}

function BackendMismatch({ detail }: { detail: string }) {
  return (
    <div className="picker-wrap">
      <div className="picker reveal">
        <div className="eyebrow">Backend mismatch</div>
        <h1>后端进程是旧版本</h1>
        <p className="sub">
          {detail}
          这个页面是新版前端，但当前端口上的 Python 进程还在提供旧 API，所以会出现
          501、404、选择文件夹无反应。
        </p>
        <div className="notice bad" style={{ marginTop: 16 }}>
          请先结束占用当前端口的旧 python 进程，再启动当前代码：
        </div>
        <pre className="mono" style={{ marginTop: 12, padding: 14, background: "var(--code-bg)", color: "var(--code-ink)", borderRadius: 10, overflow: "auto" }}>
{`# 结束旧进程（任务管理器 -> 详细信息 -> python.exe -> 结束任务）
# 或在管理员终端执行：
taskkill /PID <旧进程PID> /F

# 重新启动
python serve.py <项目目录> --port 7741`}
        </pre>
        <div className="row" style={{ marginTop: 14, gap: 8 }}>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            重新检查连接
          </button>
          <button className="btn" onClick={() => { window.location.href = `${window.location.protocol}//${window.location.hostname}:7741/`; }}>
            尝试 7741 端口
          </button>
        </div>
        <div className="hint">
          当前地址：{window.location.origin}
          <br />
          如果旧进程无法结束，直接换一个端口启动，例如 7741，然后打开对应地址。
        </div>
      </div>
    </div>
  );
}

export function App() {
  const booted = useApp((s) => s.booted);
  const booting = useApp((s) => s.booting);
  const backendStale = useApp((s) => s.backendStale);
  const workspace = useApp((s) => s.workspace);
  const error = useApp((s) => s.error);
  const boot = useApp((s) => s.boot);

  useEffect(() => {
    if (!booted && !booting) void boot();
  }, [booted, booting, boot]);

  if (backendStale) {
    return <BackendMismatch detail={backendStale} />;
  }

  if (!booted) {
    return (
      <div className="picker-wrap">
        <div className="picker reveal">
          <div className="eyebrow">Quick-TakeApart</div>
          <h1>正在准备阅读台</h1>
          <p className="sub">索引符号、调用边与文件。第一次打开真实项目可能需要几十秒。</p>
          <div className="loading" style={{ marginTop: 18 }}>正在建立索引…</div>
        </div>
      </div>
    );
  }

  if (!workspace) {
    return (
      <HashRouter>
        <ProjectPicker error={error} />
      </HashRouter>
    );
  }

  return (
    <HashRouter>
      <ShellRoutes />
    </HashRouter>
  );
}
