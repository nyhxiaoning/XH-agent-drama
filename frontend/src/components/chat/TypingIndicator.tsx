/**
 * TypingIndicator - 打字动画指示器
 *
 * 三个跳动的圆点，表示 AI 正在工作。
 * 从 AgentChat / SkillChat 中提取的公共组件。
 */
export function TypingIndicator({ color = 'bg-teal-600' }: { color?: string }) {
  return (
    <div className="flex gap-1">
      <span className={`w-1.5 h-1.5 ${color} rounded-full typing-dot`} />
      <span className={`w-1.5 h-1.5 ${color} rounded-full typing-dot`} />
      <span className={`w-1.5 h-1.5 ${color} rounded-full typing-dot`} />
    </div>
  );
}
