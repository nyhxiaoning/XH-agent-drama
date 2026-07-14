import { useDirectorStore } from "../store/directorStore";

export interface HostCaptureItemPayload {
  dataUrl: string;
  fileName: string;
}

export interface DirectorDeskHostConfig {
  theme?: "dark" | "light";
  instanceId?: string | null;
  onCaptures?: (captures: HostCaptureItemPayload[]) => void;
  onClose?: () => void;
  onPanoramaRemoved?: () => void;
  onCinematicParams?: (params: CinematicParamsPayload) => void;
}

let initialized = false;
let removeUnsubscribe: (() => void) | null = null;
let hostConfig: DirectorDeskHostConfig = {};
let suppressNextPanoramaRemovalNotice = false;

function normalizeTheme(value: unknown): "dark" | "light" | null {
  return value === "light" || value === "dark" ? value : null;
}

function applyDirectorDeskTheme(theme: "dark" | "light") {
  document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle("dark", theme === "dark");
}

function subscribeToPanoramaRemoval() {
  if (removeUnsubscribe) return;
  let prev = useDirectorStore.getState().project.panoramaAssetId;
  removeUnsubscribe = useDirectorStore.subscribe((state) => {
    const next = state.project.panoramaAssetId;
    if (prev && !next) {
      if (suppressNextPanoramaRemovalNotice) {
        suppressNextPanoramaRemovalNotice = false;
      } else {
        hostConfig.onPanoramaRemoved?.();
      }
    }
    prev = next;
  });
}

export function importPanoramaFromHost(payload: { imageUrl: string; fileName?: string; sourceNodeId?: string }) {
  const url = payload.imageUrl?.trim();
  if (!url) return;
  const fileName = payload.fileName?.trim() || "panorama.png";
  useDirectorStore.getState().addImportedAsset({ kind: "panorama", name: fileName, fileName, url, projectionMode: "backdrop" });
}

export function openHostSession(payload: { instanceId?: string | null; theme?: "dark" | "light" }) {
  const id = payload.instanceId?.trim() || null;
  const theme = normalizeTheme(payload.theme);
  if (theme) applyDirectorDeskTheme(theme);
  suppressNextPanoramaRemovalNotice = Boolean(useDirectorStore.getState().project.panoramaAssetId);
  useDirectorStore.getState().openScopedScene(id);
  suppressNextPanoramaRemovalNotice = false;
}

export function postDirectorDeskCapturesToHost(captures: Array<{ dataUrl: string; fileName?: string }>) {
  const items = captures.map((c, i) => {
    const d = c.dataUrl?.trim();
    if (!d) return null;
    return { dataUrl: d, fileName: c.fileName?.trim() || `capture-${i + 1}.png` };
  }).filter((c): c is HostCaptureItemPayload => Boolean(c));
  if (items.length === 0) return;
  hostConfig.onCaptures?.(items);
}

export function requestCloseDirectorDesk() { hostConfig.onClose?.(); }

export interface CinematicParamsPayload {
  prompt: string;
  motionMagnitude: "low" | "medium" | "high";
  cameraName: string;
}

export function postCinematicParamsToHost(params: CinematicParamsPayload) {
  hostConfig.onCinematicParams?.(params);
}

export function initDirectorDeskHostBridge(config: DirectorDeskHostConfig = {}) {
  if (initialized) return;
  initialized = true;
  hostConfig = config;
  applyDirectorDeskTheme(config.theme ?? "dark");
  if (config.instanceId !== undefined) openHostSession({ instanceId: config.instanceId, theme: config.theme });
  subscribeToPanoramaRemoval();
}

export function updateDirectorDeskHostConfig(config: Partial<DirectorDeskHostConfig>) {
  hostConfig = { ...hostConfig, ...config };
}

export function clearDirectorDeskHostBridge() {
  if (!initialized) return;
  initialized = false;
  suppressNextPanoramaRemovalNotice = false;
  hostConfig = {};
  removeUnsubscribe?.();
  removeUnsubscribe = null;
}
