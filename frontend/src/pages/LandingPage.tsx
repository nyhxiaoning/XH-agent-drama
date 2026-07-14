import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Sparkles, Play, Clapperboard, Mountain, Shirt, Plane, Feather,
  ArrowRight, Film, Wand2, Image as ImageIcon, ScrollText, User,
  Cpu, Users, LayoutTemplate, Zap, CheckCircle2, ArrowDown
} from 'lucide-react';
import { useAuthStore } from '@/store/auth';

const FEATURES = [
  { title: '剧情故事创作', desc: 'AI 编剧一键生成短剧剧本与分镜提示词包', icon: Play },
  { title: '拉片复刻', desc: '复刻经典镜头与叙事节奏，替换主体规避版权', icon: Clapperboard },
  { title: '场景设计', desc: '文字直接生成电影级场景提示词', icon: Mountain },
  { title: '我在世界杯现场', desc: '沉浸式赛事氛围视频生成', icon: Shirt },
  { title: '无人机航拍', desc: '一键生成震撼航拍视角', icon: Plane },
];

const STATS = [
  { value: '10,000+', label: '已生成短剧集数', icon: Film },
  { value: '90%', label: '节省制作成本', icon: Zap },
  { value: '6', label: '大 AI Agent', icon: Cpu },
  { value: '1080P', label: '支持输出画质', icon: ImageIcon },
];

const BENTO_CARDS = [
  {
    id: 'pipeline',
    title: '全链路自动化',
    desc: '从一句话创意到完整成片，编剧、分镜、角色、场景、视频 5 大环节自动衔接，无需手动跳转。',
    icon: LayoutTemplate,
    colSpan: 'lg:col-span-2',
    rowSpan: 'lg:row-span-2',
    gradient: 'from-teal-600/80 to-emerald-700/80',
  },
  {
    id: 'character',
    title: '角色一致性',
    desc: '3 大视觉锚点锁定角色形象，全剧人脸、服装、体型稳定可控，告别崩脸串款。',
    icon: Users,
    colSpan: 'lg:col-span-1',
    rowSpan: 'lg:row-span-1',
    gradient: 'from-teal-700/80 to-emerald-800/80',
  },
  {
    id: 'script',
    title: '爆款剧本库',
    desc: '内置钩子-反转-收尾四节拍模板，适配都市爽文、古风悬疑、情感虐恋等热门题材。',
    icon: ScrollText,
    colSpan: 'lg:col-span-1',
    rowSpan: 'lg:row-span-1',
    gradient: 'from-rose-700/80 to-orange-800/80',
  },
  {
    id: 'storyboard',
    title: '智能分镜',
    desc: '自动拆解镜头语言：景别、运镜、机位、光影、转场一次生成，支持 Seedance 2.0 标准。',
    icon: Clapperboard,
    colSpan: 'lg:col-span-2',
    rowSpan: 'lg:row-span-1',
    gradient: 'from-teal-700/80 to-emerald-800/80',
  },
];

const PREVIEW_STEPS = [
  { id: 'script', label: '剧本大纲', duration: 3000 },
  { id: 'character', label: '角色三视图', duration: 3500 },
  { id: 'storyboard', label: '智能分镜', duration: 3500 },
  { id: 'video', label: '视频成片', duration: 4000 },
];

function ScriptPreview() {
  return (
    <div className="w-full h-full p-5 flex flex-col gap-2 text-theme-main">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] font-semibold text-accent">短剧《重生2000》第1集</span>
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-black/10 dark:bg-white/10 text-theme-sub">120s</span>
      </div>
      <div className="h-2 w-3/4 rounded bg-black/10 dark:bg-white/10" />
      <div className="h-2 w-full rounded bg-black/10 dark:bg-white/10" />
      <div className="h-2 w-5/6 rounded bg-black/10 dark:bg-white/10" />
      <div className="mt-2 space-y-1.5">
        {['0-15s 强钩子：主角重生醒来', '15-60s 剧情推进：发现商机', '60-90s 反转：前世仇人出现', '90-120s 收尾：下集钩子'].map((t, i) => (
          <div key={i} className="flex items-center gap-2 text-[10px] text-theme-sub">
            <CheckCircle2 size={11} className="text-success shrink-0" />
            <span className="truncate">{t}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CharacterPreview() {
  const views = [
    { label: '正面', tone: 'from-slate-400 to-slate-600' },
    { label: '侧面', tone: 'from-amber-400 to-rose-500' },
    { label: '背面', tone: 'from-teal-500 to-emerald-600' },
  ];
  return (
    <div className="w-full h-full p-4 flex flex-col items-center justify-center gap-3">
      <div className="text-[11px] font-semibold text-accent">主角·林晚舟 · 角色三视图</div>
      <div className="flex items-end justify-center gap-4">
        {views.map((v) => (
          <div key={v.label} className="flex flex-col items-center gap-1.5">
            <div className={`w-16 h-24 rounded-lg bg-gradient-to-b ${v.tone} flex items-center justify-center shadow-soft`}>
              <User size={28} className="text-white/80" />
            </div>
            <span className="text-[10px] text-theme-sub">{v.label}</span>
          </div>
        ))}
      </div>
      <div className="flex gap-1.5 text-[9px] text-theme-hint">
        <span className="px-1.5 py-0.5 rounded bg-black/10 dark:bg-white/10">黑色风衣</span>
        <span className="px-1.5 py-0.5 rounded bg-black/10 dark:bg-white/10">短碎发</span>
        <span className="px-1.5 py-0.5 rounded bg-black/10 dark:bg-white/10">1:1面部锚点</span>
      </div>
    </div>
  );
}

function StoryboardPreview() {
  const shots = [
    { idx: '01', shot: '特写', move: '推镜头', grad: 'from-rose-500/70 to-orange-500/70' },
    { idx: '02', shot: '中景', move: '环绕', grad: 'from-teal-600/70 to-emerald-500/70' },
    { idx: '03', shot: '远景', move: '航拍', grad: 'from-teal-500/70 to-emerald-500/70' },
  ];
  return (
    <div className="w-full h-full p-4 flex flex-col gap-2">
      <div className="text-[11px] font-semibold text-accent mb-0.5">分镜脚本 · Seedance 2.0</div>
      <div className="grid grid-cols-3 gap-2 flex-1">
        {shots.map((s) => (
          <div key={s.idx} className={`rounded-lg bg-gradient-to-br ${s.grad} p-2 flex flex-col justify-between text-white`}>
            <div className="flex items-center justify-between text-[9px] font-medium">
              <span>镜头{s.idx}</span>
              <span className="px-1 rounded bg-black/20">{s.shot}</span>
            </div>
            <div className="text-[9px] opacity-90">运镜：{s.move}</div>
          </div>
        ))}
      </div>
      <div className="text-[9px] text-theme-hint text-center">3 / 24 镜头</div>
    </div>
  );
}

function VideoPreview() {
  return (
    <div className="w-full h-full relative flex items-center justify-center bg-gradient-to-br from-slate-800 to-teal-950 overflow-hidden">
      <div className="absolute inset-0 opacity-30" style={{ backgroundImage: 'radial-gradient(circle at 30% 30%, rgba(255,255,255,0.4), transparent 40%)' }} />
      <div className="relative flex flex-col items-center gap-3">
        <div className="w-14 h-14 rounded-full bg-white/95 flex items-center justify-center shadow-glow">
          <Play size={22} className="text-slate-900 ml-0.5" fill="currentColor" />
        </div>
        <div className="w-40 h-1 rounded-full bg-white/20 overflow-hidden">
          <div className="h-full w-2/3 rounded-full bg-white" />
        </div>
        <span className="text-[10px] text-white/80">正在渲染 · 1080P</span>
      </div>
    </div>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuthStore();
  const [input, setInput] = useState('');
  const [activeStep, setActiveStep] = useState(0);
  const [isHovering, setIsHovering] = useState(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  const requireAuth = (cb: () => void) => {
    if (isAuthenticated()) {
      cb();
      return;
    }
    if (window.confirm('该功能需要登录后才能使用，是否跳转到登录/注册页面？')) {
      navigate('/login');
    }
  };

  useEffect(() => {
    if (isHovering) return;
    timerRef.current = setInterval(() => {
      setActiveStep((prev) => (prev + 1) % PREVIEW_STEPS.length);
    }, PREVIEW_STEPS[activeStep].duration);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [activeStep, isHovering]);

  const handleStart = () => {
    if (!input.trim()) {
      requireAuth(() => navigate('/home'));
      return;
    }
    requireAuth(() => navigate('/home', { state: { prompt: input } }));
  };

  const renderPreview = () => {
    switch (PREVIEW_STEPS[activeStep].id) {
      case 'script': return <ScriptPreview />;
      case 'character': return <CharacterPreview />;
      case 'storyboard': return <StoryboardPreview />;
      case 'video': return <VideoPreview />;
      default: return null;
    }
  };

  return (
    <div className="min-h-screen w-full bg-canvas-bg text-theme-main overflow-x-hidden">
      {/* 动态光晕背景 */}
      <div className="fixed inset-0 -z-10 overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] bg-accent/5 rounded-full blur-[120px] animate-pulse-slow" />
        <div className="absolute top-[20%] right-[-10%] w-[50%] h-[50%] bg-blue-900/5 rounded-full blur-[120px] animate-pulse-slow animation-delay-1000" />
        <div className="absolute bottom-[-10%] left-[20%] w-[50%] h-[50%] bg-teal-950/5 rounded-full blur-[120px] animate-pulse-slow animation-delay-2000" />
      </div>

      {/* 顶部导航 */}
      <header className="fixed top-0 left-0 right-0 z-50 glass border-b border-panel-border/50">
        <div className="max-w-6xl mx-auto h-16 px-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center shadow-glow">
              <Feather size={18} className="text-theme-invert" />
            </div>
            <span className="text-lg font-bold">星河</span>
          </div>
          <nav className="hidden md:flex items-center gap-6 text-sm text-theme-muted">
            <button onClick={() => requireAuth(() => navigate('/home'))} className="hover:text-theme-main transition-colors">创作台</button>
            <button onClick={() => requireAuth(() => navigate('/agent'))} className="hover:text-theme-main transition-colors">AI Agent</button>
            <button onClick={() => requireAuth(() => navigate('/home'))} className="hover:text-theme-main transition-colors">资产库</button>
          </nav>
          <button
            onClick={() => navigate('/login')}
            className="px-5 py-2 rounded-xl text-sm font-medium btn-secondary"
          >
            登录
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="relative pt-32 pb-12 px-6">
        <div className="max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full glass border border-panel-border text-xs text-theme-sub mb-6 animate-fade-up">
            <Sparkles size={12} className="text-accent" />
            下一代 AI 短剧生产力工具
          </div>
          <h1 className="text-4xl md:text-6xl font-bold leading-tight mb-6 animate-fade-up">
            让每一个人都能<br className="hidden md:block" />
            <span className="text-accent">导演</span> 自己的短剧
          </h1>
          <p className="text-base md:text-lg text-theme-muted max-w-2xl mx-auto mb-10 animate-fade-up">
            告别繁琐流程。内置编剧、分镜、角色、场景、视频等 6 大 AI Agent，<br className="hidden md:block" />
            从灵感一闪到成片导出，仅需一杯咖啡的时间。
          </p>

          {/* 输入框演示 */}
          <div className="max-w-2xl mx-auto animate-fade-up">
            <div className="glass rounded-2xl p-2 border border-panel-border shadow-soft-lg">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={'输入你的创意：例如 "重生回到2000年，我要做互联网大佬..."'}
                  className="flex-1 h-12 px-4 rounded-xl bg-theme-input text-sm text-theme-main placeholder:text-theme-hint border border-transparent focus:outline-none focus:border-accent"
                />
                <button
                  onClick={handleStart}
                  className="h-12 px-5 rounded-xl text-sm font-medium btn-primary flex items-center gap-2 shrink-0"
                >
                  开始生成 <ArrowRight size={16} />
                </button>
              </div>
            </div>
          </div>

          {/* 动态箭头 */}
          <div className="flex justify-center py-5 animate-bounce-slow">
            <ArrowDown size={24} className="text-accent/50" />
          </div>

          {/* 结果预览轮播 */}
          <div
            className="max-w-6xl mx-auto animate-fade-up"
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => setIsHovering(false)}
          >
            <div className="glass rounded-2xl border border-panel-border shadow-soft overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 border-b border-panel-border/50 bg-panel-bg">
                <div className="text-xs font-semibold text-theme-main">AI 正在创作中...</div>
                <div className="flex items-center gap-1.5">
                  {PREVIEW_STEPS.map((s, i) => (
                    <button
                      key={s.id}
                      onClick={() => setActiveStep(i)}
                      className={`h-1.5 rounded-full transition-all duration-500 ${
                        i === activeStep ? 'w-6 bg-accent' : 'w-1.5 bg-panel-border hover:bg-accent/40'
                      }`}
                    />
                  ))}
                </div>
              </div>
              <div className="h-56 md:h-72 transition-all duration-500">
                {renderPreview()}
              </div>
              <div className="flex items-center justify-between px-4 py-2 border-t border-panel-border/50 bg-panel-bg">
                <div className="text-[10px] text-theme-sub">
                  当前步骤：<span className="text-accent font-medium">{PREVIEW_STEPS[activeStep].label}</span>
                </div>
                <div className="text-[10px] text-theme-hint">演示效果</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 信任背书条 */}
      <section className="py-10 px-6 border-y border-panel-border/50">
        <div className="max-w-5xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-6">
          {STATS.map((s) => (
            <div key={s.label} className="text-center">
              <div className="flex items-center justify-center gap-2 mb-1">
                <s.icon size={16} className="text-accent" />
                <span className="text-2xl md:text-3xl font-bold text-theme-main">{s.value}</span>
              </div>
              <div className="text-xs text-theme-sub">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Bento Grid 功能区 */}
      <section className="py-16 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-2xl md:text-3xl font-bold mb-2">核心能力</h2>
            <p className="text-sm text-theme-muted">覆盖短剧创作全链路，开箱即用</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 auto-rows-[180px]">
            {BENTO_CARDS.map((card) => (
              <div
                key={card.id}
                onClick={() => requireAuth(() => navigate('/home'))}
                className={`group relative overflow-hidden rounded-3xl border border-panel-border/50 cursor-pointer transition-all duration-300 hover:-translate-y-1 hover:shadow-soft-lg ${card.colSpan} ${card.rowSpan}`}
              >
                <div className={`absolute inset-0 bg-gradient-to-br ${card.gradient} opacity-0 group-hover:opacity-100 transition-opacity duration-500`} />
                <div className="absolute inset-0 glass" />
                <div className="relative h-full p-6 flex flex-col">
                  <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center mb-4 group-hover:bg-white/15 transition-colors">
                    <card.icon size={20} className="text-accent group-hover:text-white transition-colors" />
                  </div>
                  <h3 className="text-base font-bold text-theme-main group-hover:text-theme-invert transition-colors mb-2">
                    {card.title}
                  </h3>
                  <p className="text-xs text-theme-sub group-hover:text-white/80 transition-colors leading-relaxed">
                    {card.desc}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 亮点功能 */}
      <section className="py-16 px-6 border-y border-panel-border/50">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-2xl md:text-3xl font-bold mb-2">亮点功能</h2>
            <p className="text-sm text-theme-muted">5 大 AI 技能，满足多样化创作需求</p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {FEATURES.map((f) => (
              <button
                key={f.title}
                onClick={() => requireAuth(() => navigate('/home'))}
                className="group relative overflow-hidden rounded-2xl border border-panel-border text-left transition-all hover:-translate-y-1 shadow-soft hover:shadow-soft-lg p-5 glass"
              >
                <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center mb-4">
                  <f.icon size={20} className="text-accent" />
                </div>
                <h3 className="text-sm font-bold text-theme-main mb-1">{f.title}</h3>
                <p className="text-[10px] text-theme-sub leading-relaxed">{f.desc}</p>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* 底部 CTA */}
      <section className="py-20 px-6">
        <div className="max-w-3xl mx-auto rounded-3xl glass border border-panel-border p-8 md:p-12 text-center">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center mx-auto mb-4 shadow-glow">
            <User size={24} className="text-theme-invert" />
          </div>
          <h2 className="text-2xl md:text-3xl font-bold mb-3">准备好开启你的导演生涯了吗？</h2>
          <p className="text-sm text-theme-muted mb-6">登录后即可使用全部 AI 创作功能，无需复杂配置。</p>
          <button
            onClick={() => navigate('/login')}
            className="mx-auto px-8 py-3 rounded-2xl text-sm font-medium btn-primary shadow-glow"
          >
            立即免费体验
          </button>
        </div>
      </section>

      {/* 页脚 */}
      <footer className="py-8 px-6 border-t border-panel-border/50 text-center">
        <div className="flex items-center justify-center gap-2 mb-2">
          <Sparkles size={14} className="text-accent" />
          <span className="text-sm font-semibold">星河创作平台</span>
        </div>
        <p className="text-[11px] text-theme-hint">© 2026 星河. All rights reserved.</p>
      </footer>
    </div>
  );
}
