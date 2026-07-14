/**
 * P4: AgentChat 组件拆分 - 共享常量
 */
import {
  Palette, Clock, Sparkle, MonitorPlay, Zap, Gauge, UsersRound,
  CircleDot, Type, User, Mountain, Wand2, Ratio, Droplets, Sunrise,
  ScanEye, LayoutGrid, Eye, Shirt, Move3d, ShieldCheck, Video, Mic,
  RotateCcw, FileOutput, Waves, Focus, Proportions, ClapperboardIcon,
  type LucideIcon,
} from 'lucide-react';
import type { AgentStepKey } from '@/store/agent';

export const OPTION_ICONS: Record<string, LucideIcon> = {
  visual_style: Palette,
  episode_count: Clock,
  duration_per_episode: Clock,
  tone: Sparkle,
  target_platform: MonitorPlay,
  pacing: Zap,
  conflict_intensity: Gauge,
  protagonist_type: UsersRound,
  ending_type: CircleDot,
  dialogue_density: Type,
  character_style: User,
  scene_style: Mountain,
  image_model: Wand2,
  aspect_ratio: Ratio,
  color_scheme: Droplets,
  lighting: Sunrise,
  detail_level: ScanEye,
  background_purity: LayoutGrid,
  expression_intensity: Eye,
  costume_detail: Shirt,
  shot_language: ClapperboardIcon,
  camera_movement_preference: Move3d,
  cut_speed: Zap,
  composition: Proportions,
  storyboard_density: LayoutGrid,
  emotional_focus: Focus,
  continuity_strictness: ShieldCheck,
  video_model: Video,
  video_duration: Clock,
  video_ratio: Ratio,
  video_quality: Gauge,
  generate_audio: Mic,
  watermark: ShieldCheck,
  resolution: MonitorPlay,
  fps: Zap,
  render_style: Palette,
  motion_smoothness: Waves,
  retry_policy: RotateCcw,
  output_format: FileOutput,
  qa_strictness: ShieldCheck,
};

export const SUB_STEPS: Record<AgentStepKey, { id: string; label: string }[]> = {
  start: [],
  planning: [
    { id: 'script_planner', label: '剧本架构' },
    { id: 'screenwriter', label: '编剧拆解' },
    { id: 'reviewer', label: '导演质检' },
  ],
  asset: [
    { id: 'character_agent', label: '角色设定' },
    { id: 'scene_agent', label: '场景设定' },
    { id: 'image_gen', label: '锁定生图' },
  ],
  production: [
    { id: 'storyboard_director', label: '分镜导演' },
    { id: 'video_composer', label: '视频作曲' },
    { id: 'canvas_builder', label: '画布创建' },
  ],
  finalized: [],
};

export const OPTION_TEMPLATES: Record<AgentStepKey, Record<string, Record<string, string>>> = {
  start: {
    甜宠短剧: { tone: '甜宠', pacing: '快节奏', conflict_intensity: '弱冲突', ending_type: '圆满结局', dialogue_density: '台词密集' },
    逆袭爽剧: { tone: '热血', pacing: '快节奏', conflict_intensity: '强冲突', ending_type: '反转打脸', dialogue_density: '平衡' },
    悬疑短剧: { tone: '悬疑', pacing: '中节奏', conflict_intensity: '中等', ending_type: '悬念收尾', dialogue_density: '动作戏为主' },
  },
  planning: {},
  asset: {},
  production: {},
  finalized: {},
};

export const CORE_OPTION_KEYS: Record<AgentStepKey, string[]> = {
  start: ['visual_style', 'episode_count', 'duration_per_episode', 'tone', 'target_platform'],
  planning: ['visual_style', 'episode_count', 'duration_per_episode', 'tone', 'target_platform'],
  asset: ['image_model', 'aspect_ratio', 'detail_level', 'character_style', 'scene_style'],
  production: ['video_model', 'video_duration', 'video_ratio', 'storyboard_density', 'shot_language'],
  finalized: [],
};

export interface GlobalParamDef {
  key: string;
  label: string;
  type?: 'select';
  options?: string[];
  editable?: boolean;
}

export const GLOBAL_PARAM_DEFINITIONS: GlobalParamDef[] = [
  { key: '项目ID', label: '项目ID', editable: false },
  { key: '核心题材', label: '核心题材' },
  { key: '视觉主风格', label: '视觉主风格' },
  { key: '目标画幅', label: '目标画幅', type: 'select', options: ['9:16竖屏', '16:9横屏', '1:1', '2.39:1电影宽幅'] },
  { key: '单集时长', label: '单集时长', type: 'select', options: ['60-90秒', '90-120秒', '120-180秒'] },
  { key: '目标平台', label: '目标平台', type: 'select', options: ['抖音', '快手', 'B站', '小红书', 'YouTube Shorts', 'TikTok'] },
  { key: '渲染基准', label: '渲染基准' },
  { key: '镜头基准', label: '镜头基准' },
];

export const DRAMA_MAX_RETRIES = 3;



/** 快捷反馈标签模板 */

export const QUICK_FEEDBACK_TAGS: Record<string, string[]> = {

  start: ['换个题材', '更详细一些', '换一个灵感'],

  planning: ['节奏太慢', '对白太长', '角色不够鲜明', '剧情需要反转', '增加悬念', '减少场次'],

  asset: ['角色不够帅气', '场景太单调', '换一种画风', '增加细节', '调整服装'],

  production: ['镜头太单调', '增加运镜', '分镜太少', '节奏太快', '换视频模型'],

  finalized: [],

};



/** 每步预估 Token 消耗 */

export const STEP_TOKEN_ESTIMATES: Record<string, number> = {

  start: 500,

  planning: 3000,

  asset: 2000,

  production: 2500,

  finalized: 500,

};



/** 每步预估积分消耗 */

export const STEP_CREDIT_ESTIMATES: Record<string, number> = {

  start: 0,

  planning: 30,

  asset: 50,

  production: 40,

  finalized: 0,

};

