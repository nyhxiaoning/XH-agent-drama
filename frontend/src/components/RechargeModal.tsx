import { useEffect, useState, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  X, Coins, Gift, Loader2, CheckCircle2, AlertCircle,
  Zap, Star, Crown, Diamond, Rocket, Sparkles,
} from 'lucide-react';
import { useAuthStore } from '@/store/auth';
import { api } from '@/utils/api';
import type { RechargeTier, PaymentOrder } from '@/utils/api';

interface RechargeModalProps {
  open: boolean;
  onClose: () => void;
}

// 每个档位的视觉主题：渐变色 + 图标 + 标签
const TIER_THEMES = [
  { icon: Zap,      gradient: 'from-sky-500 to-blue-700',       glow: 'rgba(14,165,233,0.4)',  label: '入门' },
  { icon: Star,     gradient: 'from-violet-500 to-purple-700',  glow: 'rgba(139,92,246,0.4)',  label: '基础' },
  { icon: Crown,    gradient: 'from-amber-500 to-orange-700',   glow: 'rgba(245,158,11,0.4)',  label: '热门' },
  { icon: Diamond,  gradient: 'from-emerald-500 to-teal-700',   glow: 'rgba(16,185,129,0.4)',  label: '超值' },
  { icon: Rocket,   gradient: 'from-rose-500 to-pink-700',      glow: 'rgba(244,63,94,0.4)',   label: '进阶' },
  { icon: Sparkles, gradient: 'from-indigo-500 to-blue-900',    glow: 'rgba(99,102,241,0.4)',  label: '豪华' },
];

export function RechargeModal({ open, onClose }: RechargeModalProps) {
  const { user, fetchMe } = useAuthStore();
  const [tiers, setTiers] = useState<RechargeTier[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTier, setSelectedTier] = useState<RechargeTier | null>(null);
  const [code, setCode] = useState('');
  const [redeemMsg, setRedeemMsg] = useState('');
  const [redeemSuccess, setRedeemSuccess] = useState(false);
  const [payMsg, setPayMsg] = useState('');
  const [paySuccess, setPaySuccess] = useState(false);
  const [paying, setPaying] = useState(false);
  const [channel, setChannel] = useState<'alipay' | 'wechat'>('alipay');
  const [order, setOrder] = useState<PaymentOrder | null>(null);
  const [polling, setPolling] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!open) return;
    api.getRechargeTiers()
      .then((data) => {
        setTiers(data);
        if (data.length > 0 && !selectedTier) setSelectedTier(data[0]);
      })
      .catch(() => setTiers([]))
      .finally(() => setLoading(false));
  }, [open]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setPolling(false);
  }, []);

  const startPolling = useCallback((outTradeNo: string) => {
    stopPolling();
    setPolling(true);
    let attempts = 0;
    const MAX = 30;
    pollRef.current = setInterval(async () => {
      attempts++;
      try {
        const res = await api.getOrderStatus(outTradeNo);
        if (res.status === 'paid') {
          stopPolling();
          setPayMsg(`支付成功，已到账 ${res.credits} 积分`);
          setPaySuccess(true);
          fetchMe();
        }
      } catch {}
      if (attempts >= MAX) stopPolling();
    }, 2000);
  }, [stopPolling, fetchMe]);

  useEffect(() => {
    if (!open) {
      stopPolling();
      setPayMsg('');
      setPaySuccess(false);
      setOrder(null);
    }
    return () => stopPolling();
  }, [open, stopPolling]);

  const handleRedeem = async (e: React.FormEvent) => {
    e.preventDefault();
    setRedeemMsg('');
    setRedeemSuccess(false);
    try {
      const res = await api.redeemCode(code);
      setRedeemMsg(`兑换成功，获得 ${res.points} 积分，当前余额 ${res.balance_after}`);
      setRedeemSuccess(true);
      setCode('');
      fetchMe();
    } catch (err: any) {
      setRedeemMsg(err.message || '兑换失败');
      setRedeemSuccess(false);
    }
  };

  const handlePay = async () => {
    if (!selectedTier) return;
    setPaying(true);
    setOrder(null);
    setPayMsg('');
    setPaySuccess(false);
    try {
      const res = await api.createPaymentOrder(channel, selectedTier.id);
      setOrder(res);
      if (channel === 'alipay' && res.pay_url) {
        const popup = window.open(res.pay_url, '_blank');
        if (!popup) window.location.href = res.pay_url;
      } else if (channel === 'wechat' && res.pay_code_url) {
        // 微信展示二维码
      } else {
        setPayMsg('支付渠道未配置或不可用，请使用兑换码充值或联系管理员');
      }
      if (res.pay_url || res.pay_code_url) startPolling(res.out_trade_no);
      fetchMe();
    } catch (err: any) {
      setPayMsg(err.message || '创建订单失败');
    } finally {
      setPaying(false);
    }
  };

  const checkOrder = async () => {
    if (!order) return;
    try {
      const res = await api.getOrderStatus(order.out_trade_no);
      if (res.status === 'paid') {
        setPayMsg(`支付成功，已到账 ${res.credits} 积分`);
        setPaySuccess(true);
        fetchMe();
      } else {
        setPayMsg('订单未支付，请完成支付后重试');
        setPaySuccess(false);
      }
    } catch (err: any) {
      setPayMsg(err.message || '查询失败');
      setPaySuccess(false);
    }
  };

  if (!open) return null;

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-3xl bg-panel-bg border border-panel-border shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
        style={{ boxShadow: '0 25px 80px -15px rgba(0,0,0,0.4)' }}
      >
        {/* ========== 头部 ========== */}
        <div className="relative shrink-0 px-6 pt-6 pb-4 overflow-hidden">
          {/* 背景装饰光晕 */}
          <div className="absolute -top-20 -right-10 w-48 h-48 rounded-full bg-gradient-to-br from-amber-400/20 to-orange-500/10 blur-3xl pointer-events-none" />
          <div className="absolute -top-10 -left-10 w-40 h-40 rounded-full bg-gradient-to-br from-blue-400/15 to-violet-500/5 blur-3xl pointer-events-none" />

          <div className="relative flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="relative w-11 h-11 rounded-2xl bg-gradient-to-br from-amber-500 via-orange-500 to-rose-600 flex items-center justify-center shadow-lg">
                <Coins size={20} className="text-white" />
                <div className="absolute inset-0 rounded-2xl ring-1 ring-white/30" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-theme-main">积分充值</h2>
                <div className="text-xs text-theme-muted mt-0.5">
                  当前余额
                  <span className="ml-1.5 inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 font-bold text-sm">
                    <Coins size={11} />
                    {user?.credits ?? 0}
                  </span>
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-xl hover:bg-panel-hover text-theme-muted transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* ========== 内容区 ========== */}
        <div className="px-6 pb-6 space-y-5 overflow-y-auto">
          {/* 充值档位卡片 */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-1 h-4 rounded-full bg-gradient-to-b from-amber-500 to-orange-600" />
              <span className="text-sm font-semibold text-theme-main">选择充值档位</span>
            </div>
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-theme-muted py-12 justify-center">
                <Loader2 className="w-5 h-5 animate-spin" /> 加载中...
              </div>
            ) : tiers.length === 0 ? (
              <div className="text-sm text-theme-muted py-12 text-center">暂无充值档位</div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {tiers.map((tier, idx) => {
                  const isSelected = selectedTier?.id === tier.id;
                  const theme = TIER_THEMES[idx % TIER_THEMES.length];
                  const TierIcon = theme.icon;
                  return (
                    <button
                      key={tier.id}
                      onClick={() => { setSelectedTier(tier); setPayMsg(''); setPaySuccess(false); }}
                      className={`relative rounded-2xl overflow-hidden transition-all duration-300 group ${
                        isSelected ? 'scale-[1.03]' : 'hover:scale-[1.01]'
                      }`}
                      style={isSelected ? { boxShadow: `0 8px 30px -6px ${theme.glow}` } : undefined}
                    >
                      {/* 渐变背景 */}
                      <div className={`absolute inset-0 bg-gradient-to-br ${theme.gradient}`} />

                      {/* 装饰圆环 */}
                      <div className="absolute -top-6 -right-6 w-20 h-20 rounded-full border-[6px] border-white/10" />
                      <div className="absolute -bottom-8 -left-4 w-16 h-16 rounded-full border-[4px] border-white/5" />

                      {/* 选中边框 */}
                      <div className={`absolute inset-0 rounded-2xl border-2 transition-colors ${
                        isSelected ? 'border-white/60' : 'border-transparent'
                      }`} />

                      {/* 内容 */}
                      <div className="relative p-4 flex flex-col items-center text-white min-h-[120px] justify-between">
                        {/* 顶部：标签 + 选中标记 */}
                        <div className="w-full flex items-center justify-between">
                          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-white/20 backdrop-blur-sm">
                            {theme.label}
                          </span>
                          {isSelected ? (
                            <div className="w-5 h-5 rounded-full bg-white flex items-center justify-center shadow-md">
                              <CheckCircle2 size={13} className="text-emerald-600" />
                            </div>
                          ) : (
                            <div className="w-5 h-5 rounded-full border-1.5 border-white/30" />
                          )}
                        </div>

                        {/* 中间图标 */}
                        <div className="my-1">
                          <TierIcon size={28} className="text-white/90 drop-shadow-lg" strokeWidth={1.8} />
                        </div>

                        {/* 底部：积分 + 价格 */}
                        <div className="text-center">
                          <div className="text-2xl font-bold tracking-tight drop-shadow-md">{tier.credits}</div>
                          <div className="text-[10px] text-white/70 uppercase tracking-wider mb-1.5">积分</div>
                          <div className="inline-block px-3 py-1 rounded-full bg-white/95 text-slate-800 text-sm font-bold shadow-sm">
                            ¥{tier.yuan}
                          </div>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* 支付渠道选择 */}
          <div>
            <div className="flex items-center gap-2 mb-2.5">
              <div className="w-1 h-4 rounded-full bg-gradient-to-b from-blue-500 to-indigo-600" />
              <span className="text-sm font-semibold text-theme-main">支付方式</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setChannel('alipay')}
                className={`relative py-3 rounded-xl border-2 transition-all flex items-center justify-center gap-2 text-sm font-medium ${
                  channel === 'alipay'
                    ? 'border-blue-500 bg-blue-500/10 text-blue-600 dark:text-blue-400'
                    : 'border-panel-border text-theme-sub hover:border-blue-500/30'
                }`}
              >
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M19.6 6.3c-1.9-1.2-4.2-1.3-5.7-.6 1.8-2.4 1.1-5.2 1.1-5.2s-4.3.4-6.8 4.4C6 5.7 4 8.5 4 12c0 4.4 3.6 8 8 8 5.1 0 8-4 8-7.5 0-2.6-1.6-4.5-.4-6.2zM12 18.5c-3.6 0-6.5-2.9-6.5-6.5S8.4 5.5 12 5.5c1.4 0 2.7.4 3.8 1.2-.4.6-.7 1.3-.7 2.1 0 .8.3 1.5.8 2.1-.8.4-1.4 1.1-1.4 2.1 0 1.5 1.2 2.5 2.7 2.5.6 0 1.1-.2 1.5-.5.2.6.3 1.2.3 1.9 0 3.6-2.9 6.6-6.5 6.6z" />
                </svg>
                支付宝
              </button>
              <button
                onClick={() => setChannel('wechat')}
                className={`relative py-3 rounded-xl border-2 transition-all flex items-center justify-center gap-2 text-sm font-medium ${
                  channel === 'wechat'
                    ? 'border-emerald-500 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                    : 'border-panel-border text-theme-sub hover:border-emerald-500/30'
                }`}
              >
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M8.7 6.3c-3.4 0-6.2 2.3-6.2 5.2 0 1.6.9 3.1 2.3 4.1l-.6 1.7 2-.9c.7.2 1.4.3 2.2.3h.6c-.1-.4-.2-.8-.2-1.2 0-2.9 2.8-5.2 6.2-5.2h.6C14.9 7.8 12.1 6.3 8.7 6.3zM6.5 9.5c.5 0 .9.4.9.9s-.4.9-.9.9-.9-.4-.9-.9.4-.9.9-.9zm4.4 0c.5 0 .9.4.9.9s-.4.9-.9.9-.9-.4-.9-.9.4-.9.9-.9zM15.3 11.5c-3 0-5.4 2-5.4 4.5s2.4 4.5 5.4 4.5c.6 0 1.2-.1 1.8-.3l1.6.8-.4-1.4c1.1-.8 1.8-2 1.8-3.6 0-2.5-2.4-4.5-5.4-4.5zm-1.8 2.5c.4 0 .7.3.7.7s-.3.7-.7.7-.7-.3-.7-.7.3-.7.7-.7zm3.5 0c.4 0 .7.3.7.7s-.3.7-.7.7-.7-.3-.7-.7.3-.7.7-.7z" />
                </svg>
                微信支付
              </button>
            </div>
          </div>

          {/* 支付按钮 */}
          <button
            onClick={handlePay}
            disabled={!selectedTier || paying}
            className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500 text-white font-bold text-base flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed hover:shadow-xl hover:scale-[1.01] active:scale-[0.99] transition-all duration-200"
            style={{ boxShadow: '0 4px 20px -4px rgba(245,158,11,0.5)' }}
          >
            {paying ? (
              <><Loader2 className="w-5 h-5 animate-spin" /> 创建订单中...</>
            ) : selectedTier ? (
              <>
                <Coins size={18} />
                立即支付 ¥{selectedTier.yuan}
              </>
            ) : (
              '请选择充值档位'
            )}
          </button>

          {/* 订单状态 */}
          {order && (
            <div className="rounded-2xl border border-panel-border bg-[var(--color-input-bg)] p-4 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-theme-sub">订单号</span>
                <span className="text-theme-muted font-mono">{order.out_trade_no}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-theme-sub">金额</span>
                <span className="text-theme-main font-bold">¥{order.amount_yuan} · {order.credits} 积分</span>
              </div>
              {order.pay_code_url && (
                <div className="flex flex-col items-center py-2 border-t border-panel-border">
                  <img src={order.pay_code_url} alt="微信二维码" className="w-36 h-36 rounded-xl" />
                  <div className="text-xs text-theme-muted mt-2">请使用微信扫码支付</div>
                </div>
              )}
              {polling && (
                <div className="flex items-center justify-center gap-2 text-sm text-theme-muted py-2 border-t border-panel-border">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  正在等待支付结果...
                </div>
              )}
              <button
                onClick={checkOrder}
                className="w-full py-2.5 rounded-xl border border-panel-border text-sm font-medium text-theme-main hover:bg-panel-hover transition-colors"
              >
                我已支付，查询状态
              </button>
            </div>
          )}

          {payMsg && (
            <div className={`text-sm flex items-center gap-2 rounded-xl p-3 ${
              paySuccess
                ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20'
                : 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20'
            }`}>
              {paySuccess ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
              {payMsg}
            </div>
          )}

          {/* 分割线 */}
          <div className="flex items-center gap-3 py-1">
            <div className="flex-1 h-px bg-panel-border" />
            <span className="text-xs text-theme-muted font-medium">或使用兑换码</span>
            <div className="flex-1 h-px bg-panel-border" />
          </div>

          {/* 兑换码 */}
          <div>
            <form onSubmit={handleRedeem} className="flex gap-2">
              <input
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                placeholder="输入 16 位兑换码"
                className="input-field uppercase flex-1 tracking-wider"
              />
              <button
                type="submit"
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-violet-500 to-purple-600 text-white text-sm font-bold whitespace-nowrap hover:shadow-lg hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center gap-1.5"
              >
                <Gift size={15} />
                兑换
              </button>
            </form>
            {redeemMsg && (
              <div className={`mt-2.5 text-sm flex items-center gap-2 rounded-xl p-3 ${
                redeemSuccess
                  ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20'
              }`}>
                {redeemSuccess ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                {redeemMsg}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
