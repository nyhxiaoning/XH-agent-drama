import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Clapperboard, Undo2, Redo2, FolderOpen, Image as ImageIcon, History,
  Boxes, Feather, Wand2,
  Wifi, WifiOff, Home, Sun, Moon, User, Coins, LogOut, Receipt,
  X, ChevronDown, Wallet,
} from 'lucide-react';
import { RechargeModal } from './RechargeModal';
import { QueueStatusPanel } from './QueueStatusPanel';
import { useNavigate } from 'react-router-dom';
import { useEditorStore } from '@/store/editor';
import { useAgentStore } from '@/store/agent';
import { useAuthStore } from '@/store/auth';
import { useTheme } from '@/hooks/useTheme';
import { api } from '@/utils/api';
import type { CreditLedgerList } from '@/utils/api';

interface ToolbarProps {
  onOpenAgent: () => void;
}

export function Toolbar({ onOpenAgent }: ToolbarProps) {
  const navigate = useNavigate();
  const { canvas, wsConnected, toggleAssetPanel, toggleSnapshotPanel, loadCanvasList, clearCanvas } = useEditorStore();
  const { theme, toggleTheme } = useTheme();
  const setShowCanvasList = useEditorStore((s) => s.setShowCanvasList);
  const setError = useEditorStore((s) => s.setError);
  const setAgentOpen = useAgentStore((s) => s.setOpen);
  const { user, logout } = useAuthStore();
  const [menuOpen, setMenuOpen] = useState(false);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledger, setLedger] = useState<CreditLedgerList | null>(null);
  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [rechargeOpen, setRechargeOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [menuOpen]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const openLedger = async () => {
    setMenuOpen(false);
    setLedgerOpen(true);
    setLedgerLoading(true);
    try {
      const data = await api.getMyLedger(20, 0);
      setLedger(data);
    } catch {
      setLedger(null);
    } finally {
      setLedgerLoading(false);
    }
  };

  const handleOpenList = async () => {
    await loadCanvasList();
    setShowCanvasList(true);
  };

  const handleHome = () => {
    setAgentOpen(false);
    clearCanvas();
  };

  const comingSoon = (label: string) => () => {
    setError(`${label}功能开发中`);
  };

  return (
    <div className="absolute top-4 left-4 right-4 z-50 h-14 glass rounded-2xl flex items-center px-3 gap-2 shadow-soft-lg">
      <button className="flex items-center gap-2 mr-3 pl-1" onClick={handleHome} title="返回首页">
        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center shadow-glow">
          <Feather size={16} className="text-theme-invert" />
        </div>
        <span className="font-bold text-base tracking-wide bg-gradient-to-r from-teal-600 to-emerald-600 bg-clip-text text-transparent">
          星河
        </span>
      </button>

      <div className="h-5 w-px bg-panel-border mx-1" />

      <button className="btn-ghost rounded-xl" onClick={handleHome} title="返回首页">
        <Home size={16} />
        <span className="text-xs">首页</span>
      </button>

      <button className="btn-ghost rounded-xl" onClick={handleOpenList} title="打开画布">
        <FolderOpen size={16} />
        <span className="text-xs max-w-[120px] truncate">{canvas?.name || '未选择画布'}</span>
      </button>

      {/* #19 当前画布生成队列状态 */}
      {canvas?.id && <QueueStatusPanel canvasId={canvas.id} compact />}

      <button className="btn-ghost rounded-xl" onClick={comingSoon('撤销')} title="撤销（开发中）">
        <Undo2 size={16} />
      </button>
      <button className="btn-ghost rounded-xl" onClick={comingSoon('重做')} title="重做（开发中）">
        <Redo2 size={16} />
      </button>
      <button className="btn-ghost rounded-xl" onClick={toggleSnapshotPanel} title="版本快照">
        <History size={16} />
      </button>

      <div className="flex-1" />

      <button className="btn-ghost rounded-xl" onClick={onOpenAgent} title="AI 短剧创作">
        <Wand2 size={16} />
        <span className="text-xs">AI 创作</span>
      </button>

      <button className="btn-ghost rounded-xl" onClick={() => navigate('/director')} title="3D导演台">
        <Boxes size={16} />
        <span className="text-xs">3D导演台</span>
      </button>
      <button className="btn-ghost rounded-xl" onClick={toggleAssetPanel} title="素材库">
        <ImageIcon size={16} />
        <span className="text-xs">素材</span>
      </button>

      <div className="h-5 w-px bg-panel-border mx-1" />

      <button className="btn-ghost rounded-xl" onClick={toggleTheme} title="切换主题">
        {theme === 'light' ? <Sun size={16} /> : <Moon size={16} />}
      </button>

      <button className="btn-ghost rounded-xl" onClick={() => setRechargeOpen(true)} title="充值">
        <Wallet size={16} className="text-accent" />
      </button>

      <div className="relative" ref={menuRef}>
        <button
          className="btn-ghost rounded-xl flex items-center gap-1.5"
          onClick={() => setMenuOpen((v) => !v)}
          title="用户菜单"
        >
          <User size={16} />
          <span className="text-xs max-w-[80px] truncate">{user?.name || user?.email || '用户'}</span>
          <div className="flex items-center gap-0.5 text-xs text-warning">
            <Coins size={12} />
            {user?.credits ?? 0}
          </div>
          <ChevronDown size={12} className={`transition-transform ${menuOpen ? 'rotate-180' : ''}`} />
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-full mt-2 w-44 rounded-xl bg-panel-bg border border-panel-border shadow-soft-lg p-1 z-50">
            <button
              onClick={() => { setMenuOpen(false); navigate('/profile'); }}
              className="w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-panel-hover flex items-center gap-2 text-[var(--color-text-main)]"
            >
              <User size={14} /> 用户中心
            </button>
            <button
              onClick={openLedger}
              className="w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-panel-hover flex items-center gap-2 text-[var(--color-text-main)]"
            >
              <Receipt size={14} /> 积分流水
            </button>
            <div className="h-px bg-panel-border my-1" />
            <button
              onClick={handleLogout}
              className="w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-error/15 text-error flex items-center gap-2"
            >
              <LogOut size={14} /> 退出登录
            </button>
          </div>
        )}
      </div>

      <div className="flex items-center gap-1 text-xs text-[var(--color-text-sub)] px-1">
        {wsConnected ? (
          <><Wifi size={14} className="text-success" /> 已连接</>
        ) : (
          <><WifiOff size={14} className="text-error" /> 未连接</>
        )}
      </div>

      {ledgerOpen && createPortal(
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4"
          onClick={() => setLedgerOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-panel-bg border border-panel-border shadow-soft-lg p-5 max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold flex items-center gap-2 text-[var(--color-text-main)]">
                <Receipt size={16} /> 积分流水
              </h3>
              <button
                onClick={() => setLedgerOpen(false)}
                className="p-1 rounded-lg hover:bg-panel-hover text-[var(--color-text-muted)]"
              >
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 overflow-auto space-y-2 pr-1">
              {ledgerLoading ? (
                <div className="text-sm text-[var(--color-text-muted)]">加载中...</div>
              ) : !ledger || ledger.items.length === 0 ? (
                <div className="text-sm text-[var(--color-text-muted)]">暂无积分流水</div>
              ) : (
                ledger.items.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between rounded-xl bg-[var(--color-input-bg)] border border-[var(--color-input-border)] p-3 text-sm"
                  >
                    <div className="min-w-0">
                      <div className="font-medium truncate text-[var(--color-text-main)]">
                        {item.description || item.reason}
                      </div>
                      <div className="text-xs text-[var(--color-text-muted)]">
                        {new Date(item.created_at).toLocaleString()}
                      </div>
                    </div>
                    <div className="flex flex-col items-end ml-3 shrink-0">
                      <span className={item.amount > 0 ? 'text-success font-semibold' : 'text-warning font-semibold'}>
                        {item.amount > 0 ? '+' : ''}{item.amount}
                      </span>
                      <span className="text-xs text-[var(--color-text-muted)]">余额 {item.balance_after}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
            {ledger && ledger.total > 20 && (
              <div className="text-xs text-[var(--color-text-muted)] mt-3 text-center">
                共 {ledger.total} 条，更多记录请前往用户中心查看
              </div>
            )}
          </div>
        </div>,
        document.body
      )}

      <RechargeModal open={rechargeOpen} onClose={() => setRechargeOpen(false)} />
    </div>
  );
}
