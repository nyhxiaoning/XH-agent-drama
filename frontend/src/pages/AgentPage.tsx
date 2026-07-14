import { useEffect } from 'react';
import { AgentChat } from '@/components/AgentChat';
import { useAgentStore } from '@/store/agent';

export default function AgentPage() {
  const { setOpen, start, chooseAgentMode } = useAgentStore();

  useEffect(() => {
    setOpen(true);
    // 读取用户选择的 Agent 模式
    const mode = sessionStorage.getItem('agentMode');
    if (mode === 'one-click' || mode === 'step') {
      sessionStorage.removeItem('agentMode');
      chooseAgentMode(mode);
    }
    const pending = sessionStorage.getItem('agentPendingPrompt');
    if (pending) {
      sessionStorage.removeItem('agentPendingPrompt');
      start(pending).catch(() => {});
    }
  }, [setOpen, start, chooseAgentMode]);

  return <AgentChat page />;
}
