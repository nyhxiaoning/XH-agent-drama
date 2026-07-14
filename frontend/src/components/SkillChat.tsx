/**
 * SkillChat - 技能对话框组件（重构版 + 历史对话）
 *
 * 布局参考: ChatGPT / 豆包 / 即梦AI
 * - 左侧历史对话侧栏（数据库持久化）
 * - 顶部品牌渐变Header
 * - 居中对话流（加宽），空状态有引导卡片
 * - 参数面板改为折叠chips + 浮层弹窗
 * - 底部输入区带工具栏、字符计数
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Send, Sparkles,
  Loader2, Copy, Check, RotateCcw, Settings2, Brain, User,
  X, Plus, MessageSquare, Trash2, PanelLeftClose, PanelLeftOpen,
  type LucideIcon,
} from 'lucide-react';
import { api, skillConversationsApi } from '@/utils/api';
import type { SkillConversationItem, SkillMessageItem } from '@/utils/api';
import type { BrainStreamMessage } from '@/types';
import { LlmModelSelector } from '@/components/AgentChat/Controls';
// #12 公共组件去重
import type { ChatMessage } from '@/components/chat/types';
import { useAutoScroll, TypingIndicator } from '@/components/chat';

// ─── 类型 ────────────────────────────────────────────
// #12 ChatMessage 类型已从 @/components/chat/types 导入

export interface SkillParamDef {
  name: string;
  type: 'text' | 'select';
  options?: string[];
  default?: string;
  required?: boolean;
}

export interface SkillDef {
  skill_id: string;
  title: string;
  desc: string;
  icon: string;
  params: SkillParamDef[];
}


// ─── 图标映射 ────────────────────────────────────────

import { BookOpen, Clapperboard, Video, Layers, Film, PenLine, Clapperboard as ClapperIcon, FileText, Feather } from 'lucide-react';

const ICON_MAP: Record<string, LucideIcon> = {
  BookOpen,
  Clapperboard,
  Video,
  Layers,
  Film,
  PenLine,
  ClapperIcon,
  FileText,
  Feather,
};

// 技能专属渐变色
const SKILL_GRADIENTS: Record<string, string> = {
  'novel-to-shortdrama-script': 'from-teal-600 to-cyan-600',
  'storyboard-lite': 'from-amber-500 to-rose-500',
  'drama-generator-pro': 'from-teal-600 to-emerald-600',
  'muzi-3d-generator': 'from-emerald-500 to-lime-500',
  'seedance-prompt-zh': 'from-orange-500 to-amber-500',
  'xyq-short-drama': 'from-violet-600 to-purple-600',
  'storyboard-director': 'from-fuchsia-500 to-pink-600',
  'script-video-prompt-architect': 'from-indigo-600 to-blue-600',
  'novel-director': 'from-rose-600 to-orange-600',
};

function getIcon(name: string): LucideIcon {
  return ICON_MAP[name] || Sparkles;
}

function getGradient(skillId: string): string {
  return SKILL_GRADIENTS[skillId] || 'from-teal-600 to-emerald-500';
}

// ─── 技能引导信息 ────────────────────────────────────

function getGuideSteps(skillId: string): { title: string; desc: string }[] {
  switch (skillId) {
    case 'novel-to-shortdrama-script':
      return [
        { title: '粘贴小说原文', desc: '在下方输入框中粘贴小说文本' },
        { title: '智能体调度', desc: '自动提取集数、题材等参数' },
        { title: '生成剧本', desc: '输出改编总纲、分集大纲、完整剧本' },
      ];
    case 'storyboard-lite':
      return [
        { title: '粘贴剧本文本', desc: '在下方输入框中粘贴剧本内容' },
        { title: '智能体调度', desc: '自动提取故事类型、美术风格' },
        { title: '生成分镜', desc: '输出分镜表和视频组提示词' },
      ];
    case 'drama-generator-pro':
      return [
        { title: '粘贴小说原文', desc: '选择动漫风格和改编程度' },
        { title: '智能体全流程执行', desc: '自动注入全局参数并执行' },
        { title: '完整漫剧素材', desc: '剧本+人物+场景+分镜+Excel' },
      ];
    case 'muzi-3d-generator':
      return [
        { title: '输入小说/剧本', desc: '选择3D风格和分镜段数' },
        { title: '3D漫剧流水线', desc: '智能体自动执行生成流程' },
        { title: '生图提示词', desc: '角色+场景生图提示词输出' },
      ];
    case 'seedance-prompt-zh':
      return [
        { title: '描述视频内容', desc: '选择场景类型和生成时长' },
        { title: '多模态提示词', desc: '可选填写已有素材说明' },
        { title: 'Seedance 2.0', desc: '生成可直接使用的视频提示词' },
      ];
    case 'xyq-short-drama':
      return [
        { title: '输入创意描述', desc: '一句话描述你的短剧创意想法' },
        { title: '选择题材参数', desc: '指定题材类型、集数、情感基调' },
        { title: '生成完整剧本', desc: '输出世界观、角色设定、分集剧本' },
      ];
    case 'storyboard-director':
      return [
        { title: '输入故事文本', desc: '粘贴小说/故事/剧本片段' },
        { title: '镜头语言分析', desc: '自动执行两轴查询与风险注入' },
        { title: '输出分镜台本', desc: '多宫格分镜板+视频提示词' },
      ];
    case 'script-video-prompt-architect':
      return [
        { title: '粘贴剧本原文', desc: '提交一集或片段的短剧剧本' },
        { title: '三阶段处理', desc: '剧本分析→分镜拆解→Seedance提示词' },
        { title: '输出视频提示词', desc: '逐镜头分镜脚本+Seedance 2.0提示词' },
      ];
    case 'novel-director':
      return [
        { title: '设定场景人物', desc: '输入场景、人物、冲突、氛围' },
        { title: 'AI分镜演绎', desc: 'AI演绎一段剧情，在决策点停下' },
        { title: '导演掌控走向', desc: '选择选项或自由输入，决定剧情方向' },
      ];
    default:
      return [
        { title: '输入内容', desc: '在下方输入框中输入内容' },
        { title: '智能体调度', desc: '自动分析需求并提取参数' },
        { title: '查看结果', desc: '实时显示执行进度和结果' },
      ];
  }
}

function getPlaceholder(skillId: string): string {
  switch (skillId) {
    case 'novel-to-shortdrama-script': return '在此粘贴小说原文...';
    case 'storyboard-lite': return '在此粘贴剧本文本...';
    case 'drama-generator-pro': return '在此粘贴小说原文，一键生成完整漫剧素材...';
    case 'muzi-3d-generator': return '在此输入小说片段或剧本，生成3D漫剧素材...';
    case 'seedance-prompt-zh': return '描述你想创作的视频内容、主题或创意...';
    case 'xyq-short-drama': return '输入一句话创意，如：快递小哥意外获得读心术...';
    case 'storyboard-director': return '粘贴故事/小说/剧本片段，生成分镜导演台本...';
    case 'script-video-prompt-architect': return '粘贴短剧剧本原文，生成分镜脚本和Seedance视频提示词...';
    case 'novel-director': return '【场景】深夜码头，暴雨\n【人物】陈Sir（退休刑警，谨慎念旧）\n【冲突】两人互相猜忌\n【氛围】港片 noir...';
    default: return '输入内容...';
  }
}

function getExamples(skillId: string): string[] {
  switch (skillId) {
    case 'novel-to-shortdrama-script':
      return ['落魄少年被豪门看不起，最后逆袭打脸', '女总裁隐婚三年，离婚后前夫悔不当初'];
    case 'storyboard-lite':
      return ['第一场 夜 皇宫大殿 林萧跪在金砖地上...', '外卖小哥意外获得超能力，化身守护者'];
    case 'drama-generator-pro':
      return ['落魄少年被豪门看不起，最后逆袭打脸', '庶女入宫步步为营，最终登上后位'];
    case 'muzi-3d-generator':
      return ['少年在魔法学院觉醒暗属性天赋', '机器人与人类少女的跨物种友谊'];
    case 'seedance-prompt-zh':
      return ['赛博朋克城市夜景中的飞行汽车', '古风女子在桃花林中翩翩起舞'];
    case 'xyq-short-drama':
      return ['快递小哥意外获得读心术，发现客户秘密', '考古队在古墓中发现活了千年的少女'];
    case 'storyboard-director':
      return ['雨夜破庙前，男主握长剑而立，黑衣人持刀逼近...', '咖啡店里两个陌生人的眼神交汇，时间仿佛静止'];
    case 'script-video-prompt-architect':
      return ['第一场 夜 皇宫偏院 灵汐手持灯笼穿行...', '男主在咖啡店偶遇前女友，两人尴尬对坐...'];
    case 'novel-director':
      return ['【场景】深夜码头，暴雨\n【人物】陈Sir（退休刑警）阿鬼（线人）\n【冲突】互相猜忌有无带人', '【场景】古寺黄昏\n【人物】少年剑客、神秘老僧\n【冲突】少年索要失落剑谱'];
    default:
      return ['试试输入你的创意...'];
  }
}

// ─── 技能结果渲染 ────────────────────────────────────

function extractMarkdown(result: any): string {
  if (!result) return '';
  return result.full_markdown ||
    result.prompt ||
    result.storyboard_markdown ||
    [result.adaptation_overview, result.episode_outline, result.full_script, result.video_groups_markdown]
      .filter(Boolean)
      .join('\n\n---\n\n') ||
    '';
}

function extractMeta(result: any): { title: string; summary: string; tags: string[] } {
  const title = result?.work_title || result?.title || result?.skill_name || '';
  const summary = result?.summary || result?.assumptions || '';
  const tags: string[] = [];
  if (Array.isArray(result?.characters)) {
    result.characters.slice(0, 6).forEach((c: any) => {
      tags.push(`${c.name}${c.role ? '·' + c.role : ''}`);
    });
  }
  if (Array.isArray(result?.assets)) {
    result.assets.slice(0, 6).forEach((a: any) => {
      tags.push(`${a.name}·${a.type}`);
    });
  }
  if (Array.isArray(result?.scenes)) {
    tags.push(`${result.scenes.length}个场景`);
  }
  if (Array.isArray(result?.storyboards) && result.storyboards.length > 0) {
    tags.push(`共${result.storyboards.length}个分镜`);
  }
  if (Array.isArray(result?.references) && result.references.length > 0) {
    tags.push(`${result.references.length}个素材引用`);
  }
  if (result?.excel_info?.file_name) {
    tags.push('Excel已生成');
  }
  return { title, summary, tags };
}

// ─── 时间格式化 ──────────────────────────────────────

function formatTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`;
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

// ─── 历史对话侧栏 ────────────────────────────────────

function HistorySidebar({
  conversations,
  activeId,
  loading: historyLoading,
  error,
  onSelect,
  onNew,
  onDelete,
  onClose,
}: {
  conversations: SkillConversationItem[];
  activeId: string | null;
  loading: boolean;
  error: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClose?: () => void;
}) {
  return (
    <div className="h-full flex flex-col bg-canvas-bg">
      {/* 侧栏头部 */}
      <div className="p-3 border-b border-panel-border/50 flex items-center gap-2 shrink-0">
        <button
          onClick={onNew}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-gradient-to-r from-teal-600 to-emerald-500 text-white text-xs font-medium shadow-soft hover:brightness-110 transition-all"
        >
          <Plus size={14} /> 新对话
        </button>
        {onClose && (
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors lg:hidden"
            title="收起侧栏"
          >
            <PanelLeftClose size={15} />
          </button>
        )}
      </div>

      {/* 对话列表 */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {historyLoading ? (
          <div className="flex items-center justify-center py-8 text-theme-hint text-xs">
            <Loader2 size={14} className="animate-spin mr-1" /> 加载中...
          </div>
        ) : error ? (
          <div className="text-center py-6 px-3 text-xs leading-relaxed">
            <div className="text-error font-medium mb-1">⚠ 历史记录加载失败</div>
            <div className="text-theme-hint">{error}</div>
            <div className="text-theme-hint mt-2">请确认后端服务已启动</div>
          </div>
        ) : conversations.length === 0 ? (
          <div className="text-center py-8 text-theme-hint text-xs leading-relaxed">
            <MessageSquare size={20} className="mx-auto mb-2 opacity-40" />
            暂无历史对话
          </div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => onSelect(conv.id)}
              className={`group flex items-start gap-2 px-3 py-2.5 rounded-xl cursor-pointer transition-all ${
                activeId === conv.id
                  ? 'bg-teal-600/10 border border-teal-600/20'
                  : 'hover:bg-panel-hover border border-transparent'
              }`}
            >
              <MessageSquare size={13} className={`mt-0.5 shrink-0 ${activeId === conv.id ? 'text-teal-600' : 'text-theme-hint'}`} />
              <div className="flex-1 min-w-0">
                <div className={`text-xs font-medium truncate ${activeId === conv.id ? 'text-teal-600' : 'text-theme-main'}`}>
                  {conv.title || '新对话'}
                </div>
                <div className="text-[10px] text-theme-hint mt-0.5 flex items-center gap-1">
                  <span>{formatTime(conv.updated_at)}</span>
                  {conv.message_count > 0 && <span>· {conv.message_count}条</span>}
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(conv.id);
                }}
                className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded-lg flex items-center justify-center text-theme-hint hover:text-error hover:bg-error/10 transition-all shrink-0"
                title="删除对话"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────

interface SkillChatProps {
  skill: SkillDef;
  page?: boolean;
}

export function SkillChat({ skill, page }: SkillChatProps) {
  const navigate = useNavigate();
  const Icon = getIcon(skill.icon);
  const gradient = getGradient(skill.skill_id);
  const guideSteps = getGuideSteps(skill.skill_id);
  const examples = getExamples(skill.skill_id);
  const placeholder = getPlaceholder(skill.skill_id);

  // 参数状态
  const [params, setParams] = useState<Record<string, string>>(() => {
    const defaults: Record<string, string> = {};
    for (const p of skill.params) {
      defaults[p.name] = p.default ?? '';
    }
    return defaults;
  });
  const [showParamPanel, setShowParamPanel] = useState(false);
  const [llmModel, setLlmModel] = useState<string | null>(null);

  // 消息状态
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [progressText, setProgressText] = useState('');

  // 历史对话状态
  const [conversations, setConversations] = useState<SkillConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true); // 默认展开

  // 滚动（#12 使用公共 useAutoScroll）
  const scrollRef = useAutoScroll([messages, loading, progressText]);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const paramPanelRef = useRef<HTMLDivElement>(null);

  // ─── 加载历史对话列表 ───────────────────────────────
  const [historyError, setHistoryError] = useState<string | null>(null);
  const loadConversations = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = await skillConversationsApi.list(skill.skill_id);
      setConversations(res.conversations || []);
    } catch (err: any) {
      console.error('[SkillChat] 加载历史对话失败:', err);
      setHistoryError(err?.message || '加载历史对话失败');
    } finally {
      setHistoryLoading(false);
    }
  }, [skill.skill_id]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // 点击外部关闭参数浮层
  useEffect(() => {
    if (!showParamPanel) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (paramPanelRef.current && !paramPanelRef.current.contains(e.target as Node)) {
        setShowParamPanel(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showParamPanel]);

  // textarea 自适应高度
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(160, Math.max(56, el.scrollHeight))}px`;
  }, [input]);

  const handleParamChange = (name: string, value: string) => {
    setParams((prev) => ({ ...prev, [name]: value }));
  };

  // ─── 确保有 conversation（没有则创建） ─────────────
  const ensureConversation = async (userText: string): Promise<string | null> => {
    if (activeConversationId) return activeConversationId;
    try {
      const res = await skillConversationsApi.create(skill.skill_id, skill.title, params);
      const newId = res.conversation.id;
      setActiveConversationId(newId);
      // 刷新列表
      loadConversations();
      return newId;
    } catch (err: any) {
      console.error('[SkillChat] 创建对话失败:', err);
      setHistoryError(err?.message || '创建对话失败，历史记录将不会被保存');
      return null;
    }
  };

  // ─── 保存消息到后端 ─────────────────────────────────
  const saveMessage = async (convId: string, role: string, content: string, rawData?: any) => {
    try {
      await skillConversationsApi.appendMessage(convId, role, content, rawData, params);
      loadConversations(); // 刷新列表中的消息计数和时间
    } catch (err: any) {
      console.error('[SkillChat] 保存消息失败:', err);
    }
  };

  const handleSend = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || loading) return;

    // 确保有 conversation
    const convId = await ensureConversation(text);

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setProgressText('智能分析您的需求...');

    // 保存用户消息（必须 await，确保后端加载历史时能读到当前消息）
    if (convId) await saveMessage(convId, 'user', text);

    const progressId = `p-${Date.now()}`;
    setMessages((prev) => [...prev, {
      id: progressId,
      role: 'progress',
      content: '智能分析您的需求...',
      timestamp: Date.now(),
    }]);

    abortRef.current = new AbortController();

    try {
      let finalData: any = null;

await api.runSkillStream(
skill.skill_id,
text,
params,
undefined,
(msg: BrainStreamMessage) => {
// #1 根据消息类型更新进度展示
if (msg.type === 'param_extraction_thinking') {
// 流式参数提取 token：逐字追加
setProgressText((prev) => prev + msg.content);
} else if (msg.content) {
setProgressText(msg.content);
}
setMessages((prev) => prev.map(m =>
m.id === progressId
? { ...m, content: msg.type === 'param_extraction_thinking' ? (msg.content ? (m.content + msg.content) : m.content) : msg.content }
: m
));
if (msg.type === 'skill_done' && msg.data) {
finalData = msg.data;
}
if (msg.type === 'complete' && msg.data) {
finalData = msg.data;
}
},
        (data) => {
          finalData = finalData || data;
          const md = extractMarkdown(finalData);
          const assistantMsg: ChatMessage = {
            id: `a-${Date.now()}`,
            role: 'assistant',
            content: md || JSON.stringify(finalData, null, 2),
            rawData: finalData,
            timestamp: Date.now(),
          };
          setMessages((prev) => [
            ...prev.filter(m => m.id !== progressId),
            assistantMsg,
          ]);
          // 保存AI回复
          if (convId) saveMessage(convId, 'assistant', md || JSON.stringify(finalData, null, 2), finalData);
        },
        (err) => {
          setMessages((prev) => [
            ...prev.filter(m => m.id !== progressId),
            {
              id: `e-${Date.now()}`,
              role: 'error',
              content: err || '技能执行失败，请重试',
              timestamp: Date.now(),
            },
          ]);
          if (convId) saveMessage(convId, 'error', err || '技能执行失败，请重试');
        },
        abortRef.current.signal,
        undefined,
        undefined,
        convId || undefined,
        llmModel || undefined,
      );
    } catch (err: any) {
      setMessages((prev) => [
        ...prev.filter(m => m.id !== progressId),
        {
          id: `e-${Date.now()}`,
          role: 'error',
          content: err?.message || '技能执行失败，请重试',
          timestamp: Date.now(),
        },
      ]);
      if (convId) saveMessage(convId, 'error', err?.message || '技能执行失败，请重试');
    } finally {
      setLoading(false);
      setProgressText('');
      abortRef.current = null;
    }
  }, [input, loading, skill.skill_id, params, activeConversationId]);

  // ─── 重新生成：使用上一条用户消息重新发送 ───────────────
  const handleRetry = useCallback(() => {
    if (loading) return;
    // 从消息列表中找到最后一条用户消息
    const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
    if (!lastUserMsg) return;
    handleSend(lastUserMsg.content);
  }, [messages, loading, handleSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ─── 新建对话 ───────────────────────────────────────
  const handleNewChat = () => {
    setMessages([]);
    setActiveConversationId(null);
    setInput('');
    setProgressText('');
    inputRef.current?.focus();
  };

  // ─── 加载历史对话 ───────────────────────────────────
  const handleSelectConversation = async (convId: string) => {
    if (loading) return;
    setActiveConversationId(convId);
    setMessages([]);
    try {
      const res = await skillConversationsApi.get(convId);
      const restored: ChatMessage[] = (res.messages || [])
        .filter((m: SkillMessageItem) => m.role !== 'progress')
        .map((m: SkillMessageItem) => ({
          id: m.id,
          role: m.role as ChatMessage['role'],
          content: m.content,
          rawData: m.raw_data,
          timestamp: new Date(m.created_at || '').getTime() || Date.now(),
        }));
      setMessages(restored);
      // 恢复参数
      if (res.conversation?.params) {
        setParams((prev) => ({ ...prev, ...(res.conversation.params as Record<string, string>) }));
      }
    } catch (err: any) {
      console.error('[SkillChat] 加载对话详情失败:', err);
    }
  };

  // ─── 删除对话 ───────────────────────────────────────
  const handleDeleteConversation = async (convId: string) => {
    try {
      await skillConversationsApi.delete(convId);
      if (activeConversationId === convId) {
        handleNewChat();
      }
      loadConversations();
    } catch (err: any) {
      console.error('[SkillChat] 删除对话失败:', err);
    }
  };

  const handleCopy = (text: string) => {
    try {
      navigator.clipboard?.writeText(text);
    } catch {}
  };

  const handleStop = () => {
    abortRef.current?.abort();
    setLoading(false);
    setProgressText('');
  };

  const handleExampleClick = (example: string) => {
    setInput(example);
    inputRef.current?.focus();
  };

  // ─── 参数chips（折叠态） ───────────────────────────
  const paramChips = skill.params.map((p) => ({
    name: p.name,
    value: params[p.name] || p.default || '',
  })).filter(c => c.value);

  // ─── 渲染 ──────────────────────────────────────────

  const header = (
    <div className="h-14 border-b border-panel-border flex items-center justify-between px-4 shrink-0 bg-panel-bg">
      <div className="flex items-center gap-3 min-w-0">
        {!sidebarOpen && (
          <button
            onClick={() => setSidebarOpen(true)}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors shrink-0"
            title="展开历史"
          >
            <PanelLeftOpen size={16} />
          </button>
        )}
        <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${gradient} flex items-center justify-center shadow-soft shrink-0`}>
          <Icon size={18} className="text-white" />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-theme-main truncate">{skill.title}</h2>
          <p className="text-xs text-theme-sub truncate">{skill.desc}</p>
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <div className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-teal-600/10 text-teal-600 text-xs font-medium">
          <Brain size={12} className="animate-pulse" />
          <span>智能体调度</span>
        </div>
        {messages.length > 0 && (
          <button
            className="w-8 h-8 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors"
            onClick={handleNewChat}
            title="新对话"
          >
            <Plus size={16} />
          </button>
        )}
        <button
          className="w-8 h-8 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors"
          onClick={() => navigate('/home')}
          title="返回首页"
        >
          <ArrowLeft size={16} />
        </button>
      </div>
    </div>
  );

  const messagesArea = (
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-6 space-y-5">
        {messages.length === 0 && (
          /* ─── 空状态：引导卡片 + 示例 ─── */
          <div className="pt-6 pb-4 text-center animate-fade-up">
            {/* 大渐变图标 */}
            <div className={`w-16 h-16 rounded-2xl bg-gradient-to-br ${gradient} flex items-center justify-center shadow-soft-lg mx-auto mb-4`}>
              <Icon size={30} className="text-white" />
            </div>
            <h3 className="text-xl font-bold text-theme-main mb-1.5">{skill.title}</h3>
            <p className="text-sm text-theme-sub mb-6 max-w-md mx-auto">{skill.desc}</p>

            {/* 引导步骤卡片 */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-2xl mx-auto mb-6">
              {guideSteps.map((step, i) => (
                <div key={i} className="glass rounded-2xl border border-panel-border p-4 text-left hover:shadow-soft transition-all hover:-translate-y-0.5">
                  <div className="flex items-center gap-2 mb-2">
                    <div className={`w-6 h-6 rounded-lg bg-gradient-to-br ${gradient} flex items-center justify-center text-white text-xs font-bold shrink-0`}>
                      {i + 1}
                    </div>
                    <span className="text-xs font-semibold text-theme-main">{step.title}</span>
                  </div>
                  <p className="text-xs text-theme-sub leading-relaxed">{step.desc}</p>
                </div>
              ))}
            </div>

            {/* 智能体调度标识 */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-teal-600/8 border border-teal-600/20 text-xs text-teal-600 font-medium mb-6">
              <Brain size={12} />
              由 PlatformBrain 智能体调度执行
            </div>

            {/* 示例提示词 */}
            {examples.length > 0 && (
              <div className="max-w-xl mx-auto">
                <div className="text-xs text-theme-hint mb-2">试试这些示例：</div>
                <div className="flex flex-wrap gap-2 justify-center">
                  {examples.map((ex) => (
                    <button
                      key={ex}
                      onClick={() => handleExampleClick(ex)}
                      className="px-3 py-1.5 rounded-xl text-xs text-theme-sub border border-panel-border bg-panel-bg hover:border-teal-600/30 hover:bg-teal-600/5 hover:text-teal-600 transition-all"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} onCopy={handleCopy} onRetry={handleRetry} gradient={gradient} />
        ))}

        {loading && progressText && (
          <div className="flex items-start gap-3 animate-fade-in">
            <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${gradient} shadow-soft`}>
              <Brain size={15} className="text-white animate-pulse" />
            </div>
            <div className="flex items-center gap-2.5 rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border px-4 py-3 shadow-soft">
              <TypingIndicator />
              <span className="text-sm text-theme-sub">{progressText}</span>
              <button
                onClick={handleStop}
                className="ml-1 text-xs text-error hover:underline"
              >
                取消
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );

  // ─── 参数浮层 ──────────────────────────────────────
  const paramOverlay = showParamPanel && (
    <div
      ref={paramPanelRef}
      className="absolute bottom-full left-0 right-0 mb-2 glass rounded-2xl border border-panel-border shadow-soft-lg p-4 animate-panel-slide z-50"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-theme-main flex items-center gap-1.5">
          <Settings2 size={14} className="text-teal-600" />
          技能参数
        </span>
        <button
          className="w-6 h-6 rounded-lg flex items-center justify-center text-theme-hint hover:text-theme-main hover:bg-panel-hover transition-colors"
          onClick={() => setShowParamPanel(false)}
        >
          <X size={14} />
        </button>
      </div>
      <div className="space-y-4">
        {/* LLM 模型选择 */}
        <LlmModelSelector selected={llmModel} onSelect={setLlmModel} />
        {skill.params.map((p) => (
          <div key={p.name}>
            <label className="text-xs font-medium text-theme-sub mb-2 block">{p.name}</label>
            {p.type === 'select' && p.options ? (
              <div className="flex flex-wrap gap-1.5">
                {p.options.map((opt) => (
                  <button
                    key={opt}
                    onClick={() => handleParamChange(p.name, opt)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                      (params[p.name] || p.default) === opt
                        ? 'bg-teal-600 text-white shadow-soft'
                        : 'bg-canvas-bg text-theme-sub border border-panel-border hover:border-teal-600/30 hover:text-teal-600'
                    }`}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            ) : (
              <input
                type="text"
                value={params[p.name] || ''}
                onChange={(e) => handleParamChange(p.name, e.target.value)}
                placeholder={`请输入${p.name}`}
                className="w-full h-9 px-3 rounded-xl bg-theme-input text-sm text-theme-main border border-panel-border focus:outline-none focus:border-teal-600/50 transition-colors"
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );

  const inputArea = (
    <div className="border-t border-panel-border bg-panel-bg px-4 py-3 shrink-0">
      <div className="max-w-4xl mx-auto relative">
        {paramOverlay}
        {/* 参数chips行 */}
        {(paramChips.length > 0 || llmModel) && (
          <div className="flex items-center gap-1.5 mb-2 flex-wrap">
            {llmModel && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-teal-600/8 border border-teal-600/20 text-xs text-teal-600">
                <span className="text-teal-600/60">模型:</span>
                <span className="font-medium">{llmModel}</span>
              </span>
            )}
            {paramChips.map((chip) => (
              <span key={chip.name} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-canvas-bg border border-panel-border text-xs text-theme-sub">
                <span className="text-theme-hint">{chip.name}:</span>
                <span className="text-theme-main font-medium">{chip.value}</span>
              </span>
            ))}
          </div>
        )}
        {/* 输入容器 */}
        <div className="glass rounded-2xl border border-panel-border shadow-soft overflow-hidden">
          <textarea
            ref={inputRef}
            className="w-full bg-transparent text-theme-main placeholder:text-theme-hint resize-none outline-none text-sm leading-relaxed min-h-[56px] max-h-[160px] px-4 pt-3 pb-1"
            placeholder={placeholder}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
          />
          <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowParamPanel(v => !v)}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs transition-colors ${
                  showParamPanel
                    ? 'bg-teal-600/10 text-teal-600 border border-teal-600/20'
                    : 'text-theme-sub hover:text-theme-main hover:bg-panel-hover border border-transparent'
                }`}
                title="参数设置"
              >
                <Settings2 size={13} />
                <span className="hidden sm:inline">参数</span>
              </button>
              <span className="text-xs text-theme-hint hidden sm:inline">
                Enter 发送 · Shift+Enter 换行
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-theme-hint tabular-nums">{input.length}</span>
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || loading}
                className={`w-9 h-9 rounded-xl flex items-center justify-center text-white transition-all active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed bg-gradient-to-br ${gradient} shadow-soft hover:brightness-110`}
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  // ─── 主布局：左侧历史 + 右侧对话 ────────────────────
  const mainLayout = (
    <div className="flex-1 flex overflow-hidden">
      {/* 历史侧栏 */}
      {sidebarOpen && (
        <>
          <div className="w-[260px] shrink-0 border-r border-panel-border hidden lg:block">
            <HistorySidebar
              conversations={conversations}
              activeId={activeConversationId}
              loading={historyLoading}
              error={historyError}
              onSelect={handleSelectConversation}
              onNew={handleNewChat}
              onDelete={handleDeleteConversation}
              onClose={() => setSidebarOpen(false)}
            />
          </div>
          {/* 移动端抽屉 */}
          <div className="lg:hidden fixed inset-0 z-[200] bg-black/30" onClick={() => setSidebarOpen(false)}>
            <div className="w-[280px] h-full bg-panel-bg" onClick={(e) => e.stopPropagation()}>
              <HistorySidebar
                conversations={conversations}
                activeId={activeConversationId}
                loading={historyLoading}
                error={historyError}
                onSelect={(id) => { handleSelectConversation(id); setSidebarOpen(false); }}
                onNew={() => { handleNewChat(); setSidebarOpen(false); }}
                onDelete={handleDeleteConversation}
                onClose={() => setSidebarOpen(false)}
              />
            </div>
          </div>
        </>
      )}
      {/* 对话区 */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {messagesArea}
        {inputArea}
      </div>
    </div>
  );

  const body = (
    <>
      {header}
      {mainLayout}
    </>
  );

  if (page) {
    return (
      <div className="h-screen w-screen bg-canvas-bg flex flex-col overflow-hidden">
        <div className="flex-1 glass rounded-none border-0 shadow-none flex flex-col overflow-hidden">
          {body}
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-6xl h-[85vh] glass rounded-3xl border border-panel-border shadow-soft-lg flex flex-col overflow-hidden">
        {body}
      </div>
    </div>
  );
}

// ─── 消息气泡 ────────────────────────────────────────

function MessageBubble({ msg, onCopy, onRetry, gradient }: {
  msg: ChatMessage;
  onCopy: (text: string) => void;
  onRetry: () => void;
  gradient: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    onCopy(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // ── 用户消息 ──
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end items-start gap-2.5 animate-fade-up">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-teal-600/8 border border-teal-600/15 px-4 py-2.5">
          <div className="text-sm text-theme-main whitespace-pre-wrap break-words leading-relaxed">{msg.content}</div>
        </div>
        <div className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-teal-600/10 border border-teal-600/20">
          <User size={15} className="text-teal-600" />
        </div>
      </div>
    );
  }

  // ── 进度消息 ──
  if (msg.role === 'progress') {
    return (
      <div className="flex justify-start items-start gap-2.5 animate-fade-in">
        <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${gradient} shadow-soft`}>
          <Brain size={15} className="text-white animate-pulse" />
        </div>
        <div className="flex items-center gap-2.5 rounded-2xl rounded-tl-sm bg-teal-600/5 border border-teal-600/15 px-4 py-3">
          <TypingIndicator />
          <span className="text-sm text-theme-sub">{msg.content}</span>
        </div>
      </div>
    );
  }

  // ── 错误消息 ──
  if (msg.role === 'error') {
    return (
      <div className="flex justify-start items-start gap-2.5 animate-fade-up">
        <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${gradient} shadow-soft`}>
          <Brain size={15} className="text-white" />
        </div>
        <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-error/8 border border-error/25 px-4 py-3">
          <div className="text-xs text-error font-semibold mb-1">执行失败</div>
          <div className="text-sm text-error/80 whitespace-pre-wrap break-words leading-relaxed">{msg.content}</div>
          <button
            onClick={onRetry}
            className="mt-2 text-xs text-teal-600 hover:underline flex items-center gap-1 font-medium"
          >
            <RotateCcw size={12} /> 重试
          </button>
        </div>
      </div>
    );
  }

  // ── AI 回复消息 ──
  const meta = extractMeta(msg.rawData);

  return (
    <div className="flex justify-start items-start gap-2.5 animate-fade-up">
      <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${gradient} shadow-soft`}>
        <Brain size={15} className="text-white" />
      </div>

      <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border shadow-soft overflow-hidden">
        {/* 头部标识 */}
        <div className="flex items-center gap-1.5 px-4 pt-3 pb-2 text-xs text-teal-600">
          <Brain size={12} />
          <span className="font-medium">智能体调度完成</span>
        </div>

        <div className="px-4 pb-3 space-y-2.5">
          {/* 元信息 */}
          {meta.title && (
            <div className="text-sm font-bold text-theme-main">{meta.title}</div>
          )}
          {meta.summary && (
            <div className="text-xs text-theme-sub leading-relaxed">{meta.summary}</div>
          )}
          {meta.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {meta.tags.map((tag, i) => (
                <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-canvas-bg border border-panel-border text-theme-sub">
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* 主内容 */}
          <div className="rounded-xl bg-canvas-bg/50 border border-panel-border/40 p-3 max-h-[500px] overflow-y-auto">
            <div className="chat-content">{msg.content}</div>
          </div>

          {/* 操作栏 */}
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={handleCopy}
              className="text-xs text-theme-sub hover:text-teal-600 flex items-center gap-1 transition-colors"
            >
              {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
              {copied ? '已复制' : '复制'}
            </button>
            <button
              onClick={onRetry}
              className="text-xs text-theme-sub hover:text-teal-600 flex items-center gap-1 transition-colors"
            >
              <RotateCcw size={12} />
              重新生成
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
