/**
 * 预设功能注册表
 * 定义节点属性面板中可用的预设快捷功能
 */
import {
  User, RefreshCw, Lock, Camera, Clapperboard, Sparkles,
  Zap, Scissors, Focus, TrendingUp, Expand, Eraser,
  FileText, Wand2, Film, type LucideIcon,
} from 'lucide-react';

export interface PresetFeature {
  id: string;
  label: string;
  desc: string;
  icon: LucideIcon;
  /** 适用节点类型，空数组表示全部 */
  nodeTypes: string[];
  /** 需要已生成结果（result_url） */
  requiresResult?: boolean;
}

export const PRESET_FEATURES: PresetFeature[] = [
  // ── 角色相关 ──
  {
    id: 'character_sheet',
    label: '角色三视图',
    desc: '生成正面/侧面/背面三视图大图',
    icon: User,
    nodeTypes: ['character'],
  },
  {
    id: 'character_360',
    label: '360°角度呈现',
    desc: '生成多角度视图（6-8个角度）',
    icon: RefreshCw,
    nodeTypes: ['character'],
  },
  {
    id: 'lock_character',
    label: '锁定角色一致性',
    desc: '提取并锁定角色特征，确保跨分镜一致',
    icon: Lock,
    nodeTypes: ['character'],
  },

  // ── 分镜/生成相关 ──
  {
    id: 'multi_angle_9',
    label: '多机位九宫格',
    desc: '一次生成9种机位角度',
    icon: Camera,
    nodeTypes: ['image', 'character', 'scene', 'storyboard'],
  },
  {
    id: 'storyboard_25',
    label: '25宫格分镜',
    desc: '一句话拆分为25个画面',
    icon: Clapperboard,
    nodeTypes: ['script'],
  },
  {
    id: 'story_evolution_4',
    label: '剧情推演四宫格',
    desc: '推演4种可能的后续画面',
    icon: Sparkles,
    nodeTypes: ['image', 'storyboard'],
    requiresResult: true,
  },
  {
    id: 'batch_generate',
    label: '批量生成',
    desc: '批量执行多个分镜节点生成',
    icon: Zap,
    nodeTypes: ['storyboard', 'image', 'video'],
  },

  // ── 图像编辑相关 ──
  {
    id: 'grid_split',
    label: '宫格切分',
    desc: '将大图切分为多张子图',
    icon: Scissors,
    nodeTypes: ['image', 'character', 'scene', 'storyboard'],
    requiresResult: true,
  },
  {
    id: 'focus_crop',
    label: '聚焦特写',
    desc: '框选区域生成特写图',
    icon: Focus,
    nodeTypes: ['image', 'storyboard', 'character', 'scene'],
    requiresResult: true,
  },
  {
    id: 'upscale',
    label: '高清放大',
    desc: '提升图片分辨率',
    icon: TrendingUp,
    nodeTypes: ['image', 'character', 'scene', 'storyboard'],
    requiresResult: true,
  },
  {
    id: 'outpaint',
    label: '扩图',
    desc: '向外扩展画面内容',
    icon: Expand,
    nodeTypes: ['image', 'storyboard', 'character', 'scene'],
    requiresResult: true,
  },
  {
    id: 'remove_bg',
    label: '抠图',
    desc: '移除背景，保留主体',
    icon: Eraser,
    nodeTypes: ['image', 'character', 'scene', 'storyboard'],
    requiresResult: true,
  },

  // ── 脚本相关 ──
  {
    id: 'script_parse',
    label: 'AI剧本解析',
    desc: '将文本拆分为结构化剧本',
    icon: FileText,
    nodeTypes: ['script'],
  },
  {
    id: 'script_optimize',
    label: 'AI脚本优化',
    desc: '润色对白、调整节奏',
    icon: Wand2,
    nodeTypes: ['script'],
  },
  {
    id: 'film_analysis',
    label: '一键拉片分析',
    desc: '分析视频镜头语言与叙事节奏',
    icon: Film,
    nodeTypes: ['video'],
    requiresResult: true,
  },
];

/** 根据节点类型过滤可用预设 */
export function getAvailablePresets(nodeType: string, hasResult: boolean): PresetFeature[] {
  return PRESET_FEATURES.filter((f) => {
    if (f.nodeTypes.length > 0 && !f.nodeTypes.includes(nodeType)) return false;
    if (f.requiresResult && !hasResult) return false;
    return true;
  });
}

/** 预设功能 Prompt 模板 */
export const PRESET_PROMPTS: Record<string, (prompt: string, style?: string) => string> = {
  character_sheet: (p, s) =>
    `character design sheet, three views: front view, side profile view, back view, full body, ${p}, white background, concept art style, consistent lighting${s ? `, ${s}` : ''}`,

  character_360: (p, s) =>
    `character turnaround sheet, 8 angles: front, 3/4 front, side, 3/4 back, back, 3/4 back, side, 3/4 front, full body, ${p}, white background, consistent design${s ? `, ${s}` : ''}`,

  multi_angle_9: (p, s) =>
    `3x3 grid layout, 9 different camera angles of the same subject: bird's eye view, high angle, eye level, low angle, dutch angle, over the shoulder, close-up, medium shot, wide shot, ${p}, consistent character design${s ? `, ${s}` : ''}, white grid lines`,

  story_evolution_4: (p, s) =>
    `2x2 grid layout, 4 possible next scenes: top-left=${p} continuation A, top-right=${p} continuation B, bottom-left=${p} continuation C, bottom-right=${p} continuation D${s ? `, ${s}` : ''}, cinematic storytelling`,

  upscale: (p) => `high resolution, ultra detailed, ${p}, 4K, sharp focus`,

  outpaint: (p, s) => `extended scene, wider view, ${p}, seamless expansion${s ? `, ${s}` : ''}`,

  remove_bg: (p) => `${p}, isolated subject on transparent background, clean cutout, no background`,
};
