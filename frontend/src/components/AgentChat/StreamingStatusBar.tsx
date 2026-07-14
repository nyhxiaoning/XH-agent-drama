/**
 * #15 实时步骤指示器
 * 在 AgentChat 流式执行时，于消息区顶部显示：
 * - 当前 Agent 名称 + 图标
 * - 实时耗时计时器
 * - 动画进度条
 * - 三阶段进度灯（planning → asset → production）
 */
import { useEffect, useState } from 'react';
import { Brain, BookOpen, User, Film, Loader2 } from 'lucide-react';
import { useAgentStore, AGENT_STEPS } from '@/store/agent';
import type { LucideIcon } from 'lucide-react';

const STAGE_ICONS: Record<string, LucideIcon> = {
  planning: BookOpen,
  asset: User,
  production: Film,
};

const STAGE_LABELS: Record<string, string> = {
  planning: '前期策划',
  asset: '资产设定',
  production: '拍摄制作',
};

const AGENT_DISPLAY: Record<string, { name: string; icon: LucideIcon }> = {
  script_planner: { name: '剧本架构师', icon: BookOpen },
  screenwriter: { name: '文学编剧', icon: BookOpen },
  character_designer: { name: '角色设计师', icon: User },
  scene_prop_designer: { name: '场景设计师', icon: User },
  storyboard_director: { name: '分镜导演', icon: Film },
  video_composer: { name: '视频作曲', icon: Film },
  director_brain: { name: '总导演智能体', icon: Brain },
  asset_parallel: { name: '资产调度', icon: User },
  system: { name: '系统', icon: Brain },
};

export function StreamingStatusBar() {
  const { streaming, currentAgent, streamElapsed, currentStep } = useAgentStore();
  const [elapsed, setElapsed] = useState(0);

  // 实时更新计时器
  useEffect(() => {
    if (!streaming) {
      setElapsed(0);
      return;
    }
    setElapsed(streamElapsed);
    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [streaming, streamElapsed]);

  if (!streaming) return null;

  const agentInfo = currentAgent
    ? AGENT_DISPLAY[currentAgent] || { name: currentAgent, icon: Brain }
    : { name: '智能体调度中', icon: Brain };
  const AgentIcon = agentInfo.icon;

  // 三阶段进度
  const stages = ['planning', 'asset', 'production'];
  const currentStageIdx = stages.indexOf(currentStep);

  // 格式化时间
  const formatTime = (s: number) => {
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  return (
    <div className="border-b border-panel-border bg-gradient-to-r from-teal-600/5 via-emerald-500/5 to-transparent shrink-0">
      <div className="max-w-4xl mx-auto px-4 py-2.5">
        {/* 第一行：Agent 信息 + 计时器 */}
        <div className="flex items-center gap-3 mb-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-teal-600 to-emerald-500 flex items-center justify-center shadow-soft shrink-0">
            <AgentIcon size={13} className="text-white animate-pulse" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-theme-main truncate">{agentInfo.name}</span>
              <span className="text-[10px] text-teal-600 font-medium">
                {STAGE_LABELS[currentStep] || currentStep}
              </span>
            </div>
            <div className="text-[10px] text-theme-hint">
              正在处理...
            </div>
          </div>
          {/* 计时器 */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-panel-bg border border-panel-border/50 shrink-0">
            <Loader2 size={10} className="text-teal-600 animate-spin" />
            <span className="text-xs font-mono tabular-nums text-theme-sub">{formatTime(elapsed)}</span>
          </div>
        </div>

        {/* 第二行：三阶段进度灯 */}
        <div className="flex items-center gap-2">
          {stages.map((stage, idx) => {
            const StageIcon = STAGE_ICONS[stage] || Brain;
            const isDone = currentStageIdx > idx;
            const isActive = currentStageIdx === idx;
            const isLocked = currentStageIdx < idx;
            return (
              <div key={stage} className="flex items-center gap-1.5 flex-1">
                <div
                  className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px] font-medium transition-all ${
                    isDone
                      ? 'bg-success/10 text-success'
                      : isActive
                      ? 'bg-teal-600/15 text-teal-600'
                      : 'bg-canvas-bg/50 text-theme-hint'
                  }`}
                >
                  <StageIcon
                    size={10}
                    className={isActive ? 'animate-pulse' : ''}
                  />
                  <span>{STAGE_LABELS[stage]}</span>
                  {isDone && <span className="text-success">✓</span>}
                </div>
                {idx < stages.length - 1 && (
                  <div className="w-3 h-0.5 rounded-full bg-panel-border/40 overflow-hidden shrink-0">
                    <div
                      className="h-full bg-teal-600 rounded-full transition-all duration-500"
                      style={{ width: isDone ? '100%' : isActive ? '50%' : '0%' }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* 第三行：动画进度条 */}
        <div className="mt-2 h-0.5 rounded-full bg-panel-border/30 overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-teal-600 to-emerald-500 rounded-full"
            style={{
              width: '30%',
              animation: 'slide-progress 2s ease-in-out infinite',
            }}
          />
        </div>
      </div>

      {/* 动画 keyframes */}
      <style>{`
        @keyframes slide-progress {
          0% { width: 10%; margin-left: 0%; }
          50% { width: 40%; margin-left: 30%; }
          100% { width: 10%; margin-left: 90%; }
        }
      `}</style>
    </div>
  );
}
