/**
 * BrainResultPage - 大脑路由结果展示页
 *
 * 当用户在首页输入框发送消息后，大脑决定路由到 Skill 时，
 * 结果会传到此页面展示。
 * 布局风格：仿豆包/千问 —— 用户消息右对齐，AI 消息左对齐，带头像。
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Brain, Copy, Check, Sparkles, User } from 'lucide-react';

interface BrainResultData {
  prompt: string;
  data?: any;
  results?: any[];
  reasoning: string;
}

export default function BrainResultPage() {
  const navigate = useNavigate();
  const [result, setResult] = useState<BrainResultData | null>(null);

  useEffect(() => {
    const raw = sessionStorage.getItem('brainSkillResult');
    if (raw) {
      try {
        setResult(JSON.parse(raw));
      } catch {
        navigate('/home');
      }
      sessionStorage.removeItem('brainSkillResult');
    } else {
      navigate('/home');
    }
  }, [navigate]);

  if (!result) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-canvas-bg">
        <div className="text-theme-sub text-sm">加载中...</div>
      </div>
    );
  }

  return (
    <div className="h-screen w-screen bg-canvas-bg overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-accent-glow flex items-center justify-center shadow-glow">
              <Brain size={20} className="text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold text-theme-main">智能体调度结果</h1>
              <p className="text-[11px] text-theme-sub">{result.reasoning}</p>
            </div>
          </div>
          <button
            onClick={() => navigate('/home')}
            className="btn-ghost p-2 rounded-lg"
            title="返回首页"
          >
            <ArrowRight size={16} />
          </button>
        </div>

        {/* 用户输入 —— 右对齐气泡 + 用户头像 */}
        <div className="flex justify-end items-start gap-3">
          <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-accent/12 border border-accent/20 px-4 py-3">
            <div className="text-sm text-theme-main whitespace-pre-wrap break-words leading-relaxed">{result.prompt}</div>
          </div>
          <div className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-accent/15 border border-accent/20">
            <User size={15} className="text-theme-main" />
          </div>
        </div>

        {/* 单技能结果 —— 左对齐 + AI 头像 */}
        {result.data && !result.results && (
          <div className="flex justify-start items-start gap-3">
            <div className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br from-accent to-accent-glow shadow-glow">
              <Brain size={15} className="text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <ResultCard data={result.data} />
            </div>
          </div>
        )}

        {/* 多技能结果 —— 左对齐 + AI 头像 */}
        {result.results && result.results.length > 0 && (
          <div className="flex justify-start items-start gap-3">
            <div className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br from-accent to-accent-glow shadow-glow">
              <Brain size={15} className="text-white" />
            </div>
            <div className="flex-1 min-w-0 space-y-4">
              {result.results.map((r, i) => (
                <div key={i}>
                  <div className="flex items-center gap-2 mb-2 text-xs text-theme-sub">
                    <Sparkles size={12} className="text-accent" />
                    第 {i + 1} 步：{r.skill_name || r.skill_id}
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${r.status === 'success' ? 'bg-success/10 text-success' : 'bg-error/10 text-error'}`}>
                      {r.status === 'success' ? '成功' : '失败'}
                    </span>
                  </div>
                  {r.data && <ResultCard data={r.data} />}
                  {r.error && (
                    <div className="glass rounded-xl border border-error/30 p-3 text-xs text-error">
                      {r.error}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 继续创作 */}
        <div className="flex items-center gap-3 pt-4">
          <button
            onClick={() => navigate('/home')}
            className="px-4 h-10 rounded-xl text-xs btn-ghost border border-panel-border"
          >
            返回首页
          </button>
          <button
            onClick={() => {
              sessionStorage.setItem('agentPendingPrompt', result.prompt);
              navigate('/agent');
            }}
            className="px-4 h-10 rounded-xl text-xs btn-primary flex items-center gap-1.5"
          >
            <Brain size={13} />
            送入 Agent 继续加工
          </button>
        </div>
      </div>
    </div>
  );
}

function ResultCard({ data }: { data: any }) {
  const [copied, setCopied] = useState(false);

  const md = data?.full_markdown ||
    [data?.adaptation_overview, data?.episode_outline, data?.full_script, data?.video_groups_markdown]
      .filter(Boolean).join('\n\n---\n\n') ||
    JSON.stringify(data, null, 2);

  const title = data?.work_title || data?.skill_name || data?.scene_summary || '';

  const handleCopy = () => {
    try {
      navigator.clipboard?.writeText(md);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <div className="rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border p-4 space-y-3 shadow-soft">
      {title && (
        <div className="text-sm font-semibold text-theme-main">{title}</div>
      )}
      {data?.summary && (
        <div className="text-[11px] text-theme-sub leading-relaxed">{data.summary}</div>
      )}
      <div className="rounded-xl bg-canvas-bg/60 border border-panel-border/40 p-3 max-h-[500px] overflow-y-auto">
        <div className="chat-content">{md}</div>
      </div>
      <button
        onClick={handleCopy}
        className="text-[11px] text-theme-sub hover:text-accent flex items-center gap-1 transition-colors"
      >
        {copied ? <Check size={11} className="text-success" /> : <Copy size={11} />}
        {copied ? '已复制' : '复制'}
      </button>
    </div>
  );
}
