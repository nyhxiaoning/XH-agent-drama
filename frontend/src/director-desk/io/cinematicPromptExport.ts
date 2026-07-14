/**
 * 影视级运镜 Prompt 生成器
 * 将导演台 3D 机位参数 + 运镜预设 + 镜头参数 → 视频生成 prompt
 */
import { getMovementPresetById, type MotionMagnitude } from "../presets/cameraMovementPresets";
import type { DirectorCameraShot } from "../schema/directorProject";

// 全画幅传感器宽度 (mm)
const SENSOR_WIDTH_35MM = 36;

/** 焦距 mm → FOV 度 */
export function focalLengthToFov(focalLengthMm: number): number {
  return 2 * Math.atan(SENSOR_WIDTH_35MM / (2 * focalLengthMm)) * (180 / Math.PI);
}

/** FOV 度 → 焦距 mm */
export function fovToFocalLength(fov: number): number {
  return SENSOR_WIDTH_35MM / (2 * Math.tan((fov * Math.PI) / 360));
}

/** 常见焦段预设 */
export const FOCAL_LENGTH_PRESETS = [
  { mm: 14, label: "14mm 超广角", useCase: "建立镜头" },
  { mm: 24, label: "24mm 广角", useCase: "场景全景" },
  { mm: 35, label: "35mm 环境", useCase: "环境人像" },
  { mm: 50, label: "50mm 标准", useCase: "中景对话" },
  { mm: 85, label: "85mm 人像", useCase: "特写人像" },
  { mm: 135, label: "135mm 长焦", useCase: "大特写" },
];

/** 光圈 → 景深描述 */
const APERTURE_DOF_MAP: Record<string, string> = {
  "f/1.4": "very shallow depth of field, creamy bokeh",
  "f/1.8": "very shallow depth of field, smooth bokeh",
  "f/2.0": "shallow depth of field, bokeh background",
  "f/2.8": "shallow depth of field",
  "f/4.0": "moderate shallow depth of field",
  "f/5.6": "moderate depth of field",
  "f/8.0": "deep depth of field, most elements in focus",
  "f/11": "deep depth of field, everything in focus",
  "f/16": "very deep depth of field, fully sharp",
};

export const APERTURE_OPTIONS = [
  "f/1.4", "f/1.8", "f/2.0", "f/2.8", "f/4.0",
  "f/5.6", "f/8.0", "f/11", "f/16",
];

/** 滤镜预设 */
const COLOR_GRADE_MAP: Record<string, string> = {
  teal_orange: "teal and orange color grading, blockbuster look",
  noir: "high contrast black and white, film noir style",
  warm: "warm golden tones, nostalgic feel",
  cool: "cool blue tones, melancholic atmosphere",
  vintage: "vintage film look, faded colors, grainy texture",
  natural: "natural color grading, true to life",
};

export const COLOR_GRADE_OPTIONS = [
  { id: "natural", label: "自然", icon: "◐" },
  { id: "teal_orange", label: "青橙", icon: "◑" },
  { id: "noir", label: "黑白", icon: "◯" },
  { id: "warm", label: "暖调", icon: "☀" },
  { id: "cool", label: "冷调", icon: "❄" },
  { id: "vintage", label: "复古", icon: "▣" },
];

/** FOV → 景别推断 */
function inferShotType(fov: number): string {
  if (fov <= 20) return "extreme close-up";
  if (fov <= 35) return "close-up";
  if (fov <= 55) return "medium shot";
  if (fov <= 75) return "full shot";
  return "wide shot";
}

/** 生成影视级 prompt */
export function generateCinematicPrompt(camera: DirectorCameraShot): string {
  const parts: string[] = [];

  // 景别
  const shotType = inferShotType(camera.fov);
  parts.push(shotType);

  // 焦距
  const focalLength = camera.cinematic?.focalLength ?? Math.round(fovToFocalLength(camera.fov));
  parts.push(`${focalLength}mm cinematic lens`);

  // 光圈 → 景深
  if (camera.cinematic?.aperture) {
    const dof = APERTURE_DOF_MAP[camera.cinematic.aperture];
    if (dof) parts.push(dof);
  } else {
    parts.push("shallow depth of field");
  }

  // 运镜
  if (camera.cinematic?.movementPresetId) {
    const preset = getMovementPresetById(camera.cinematic.movementPresetId);
    if (preset) parts.push(preset.promptFragment);
  } else {
    parts.push("locked-off static camera with subtle micro-movement");
  }

  // 滤镜
  if (camera.cinematic?.colorGrade) {
    const grade = COLOR_GRADE_MAP[camera.cinematic.colorGrade];
    if (grade) parts.push(grade);
  }

  // 胶片质感
  parts.push("35mm cinematic film grain, Kodak 5207");

  return parts.join(", ");
}

/** 获取运镜运动幅度 */
export function getMotionMagnitude(camera: DirectorCameraShot): MotionMagnitude {
  if (camera.cinematic?.movementPresetId) {
    const preset = getMovementPresetById(camera.cinematic.movementPresetId);
    if (preset) return preset.motionMagnitude;
  }
  return "low";
}

/** 导出镜头清单 */
export interface ShotListEntry {
  index: number;
  name: string;
  shotType: string;
  focalLength: string;
  aperture: string;
  movement: string;
  motionMagnitude: MotionMagnitude;
  position: [number, number, number];
  target: [number, number, number];
  fov: number;
  prompt: string;
}

export function exportShotList(cameras: DirectorCameraShot[]): ShotListEntry[] {
  return cameras.map((cam, i) => {
    const preset = getMovementPresetById(cam.cinematic?.movementPresetId);
    const focalLength = cam.cinematic?.focalLength ?? Math.round(fovToFocalLength(cam.fov));
    return {
      index: i + 1,
      name: cam.name,
      shotType: inferShotType(cam.fov),
      focalLength: `${focalLength}mm`,
      aperture: cam.cinematic?.aperture || "f/2.8",
      movement: preset?.nameEn || "Static",
      motionMagnitude: getMotionMagnitude(cam),
      position: cam.transform.position,
      target: cam.target,
      fov: cam.fov,
      prompt: generateCinematicPrompt(cam),
    };
  });
}

/** 镜头清单导出为 CSV */
export function exportShotListCSV(cameras: DirectorCameraShot[]): string {
  const entries = exportShotList(cameras);
  const header = "Shot,Name,Shot Type,Focal Length,Aperture,Movement,Motion Magnitude,FOV,Position,Target,Prompt";
  const rows = entries.map((e) =>
    [
      e.index,
      `"${e.name}"`,
      e.shotType,
      e.focalLength,
      e.aperture,
      e.movement,
      e.motionMagnitude,
      `${e.fov}°`,
      `"(${e.position.join(", ")})"`,
      `"(${e.target.join(", ")})"`,
      `"${e.prompt.replace(/"/g, '""')}"`,
    ].join(",")
  );
  return [header, ...rows].join("\n");
}

/** 镜头清单导出为 JSON */
export function exportShotListJSON(cameras: DirectorCameraShot[]): string {
  return JSON.stringify(exportShotList(cameras), null, 2);
}

/** 下载文本文件 */
export function downloadTextFile(content: string, fileName: string, mimeType = "text/plain") {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
