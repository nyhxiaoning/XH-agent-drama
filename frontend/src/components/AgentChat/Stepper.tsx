/**
 * P4: Stepper 组件 - 顶部步骤条（重构版）
 * - 从80px双行 → 紧凑pill式单行布局
 * - 当前步骤用渐变高亮+脉冲
 * - 子步骤改为细线进度条
 */
import { CheckCircle } from 'lucide-react';
import { AGENT_STEPS, type AgentStepKey } from '@/store/agent';
import type { AgentSession } from '@/types';
import { SUB_STEPS } from './constants';

export function Stepper({
  currentStep, session, docked, onGoToStep,
}: {
  currentStep: AgentStepKey;
  session: AgentSession | null;
  docked?: boolean;
  onGoToStep?: (step: AgentStepKey) => void;
}) {
  const currentSub = (session as any)?.current_sub_step as string | undefined;
  const subSteps = SUB_STEPS[currentStep as AgentStepKey] || [];
  const activeIdx = subSteps.findIndex((s) => s.id === currentSub);
  const hasSubSteps = subSteps.length > 0;

  return (
    <div className={`border-b border-panel-border bg-panel-bg shrink-0 ${hasSubSteps ? 'py-2' : 'py-2.5'}`}>
      <div className={`flex items-center gap-1.5 max-w-5xl mx-auto ${docked ? 'px-2' : 'px-4'}`}>
        {AGENT_STEPS.map((s, idx) => {
          const active = currentStep === s.key;
          const stepIdx = AGENT_STEPS.findIndex((x) => x.key === currentStep);
          const done = stepIdx > idx;
          const isLocked = stepIdx < idx;
          const canClickBack = done && onGoToStep && !isLocked;

          return (
            <div key={s.key} className="flex items-center min-w-0">
              {/* 步骤pill */}
              <button
                disabled={!canClickBack}
                onClick={() => canClickBack && onGoToStep!(s.key)}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all shrink-0 ${
                  canClickBack ? 'cursor-pointer hover:scale-105' : 'cursor-default'
                } ${
                  active
                    ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white shadow-soft'
                    : done
                    ? 'bg-success/10 text-success border border-success/20'
                    : isLocked
                    ? 'bg-canvas-bg text-theme-hint border border-panel-border/50'
                    : 'bg-canvas-bg text-theme-sub border border-panel-border'
                }`}
                title={canClickBack ? `回退到${s.label}` : s.label}
              >
                {done ? (
                  <CheckCircle size={12} className="shrink-0" />
                ) : (
                  <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                    active ? 'bg-white/20' : 'bg-panel-border/30'
                  }`}>
                    {idx + 1}
                  </span>
                )}
                <span className={`whitespace-nowrap ${docked ? 'hidden' : ''}`}>{s.label}</span>
                {active && (
                  <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse shrink-0" />
                )}
              </button>

              {/* 连接线 */}
              {idx < AGENT_STEPS.length - 1 && (
                <div className="w-3 h-0.5 mx-0.5 rounded-full shrink-0 overflow-hidden bg-panel-border/40">
                  <div
                    className="h-full bg-success rounded-full transition-all duration-500"
                    style={{ width: done ? '100%' : '0%' }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 子步骤进度条 */}
      {hasSubSteps && (
        <div className="max-w-5xl mx-auto mt-1.5 px-4">
          <div className="flex items-center gap-1">
            {subSteps.map((sub, idx) => {
              const isActive = activeIdx === idx;
              const isDone = activeIdx > idx;
              return (
                <div key={sub.id} className="flex items-center flex-1 min-w-0">
                  <div
                    className={`flex-1 h-1 rounded-full transition-all duration-500 ${
                      isDone ? 'bg-success' : isActive ? 'bg-indigo-500 animate-pulse' : 'bg-panel-border/40'
                    }`}
                  />
                  {idx < subSteps.length - 1 && <div className="w-0.5 shrink-0" />}
                </div>
              );
            })}
          </div>
          {activeIdx >= 0 && (
            <div className="text-[10px] text-indigo-500 font-medium mt-0.5 text-center">
              {subSteps[activeIdx]?.label}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
