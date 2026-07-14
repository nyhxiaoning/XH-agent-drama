/**
 * chat 公共组件统一导出
 *
 * 从 AgentChat / SkillChat 中提取的公共聊天组件和 Hook。
 */
export type { ChatMessage, ChatRole, CardType, AgentMeta } from './types';
export { TypingIndicator } from './TypingIndicator';
export { MessageBubble } from './MessageBubble';
export type { MessageBubbleProps } from './MessageBubble';
export { useAutoScroll } from './useAutoScroll';
export { useSSEStream } from './useSSEStream';
export type { SSEMessage, UseSSEStreamOptions, UseSSEStreamResult } from './useSSEStream';
