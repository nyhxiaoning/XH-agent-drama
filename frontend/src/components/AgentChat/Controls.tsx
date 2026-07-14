/**
 * P4: Controls 组件 - StepOptionsPanel + SkipButton + LlmModelSelector
 */
import { useState, useEffect } from 'react';
import {
  Settings2, ChevronLeft, ChevronRight, SkipForward, SlidersHorizontal, Coins,
  Cpu, Loader2,
} from 'lucide-react';
import { useAgentStore, STEP_OPTION_DEFINITIONS, type AgentStepKey } from '@/store/agent';
import { api, type LlmModel } from '@/utils/api';
import { OPTION_ICONS, OPTION_TEMPLATES, CORE_OPTION_KEYS, STEP_TOKEN_ESTIMATES, STEP_CREDIT_ESTIMATES } from './constants';

export function StepOptionsPanel({
  step, className, variant = 'chips', showTemplate = true
}: {
  step: AgentStepKey;
  className?: string;
  variant?: 'chips' | 'compact';
  showTemplate?: boolean;
}) {
  const { stepOptions, setStepOption } = useAgentStore();
  const [expanded, setExpanded] = useState(false);
  const defs = STEP_OPTION_DEFINITIONS[step] || [];
  if (defs.length === 0) return null;

  const coreIds = CORE_OPTION_KEYS[step] || [];
  const coreDefs = defs.filter((d) => coreIds.includes(d.id));
  const advancedDefs = defs.filter((d) => !coreIds.includes(d.id));
  const visibleDefs = variant === 'compact' && !expanded ? coreDefs : defs;

  const applyTemplate = (name: string) => {
    const t = OPTION_TEMPLATES[step]?.[name];
    if (!t) return;
    Object.entries(t).forEach(([k, v]) => setStepOption(step, k, v));
  };

  if (variant === 'compact') {
    return (
      <div className={`space-y-3 ${className || ''}`}>
        {showTemplate && step === 'start' && (
          <div className="flex flex-wrap gap-1.5">
            {Object.keys(OPTION_TEMPLATES.start).map((name) => (
              <button
                key={name}
                onClick={() => applyTemplate(name)}
                className="px-2 py-0.5 rounded-md text-[10px] border border-panel-border bg-panel-bg text-theme-sub hover:border-teal-600/30 hover:text-teal-600 transition-all"
              >
                套用{name}
              </button>
            ))}
          </div>
        )}
        <div className={`grid gap-3 ${expanded ? 'grid-cols-2' : 'grid-cols-1 sm:grid-cols-2'}`}>
          {visibleDefs.map((def) => {
            const Icon = OPTION_ICONS[def.id] || SlidersHorizontal;
            const current = stepOptions[step]?.[def.id] ?? def.choices[0] ?? '';
            return (
              <div key={def.id} className="space-y-1.5">
                <label className="text-[11px] text-theme-sub flex items-center gap-1">
                  <Icon size={10} />
                  {def.label}
                </label>
                <input
                  type="text"
                  list={`${step}-${def.id}-list`}
                  className="w-full text-xs bg-theme-input border border-theme-input rounded-lg px-2 py-1.5 text-theme-main outline-none focus:border-teal-600 transition-colors"
                  value={current}
                  placeholder={def.choices[0] || '自定义输入'}
                  onChange={(e) => setStepOption(step, def.id, e.target.value)}
                />
                <datalist id={`${step}-${def.id}-list`}>
                  {def.choices.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
                {def.choices.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {def.choices.slice(0, 6).map((c) => (
                      <button
                        key={c}
                        onClick={() => setStepOption(step, def.id, c)}
                    className={`px-1.5 py-0.5 rounded text-[10px] border transition-all ${
                      current === c
                        ? 'bg-teal-600 text-white border-teal-600'
                        : 'bg-panel-bg border-panel-border text-theme-sub hover:border-teal-600/30 hover:text-teal-600'
                    }`}
                        title={c}
                      >
                        {c.length > 8 ? `${c.slice(0, 8)}…` : c}
                      </button>
                    ))}
                    {def.choices.length > 6 && (
                      <span className="text-[10px] text-theme-hint self-center">+{def.choices.length - 6}</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {advancedDefs.length > 0 && (
            <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border border-panel-border bg-panel-bg text-theme-sub hover:border-teal-600/30 hover:text-teal-600 transition-all"
          >
            <SlidersHorizontal size={11} />
            {expanded ? '收起高级参数' : `展开高级参数 (${advancedDefs.length})`}
            {expanded ? <ChevronLeft size={10} /> : <ChevronRight size={10} />}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={`space-y-4 ${className || ''}`}>
      <div className="flex items-center gap-2 text-theme-main">
        <Settings2 size={14} className="text-teal-600" />
        <span className="text-sm font-bold">创作参数</span>
        <span className="text-xs text-theme-sub ml-auto">自由输入，或点击推荐值</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {defs.map((def) => {
          const Icon = OPTION_ICONS[def.id] || SlidersHorizontal;
          const current = stepOptions[step]?.[def.id] ?? def.choices[0] ?? '';
          return (
            <div key={def.id} className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs text-theme-sub">
                <Icon size={12} className="text-teal-600" />
                <span>{def.label}</span>
              </div>
              <input
                type="text"
                list={`${step}-${def.id}-list`}
                className="w-full text-xs bg-panel-bg border border-panel-border rounded-lg px-2.5 py-1.5 text-theme-main outline-none focus:border-teal-600/50 transition-all"
                value={current}
                placeholder={def.choices[0] || '自定义输入'}
                onChange={(e) => setStepOption(step, def.id, e.target.value)}
              />
              <datalist id={`${step}-${def.id}-list`}>
                {def.choices.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
              <div className="flex flex-wrap gap-1.5">
                {def.choices.map((c) => (
                <button
                  key={c}
                  onClick={() => setStepOption(step, def.id, c)}
                  className={`px-2 py-0.5 rounded-md text-[10px] border transition-all ${
                    current === c
                      ? 'bg-teal-600 text-white border-teal-600'
                      : 'bg-panel-bg border-panel-border text-theme-sub hover:border-teal-600/30 hover:text-teal-600'
                  }`}
                >
                    {c}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SkipButton({ onClick, loading, label }: { onClick: () => void; loading: boolean; label: string }) {
  return (
    <button
      className="btn-secondary text-xs px-2 py-1"
      onClick={onClick}
      disabled={loading}
      title={label}
    >
      <SkipForward size={12} />
      <span>{label}</span>
    </button>
  );
}

/** #11 成本预估徽标 */
export function CostEstimateBadge({ step }: { step: AgentStepKey }) {
  const tokens = STEP_TOKEN_ESTIMATES[step] || 0;
  const credits = STEP_CREDIT_ESTIMATES[step] || 0;
  if (tokens === 0 && credits === 0) return null;
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-theme-hint bg-theme-input/50 rounded-md px-1.5 py-0.5">
      <Coins size={9} className="text-teal-600/60" />
      {tokens > 0 && <span>~{tokens.toLocaleString()} tokens</span>}
      {credits > 0 && <span>· {credits} 积分</span>}
    </span>
  );
}

export function LlmModelSelector({
  selected, onSelect, disabled,
}: {
  selected: string | null;
  onSelect: (modelId: string) => void;
  disabled?: boolean;
}) {
  const [models, setModels] = useState<LlmModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    api.listLlmModels()
      .then((data) => {
        if (!mounted) return;
        const list = data || [];
        setModels(list);
        if (list.length > 0) {
          // 检查当前选中的模型是否在列表中
          const isSelectedValid = selected && list.some(m => m.model_id === selected);
          if (!isSelectedValid) {
            // 选中模型无效（可能已从数据库移除），优先选 gpt-5.6-terra，其次取第一个
            const defaultModel = list.find(m => m.model_id === 'gpt-5.6-terra');
            onSelect(defaultModel ? defaultModel.model_id : list[0].model_id);
          }
        }
      })
      .catch((e: any) => {
        if (!mounted) return;
        setError(e.message || '加载模型列表失败');
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-theme-sub flex items-center gap-1.5">
        <Cpu size={12} className="text-teal-600" />
        语言大模型
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-teal-600/10 text-teal-600">全局</span>
      </label>
      {loading ? (
        <div className="flex items-center gap-2 text-xs text-theme-hint">
          <Loader2 size={12} className="animate-spin" />
          加载模型列表...
        </div>
      ) : models.length <= 1 ? (
        <select
          className="w-full text-sm bg-canvas-bg border border-panel-border/60 rounded-xl px-3 py-2 text-theme-main outline-none focus:border-teal-600/50 transition-all disabled:opacity-50"
          value={selected ?? ''}
          onChange={(e) => onSelect(e.target.value)}
          disabled={disabled}
        >
          {models.map((m) => (
            <option key={m.model_id} value={m.model_id}>
              {m.name}
            </option>
          ))}
        </select>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {models.map((m) => (
            <button
              key={m.model_id}
              onClick={() => onSelect(m.model_id)}
              disabled={disabled}
              className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                selected === m.model_id
                  ? 'bg-teal-600 text-white shadow-soft'
                  : 'bg-canvas-bg text-theme-sub border border-panel-border hover:border-teal-600/30 hover:text-teal-600'
              }`}
            >
              {m.name}
            </button>
          ))}
        </div>
      )}
      {models.length === 1 && (
        <p className="text-[10px] text-theme-hint">当前仅配置一个可用模型，后续可在后台添加更多语言大模型。</p>
      )}
      {error && <p className="text-xs text-error">{error}</p>}
    </div>
  );
}
