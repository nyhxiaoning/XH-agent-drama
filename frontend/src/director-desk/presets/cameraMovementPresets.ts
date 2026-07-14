/**
 * 运镜预设库
 * 复用 short_drama.py 中的中文→英文运镜映射，提取为前端可用的结构化预设
 */

export type MotionMagnitude = "low" | "medium" | "high";
export type CameraMovementCategory = "basic" | "advanced" | "special";

export interface CameraKeyframeOffset {
  positionOffset: [number, number, number];
  targetOffset: [number, number, number];
  fovDelta: number;
}

export interface CameraMovementPreset {
  id: string;
  name: string;
  nameEn: string;
  category: CameraMovementCategory;
  description: string;
  /** 运镜在视频 prompt 中的英文描述 */
  promptFragment: string;
  /** 运动幅度（对应 Seedance motion_magnitude） */
  motionMagnitude: MotionMagnitude;
  /** 关键帧偏移（相对于当前机位） */
  keyframes: {
    start: CameraKeyframeOffset;
    end: CameraKeyframeOffset;
  };
  /** 适用景别 */
  suitableShots: string[];
  /** 图标 emoji */
  icon: string;
}

export const CAMERA_MOVEMENT_PRESETS: CameraMovementPreset[] = [
  {
    id: "static",
    name: "固定",
    nameEn: "Static",
    category: "basic",
    description: "锁定机位，仅有微妙呼吸感动效",
    promptFragment: "locked-off static camera with subtle micro-movement",
    motionMagnitude: "low",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["close-up", "medium shot", "full shot"],
    icon: "▣",
  },
  {
    id: "dolly-in",
    name: "推镜",
    nameEn: "Dolly In",
    category: "basic",
    description: "摄像机沿光轴前进，缓慢靠近主体",
    promptFragment: "slow dolly in, camera moves forward smoothly toward subject",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 2], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["close-up", "medium shot"],
    icon: "↑",
  },
  {
    id: "dolly-out",
    name: "拉镜",
    nameEn: "Dolly Out",
    category: "basic",
    description: "摄像机沿光轴后退，缓缓远离主体",
    promptFragment: "slow dolly out, camera pulls back revealing wider scene",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 2], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["medium shot", "full shot", "wide shot"],
    icon: "↓",
  },
  {
    id: "pan-left",
    name: "左摇",
    nameEn: "Pan Left",
    category: "basic",
    description: "摄像机水平向左旋转",
    promptFragment: "gentle pan left, camera rotates horizontally to the left",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [-1, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["wide shot", "full shot"],
    icon: "←",
  },
  {
    id: "pan-right",
    name: "右摇",
    nameEn: "Pan Right",
    category: "basic",
    description: "摄像机水平向右旋转",
    promptFragment: "gentle pan right, camera rotates horizontally to the right",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [1, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["wide shot", "full shot"],
    icon: "→",
  },
  {
    id: "tilt-up",
    name: "上仰",
    nameEn: "Tilt Up",
    category: "basic",
    description: "摄像机垂直向上仰拍",
    promptFragment: "gentle tilt up, camera rotates vertically upward",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 1, 0], fovDelta: 0 },
    },
    suitableShots: ["full shot", "wide shot"],
    icon: "↗",
  },
  {
    id: "tilt-down",
    name: "下俯",
    nameEn: "Tilt Down",
    category: "basic",
    description: "摄像机垂直向下俯拍",
    promptFragment: "gentle tilt down, camera rotates vertically downward",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, -1, 0], fovDelta: 0 },
    },
    suitableShots: ["full shot", "wide shot"],
    icon: "↘",
  },
  {
    id: "tracking",
    name: "横移",
    nameEn: "Tracking",
    category: "advanced",
    description: "摄像机水平横向移动，保持朝向不变",
    promptFragment: "tracking shot, camera moves laterally alongside subject",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [-2, 0, 0], targetOffset: [-2, 0, 0], fovDelta: 0 },
      end: { positionOffset: [2, 0, 0], targetOffset: [2, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["medium shot", "full shot"],
    icon: "⇄",
  },
  {
    id: "follow",
    name: "跟拍",
    nameEn: "Following",
    category: "advanced",
    description: "摄像机跟随主体运动方向",
    promptFragment: "following shot, camera tracks subject movement from behind",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 1], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, -1], fovDelta: 0 },
    },
    suitableShots: ["full shot", "wide shot"],
    icon: "→↑",
  },
  {
    id: "crane-up",
    name: "升镜",
    nameEn: "Crane Up",
    category: "advanced",
    description: "摄像机垂直上升，展现更广阔的场景",
    promptFragment: "crane shot, camera rises vertically revealing wider scene",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 3, 0], targetOffset: [0, 0, 0], fovDelta: 5 },
    },
    suitableShots: ["full shot", "wide shot"],
    icon: "⤴",
  },
  {
    id: "crane-down",
    name: "降镜",
    nameEn: "Crane Down",
    category: "advanced",
    description: "摄像机垂直下降，从高处降落",
    promptFragment: "crane down shot, camera descends vertically from above",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 3, 0], targetOffset: [0, 0, 0], fovDelta: 5 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["full shot", "wide shot"],
    icon: "⤵",
  },
  {
    id: "orbit",
    name: "环绕",
    nameEn: "Orbit",
    category: "advanced",
    description: "摄像机围绕主体做 360 度旋转",
    promptFragment: "slow orbit around subject, 360-degree rotation",
    motionMagnitude: "high",
    keyframes: {
      start: { positionOffset: [2, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [-2, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["medium shot", "full shot"],
    icon: "↻",
  },
  {
    id: "handheld",
    name: "手持晃动",
    nameEn: "Handheld",
    category: "special",
    description: "手持摄影风格，带有自然晃动感",
    promptFragment: "slight handheld camera movement, documentary feel",
    motionMagnitude: "high",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["close-up", "medium shot"],
    icon: "≋",
  },
  {
    id: "whip-pan",
    name: "甩镜",
    nameEn: "Whip Pan",
    category: "special",
    description: "快速水平甩动，产生运动模糊",
    promptFragment: "fast whip pan, rapid horizontal camera rotation with motion blur",
    motionMagnitude: "high",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [-2, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [2, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["medium shot", "full shot"],
    icon: "⟿",
  },
  {
    id: "dutch-angle",
    name: "荷兰角",
    nameEn: "Dutch Angle",
    category: "special",
    description: "摄像机倾斜，营造心理紧张感",
    promptFragment: "Dutch angle tilt, camera rolled for psychological tension",
    motionMagnitude: "low",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["close-up", "medium shot"],
    icon: "◢",
  },
  {
    id: "zoom-in",
    name: "变焦推近",
    nameEn: "Zoom In",
    category: "special",
    description: "通过焦距变化模拟推近效果",
    promptFragment: "slow zoom in, focal length increases creating compression",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: -15 },
    },
    suitableShots: ["close-up", "medium shot"],
    icon: "⊕",
  },
  {
    id: "zoom-out",
    name: "变焦拉远",
    nameEn: "Zoom Out",
    category: "special",
    description: "通过焦距变化模拟拉远效果",
    promptFragment: "slow zoom out, focal length decreases revealing wider view",
    motionMagnitude: "medium",
    keyframes: {
      start: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: -15 },
      end: { positionOffset: [0, 0, 0], targetOffset: [0, 0, 0], fovDelta: 0 },
    },
    suitableShots: ["medium shot", "full shot"],
    icon: "⊖",
  },
];

export const CAMERA_MOVEMENT_CATEGORIES: { id: CameraMovementCategory; label: string }[] = [
  { id: "basic", label: "基础运镜" },
  { id: "advanced", label: "高级运镜" },
  { id: "special", label: "特效运镜" },
];

export function getMovementPresetById(id: string | undefined): CameraMovementPreset | undefined {
  if (!id) return undefined;
  return CAMERA_MOVEMENT_PRESETS.find((p) => p.id === id);
}
