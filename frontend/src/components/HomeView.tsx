import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Home, PlusSquare, BarChart2, FolderKanban, Image, Wrench,
  Feather, Send, Sparkles, Clapperboard, Brain,
  ChevronRight, FolderOpen, User,
  FilePlus, Upload, Search, Package, Film, BookOpen, Wand2,
  Palette, MapPin, Music, Loader2, Video, Layers, Film as FilmIcon, LayoutGrid,
  Zap, AlertCircle, Clapperboard as ClapperIcon, PenLine, type LucideIcon
} from 'lucide-react';
import { useEditorStore } from '@/store/editor';
import { api } from '@/utils/api';
import { STYLE_PRESETS, type StylePreset } from '@/utils/model-config';
import type { Asset } from '@/types';
import type { SkillDef } from '@/components/SkillChat';
import { QueueStatusPanel } from '@/components/QueueStatusPanel';

interface HomeViewProps {
  onOpenAgent: () => void;
}

const SIDEBAR_ITEMS = [
  { icon: Home, label: '首页', active: true },
  { icon: PlusSquare, label: '创建' },
  { icon: BarChart2, label: '数据' },
  { icon: FolderKanban, label: '项目' },
  { icon: Image, label: '资产' },
  { icon: Wrench, label: '技能' },
];

const comingSoon = (label: string) => () => {
  window.alert(`${label} 功能开发中`);
};

const FEATURES = [
  { title: '小说改编短剧', skill_id: 'novel-to-shortdrama-script', desc: '小说原文一键改编为可拍摄短剧剧本', icon: BookOpen, color: 'from-blue-700 to-slate-800' },
  { title: '轻量分镜制作', skill_id: 'storyboard-lite', desc: '剧本智能拆解分镜表与视频提示词', icon: Clapperboard, color: 'from-rose-600 to-orange-700' },
  { title: 'AI漫剧全流程', skill_id: 'drama-generator-pro', desc: '小说一键生成完整漫剧素材包含Excel', icon: Layers, color: 'from-teal-700 to-emerald-900' },
  { title: '3D精品漫剧', skill_id: 'muzi-3d-generator', desc: '3D分镜脚本+角色场景生图提示词', icon: FilmIcon, color: 'from-emerald-600 to-teal-800' },
  { title: 'Seedance提示词', skill_id: 'seedance-prompt-zh', desc: '即梦Seedance 2.0多模态视频提示词', icon: Video, color: 'from-amber-600 to-red-700' },
  { title: '短剧剧本创作', skill_id: 'xyq-short-drama', desc: '一句话创意展开为完整短剧剧本', icon: PenLine, color: 'from-violet-600 to-purple-700' },
  { title: '分镜导演台本', skill_id: 'storyboard-director', desc: '小说自动拆解为专业分镜导演台本', icon: ClapperIcon, color: 'from-fuchsia-600 to-pink-700' },
];

const SCRIPT_TEMPLATES = [
  { title: '都市逆袭', desc: '落魄少年被豪门看不起，最后逆袭打脸', text: '落魄少年被豪门看不起，受尽冷眼与羞辱，最后凭借真实身份逆袭打脸。' },
  { title: '甜宠虐恋', desc: '女总裁隐婚三年，离婚后前夫悔不当初', text: '女总裁隐婚三年默默付出，离婚后前夫才发现她的真实身份，追悔莫及。' },
  { title: '奇幻冒险', desc: '外卖小哥意外获得超能力，守护城市正义', text: '外卖小哥意外获得超能力，从此化身城市守护者，对抗黑暗势力。' },
  { title: '悬疑推理', desc: '侦探追查连环失踪案，真相藏在身边人', text: '私家侦探追查连环失踪案，线索却一步步指向最亲近的身边人。' },
  { title: '古装权谋', desc: '庶女入宫步步为营，最终登上后位', text: '庶女入宫步步为营，在权谋斗争中逆袭，最终登上后位。' },
];

interface SkillTemplate {
  skill_id: string;
  title: string;
  desc: string;
  icon: LucideIcon;
  params: { name: string; type: 'text' | 'select'; options?: string[]; default?: string; required?: boolean; description?: string }[];
}

const SKILL_TEMPLATES: SkillTemplate[] = [
  {
    skill_id: 'novel-to-shortdrama-script',
    title: '小说改编短剧',
    desc: '将小说原文改编成可拍摄的短剧剧本',
    icon: BookOpen,
    params: [
      { name: '集数', type: 'select', options: ['3集', '5集', '8集', '10集', '12集', '20集', '30集'], default: '5集' },
      { name: '每集分钟', type: 'select', options: ['1分钟', '2分钟', '3分钟', '5分钟'], default: '2分钟' },
      { name: '题材类型', type: 'select', options: ['甜宠', '复仇', '重生逆袭', '家庭伦理', '战神/赘婿', '虐恋/追妻', '萌宝/寻亲'], default: '重生逆袭' },
    ],
  },
  {
    skill_id: 'storyboard-lite',
    title: '轻量分镜制作',
    desc: '剧本一键生成分镜表和视频组提示词',
    icon: Clapperboard,
    params: [
      { name: '故事类型', type: 'select', options: ['都市职场', '甜宠恋爱', '悬疑惊悚', '热血动作', '仙侠玄幻', '家庭温情', '喜剧幽默', '科幻末世', '历史史诗', '心理剧情', '恐怖超自然', '成长剧情'], default: '都市职场' },
      { name: '美术风格', type: 'select', options: ['真人现代都市', '真人古装中国', '真人武侠', '2D 国风', '2D 日漫', '2D 扁平设计', '2D 成熟都市恋爱', '3D 动画', '3D 国风', '3D 国风赛博', '3D 黏土定格'], default: '真人现代都市' },
      { name: '输出格式', type: 'select', options: ['Markdown', 'CSV', 'JSON'], default: 'Markdown' },
    ],
  },
  {
    skill_id: 'drama-generator-pro',
    title: 'AI漫剧全流程生成',
    desc: '小说一键生成完整漫剧素材包（剧本+人物+场景+分镜+Excel）',
    icon: Layers,
    params: [
      { name: '动漫风格', type: 'select', options: ['美式卡通', '2D古风', '3D古风', '韩漫二次元', '现代都市', '3D卡通', '日漫二次元', '中国工笔画', '写实风格', '彩色水墨', '厚涂古风', '吉卜力', '赛博朋克', '胶片质感'], default: '现代都市' },
      { name: '改编程度', type: 'select', options: ['忠实原著', '适度改编', '创意改编'], default: '适度改编' },
    ],
  },
  {
    skill_id: 'muzi-3d-generator',
    title: '3D精品漫剧生成器',
    desc: '3D分镜脚本+角色生图提示词+场景生图提示词，适配即梦Seedance 2.0',
    icon: FilmIcon,
    params: [
      { name: '3D风格', type: 'select', options: ['3D Q版卡通', '3D写实', '二次元3D', '3D国风', '3D赛博朋克'], default: '3D Q版卡通' },
      { name: '分镜段数', type: 'select', options: ['2段', '3段', '4段', '5段'], default: '4段' },
    ],
  },
  {
    skill_id: 'seedance-prompt-zh',
    title: 'Seedance提示词生成',
    desc: '为即梦Seedance 2.0生成多模态视频提示词，支持12种创作场景',
    icon: Video,
    params: [
      { name: '场景类型', type: 'select', options: ['人物一致性', '运镜精准复刻', '创意模版/特效复刻', '视频延长', '视频编辑', '音乐卡点', '对话与声音演绎', '一镜到底', '电商/产品展示', '科普/教育内容', 'AI短剧/漫改', '视频融合/续写'], default: '人物一致性' },
      { name: '生成时长', type: 'select', options: ['4秒', '5秒', '8秒', '10秒', '13秒', '15秒'], default: '10秒' },
      { name: '素材说明', type: 'text', default: '', description: '已有素材说明（如：3张图片、1个参考视频等），无则留空' },
    ],
  },
  {
    skill_id: 'xyq-short-drama',
    title: '短剧剧本创作',
    desc: '一句话创意展开为完整短剧剧本（含世界观、角色、分集剧本）',
    icon: PenLine,
    params: [
      { name: '题材类型', type: 'select', options: ['悬疑推理', '甜宠恋爱', '都市职场', '古装权谋', '奇幻冒险', '治愈温情', '爽文逆袭', '校园青春', '家庭伦理', '末日生存'], default: '悬疑推理' },
      { name: '集数', type: 'select', options: ['5集', '10集', '15集', '20集', '30集'], default: '10集' },
      { name: '每集场数', type: 'select', options: ['3场', '4场', '5场'], default: '4场' },
      { name: '情感基调', type: 'select', options: ['温情', '刺激', '搞笑', '虐心', '爽感', '悬疑'], default: '悬疑' },
    ],
  },
  {
    skill_id: 'storyboard-director',
    title: '分镜导演台本',
    desc: '小说/故事自动拆解为专业分镜导演台本（含景别、运镜、对话、音效）',
    icon: ClapperIcon,
    params: [
      { name: '风格', type: 'select', options: ['写实', '动画', '3D', '水墨国风', '赛博朋克'], default: '写实' },
      { name: '画幅', type: 'select', options: ['9:16竖屏', '16:9横屏', '1:1方形'], default: '9:16竖屏' },
      { name: '镜头数限制', type: 'select', options: ['20镜', '30镜', '50镜', '80镜', '不限'], default: '30镜' },
      { name: '目标平台', type: 'select', options: ['抖音', '快手', 'B站', '小红书', 'YouTube'], default: '抖音' },
    ],
  },
];

const ASSET_TYPE_OPTIONS: { value: string; label: string; icon: React.ReactNode }[] = [
  { value: 'all', label: '全部', icon: <Package size={12} /> },
  { value: 'character', label: '角色', icon: <User size={12} /> },
  { value: 'scene', label: '场景', icon: <MapPin size={12} /> },
  { value: 'image', label: '图片', icon: <Image size={12} /> },
  { value: 'video', label: '视频', icon: <Film size={12} /> },
  { value: 'audio', label: '音频', icon: <Music size={12} /> },
];

function getGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return '上午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

export function HomeView({ onOpenAgent }: HomeViewProps) {
  const [input, setInput] = useState('');
  const { canvasList, loadCanvasList, createNewCanvas } = useEditorStore();
  const navigate = useNavigate();

  const [activeTool, setActiveTool] = useState<'script' | 'skill' | 'style' | 'asset' | null>(null);
  const toolPanelRef = useRef<HTMLDivElement>(null);
  const [agentPickerOpen, setAgentPickerOpen] = useState(false);
  const agentPickerRef = useRef<HTMLDivElement>(null);

  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetFilter, setAssetFilter] = useState('all');
  const [assetQuery, setAssetQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [assetLoading, setAssetLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadCanvasList();
  }, [loadCanvasList]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(assetQuery), 300);
    return () => clearTimeout(t);
  }, [assetQuery]);

  useEffect(() => {
    if (!activeTool) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (toolPanelRef.current && !toolPanelRef.current.contains(e.target as Node)) {
        setActiveTool(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [activeTool]);

  useEffect(() => {
    if (!agentPickerOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (agentPickerRef.current && !agentPickerRef.current.contains(e.target as Node)) {
        setAgentPickerOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [agentPickerOpen]);

  const handleAgentSelect = (agentMode: 'step' | 'one-click') => {
    setAgentPickerOpen(false);
    sessionStorage.setItem('agentMode', agentMode);
    onOpenAgent();
  };

  const loadAssets = useCallback(async () => {
    setAssetLoading(true);
    try {
      const data = await api.listAssets(
        assetFilter === 'all' ? undefined : assetFilter,
        debouncedQuery || undefined,
        undefined
      );
      setAssets(data || []);
    } catch {
      setAssets([]);
    } finally {
      setAssetLoading(false);
    }
  }, [assetFilter, debouncedQuery]);

  useEffect(() => {
    if (activeTool === 'asset') {
      loadAssets();
    }
  }, [activeTool, loadAssets]);

  const [brainLoading, setBrainLoading] = useState(false);
  const [brainProgress, setBrainProgress] = useState('');
  const [brainError, setBrainError] = useState('');

  // 画布缩略图：canvasId -> 第一张生成图片 url
  const [canvasThumbs, setCanvasThumbs] = useState<Record<string, string>>({});

  // #14: 从 sessionStorage 恢复缓存的缩略图
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('canvasThumbsCache');
      if (raw) setCanvasThumbs(JSON.parse(raw));
    } catch { /* ignore */ }
  }, []);

  // 加载最近项目缩略图（#14: 仅请求未缓存的画布）
  useEffect(() => {
    if (!canvasList.length) return;
    const top4 = canvasList.slice(0, 4);
    // 过滤已有缓存的画布，只请求缺失的
    const needFetch = top4.filter(c => !canvasThumbs[c.id]);
    if (needFetch.length === 0) return;
    let cancelled = false;
    Promise.all(
      needFetch.map(async (c) => {
        try {
          const full = await api.getCanvas(c.id);
          const nodes = full.nodes || [];
          // 优先找有 result_url 的 image/video 节点
          const imgNode = nodes.find(n =>
            (n.node_type === 'image' || n.node_type === 'video' || n.node_type === 'storyboard') &&
            (n.result_url || n.thumbnail_url)
          );
          return { id: c.id, url: imgNode?.result_url || imgNode?.thumbnail_url || '' };
        } catch {
          return { id: c.id, url: '' };
        }
      })
    ).then(results => {
      if (cancelled) return;
      setCanvasThumbs(prev => {
        const updated = { ...prev };
        for (const r of results) {
          if (r.url) updated[r.id] = r.url;
        }
        // 持久化到 sessionStorage
        try {
          sessionStorage.setItem('canvasThumbsCache', JSON.stringify(updated));
        } catch { /* ignore */ }
        return updated;
      });
    });
    return () => { cancelled = true; };
  }, [canvasList]);

  const handleSubmit = async () => {
    if (!input.trim() || brainLoading) return;
    const prompt = input.trim();
    setInput('');
    setBrainLoading(true);
    setBrainProgress('智能分析您的需求...');
    setBrainError('');

    let navigated = false;
    const safeNavigate = (fn: () => void) => {
      if (navigated) return;
      navigated = true;
      fn();
    };

    try {
      let brainResult: any = null;
      let streamError: string | null = null;
      let thinkingBuffer = '';  // #1 流式推理文本缓冲区

      await api.runPlatformBrainStream(
        prompt,
        undefined,
        (msg) => {
          // #1 根据消息类型更新进度展示
          if (msg.type === 'routing_thinking') {
            // 流式推理 token：逐字追加
            thinkingBuffer += msg.content;
            setBrainProgress(thinkingBuffer);
          } else if (msg.type === 'tool_call') {
            // 工具调用决策
            thinkingBuffer = '';
            setBrainProgress(msg.content);
          } else if (msg.type === 'param_extraction_thinking') {
            // 流式参数提取 token
            thinkingBuffer += msg.content;
            setBrainProgress(thinkingBuffer);
          } else {
            // 其他消息类型：直接展示 content
            thinkingBuffer = '';
            if (msg.content) {
              setBrainProgress(msg.content);
            }
          }
        },
        (result) => {
          brainResult = result;
        },
        (err) => {
          // 大脑流式失败，记录错误但不立即跳转，让 await 后的逻辑统一处理
          console.error('Brain stream error:', err);
          streamError = err;
        },
      );

      // 如果流式调用出错，显示错误并提供重试/跳转选项
      if (streamError && !brainResult) {
        setBrainError(streamError);
        setBrainLoading(false);
        setBrainProgress('');
        return;
      }

      if (!brainResult) {
        // 降级：走 Agent
        sessionStorage.setItem('agentPendingPrompt', prompt);
        safeNavigate(onOpenAgent);
        return;
      }

      const decision = brainResult.decision;
      if (decision === 'short_drama') {
        // 路由到短剧 Agent
        const sdPrompt = brainResult.short_drama_params?.prompt || prompt;
        sessionStorage.setItem('agentPendingPrompt', sdPrompt);
        safeNavigate(onOpenAgent);
      } else if (decision === 'single_skill' && brainResult.data) {
        // 路由到技能结果展示页
        sessionStorage.setItem('brainSkillResult', JSON.stringify({
          prompt,
          data: brainResult.data,
          reasoning: brainResult.reasoning || '',
        }));
        safeNavigate(() => navigate('/skill-result'));
      } else if (decision === 'multi_skill' && brainResult.results) {
        // 多技能结果
        sessionStorage.setItem('brainSkillResult', JSON.stringify({
          prompt,
          results: brainResult.results,
          reasoning: brainResult.reasoning || '',
        }));
        safeNavigate(() => navigate('/skill-result'));
      } else {
        // 兜底：走 Agent
        sessionStorage.setItem('agentPendingPrompt', prompt);
        safeNavigate(onOpenAgent);
      }
    } catch (err: any) {
      // 显示错误而非静默跳转
      setBrainError(err?.message || '请求失败，请重试');
    } finally {
      setBrainLoading(false);
      setBrainProgress('');
    }
  };

  const handleExample = (example: string) => {
    setInput(example);
    sessionStorage.setItem('agentPendingPrompt', example);
    onOpenAgent();
  };

  const handleOpenCanvas = (id: string) => {
    useEditorStore.getState().loadCanvas(id);
  };

  const handleCustomCanvas = async () => {
    await createNewCanvas('自定义创作');
  };

  const handleSidebarClick = (label: string) => {
    if (label === '创建') {
      onOpenAgent();
    } else if (label === '首页') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (label === '项目') {
      window.dispatchEvent(new CustomEvent('openCanvasList'));
    } else if (label === '资产') {
      useEditorStore.getState().toggleAssetPanel();
    } else {
      comingSoon(label)();
    }
  };

  const handleImageUpload = async (file: File) => {
    setUploading(true);
    try {
      const asset = await api.uploadAsset(file, { assetType: 'image', name: file.name });
      const marker = `\n[图片资产:${asset.id}]\n`;
      setInput((prev) => prev + marker);
    } catch {
      window.alert('图片上传失败，请重试');
    } finally {
      setUploading(false);
    }
  };

  const handlePaste = async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(e.clipboardData.items);
    let hasImage = false;
    for (const item of items) {
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          hasImage = true;
          e.preventDefault();
          await handleImageUpload(file);
        }
      }
    }
    // 文本保留浏览器默认粘贴行为，确保插入到光标位置
    if (!hasImage) return;
  };

  const handleDrop = async (e: React.DragEvent<HTMLTextAreaElement>) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files);
    const text = e.dataTransfer.getData('text');
    for (const file of files) {
      if (file.type.startsWith('image/')) {
        await handleImageUpload(file);
      }
    }
    if (text) {
      setInput((prev) => prev + text);
    }
  };

  const handleToolClick = (tool: typeof activeTool) => {
    setActiveTool((prev) => (prev === tool ? null : tool));
  };

  const handleScriptSelect = (text: string) => {
    setInput((prev) => (prev ? `${prev}\n${text}` : text));
    setActiveTool(null);
  };

  // 点击技能卡片 → 跳转到技能对话框页面
  const openSkillChat = (skill: SkillTemplate) => {
    const iconName = skill.icon === BookOpen ? 'BookOpen'
      : skill.icon === Clapperboard ? 'Clapperboard'
      : skill.icon === Layers ? 'Layers'
      : skill.icon === FilmIcon ? 'Film'
      : skill.icon === Video ? 'Video'
      : 'Sparkles';
    const skillDef: SkillDef = {
      skill_id: skill.skill_id,
      title: skill.title,
      desc: skill.desc,
      icon: iconName,
      params: skill.params.map((p) => ({
        name: p.name,
        type: p.type,
        options: p.options,
        default: p.default,
        required: p.required,
      })),
    };
    sessionStorage.setItem('skillChatData', JSON.stringify(skillDef));
    setActiveTool(null);
    navigate('/skill');
  };

  const handleStyleSelect = (style: StylePreset) => {
    const tag = `\n视觉风格：${style.name}\n`;
    setInput((prev) => prev + tag);
    setActiveTool(null);
  };

  const handleAssetSelect = (asset: Asset) => {
    const marker = `\n[资产:${asset.asset_type}:${asset.id}:${asset.name}]\n`;
    setInput((prev) => prev + marker);
    setActiveTool(null);
  };

  const handleAssetUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleAssetFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await handleImageUpload(file);
    e.target.value = '';
    loadAssets();
  };

  const renderToolPanel = () => {
    if (!activeTool) return null;
    return (
      <div
        ref={toolPanelRef}
        className="absolute left-0 right-0 top-full mt-2 glass rounded-2xl border border-panel-border shadow-soft-lg z-[60] p-3"
      >
        {activeTool === 'script' && (
          <div className="space-y-2">
            <div className="text-xs font-semibold text-theme-main flex items-center gap-2">
              <BookOpen size={14} className="text-accent" /> 选择剧本模板
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[240px] overflow-y-auto">
              {SCRIPT_TEMPLATES.map((t) => (
                <button
                  key={t.title}
                  onClick={() => handleScriptSelect(t.text)}
                  className="text-left p-2.5 rounded-xl bg-panel-bg border border-panel-border hover:border-accent/40 hover:bg-accent/10 transition-colors"
                >
                  <div className="text-xs font-semibold text-theme-main">{t.title}</div>
                  <div className="text-[10px] text-theme-sub line-clamp-2 mt-0.5">{t.desc}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {activeTool === 'skill' && (
          <div className="space-y-2">
            <div className="text-xs font-semibold text-theme-main flex items-center gap-2">
              <Wand2 size={14} className="text-accent" /> 选择创作技能
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {SKILL_TEMPLATES.map((s) => (
                <button
                  key={s.skill_id}
                  onClick={() => openSkillChat(s)}
                  className="text-left p-3 rounded-xl bg-panel-bg border border-panel-border hover:border-accent/40 hover:bg-accent/10 transition-colors"
                >
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-theme-main">
                    <s.icon size={14} className="text-accent" /> {s.title}
                  </div>
                  <div className="text-[10px] text-theme-sub line-clamp-2 mt-0.5">{s.desc}</div>
                  <div className="text-[9px] text-accent/70 mt-1 flex items-center gap-0.5">
                    点击进入对话框 <ChevronRight size={9} />
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {activeTool === 'style' && (
          <div className="space-y-3">
            <div className="text-xs font-semibold text-theme-main flex items-center gap-2">
              <Palette size={14} className="text-accent" /> 选择视觉风格
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-3 max-h-[320px] overflow-y-auto p-0.5">
              {STYLE_PRESETS.map((s) => (
                <button
                  key={s.name}
                  onClick={() => handleStyleSelect(s)}
                  className="group relative overflow-hidden rounded-2xl border border-panel-border bg-panel-bg hover:border-accent transition-all shadow-soft hover:shadow-glow text-left"
                  title={s.name}
                >
                  <div className="aspect-[4/3] w-full overflow-hidden">
                    <img
                      src={s.image}
                      alt={s.name}
                      className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent" />
                  </div>
                  <div className="absolute bottom-0 left-0 right-0 p-2">
                    <span className="text-[11px] font-medium text-white drop-shadow-md line-clamp-1">
                      {s.name}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {activeTool === 'asset' && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold text-theme-main flex items-center gap-2">
                <FolderOpen size={14} className="text-accent" /> 资产库
              </div>
              <button
                onClick={handleAssetUploadClick}
                disabled={uploading}
                className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] btn-secondary disabled:opacity-50"
              >
                <Upload size={10} />
                {uploading ? '上传中' : '上传图片'}
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleAssetFileChange}
            />
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-theme-hint" />
              <input
                className="input-field pl-7 text-xs"
                placeholder="搜索资产..."
                value={assetQuery}
                onChange={(e) => setAssetQuery(e.target.value)}
              />
            </div>
            <div className="flex flex-wrap gap-1">
              {ASSET_TYPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setAssetFilter(opt.value)}
                  className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] border transition-colors ${
                    assetFilter === opt.value
                      ? 'bg-accent/20 border-accent text-accent'
                      : 'bg-canvas-bg border-panel-border text-theme-sub hover:border-panel-border/80'
                  }`}
                >
                  {opt.icon}
                  {opt.label}
                </button>
              ))}
            </div>
            <div className="max-h-[200px] overflow-y-auto space-y-1.5">
              {assetLoading ? (
                <div className="text-center text-theme-hint text-xs py-6">加载中...</div>
              ) : assets.length === 0 ? (
                <div className="text-center text-theme-hint text-xs py-6">
                  <Package size={24} className="mx-auto mb-1.5 opacity-30" />
                  暂无资产
                </div>
              ) : (
                assets.map((asset) => (
                  <button
                    key={asset.id}
                    onClick={() => handleAssetSelect(asset)}
                    className="w-full text-left p-2 rounded-xl bg-panel-bg border border-panel-border hover:border-accent/40 hover:bg-accent/10 transition-colors flex items-center gap-2"
                  >
                    <div className="w-8 h-8 rounded-lg bg-canvas-bg flex items-center justify-center shrink-0 overflow-hidden">
                      {asset.file_url?.match(/\.(jpg|jpeg|png|webp|gif|svg)(\?|$)/i) ? (
                        <img
                          src={asset.thumbnail_url || asset.file_url}
                          alt=""
                          className="w-full h-full object-cover"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                        />
                      ) : (
                        ASSET_TYPE_OPTIONS.find((t) => t.value === asset.asset_type)?.icon || <Package size={12} />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] font-medium text-theme-main truncate">{asset.name}</div>
                      <div className="text-[9px] text-theme-hint">{asset.asset_type}</div>
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="h-full w-full flex bg-canvas-bg">
      {/* 左侧导航 */}
      <div className="w-16 shrink-0 h-full flex flex-col items-center justify-center py-4 ml-4 mr-2">
        <div className="glass rounded-2xl p-2 flex flex-col items-center gap-4 shadow-soft">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center shadow-glow">
            <Feather size={18} className="text-theme-invert" />
          </div>
          <nav className="flex flex-col gap-2">
            {SIDEBAR_ITEMS.map((item) => (
              <button
                key={item.label}
                title={item.label}
                onClick={() => handleSidebarClick(item.label)}
                className={`w-10 h-10 rounded-xl flex items-center justify-center transition-colors ${
                  item.active
                    ? 'bg-accent/10 text-accent'
                    : 'text-theme-muted hover:text-theme-main hover:bg-panel-hover'
                }`}
              >
                <item.icon size={20} />
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* 主内容 */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* 可滚动内容 */}
        <div className="flex-1 overflow-y-auto px-6 pb-10">
          <div className="max-w-4xl mx-auto pt-8">
            {/* 问候 */}
            <div className="flex items-center justify-center gap-2 mb-6">
              <Feather size={28} className="text-accent" />
              <h1 className="text-3xl font-bold text-theme-main">{getGreeting()}，导演！</h1>
            </div>

            {/* 中央输入 */}
            <div className="relative z-50 glass rounded-3xl p-5 mb-4 shadow-soft-lg">
              <textarea
                className="w-full bg-transparent text-theme-main placeholder:text-theme-hint resize-none outline-none text-base min-h-[80px] px-1"
                placeholder={brainLoading ? brainProgress : "拖拽 / 粘贴 图片到这里，试试技能、风格、资产"}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit();
                  }
                }}
                onPaste={handlePaste}
                onDrop={handleDrop}
                onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }}
              />
              <div className="flex items-center justify-between mt-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    onClick={() => handleToolClick('script')}
                    className={`flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs transition-colors ${
                      activeTool === 'script' ? 'text-accent bg-accent/10 border border-accent/20' : 'text-theme-muted hover:bg-panel-hover'
                    }`}
                  >
                    <BookOpen size={12} />
                    剧本
                  </button>
                  <button
                    onClick={() => handleToolClick('skill')}
                    className={`flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs transition-colors ${
                      activeTool === 'skill' ? 'text-accent bg-accent/10 border border-accent/20' : 'text-theme-muted hover:bg-panel-hover'
                    }`}
                  >
                    <Wand2 size={12} />
                    技能
                  </button>
                  <div className="relative" ref={agentPickerRef}>
                    <button
                      onClick={() => setAgentPickerOpen((v) => !v)}
                      className={`flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs transition-colors ${
                        agentPickerOpen
                          ? 'text-accent bg-accent/15 border border-accent/30'
                          : 'text-accent bg-accent/10 border border-accent/20'
                      }`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                      Agent
                    </button>
                    {agentPickerOpen && (
                      <div className="absolute left-0 top-full mt-2 z-[70] glass rounded-2xl border border-panel-border shadow-soft-lg p-3 w-[380px]">
                        <div className="text-xs font-semibold text-theme-main mb-2.5 flex items-center gap-1.5 px-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                          选择创作模式
                        </div>
                        <div className="grid grid-cols-2 gap-2.5">
                          <button
                            onClick={() => handleAgentSelect('step')}
                            className="group relative overflow-hidden rounded-xl p-3.5 text-left border border-panel-border bg-panel-bg hover:border-teal-600/40 hover:bg-teal-600/5 transition-all hover:-translate-y-0.5 shadow-soft"
                          >
                            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-500 flex items-center justify-center shadow-soft mb-2.5">
                              <Brain size={16} className="text-white" />
                            </div>
                            <div className="text-sm font-bold text-theme-main mb-0.5">智能对话</div>
                            <div className="text-[10px] text-theme-sub leading-relaxed">分步交互创作，智能体调度6步流水线，精细可控</div>
                            <div className="text-[9px] text-teal-600/70 mt-1.5 flex items-center gap-0.5">
                              点击进入 <ChevronRight size={9} />
                            </div>
                          </button>
                          <button
                            onClick={() => handleAgentSelect('one-click')}
                            className="group relative overflow-hidden rounded-xl p-3.5 text-left border border-panel-border bg-panel-bg hover:border-emerald-500/40 hover:bg-emerald-500/5 transition-all hover:-translate-y-0.5 shadow-soft"
                          >
                            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-soft mb-2.5">
                              <Zap size={16} className="text-white" />
                            </div>
                            <div className="text-sm font-bold text-theme-main mb-0.5">一键全自动</div>
                            <div className="text-[10px] text-theme-sub leading-relaxed">输入灵感即可，全自动生成剧本到画布全流程</div>
                            <div className="text-[9px] text-emerald-500/70 mt-1.5 flex items-center gap-0.5">
                              点击进入 <ChevronRight size={9} />
                            </div>
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => handleToolClick('style')}
                    className={`flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs transition-colors ${
                      activeTool === 'style' ? 'text-accent bg-accent/10 border border-accent/20' : 'text-theme-muted hover:bg-panel-hover'
                    }`}
                  >
                    <Palette size={12} />
                    风格
                  </button>
                  <button
                    onClick={() => handleToolClick('asset')}
                    className={`flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs transition-colors ${
                      activeTool === 'asset' ? 'text-accent bg-accent/10 border border-accent/20' : 'text-theme-muted hover:bg-panel-hover'
                    }`}
                  >
                    <FolderOpen size={12} />
                    资产
                  </button>
                </div>
<button
onClick={handleSubmit}
disabled={!input.trim() || uploading || brainLoading}
className="w-10 h-10 rounded-full bg-gradient-to-br from-accent to-accent-glow hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center text-theme-invert transition-all shadow-glow"
>
{brainLoading ? <Loader2 size={18} className="animate-spin" /> : uploading ? <LoaderIcon /> : <Send size={18} />}
</button>
              </div>
              {renderToolPanel()}
            </div>

            {/* 大脑处理进度条 */}
            {brainLoading && (
              <div className="flex items-center gap-3 mb-4 px-5 py-3 rounded-2xl glass border border-accent/20 shadow-soft animate-fade-in">
                <Loader2 size={18} className="animate-spin text-accent shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-theme-main font-medium truncate">{brainProgress || '智能分析您的需求...'}</div>
                  <div className="mt-1.5 h-1 rounded-full bg-panel-border overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-accent to-accent-glow rounded-full animate-pulse" style={{ width: '60%' }} />
                  </div>
                </div>
              </div>
            )}

            {/* 错误提示 */}
            {brainError && !brainLoading && (
              <div className="flex items-center gap-3 mb-4 px-5 py-3 rounded-2xl bg-error/8 border border-error/25 animate-fade-in">
                <AlertCircle size={18} className="text-error shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-error font-medium">智能体处理失败</div>
                  <div className="text-xs text-error/70 mt-0.5 break-all">{brainError}</div>
                </div>
                <button
                  onClick={() => { setBrainError(''); }}
                  className="text-xs text-error hover:underline shrink-0 font-medium"
                >
                  关闭
                </button>
              </div>
            )}

            {/* 示例提示词 */}
            <div className="flex items-center gap-2 mb-10 flex-wrap justify-center">
              {[
                '落魄少年被豪门看不起，最后逆袭打脸',
                '女总裁隐婚三年，离婚后前夫悔不当初',
                '外卖小哥意外获得超能力，守护城市正义',
              ].map((ex) => (
                <button
                  key={ex}
                  onClick={() => handleExample(ex)}
                  className="px-3 py-1.5 rounded-full text-xs text-theme-muted border border-panel-border hover:border-accent/40 hover:text-accent transition-colors bg-panel-bg"
                >
                  {ex}
                </button>
              ))}
            </div>

            {/* #19 生成队列状态 */}
            <div className="mb-6">
              <QueueStatusPanel compact />
            </div>

            {/* 最近项目 */}
            <div className="mb-10">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-theme-main">最近项目</h2>
                <button
                  onClick={() => window.dispatchEvent(new CustomEvent('openCanvasList'))}
                  className="text-xs text-theme-sub hover:text-theme-main flex items-center gap-0.5"
                >
                  全部 <ChevronRight size={12} />
                </button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-4">
                <button
                  onClick={handleCustomCanvas}
                  className="aspect-[4/3] rounded-2xl glass border border-panel-border/60 hover:border-accent/40 flex flex-col items-center justify-center gap-2 text-theme-muted hover:text-accent transition-colors shadow-soft hover:shadow-soft-lg hover:-translate-y-0.5"
                >
                  <LayoutGrid size={24} />
                  <span className="text-xs font-medium">进入画布创作</span>
                </button>
                {canvasList.slice(0, 4).map((c) => {
                  const thumb = canvasThumbs[c.id];
                  return (
                    <button
                      key={c.id}
                      onClick={() => handleOpenCanvas(c.id)}
                      className="group relative aspect-[4/3] rounded-2xl glass border border-panel-border hover:border-accent/30 p-3 flex flex-col justify-between text-left transition-all hover:-translate-y-0.5 shadow-soft overflow-hidden"
                    >
                      {thumb ? (
                        <img
                          src={thumb}
                          alt=""
                          className="absolute inset-0 w-full h-full object-cover opacity-40 group-hover:opacity-50 transition-opacity"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                        />
                      ) : (
                        <div className="absolute inset-0 bg-gradient-to-br from-accent/5 to-transparent" />
                      )}
                      <div className="relative z-10 w-8 h-8 rounded-xl bg-gradient-to-br from-accent to-accent-glow flex items-center justify-center shadow-glow">
                        <Clapperboard size={14} className="text-theme-invert" />
                      </div>
                      <div className="relative z-10">
                        <div className="text-xs font-medium text-theme-main truncate drop-shadow-sm">{c.name}</div>
                        <div className="text-[10px] text-theme-sub">
                          {c.updated_at && !isNaN(new Date(c.updated_at).getTime())
                            ? new Date(c.updated_at).toLocaleDateString()
                            : c.created_at && !isNaN(new Date(c.created_at).getTime())
                            ? new Date(c.created_at).toLocaleDateString()
                            : '-'}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 亮点功能 */}
            <div>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-theme-main">亮点功能</h2>
                <button onClick={comingSoon('创建技能')} className="px-3 py-1.5 rounded-xl text-[10px] text-theme-muted border border-panel-border hover:bg-panel-hover">
                  创建技能
                </button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5 max-w-4xl">
                {FEATURES.map((f) => (
                  <div
                    key={f.title}
                    onClick={() => {
                      const skill = SKILL_TEMPLATES.find((s) => s.skill_id === f.skill_id);
                      if (skill) openSkillChat(skill);
                      else onOpenAgent();
                    }}
                    className="relative overflow-hidden rounded-xl p-3 h-[110px] flex flex-col justify-between glass border border-panel-border/50 hover:border-white/30 transition-all cursor-pointer shadow-soft hover:shadow-soft-lg hover:-translate-y-0.5"
                  >
                    <div className={`absolute inset-0 bg-gradient-to-br ${f.color} opacity-85`} />
                    <div className="relative z-10 w-7 h-7 rounded-lg bg-white/20 backdrop-blur-sm flex items-center justify-center border border-white/10">
                      <f.icon size={14} className="text-white" />
                    </div>
                    <div className="relative z-10">
                      <div className="text-xs font-semibold text-white drop-shadow">{f.title}</div>
                      <div className="text-[9px] text-white/80 mt-0.5 drop-shadow line-clamp-1">{f.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function LoaderIcon() {
  return (
    <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  );
}
