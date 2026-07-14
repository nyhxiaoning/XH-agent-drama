import "./director-desk.css";
import { useEffect } from "react";
import { X } from "lucide-react";
import { DirectorDeskShell } from "./DirectorDeskShell";
import { DirectorCanvas } from "./canvas/DirectorCanvas";
import {
  initDirectorDeskHostBridge,
  clearDirectorDeskHostBridge,
  type DirectorDeskHostConfig,
} from "./io/hostBridge";
import { useDirectorStore } from "./store/directorStore";

export interface DirectorDeskProps extends DirectorDeskHostConfig {
  onClose?: () => void;
}

export function DirectorDesk({ onClose, ...hostConfig }: DirectorDeskProps) {
  const viewMode = useDirectorStore((state) => state.viewMode);
  const setViewMode = useDirectorStore((state) => state.setViewMode);

  useEffect(() => {
    initDirectorDeskHostBridge({
      ...hostConfig,
      onClose,
    });
    return () => {
      clearDirectorDeskHostBridge();
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      if (!event.metaKey && !event.ctrlKey) return;
      const key = event.key.toLowerCase();
      if (key === "c") { event.preventDefault(); useDirectorStore.getState().copySelectedObjects(); return; }
      if (key === "v") { event.preventDefault(); useDirectorStore.getState().pasteClipboardObjects(); return; }
      if (key === "z" && !event.shiftKey) { event.preventDefault(); useDirectorStore.getState().undo(); }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="app-shell director-desk-root">
      <header className="top-bar">
        <div className="top-bar-left">
          <h1 className="top-bar-title">3D导演台</h1>
        </div>
        <div className="top-bar-center">
          <div className="mode-toggle ui-segmented" role="group" aria-label="视角切换">
            <button
              className={`mode-toggle-button ui-segmented-item ${viewMode === "director" ? "ui-segmented-item-active" : ""}`}
              aria-pressed={viewMode === "director"}
              type="button"
              onClick={() => setViewMode("director")}
            >
              导演视角
            </button>
            <button
              className={`mode-toggle-button ui-segmented-item ${viewMode === "camera" ? "ui-segmented-item-active" : ""}`}
              aria-pressed={viewMode === "camera"}
              type="button"
              onClick={() => setViewMode("camera")}
            >
              机位视角
            </button>
          </div>
        </div>
        <div className="top-bar-actions">
          {onClose && (
            <button
            className="top-bar-action-button"
            type="button"
            aria-label="关闭"
            title="关闭"
            onClick={onClose}
          >
            <X aria-hidden="true" size={16} strokeWidth={1.8} />
            </button>
          )}
        </div>
      </header>
      <DirectorDeskShell>
        <DirectorCanvas />
      </DirectorDeskShell>
    </div>
  );
}
