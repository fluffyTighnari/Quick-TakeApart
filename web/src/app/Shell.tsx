import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
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

  const positions = useRef(new Map<string, number>());
  const keyRef = useRef(location.pathname + location.search);

  // Remember the main scroll position per route. The reader used to jump to
  // the top whenever a slice/segment changed; IDE-style back-and-forth needs
  // to land exactly where the user left.
  useEffect(() => {
    const main = document.querySelector<HTMLElement>(".main");
    if (!main) return;
    const record = () => positions.current.set(keyRef.current, main.scrollTop);
    main.addEventListener("scroll", record, { passive: true });
    return () => {
      record();
      main.removeEventListener("scroll", record);
    };
  }, []);

  useLayoutEffect(() => {
    const main = document.querySelector<HTMLElement>(".main");
    if (!main) return;
    const key = location.pathname + location.search;
    keyRef.current = key;
    const target = positions.current.get(key) ?? 0;
    let frame = 0;
    let cancel = false;
    const stop = () => { cancel = true; };
    const tick = () => {
      if (cancel) return;
      const max = Math.max(0, main.scrollHeight - main.clientHeight);
      main.scrollTop = Math.min(target, max);
      if (performance.now() - started < 1800 && Math.abs(main.scrollTop - target) > 2) {
        frame = requestAnimationFrame(tick);
      }
    };
    const started = performance.now();
    if (target > 0) {
      // Set once synchronously; requestAnimationFrame is throttled when the
      // window is not visible, which made the position look forgotten.
      main.scrollTop = Math.min(target, Math.max(0, main.scrollHeight - main.clientHeight));
      main.addEventListener("wheel", stop, { passive: true, once: true });
      main.addEventListener("touchstart", stop, { passive: true, once: true });
      frame = requestAnimationFrame(tick);
    } else {
      main.scrollTop = 0;
    }
    return () => {
      // Save on the old key while the outgoing route is still the one in
      // `keyRef`. Relying only on delayed scroll events made the position land
      // under the next route.
      positions.current.set(key, main.scrollTop);
      cancelAnimationFrame(frame);
      main.removeEventListener("wheel", stop);
      main.removeEventListener("touchstart", stop);
    };
  }, [location.pathname, location.search]);

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
