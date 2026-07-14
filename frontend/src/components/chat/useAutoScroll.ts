/**
 * useAutoScroll - 自动滚动到底部 Hook
 *
 * 当依赖项变化时（新消息、loading 状态等），自动滚动容器到底部。
 * 从 AgentChat / SkillChat 中提取的公共逻辑。
 */
import { useRef, useEffect } from 'react';

export function useAutoScroll<T>(deps: T[]) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return ref;
}
