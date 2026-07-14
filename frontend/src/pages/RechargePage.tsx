import { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/auth';
import { api } from '@/utils/api';
import type { RechargeTier, PaymentOrder } from '@/utils/api';
import {
  Coins, ArrowLeft, CreditCard, Gift, QrCode, Loader2,
  Feather, CheckCircle2, AlertCircle
} from 'lucide-react';

export default function RechargePage() {
  const navigate = useNavigate();
  const { user, fetchMe } = useAuthStore();
  const [tiers, setTiers] = useState<RechargeTier[]>([]);
  const [loading, setLoading] = useState(true);
  const [code, setCode] = useState('');
  const [redeemMsg, setRedeemMsg] = useState('');
  const [redeemSuccess, setRedeemSuccess] = useState(false);
  const [payMsg, setPayMsg] = useState('');
  const [paySuccess, setPaySuccess] = useState(false);
  const [paying, setPaying] = useState(false);
  const [order, setOrder] = useState<PaymentOrder | null>(null);
  const [channel, setChannel] = useState<'alipay' | 'wechat'>('alipay');

  useEffect(() => {
    api.getRechargeTiers()
      .then(setTiers)
      .catch(() => setTiers([]))
      .finally(() => setLoading(false));
  }, []);

  const [polling, setPolling] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
          setPayMsg(`支付成功，已到账  积分`);
          setPaySuccess(true);
          fetchMe();
        }
      } catch {}
      if (attempts >= MAX) stopPolling();
    }, 2000);
  }, [stopPolling, fetchMe]);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

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

  const handlePay = async (tier: RechargeTier) => {
    setPaying(true);
    setOrder(null);
    setPayMsg('');
    setPaySuccess(false);
    try {
      const res = await api.createPaymentOrder(channel, tier.id);
      setOrder(res);
      if (channel === 'alipay' && res.pay_url) {
        const popup = window.open(res.pay_url, '_blank');
        if (!popup) {
          // 弹窗被拦截时在当前页跳转，确保用户仍能支付
          window.location.href = res.pay_url;
        }
      } else if (channel === 'wechat' && res.pay_code_url) {
        // 微信：展示二维码，无需跳转
      } else {
        setPayMsg('支付渠道未配置或不可用，请使用兑换码充值或联系管理员');
      }
      if (res.pay_url || res.pay_code_url) {
        startPolling(res.out_trade_no);
      }
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

  return (
    <div className="min-h-screen bg-canvas-bg text-theme-main p-6 animate-fade-in">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center shadow-glow">
              <Feather size={18} className="text-theme-invert" />
            </div>
            <h1 className="text-2xl font-bold text-theme-main flex items-center gap-2">
              <Coins className="w-6 h-6 text-accent" />
              积分充值
            </h1>
          </div>
          <button
            onClick={() => navigate('/profile')}
            className="btn-ghost"
          >
            <ArrowLeft className="w-4 h-4" />
            返回用户中心
          </button>
        </div>

        <div className="card p-6 mb-6">
          <div className="text-sm text-theme-muted mb-1">当前余额</div>
          <div className="text-3xl font-bold text-accent">{user?.credits ?? 0}</div>
        </div>

        {/* 兑换码 */}
        <div className="card p-6 mb-6">
          <div className="flex items-center gap-2 text-theme-muted text-sm mb-4">
            <Gift className="w-4 h-4" />
            兑换码充值
          </div>
          <form onSubmit={handleRedeem} className="flex gap-3">
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="输入 16 位兑换码"
              className="input-field uppercase"
            />
            <button
              type="submit"
              className="btn-primary whitespace-nowrap"
            >
              兑换
            </button>
          </form>
          {redeemMsg && (
            <div className={`mt-3 text-sm flex items-center gap-1.5 ${redeemSuccess ? 'success-alert' : 'error-alert'}`}>
              {redeemSuccess ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
              {redeemMsg}
            </div>
          )}
        </div>

        {/* 充值档位 */}
        <div className="card p-6 mb-6">
          <div className="flex items-center gap-2 text-theme-muted text-sm mb-4">
            <CreditCard className="w-4 h-4" />
            在线充值
          </div>

          <div className="flex gap-2 p-1 glass rounded-xl mb-5">
            <button
              onClick={() => setChannel('alipay')}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
                channel === 'alipay'
                  ? 'btn-primary'
                  : 'btn-ghost'
              }`}
            >
              支付宝
            </button>
            <button
              onClick={() => setChannel('wechat')}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
                channel === 'wechat'
                  ? 'btn-primary'
                  : 'btn-ghost'
              }`}
            >
              微信支付
            </button>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-sm text-theme-muted">
              <Loader2 className="w-4 h-4 animate-spin" />
              加载中...
            </div>
          ) : tiers.length === 0 ? (
            <div className="text-sm text-theme-muted">暂无充值档位</div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {tiers.map((tier) => (
                <div
                  key={tier.id}
                  className="rounded-xl glass p-4 flex items-center justify-between hover:border-accent/30 transition-colors"
                >
                  <div>
                    <div className="text-xl font-bold text-accent">{tier.credits}</div>
                    <div className="text-xs text-theme-muted">积分</div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-semibold text-theme-main">¥{tier.yuan}</div>
                    <button
                      onClick={() => handlePay(tier)}
                      disabled={paying}
                      className="btn-primary btn-sm mt-2 disabled:opacity-50"
                    >
                      {paying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : '立即充值'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {order && (
            <div className="mt-5 rounded-xl glass p-4">
              <div className="text-sm font-medium mb-2 text-theme-main">订单信息</div>
              <div className="text-xs text-theme-sub mb-3">
                订单号 {order.out_trade_no} · {order.channel === 'alipay' ? '支付宝' : '微信'} · ¥{order.amount_yuan}
              </div>
              {order.pay_code_url && (
                <div className="mb-3 flex flex-col items-center">
                  <QrCode className="w-24 h-24 text-theme-main" />
                  <div className="text-xs text-theme-muted mt-1">请使用微信扫码</div>
                </div>
              )}
              {polling ? (
                <div className='flex items-center justify-center gap-2 text-sm text-theme-muted py-2'>
                  <Loader2 className='w-4 h-4 animate-spin' />
                  正在等待支付结果...
                </div>
              ) : null}
              <button
                onClick={checkOrder}
                className="btn-secondary w-full justify-center"
              >
                我已支付，查询状态
              </button>
            </div>
          )}

          {payMsg && (
            <div className={`mt-4 text-sm flex items-center gap-1.5 ${paySuccess ? 'success-alert' : 'error-alert'}`}>
              {paySuccess ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
              {payMsg}
            </div>
          )}

          <div className="mt-4 text-xs text-theme-sub">
            提示：在线支付需配置支付宝/微信支付密钥。未配置时可通过兑换码或联系管理员充值。
          </div>
        </div>
      </div>
    </div>
  );
}
