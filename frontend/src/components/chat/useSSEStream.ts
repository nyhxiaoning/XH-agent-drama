/**
 * useSSEStream - SSE 流式接收 Hook
 *
 * 封装 Server-Sent Events 的连接、解析、消息分发、断开控制。
 * 从 AgentChat / SkillChat 中提取的公共逻辑。
 *
 * #11 SSE 重连机制 + 前端缓存：
 * - 连接断开时自动重连（指数退避）
 * - 消息缓存到 sessionStorage，重连后可恢复状态
 * - 提供 onReconnect 回调通知组件
 *
 * 用法：
 *   const { streaming, messages, start, stop } = useSSEStream({
 *     url: '/agent/skills/run/stream',
 *     method: 'POST',
 *     body: { skill_id, prompt, params },
 *     onMessage: (msg) => { ... },
 *     onDone: (finalData) => { ... },
 *     onError: (err) => { ... },
 *     maxRetries: 3,
 *     retryDelay: 1000,
 *     onReconnect: (attempt, max) => { ... },
 *     cacheKey: 'skill_stream_123',
 *   });
 */
import { useState, useRef, useCallback } from 'react';
import { getAuthHeaders } from '@/utils/api';

export interface SSEMessage {
  type: string;
  content?: string;
  agent?: string;
  step?: string;
  data?: any;
  [key: string]: any;
}

export interface UseSSEStreamOptions {
  url: string;
  method?: 'POST' | 'GET';
  body?: Record<string, any>;
  /** 收到消息时的回调 */
  onMessage?: (msg: SSEMessage) => void;
  /** 流结束时回调（传入最终数据） */
  onDone?: (finalData: any) => void;
  /** 出错时回调 */
  onError?: (err: string) => void;
  /** #11 最大重连次数，默认 3 */
  maxRetries?: number;
  /** #11 基础重连延迟（ms），默认 1000，指数退避 */
  retryDelay?: number;
  /** #11 重连时回调 */
  onReconnect?: (attempt: number, maxRetries: number) => void;
  /** #11 消息缓存 key，用于 sessionStorage 持久化。不设则不持久化 */
  cacheKey?: string;
}

export interface UseSSEStreamResult {
  /** 是否正在流式接收 */
  streaming: boolean;
  /** 错误信息 */
  error: string | null;
  /** #11 是否正在重连 */
  reconnecting: boolean;
  /** #11 当前重连次数 */
  retryCount: number;
  /** #11 缓存的消息列表 */
  cachedMessages: SSEMessage[];
  /** 启动 SSE 流 */
  start: (overrideBody?: Record<string, any>) => Promise<void>;
  /** 停止 SSE 流 */
  stop: () => void;
}

// #11 sessionStorage 消息缓存工具
const SSE_CACHE_PREFIX = 'sse_cache_';

function loadCache(cacheKey: string): SSEMessage[] {
  try {
    const raw = sessionStorage.getItem(SSE_CACHE_PREFIX + cacheKey);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return [];
}

function saveCache(cacheKey: string, messages: SSEMessage[]) {
  try {
    // 只缓存最近 200 条，避免 sessionStorage 溢出
    const toSave = messages.slice(-200);
    sessionStorage.setItem(SSE_CACHE_PREFIX + cacheKey, JSON.stringify(toSave));
  } catch { /* ignore quota errors */ }
}

function clearCache(cacheKey: string) {
  try {
    sessionStorage.removeItem(SSE_CACHE_PREFIX + cacheKey);
  } catch { /* ignore */ }
}

export function useSSEStream(opts: UseSSEStreamOptions): UseSSEStreamResult {
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [cachedMessages, setCachedMessages] = useState<SSEMessage[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  // #11 内部状态 ref（避免闭包过期）
  const retryRef = useRef(0);
  const msgCacheRef = useRef<SSEMessage[]>([]);
  const finalResultRef = useRef<any>(null);
  const stoppedRef = useRef(false);  // 用户主动停止标记

  const stop = useCallback(() => {
    stoppedRef.current = true;
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setReconnecting(false);
    setRetryCount(0);
    retryRef.current = 0;
  }, []);

  const start = useCallback(async (overrideBody?: Record<string, any>) => {
    const {
      url, method = 'POST', body, onMessage, onDone, onError,
      maxRetries = 3, retryDelay = 1000, onReconnect, cacheKey,
    } = optsRef.current;
    const finalBody = overrideBody || body;

    // 重置状态
    stoppedRef.current = false;
    retryRef.current = 0;
    finalResultRef.current = null;
    msgCacheRef.current = [];

    // #11 加载缓存
    if (cacheKey) {
      const cached = loadCache(cacheKey);
      msgCacheRef.current = cached;
      setCachedMessages(cached);
    } else {
      setCachedMessages([]);
    }

    // 中断已有连接
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setStreaming(true);
    setError(null);
    setReconnecting(false);
    setRetryCount(0);

    /**
     * #11 执行单次 SSE 连接
     * 返回 'done' | 'error' | 'aborted'
     */
    const connectOnce = async (): Promise<'done' | 'error' | 'aborted'> => {
      const headers: Record<string, string> = { ...getAuthHeaders() };
      let res: Response;

      if (method === 'GET') {
        const qs = new URLSearchParams(finalBody || {}).toString();
        res = await fetch(`${url}?${qs}`, { headers, signal: abortRef.current!.signal });
      } else {
        headers['Content-Type'] = 'application/json';
        res = await fetch(url, {
          method,
          headers,
          body: JSON.stringify(finalBody || {}),
          signal: abortRef.current!.signal,
        });
      }

      if (!res.ok) {
        throw new Error(`请求失败 (${res.status})`);
      }

      if (!res.body) {
        throw new Error('响应体为空');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload) continue;

          try {
            const msg = JSON.parse(payload) as SSEMessage;

            if (msg.type === 'error') {
              throw new Error(msg.content || '执行失败');
            }

            if (msg.type === 'complete') {
              finalResultRef.current = {
                decision: (msg as any).decision,
                data: (msg as any).data,
                results: (msg as any).results,
                short_drama_params: (msg as any).short_drama_params,
                ...msg,
              };
            }

            if (msg.type === 'skill_done' && msg.data) {
              finalResultRef.current = finalResultRef.current || {};
              finalResultRef.current.data = msg.data;
            }

            // #11 缓存消息
            msgCacheRef.current.push(msg);
            setCachedMessages([...msgCacheRef.current]);
            if (cacheKey) {
              saveCache(cacheKey, msgCacheRef.current);
            }

            onMessage?.(msg);
          } catch (parseErr: any) {
            // 如果是主动抛出的 Error（如 msg.type === 'error'），重新抛出
            if (parseErr instanceof Error && parseErr.message !== 'JSON parse error') {
              throw parseErr;
            }
            /* ignore JSON parse errors */
          }
        }
      }

      return 'done';
    };

    // #11 带重连的 SSE 连接循环
    let lastError: string | null = null;

    while (retryRef.current <= maxRetries) {
      if (stoppedRef.current) {
        return;  // 用户主动停止
      }

      try {
        setReconnecting(retryRef.current > 0);
        setRetryCount(retryRef.current);

        const result = await connectOnce();

        if (result === 'done') {
          // 正常结束
          setReconnecting(false);
          setRetryCount(0);
          retryRef.current = 0;
          // #11 清理缓存
          if (cacheKey) clearCache(cacheKey);
          onDone?.(finalResultRef.current);
          return;
        }
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          // 用户主动中断，不重连
          return;
        }

        lastError = e?.message || 'SSE 连接异常';

        // 检查是否应该重连
        if (retryRef.current < maxRetries && !stoppedRef.current) {
          retryRef.current++;
          setRetryCount(retryRef.current);
          setReconnecting(true);

          // 通知组件正在重连
          onReconnect?.(retryRef.current, maxRetries);

          // 指数退避：retryDelay * 2^(retry-1)
          const delay = retryDelay * Math.pow(2, retryRef.current - 1);
          await new Promise(resolve => setTimeout(resolve, delay));

          // 创建新的 AbortController 用于重连
          if (!stoppedRef.current) {
            abortRef.current?.abort();
            abortRef.current = new AbortController();
            continue;  // 重试
          }
        }

        // 重试次数用尽或用户停止
        break;
      }
    }

    // 所有重试失败
    if (!stoppedRef.current && lastError) {
      setError(lastError);
      onError?.(lastError);
    }

    setReconnecting(false);
    setStreaming(false);
    abortRef.current = null;
  }, []);

  return { streaming, error, reconnecting, retryCount, cachedMessages, start, stop };
}
