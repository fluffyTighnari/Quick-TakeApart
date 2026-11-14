import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useApp } from "../core/store";
import { TopBar } from "./TopBar";
import { SideRail } from "./SideRail";
import { ContextDock } from "../features/context/ContextDock";
import { StatusBar } from "./StatusBar";
import { CommandPalette } from "./CommandPalette";

export function Shell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const workspace = useApp((s) => s.workspace);
  const track = useApp((s) => s.track);
  const railOpen = useApp((s) => s.railOpen);
  const dockOpen = useApp((s) => s.dockOpen);
  const focusMode = useApp((s) => s.focusMode);
  const home = location.pathname === "/";
  const noDock = home || !workspace || !track;
  const railHidden = focusMode || !railOpen;
  const dockHidden = focusMode || !dockOpen;

  return (
    <div className="app">
      <TopBar />
      <div className={`body${noDock ? " no-dock" : ""}${railHidden ? " rail-closed" : ""}${dockHidden ? " dock-closed" : ""}`}>
        <SideRail />
        <main className="main">{children}</main>
        {!noDock ? <ContextDock /> : null}
      </div>
      <StatusBar />
      <CommandPalette />
    </div>
  );
}
