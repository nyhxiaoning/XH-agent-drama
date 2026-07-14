import { create } from 'zustand';
import { api } from '@/utils/api';
import type { AgentSession, AgentMessage, ShortDramaScript, ShortDramaAssets, ShortDramaStoryboard, ShortDramaVideos, LockedAsset } from '@/types';

export type AgentStepKey = 'start' | 'planning' | 'asset' | 'production' | 'finalized';

export type StepOptionMap = Record<string, string>;

interface AgentState {
  isOpen: boolean;
  session: AgentSession | null;
  currentStep: AgentStepKey;
  loading: boolean;
  error: string | null;
  selectedChars: string[];
  selectedScenes: string[];
  finalizedCanvasId: string | null;
  stepOptions: Record<AgentStepKey, StepOptionMap>;
  globalParams: Record<string, string>;
  parameterPending: boolean;
  selectedLlmModel: string | null;
  streaming: boolean;
  currentAgent: string | null;
  streamMessages: AgentMessage[];
  streamElapsed: number;
  streamStartedAt: number | null;

  // 一键模式
  agentMode: 'step' | 'one-click';
  modeChosen: boolean;
  oneClickRunning: boolean;
  oneClickProgress: number;
  oneClickStage: string | null;
  oneClickMessages: AgentMessage[];
  oneClickCanvasId: string | null;

  setOpen: (open: boolean) => void;
  reset: () => void;
  toggleChar: (id: string) => void;
  toggleScene: (id: string) => void;
  selectAllAssets: () => void;

  start: (prompt: string, mode?: string, scriptText?: string) => Promise<void>;
  runStep: (step: 'planning' | 'asset' | 'production' | 'script' | 'assets' | 'storyboard' | 'video') => Promise<void>;
  lockAssets: () => Promise<void>;
  finalize: (canvasId?: string, autoGenerate?: boolean) => Promise<string | null>;
  hydrateSession: (sessionId: string) => Promise<void>;
  /** #13 增量同步会话数据到已有画布（阶段完成后自动触发） */
  syncCanvas: () => Promise<void>;

  setSession: (session: AgentSession) => void;
  setStepOption: (step: AgentStepKey, key: string, value: string) => void;
  getStepOption: (step: AgentStepKey, key: string, defaultValue?: string) => string;
  setGlobalParam: (key: string, value: string) => void;
  setSelectedLlmModel: (modelId: string | null) => void;
  suggestParameters: () => Promise<void>;
  confirmParameters: () => Promise<void>;
  confirmVideoStep: () => void;
  skipStep: () => Promise<string | null>;
  /** #8 回退到已完成的上一步（仅前端视图切换，不删除后端数据） */
  goToStep: (step: AgentStepKey) => void;
  /** #7 保存/读取会话 ID 到 localStorage */
  saveSessionId: () => void;
  loadSavedSessionId: () => string | null;
  clearSavedSessionId: () => void;

  // 一键模式
  setAgentMode: (mode: 'step' | 'one-click') => void;
  chooseAgentMode: (mode: 'step' | 'one-click') => void;
  backToAgentSelector: () => void;
  oneClickStart: (prompt: string, mode?: string, scriptText?: string) => Promise<void>;
  oneClickReset: () => void;
}

const INITIAL_STEP: AgentStepKey = 'start';

const DEFAULT_STEP_OPTIONS: Record<AgentStepKey, StepOptionMap> = {
  start: {
    visual_style: '电影写实',
    episode_count: '1集',
    duration_per_episode: '60-90秒',
    tone: '紧张',
    target_platform: '抖音',
    pacing: '快节奏',
    conflict_intensity: '强冲突',
    protagonist_type: '逆袭男主',
    ending_type: '悬念收尾',
    dialogue_density: '平衡',
  },
  planning: {
    visual_style: '电影写实',
    episode_count: '1集',
    duration_per_episode: '60-90秒',
    tone: '紧张',
    target_platform: '抖音',
    pacing: '快节奏',
    conflict_intensity: '强冲突',
    protagonist_type: '逆袭男主',
    ending_type: '悬念收尾',
    dialogue_density: '平衡',
    scene_structure: '三幕式',
    dialogue_style: '口语化',
    action_density: '高密度',
    emotion_arc: '递进式',
    cliffhanger: '强悬念',
  },
  asset: {
    character_style: '写实',
    image_model: 'gpt-image-2',
    aspect_ratio: '9:16',
    detail_level: '超高细节',
    background_purity: '纯白底',
    expression_intensity: '自然',
    costume_detail: '日常',
    scene_style: '写实',
    color_scheme: '冷调',
    lighting: '戏剧光',
  },
  production: {
    shot_language: '电影感',
    camera_movement_preference: '稳',
    cut_speed: '中速',
    storyboard_density: '2-3镜',
    emotional_focus: 'facial',
    continuity_strictness: '严格连续',
    video_model: 'Seedance',
    video_duration: '5秒',
    video_ratio: '9:16',
    video_quality: '高质量',
    generate_audio: '有声音',
    watermark: '无水印',
    resolution: '1080p',
    fps: '24fps',
    render_style: '写实',
    motion_smoothness: '平滑',
    retry_policy: '自动重试',
    output_format: 'mp4',
    qa_strictness: '严格质检',
  },
  finalized: {},
};

const deriveStep = (session: AgentSession | null): AgentStepKey => {
  if (!session) return INITIAL_STEP;
  if (session.status === 'finalized') return 'finalized';
  // 如果还在等待用户确认全局参数/模型，优先停留在开始面板
  if (session.parameter_pending) return 'start';
  // 优先使用三阶段大脑状态
  if (session.current_stage === 'finished') return 'production';
  if (session.video_plan || session.videos) return 'production';
  if (session.storyboard_data || session.storyboard) return 'production';
  if (session.character_assets || session.scene_assets || session.character || session.scene || session.assets) return 'asset';
  if (session.full_script || session.screenwriter || session.script_outline || session.script) return 'planning';
  return INITIAL_STEP;
};

export const useAgentStore = create<AgentState>((set, get) => ({
  isOpen: false,
  session: null,
  currentStep: INITIAL_STEP,
  loading: false,
  error: null,
  selectedChars: [],
  selectedScenes: [],
  finalizedCanvasId: null,
  stepOptions: JSON.parse(JSON.stringify(DEFAULT_STEP_OPTIONS)),
  globalParams: {},
  parameterPending: false,
  selectedLlmModel: null,
  streaming: false,
  currentAgent: null,
  streamMessages: [],
  streamElapsed: 0,
  streamStartedAt: null,

  agentMode: 'step',
  modeChosen: false,
  oneClickRunning: false,
  oneClickProgress: 0,
  oneClickStage: null,
  oneClickMessages: [],
  oneClickCanvasId: null,

  setOpen: (open) => set({ isOpen: open }),

  setSession: (session) => set({ session, currentStep: deriveStep(session) }),

  reset: () => {
    localStorage.removeItem('agentSessionId');
    set({
      session: null,
      currentStep: INITIAL_STEP,
      loading: false,
      error: null,
      selectedChars: [],
      selectedScenes: [],
      finalizedCanvasId: null,
      stepOptions: JSON.parse(JSON.stringify(DEFAULT_STEP_OPTIONS)),
      globalParams: {},
      parameterPending: false,
      selectedLlmModel: null,
      streaming: false,
      currentAgent: null,
      streamMessages: [],
      streamElapsed: 0,
      streamStartedAt: null,
      agentMode: 'step',
      modeChosen: false,
      oneClickRunning: false,
      oneClickProgress: 0,
      oneClickStage: null,
      oneClickMessages: [],
      oneClickCanvasId: null,
    });
  },

  toggleChar: (id) => set((s) => ({
    selectedChars: s.selectedChars.includes(id)
      ? s.selectedChars.filter((x) => x !== id)
      : [...s.selectedChars, id],
  })),

  toggleScene: (id) => set((s) => ({
    selectedScenes: s.selectedScenes.includes(id)
      ? s.selectedScenes.filter((x) => x !== id)
      : [...s.selectedScenes, id],
  })),

  selectAllAssets: () => {
    const { session } = get();
    if (!session) return;
    const characters = session.character?.characters || session.assets?.characters || [];
    const scenes = session.scene?.scenes || session.assets?.scenes || [];
    set({
      selectedChars: characters.map((c) => c.char_id),
      selectedScenes: scenes.map((s) => s.scene_id),
    });
  },

  setStepOption: (step, key, value) => {
    set((s) => ({
      stepOptions: {
        ...s.stepOptions,
        [step]: { ...s.stepOptions[step], [key]: value },
      },
    }));
    const { session } = get();
    if (session) {
      api.shortDramaSetOption(session.id, `${step}.${key}`, value).catch(() => {});
    }
  },

  getStepOption: (step, key, defaultValue = '') => {
    return get().stepOptions[step]?.[key] ?? defaultValue;
  },

  setGlobalParam: (key, value) => {
    set((s) => ({
      globalParams: { ...s.globalParams, [key]: value },
    }));
  },

  setSelectedLlmModel: (modelId) => set({ selectedLlmModel: modelId }),

  suggestParameters: async () => {
    const { session } = get();
    if (!session) return;
    set({ loading: true, error: null });
    try {
      const res = await api.shortDramaSuggestParameters(session.id);
      set({ globalParams: res.suggestions });
    } catch (e: any) {
      set({ error: e.message || '获取参数推荐失败' });
    } finally {
      set({ loading: false });
    }
  },

  confirmParameters: async () => {
    const { session, globalParams, selectedLlmModel } = get();
    if (!session) return;
    set({ loading: true, error: null });
    try {
      const res = await api.shortDramaConfirmParameters(session.id, globalParams, selectedLlmModel ?? undefined);
      set({
        session: res.session,
        parameterPending: false,
        globalParams: res.session.global_params ?? globalParams,
      });
      await get().runStep('planning');
    } catch (e: any) {
      set({ error: e.message || '参数确认失败' });
    } finally {
      set({ loading: false });
    }
  },

  confirmVideoStep: () => {
    set((s) => {
      if (!s.session) return s;
      const updatedSession = {
        ...s.session,
        status: 'video_ready',
        videos: {
          videos: [],
          summary: '请选择下一步操作',
          next_action: 'confirm_finalize',
          options: [
            { key: 'generate', label: '直接生成图片', desc: '自动生成所有角色、场景图，进入画布后可手动生成分镜和视频' },
            { key: 'skip', label: '进入画布', desc: '只创建节点卡片，所有图片视频手动生成' },
          ],
        },
      };
      return {
        session: updatedSession,
        currentStep: deriveStep(updatedSession),
        error: null,
      };
    });
  },

  /** #8 回退到已完成的上一步 */
  goToStep: (step) => {
    const { currentStep, session } = get();
    if (!session) return;
    const currentIdx = AGENT_STEPS.findIndex((s) => s.key === currentStep);
    const targetIdx = AGENT_STEPS.findIndex((s) => s.key === step);
    // 仅允许回退到已完成的步骤（targetIdx < currentIdx）
    if (targetIdx >= currentIdx || targetIdx < 0) return;
    set({ currentStep: step, error: null });
  },

  /** #7 会话持久化 */
  saveSessionId: () => {
    const { session } = get();
    if (session?.id) {
      localStorage.setItem('agentSessionId', session.id);
    }
  },
  loadSavedSessionId: () => {
    return localStorage.getItem('agentSessionId');
  },
  clearSavedSessionId: () => {
    localStorage.removeItem('agentSessionId');
  },

  skipStep: async () => {
    const { currentStep, runStep, finalize } = get();
    if (currentStep === 'start') {
      await runStep('planning');
    } else if (currentStep === 'planning') {
      await runStep('asset');
    } else if (currentStep === 'asset') {
      await runStep('production');
    } else if (currentStep === 'production') {
      // 跳过视频生成，直接进入画布（后端 finalize 默认 auto_generate=False）
      const canvasId = await finalize(undefined);
      return canvasId;
    }
    return null;
  },

  start: async (prompt, mode = 'inspiration', scriptText) => {
    const { session, selectedLlmModel } = get();
    if (session) return;
    set({ loading: true, error: null });
    try {
      const res = await api.shortDramaStart(prompt, mode, scriptText, selectedLlmModel ?? undefined);
      set({
        session: res.session,
        currentStep: deriveStep(res.session),
        selectedChars: [],
        selectedScenes: [],
        finalizedCanvasId: null,
        stepOptions: JSON.parse(JSON.stringify(DEFAULT_STEP_OPTIONS)),
        parameterPending: res.session.parameter_pending ?? true,
        globalParams: res.session.global_params ?? {},
      });
      // 先让用户确认全局参数，确认后再进入 planning
      await get().suggestParameters();
      // #7 持久化 session ID
      get().saveSessionId();
    } catch (e: any) {
      set({ error: e.message || '启动失败' });
    } finally {
      set({ loading: false });
    }
  },

  runStep: async (step) => {
    const { session, stepOptions } = get();
    if (!session) return;
    set({ loading: true, error: null, streaming: true, streamMessages: [], currentAgent: null, streamElapsed: 0, streamStartedAt: Date.now() });
    const stageMap: Record<string, 'planning' | 'asset' | 'production'> = {
      script: 'planning', screenwriter: 'planning', planning: 'planning',
      assets: 'asset', character: 'asset', scene: 'asset', asset: 'asset',
      storyboard: 'production', video: 'production', production: 'production',
    };
    const stage = stageMap[step];
    if (!stage) {
      set({ error: `未知步骤: ${step}`, loading: false, streaming: false });
      return;
    }
    try {
      const opts = stepOptions[stage] || {};
      for (const [key, value] of Object.entries(opts)) {
        await api.shortDramaSetOption(session.id, `${stage}.${key}`, value);
      }
      // 流式接收 SSE 推送的子 Agent 进度
      await api.shortDramaStepStream(
        session.id,
        stage,
        (msg) => {
          // 心跳消息：更新耗时和当前 agent，但不加入聊天消息列表
          if (msg.step === 'heartbeat') {
            const elapsed = msg.payload?.elapsed ?? Math.floor((Date.now() - (get().streamStartedAt || Date.now())) / 1000);
            set({ streamElapsed: elapsed as number, currentAgent: msg.agent });
            return;
          }
          // 正常进度消息：追加到 streamMessages 并更新当前 agent
          set((s) => ({
            streamMessages: [...s.streamMessages, {
              role: msg.role || 'agent',
              content: msg.content,
              agent: msg.agent,
              ts: Date.now() / 1000,
            } as AgentMessage],
            currentAgent: msg.agent,
          }));
        },
        () => {
          // 流结束：拉取最新 session（SSE 不返回完整 session，需手动 hydrate）
          get().hydrateSession(session.id);
          // #13: 如果已有画布，增量同步本次阶段产出
          get().syncCanvas();
        },
        (err) => {
          set({ error: err || '步骤执行失败' });
        }
      );
    } catch (e: any) {
      set({ error: e.message || '步骤执行失败' });
    } finally {
      set({ loading: false, streaming: false, currentAgent: null, streamElapsed: 0, streamStartedAt: null });
    }
  },

  lockAssets: async () => {
    const { session, selectedChars, selectedScenes, stepOptions } = get();
    if (!session) return;
    if (session.locked_assets && session.locked_assets.length > 0) return;
    if (selectedChars.length === 0 && selectedScenes.length === 0) {
      set({ error: '请至少选择一个角色或场景进行锁定' });
      return;
    }
    set({ loading: true, error: null });
    try {
      const opts = stepOptions.asset || {};
      for (const [key, value] of Object.entries(opts)) {
        await api.shortDramaSetOption(session.id, `asset.${key}`, value as string);
      }
      const res = await api.shortDramaLockAssets(session.id, selectedChars, selectedScenes);
      const updated = res.session;
      set({ session: updated, currentStep: deriveStep(updated) });
      await get().runStep('production');
    } catch (e: any) {
      set({ error: e.message || '资产锁定失败' });
    } finally {
      set({ loading: false });
    }
  },

  finalize: async (canvasId) => {
    const { session, finalizedCanvasId } = get();
    if (!session) return null;
    // #13: 如果已有画布，自动传入 canvas_id 触发增量同步
    const effectiveCanvasId = canvasId || finalizedCanvasId || session?.finalized_canvas_id;
    set({ loading: true, error: null });
    try {
      const res = await api.shortDramaFinalize(session.id, effectiveCanvasId);
      const updated = res.session;
      set({
        session: updated,
        currentStep: deriveStep(updated),
        finalizedCanvasId: res.canvas_id,
      });
      return res.canvas_id;
    } catch (e: any) {
      set({ error: e.message || '生成画布失败' });
      return null;
    } finally {
      set({ loading: false });
    }
  },

  /** #13 增量同步会话数据到已有画布 */
  syncCanvas: async () => {
    const { session, finalizedCanvasId } = get();
    if (!session) return;
    const canvasId = finalizedCanvasId || session?.finalized_canvas_id;
    if (!canvasId) return; // 还没有画布，跳过
    try {
      const res = await api.syncSessionToCanvas(session.id, canvasId);
      // 静默成功，仅在控制台记录
      console.info('[syncCanvas] 已同步画布:', res);
    } catch (e: any) {
      // 同步失败不阻断主流程，仅记录警告
      console.warn('[syncCanvas] 同步失败:', e?.message || e);
    }
  },

  hydrateSession: async (sessionId) => {
    set({ loading: true, error: null });
    try {
      const res = await api.getShortDramaSession(sessionId);
      const updated = res.session;
      set({
        session: updated,
        currentStep: deriveStep(updated),
        selectedChars: (updated.locked_assets || []).filter((a) => a.type === 'character').map((a) => a.char_id),
        selectedScenes: (updated.locked_assets || []).filter((a) => a.type === 'scene').map((a) => a.scene_id),
        stepOptions: updated.options ? mergeOptionsWithDefaults(updated.options as Record<string, string>) : JSON.parse(JSON.stringify(DEFAULT_STEP_OPTIONS)),
        parameterPending: updated.parameter_pending ?? (
          (updated.status === 'created' || updated.status === 'script_ready') &&
          !updated.script_outline &&
          !updated.script
        ),
        globalParams: updated.global_params ?? {},
        // #13: 恢复画布关联 ID
        finalizedCanvasId: updated.finalized_canvas_id || updated.one_click_canvas_id || null,
      });
    } catch (e: any) {
      set({ error: e.message || '加载会话失败' });
    } finally {
      set({ loading: false });
    }
    // #7 持久化恢复的 session ID
    get().saveSessionId();
  },

  // ==================== 一键模式 ====================

  setAgentMode: (mode) => set({ agentMode: mode }),

  chooseAgentMode: (mode) => set({ agentMode: mode, modeChosen: true }),

  backToAgentSelector: () => set({
    modeChosen: false,
    oneClickRunning: false,
    oneClickProgress: 0,
    oneClickStage: null,
    oneClickMessages: [],
    oneClickCanvasId: null,
    session: null,
    currentStep: INITIAL_STEP,
    error: null,
  }),

  oneClickStart: async (prompt, mode = 'inspiration', scriptText) => {
    const { selectedLlmModel } = get();
    set({ oneClickRunning: true, oneClickProgress: 0, oneClickStage: null, oneClickMessages: [], oneClickCanvasId: null, error: null });
    try {
      const res = await api.oneClickStart(prompt, mode, scriptText, selectedLlmModel ?? undefined);
      set({ session: res.session });
      // 流式接收 SSE
      await api.oneClickStream(
        res.session_id,
        (msg) => {
          if (msg.step === 'heartbeat') {
            // 心跳：不加入消息列表，仅更新当前阶段
            const stage = msg.payload?.agent as string | undefined;
            set((s) => ({
              oneClickStage: stage || s.oneClickStage,
            }));
            return;
          }
          // 正常消息
          const progress = msg.payload?.overall_progress as number | undefined;
          const stage = msg.payload?.current_stage as string | undefined;
          set((s) => ({
            oneClickMessages: [...s.oneClickMessages, {
              role: msg.role || 'system',
              content: msg.content,
              agent: msg.agent,
              step: msg.step,
              ts: Date.now() / 1000,
            } as AgentMessage],
            oneClickProgress: progress ?? s.oneClickProgress,
            oneClickStage: stage ?? s.oneClickStage,
          }));
        },
        (canvasId) => {
          set({ oneClickRunning: false, oneClickProgress: 100, oneClickCanvasId: canvasId ?? null });
          if (canvasId) {
            get().hydrateSession(res.session_id);
          }
        },
        (err) => {
          set({ oneClickRunning: false, error: err });
        }
      );
    } catch (e: any) {
      set({ oneClickRunning: false, error: e.message || '一键启动失败' });
    }
  },

  oneClickReset: () => {
    set({
      oneClickRunning: false,
      oneClickProgress: 0,
      oneClickStage: null,
      oneClickMessages: [],
      oneClickCanvasId: null,
      modeChosen: false,
      session: null,
      currentStep: INITIAL_STEP,
      error: null,
    });
  },
}));

function mergeOptionsWithDefaults(serverOptions: Record<string, string>): Record<AgentStepKey, StepOptionMap> {
  const merged = JSON.parse(JSON.stringify(DEFAULT_STEP_OPTIONS));
  for (const [key, value] of Object.entries(serverOptions)) {
    const [step, ...rest] = key.split('.');
    if (step && rest.length > 0 && step in merged) {
      merged[step as AgentStepKey][rest.join('.')] = value;
    }
  }
  return merged;
}

export const AGENT_STEPS: { key: AgentStepKey; label: string; desc: string }[] = [
  { key: 'start', label: '开始', desc: '输入灵感或上传剧本' },
  { key: 'planning', label: '前期策划', desc: '剧本 + 编剧' },
  { key: 'asset', label: '资产设定', desc: '角色 + 场景道具' },
  { key: 'production', label: '拍摄制作', desc: '分镜 + 视频' },
  { key: 'finalized', label: '完成', desc: '创建画布' },
];

export const STEP_OPTION_DEFINITIONS: Record<AgentStepKey, { id: string; label: string; choices: string[] }[]> = {
  start: [
    { id: 'visual_style', label: '视觉风格', choices: ['电影写实', '日系二次元', '古风国画', '赛博朋克', '复古港风', '悬疑暗黑', '甜宠清新', '史诗奇幻', '纪录真实', '商业广告'] },
    { id: 'episode_count', label: '集数', choices: ['1集', '3集', '5集', '10集'] },
    { id: 'duration_per_episode', label: '每集时长', choices: ['60-90秒', '90-120秒', '120-180秒'] },
    { id: 'tone', label: '情绪基调', choices: ['轻松', '紧张', '悬疑', '热血', '甜宠', '悲情', '励志', '恐怖', '喜剧', '温情'] },
    { id: 'target_platform', label: '投放平台', choices: ['抖音', '快手', '腾讯', 'B站', '小红书', 'YouTube Shorts', 'TikTok'] },
    { id: 'pacing', label: '叙事节奏', choices: ['快节奏', '中节奏', '慢节奏'] },
    { id: 'conflict_intensity', label: '冲突强度', choices: ['强冲突', '中等', '弱冲突'] },
    { id: 'protagonist_type', label: '主角类型', choices: ['逆袭男主', '大女主', '双强', '群像', '反派主角', '成长型'] },
    { id: 'ending_type', label: '结尾方式', choices: ['悬念收尾', '圆满结局', '开放式', '反转打脸', '情绪爆发'] },
    { id: 'dialogue_density', label: '台词密度', choices: ['台词密集', '动作戏为主', '平衡'] },
  ],
  planning: [
    { id: 'visual_style', label: '视觉风格', choices: ['电影写实', '日系二次元', '古风国画', '赛博朋克', '复古港风', '悬疑暗黑', '甜宠清新', '史诗奇幻', '纪录真实', '商业广告'] },
    { id: 'episode_count', label: '集数', choices: ['1集', '3集', '5集', '10集'] },
    { id: 'duration_per_episode', label: '每集时长', choices: ['60-90秒', '90-120秒', '120-180秒'] },
    { id: 'tone', label: '情绪基调', choices: ['轻松', '紧张', '悬疑', '热血', '甜宠', '悲情', '励志', '恐怖', '喜剧', '温情'] },
    { id: 'target_platform', label: '投放平台', choices: ['抖音', '快手', '腾讯', 'B站', '小红书', 'YouTube Shorts', 'TikTok'] },
    { id: 'pacing', label: '叙事节奏', choices: ['快节奏', '中节奏', '慢节奏'] },
    { id: 'conflict_intensity', label: '冲突强度', choices: ['强冲突', '中等', '弱冲突'] },
    { id: 'protagonist_type', label: '主角类型', choices: ['逆袭男主', '大女主', '双强', '群像', '反派主角', '成长型'] },
    { id: 'ending_type', label: '结尾方式', choices: ['悬念收尾', '圆满结局', '开放式', '反转打脸', '情绪爆发'] },
    { id: 'dialogue_density', label: '台词密度', choices: ['台词密集', '动作戏为主', '平衡'] },
    { id: 'scene_structure', label: '分场结构', choices: ['三幕式', '多幕式', '线性叙事', '非线性', '环形结构'] },
    { id: 'dialogue_style', label: '台词风格', choices: ['口语化', '书面化', '诗意', '方言', '网络梗'] },
    { id: 'action_density', label: '动作密度', choices: ['高密度', '中等', '低密度'] },
    { id: 'emotion_arc', label: '情绪曲线', choices: ['递进式', '波浪式', '断崖式', '平稳'] },
    { id: 'cliffhanger', label: '悬念强度', choices: ['强悬念', '中等', '弱悬念', '无悬念'] },
  ],
  asset: [
    { id: 'character_style', label: '角色画风', choices: ['写实', '二次元', '3D', '国风', '欧美', 'Q版', '水墨', '像素', '美漫', '迪士尼'] },
    { id: 'image_model', label: '生图模型', choices: ['gpt-image-2', 'gemini-3.1-flash-lite-image', 'doubao-seedream-5-0-pro-260628'] },
    { id: 'aspect_ratio', label: '画面比例', choices: ['1:1', '9:16', '16:9', '3:4', '4:3'] },
    { id: 'detail_level', label: '细节程度', choices: ['超高细节', '平衡', '风格化', '极简', '梦幻虚化'] },
    { id: 'background_purity', label: '背景处理', choices: ['纯白底', '透明', '环境融合', '纯色渐变', '景深虚化'] },
    { id: 'expression_intensity', label: '表情强度', choices: ['夸张', '自然', '内敛', '戏剧化', '无表情'] },
    { id: 'costume_detail', label: '服装复杂度', choices: ['华丽', '日常', '简约', '未来感', '古装繁复'] },
    { id: 'scene_style', label: '场景画风', choices: ['写实', '概念艺术', '微缩模型', '水墨', '油画', '赛博朋克', '哥特', '极简', '梦幻', '废土'] },
    { id: 'color_scheme', label: '色彩倾向', choices: ['冷调', '暖调', '高对比', '低饱和', '霓虹', '黑白', '电影青橙', 'Pastel'] },
    { id: 'lighting', label: '光影风格', choices: ['自然光', '戏剧光', '霓虹光', '柔光', '逆光', '顶光', '伦勃朗光', '剪影', '雾光', '黄昏金'] },
  ],
  production: [
    { id: 'shot_language', label: '镜头语言', choices: ['电影感', '短视频', '纪录片', '广告', 'MV', '惊悚', '浪漫', '武侠', '科幻', '生活流'] },
    { id: 'camera_movement_preference', label: '运镜偏好', choices: ['稳', '动感', '环绕', '手持', '航拍', '一镜到底', '快切', '推轨', '斯坦尼康', '固定长镜'] },
    { id: 'cut_speed', label: '剪辑速度', choices: ['快剪', '中速', '长镜头'] },
    { id: 'storyboard_density', label: '分镜密度', choices: ['每场景1镜', '2-3镜', '多镜'] },
    { id: 'emotional_focus', label: '情绪焦点', choices: ['facial', '身体语言', '环境', '道具', '群像', '眼神', '手部', '脚步', '背影', '空镜'] },
    { id: 'continuity_strictness', label: '连续性', choices: ['严格连续', '宽松'] },
    { id: 'video_model', label: '视频模型', choices: ['Seedance', 'Wan2.7', 'Vidu Q3 Turbo'] },
    { id: 'video_duration', label: '单镜时长', choices: ['3秒', '5秒', '8秒'] },
    { id: 'video_ratio', label: '视频比例', choices: ['9:16', '16:9', '1:1', '3:4'] },
    { id: 'video_quality', label: '视频质量', choices: ['高质量', '快速'] },
    { id: 'generate_audio', label: '生成音频', choices: ['有声音', '无声音'] },
    { id: 'watermark', label: '水印', choices: ['无水印', '有水印'] },
    { id: 'resolution', label: '分辨率', choices: ['1080p', '720p', '480p'] },
    { id: 'fps', label: '帧率', choices: ['30fps', '24fps', '60fps'] },
    { id: 'render_style', label: '渲染风格', choices: ['写实', '电影', '动画', '胶片', '数字'] },
    { id: 'motion_smoothness', label: '运动平滑度', choices: ['平滑', '自然抖动'] },
    { id: 'retry_policy', label: '失败重试', choices: ['自动重试', '人工确认'] },
    { id: 'output_format', label: '输出格式', choices: ['mp4', 'mov', 'webm'] },
    { id: 'qa_strictness', label: '质检严格度', choices: ['严格质检', '宽松'] },
  ],
  finalized: [],
};
