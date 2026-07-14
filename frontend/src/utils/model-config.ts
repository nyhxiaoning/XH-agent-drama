export interface ModelOption {
  id: string;
  label: string;
  provider: string;
  type: 'llm' | 'image' | 'video' | 'audio';
}

// ── 硬编码默认列表（降级回退用） ──
const _DEFAULT_LLM_MODELS: ModelOption[] = [
  { id: 'gpt-5.6-terra', label: 'GPT-5.6 Terra', provider: 'OpenAI', type: 'llm' },
  { id: 'gpt-5.6-luna', label: 'GPT-5.6 Luna', provider: 'OpenAI', type: 'llm' },
];

const _DEFAULT_IMAGE_MODELS: ModelOption[] = [
  { id: 'gpt-image-2', label: 'GPT Image 2', provider: '91API', type: 'image' },
  { id: 'gemini-3.1-flash-lite-image', label: 'Gemini 3.1 Flash Lite', provider: '91API', type: 'image' },
  { id: 'doubao-seedream-5-0-pro-260628', label: '豆包 Seedream 5.0 Pro', provider: '火山方舟', type: 'image' },
];

const _DEFAULT_VIDEO_MODELS: ModelOption[] = [
  { id: 'doubao-seedance-2-0-260128', label: 'Seedance 2.0', provider: '火山方舟', type: 'video' },
  { id: 'doubao-seedance-2-0-fast-260128', label: 'Seedance 2.0 Fast', provider: '火山方舟', type: 'video' },
  { id: 'wan2.7-video', label: '万相 2.7 视频', provider: '阿里云百炼', type: 'video' },
  { id: 'wan2.7-t2v', label: '万相 2.7 T2V', provider: '阿里云百炼', type: 'video' },
  { id: 'wan2.7-i2v', label: '万相 2.7 I2V', provider: '阿里云百炼', type: 'video' },
  { id: 'wan2.7-r2v', label: '万相 2.7 R2V', provider: '阿里云百炼', type: 'video' },
  { id: 'viduq3-turbo', label: 'Vidu Q3 Turbo', provider: 'Modelink', type: 'video' },
];

const _DEFAULT_AUDIO_MODELS: ModelOption[] = [
  { id: 'default', label: '默认语音合成', provider: '系统', type: 'audio' },
];

// ── 运行时模型列表（启动时从后端 /config/runtime-models 拉取并合并） ──
let LLM_MODELS: ModelOption[] = [..._DEFAULT_LLM_MODELS];
let IMAGE_MODELS: ModelOption[] = [..._DEFAULT_IMAGE_MODELS];
let VIDEO_MODELS: ModelOption[] = [..._DEFAULT_VIDEO_MODELS];
let AUDIO_MODELS: ModelOption[] = [..._DEFAULT_AUDIO_MODELS];

// 运行时默认 LLM 模型 ID（从后端 .env 同步）
let _runtimeDefaultLlm = '';

export const ASPECT_RATIOS = ['1:1', '16:9', '9:16', '4:3', '3:4', '21:9'];

export const RESOLUTIONS = ['720P', '1080P', '2K', '3K', '4K'];

// 图片模型分辨率选项（Seedream 系列）
export const IMAGE_RESOLUTIONS = ['1K', '2K', '4K'];

// 判断是否为 Seedream 模型（需要分辨率选择）
export function isSeedreamModel(model: string): boolean {
  const m = (model || '').toLowerCase();
  return m.includes('seedream');
}

// 视频模型按时长档位（参考项目：Seedance 5/10/15s；万相 2-15s 任意整数，提供常用档位）
export const VIDEO_DURATION_OPTIONS: Record<string, number[]> = {
  'doubao-seedance-2-0-260128': [5, 10, 15],
  'doubao-seedance-2-0-fast-260128': [5, 10, 15],
  'wan2.7-video': [3, 5, 8, 10, 15],
  'wan2.7-t2v': [3, 5, 8, 10, 15],
  'wan2.7-i2v': [3, 5, 8, 10, 15],
  'wan2.7-r2v': [3, 5, 8, 10],
  'viduq3-turbo': [3, 5, 8, 10, 16],
};

// 视频模型按分辨率
export const VIDEO_RESOLUTION_OPTIONS: Record<string, string[]> = {
  'doubao-seedance-2-0-260128': ['480p', '720p', '1080p'],
  'doubao-seedance-2-0-fast-260128': ['480p', '720p', '1080p'],
  'wan2.7-video': ['720P', '1080P'],
  'wan2.7-t2v': ['720P', '1080P'],
  'wan2.7-i2v': ['720P', '1080P'],
  'wan2.7-r2v': ['720P', '1080P'],
  'viduq3-turbo': ['540p', '720p', '1080p'],
};

// 视频模型按比例（wan2.7-i2v 跟随首帧，不展示比例）
export const VIDEO_ASPECT_RATIO_OPTIONS: Record<string, string[]> = {
  'doubao-seedance-2-0-260128': ['1:1', '4:3', '3:4', '16:9', '9:16', '21:9', 'adaptive'],
  'doubao-seedance-2-0-fast-260128': ['1:1', '4:3', '3:4', '16:9', '9:16', '21:9', 'adaptive'],
  'wan2.7-video': ['16:9', '9:16', '1:1', '4:3', '3:4'],
  'wan2.7-t2v': ['16:9', '9:16', '1:1', '4:3', '3:4'],
  'wan2.7-i2v': [],
  'wan2.7-r2v': ['16:9', '9:16', '1:1', '4:3', '3:4'],
  'viduq3-turbo': ['16:9', '9:16', '1:1', '4:3', '3:4'],
};

// 支持声音生成的视频模型（Seedance 2.0 系列 + Vidu Q3 Turbo）
export const VIDEO_SOUND_SUPPORT = new Set<string>([
  'doubao-seedance-2-0-260128',
  'doubao-seedance-2-0-fast-260128',
  'viduq3-turbo',
]);

// 支持 watermark 参数的视频模型
export const VIDEO_WATERMARK_SUPPORT = new Set<string>([
  'doubao-seedance-2-0-260128',
  'doubao-seedance-2-0-fast-260128',
  'wan2.7-video',
  'wan2.7-t2v',
  'wan2.7-i2v',
  'wan2.7-r2v',
  'viduq3-turbo',
]);

export function getVideoDurations(model: string): number[] {
  return VIDEO_DURATION_OPTIONS[model] || [5];
}

export function getVideoResolutions(model: string): string[] {
  return VIDEO_RESOLUTION_OPTIONS[model] || ['720P'];
}

export function getVideoAspectRatios(model: string): string[] {
  return VIDEO_ASPECT_RATIO_OPTIONS[model] || ASPECT_RATIOS;
}

export function supportsVideoSound(model: string): boolean {
  return VIDEO_SOUND_SUPPORT.has(model);
}

export function supportsVideoWatermark(model: string): boolean {
  return VIDEO_WATERMARK_SUPPORT.has(model);
}

export interface StylePreset {
  name: string;
  image: string;
}

export const STYLE_PRESETS: StylePreset[] = [
  { name: '电影质感', image: '/images/styles/cinematic.jpg' },
  { name: '日系二次元', image: '/images/styles/anime.jpg' },
  { name: '写实摄影', image: '/images/styles/realistic.jpg' },
  { name: '赛博朋克', image: '/images/styles/cyberpunk.jpg' },
  { name: '国风古韵', image: '/images/styles/guofeng.jpg' },
  { name: '水墨画风', image: '/images/styles/ink.jpg' },
  { name: '3D 卡通', image: '/images/styles/cartoon3d.jpg' },
  { name: '复古胶片', image: '/images/styles/vintage.jpg' },
  { name: '黑金色调', image: '/images/styles/blackgold.jpg' },
  { name: '清新明亮', image: '/images/styles/fresh.jpg' },
  { name: '90年代香港风格', image: '/images/styles/xg90.jpg' },
  { name: '国漫3D风格', image: '/images/styles/gm3d.png' },
  { name: '欧美真人风格', image: '/images/styles/omzhenren.png' },
];

/**
 * 从后端 /config/runtime-models 拉取 .env 配置的模型列表，合并到运行时列表中。
 * - 后端返回的模型如果不在硬编码列表中，则追加
 * - 已存在的则用后端的 label/provider 覆盖更新
 * - 同步更新默认 LLM 模型 ID
 *
 * 由 editor store 在启动时调用，失败时静默降级使用硬编码列表。
 */
export async function loadRuntimeModels(): Promise<void> {
  try {
    const { api } = await import('@/utils/api');
    const res = await api.getRuntimeModels();

    // 合并函数：后端模型追加到硬编码列表前面（优先展示），已有的更新 label/provider
    const mergeModels = (defaults: ModelOption[], runtime: { model_id: string; label: string; provider: string; type: string }[]): ModelOption[] => {
      const merged: ModelOption[] = [];
      const seen = new Set<string>();

      // 先放后端返回的模型（.env 配置的优先展示）
      for (const r of runtime) {
        if (!r.model_id) continue;
        merged.push({ id: r.model_id, label: r.label || r.model_id, provider: r.provider || '', type: r.type as ModelOption['type'] });
        seen.add(r.model_id);
      }
      // 再追加硬编码列表中不重复的
      for (const d of defaults) {
        if (!seen.has(d.id)) {
          merged.push(d);
          seen.add(d.id);
        }
      }
      return merged;
    };

    LLM_MODELS = mergeModels(_DEFAULT_LLM_MODELS, res.llm_models || []);
    IMAGE_MODELS = mergeModels(_DEFAULT_IMAGE_MODELS, res.image_models || []);
    VIDEO_MODELS = mergeModels(_DEFAULT_VIDEO_MODELS, res.video_models || []);
    AUDIO_MODELS = mergeModels(_DEFAULT_AUDIO_MODELS, res.audio_models || []);

    // 同步默认 LLM 模型
    if (res.default_llm_model) {
      _runtimeDefaultLlm = res.default_llm_model;
    }
  } catch {
    // 静默失败，使用硬编码列表作为降级
  }
}

/**
 * 动态已启用模型 ID 集合（由 store 加载后调用 setEnabledModelIds 更新）。
 * 为空时降级返回硬编码列表。
 */
let _enabledModelIds: Set<string> | null = null;

export function setEnabledModelIds(ids: string[] | null) {
  _enabledModelIds = ids ? new Set(ids) : null;
}

/**
 * 获取当前已启用的模型列表（动态过滤）。
 * 如果 setEnabledModelIds 已设置，则只返回启用的；
 * 否则降级返回硬编码列表。
 */
export function getModelsForNodeType(nodeType: string): ModelOption[] {
  let baseModels: ModelOption[] = [];
  if (nodeType === 'image' || nodeType === 'storyboard' || nodeType === 'character' || nodeType === 'scene') baseModels = IMAGE_MODELS;
  else if (nodeType === 'video') baseModels = VIDEO_MODELS;
  else if (nodeType === 'audio') baseModels = AUDIO_MODELS;
  else if (nodeType === 'script') baseModels = LLM_MODELS;
  else return [];

  if (_enabledModelIds && _enabledModelIds.size > 0) {
    const filtered = baseModels.filter(m => _enabledModelIds!.has(m.id));
    // 如果过滤后还有模型，返回过滤结果；否则降级返回全部（避免列表为空导致用户无法操作）
    return filtered.length > 0 ? filtered : baseModels;
  }
  return baseModels;
}

export function getDefaultModelForNodeType(nodeType: string): string {
  if (nodeType === 'image' || nodeType === 'character' || nodeType === 'scene') return 'gpt-image-2';
  if (nodeType === 'storyboard') return 'gpt-image-2';
  if (nodeType === 'video') return 'doubao-seedance-2-0-260128';
  if (nodeType === 'audio') return 'default';
  if (nodeType === 'script') return _runtimeDefaultLlm || 'gpt-5.6-terra';
  return '';
}

import type { CanvasNode } from '@/types';
import type { ModelPricing } from '@/utils/api';

/** 估算单次生成所需积分 */
export function getEstimatedCost(node: CanvasNode, modelPricing: ModelPricing[]): number {
  const cfg = node.config || {};
  const nt = node.node_type;
  if (nt === 'audio') return 5;
  if (nt === 'script') return 0;
  if (nt === 'video') {
    const duration = Number(cfg.duration || cfg.durationSec || cfg.duration_seconds || 5);
    const model = String(cfg.model || '').toLowerCase();
    const pricing = modelPricing.find((p) => p.model_id.toLowerCase() === model && p.type === 'video');
    if (pricing) {
      if (duration <= 5 && pricing.credits_5s > 0) return pricing.credits_5s;
      if (duration <= 10 && pricing.credits_10s > 0) return pricing.credits_10s;
      if (duration <= 15 && pricing.credits_15s > 0) return pricing.credits_15s;
      if (pricing.credits > 0) return Math.round(duration * pricing.credits);
    }
    return Math.max(50, Math.round(duration * 10));
  }
  const model = String(cfg.model || '').toLowerCase();
  const pricing = modelPricing.find((p) => p.model_id.toLowerCase() === model && p.type === 'image');
  if (pricing && pricing.credits > 0) return pricing.credits;
  let cost = 10;
  const resolution = String(cfg.resolution || '').toLowerCase();
  if (resolution === '1024x1536' || resolution === '1536x1024') cost = 12;
  else if (resolution === '1k') cost = 10;
  else if (resolution === '2k') cost = 15;
  else if (resolution === '4k') cost = 20;
  // 默认（无分辨率选择）= 1K = 10 积分
  return cost;
}
