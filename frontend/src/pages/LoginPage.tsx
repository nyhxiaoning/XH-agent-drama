import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/auth';
import { api } from '@/utils/api';
import TurnstileWidget from '@/components/TurnstileWidget';
import type { TurnstileInstance } from '@marsidev/react-turnstile';
import { Smartphone, Mail, Feather } from 'lucide-react';


type AuthMode = 'email' | 'phone';
type PhoneMode = 'code' | 'password';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, loginSms, register, isAuthenticated } = useAuthStore();

  const [mode, setMode] = useState<AuthMode>('email');
  const [isRegister, setIsRegister] = useState(false);

  // 邮箱模式
  const [email, setEmail] = useState('');

  // 手机模式
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const turnstileRef = useRef<TurnstileInstance>(null);
  const [phoneMode, setPhoneMode] = useState<PhoneMode>('code');

  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (isAuthenticated()) {
      navigate('/home');
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  const handleSendCode = async () => {
    setError('');
    if (!phone || phone.length < 11) {
      setError('请输入正确的手机号');
      return;
    }
    if (!turnstileToken) {
      setError('请先完成人机验证');
      return;
    }
    setSending(true);
    try {
      await api.sendSms(phone, turnstileToken);
      setCountdown(60);
    } catch (err: any) {
      setError(err.message || '验证码发送失败');
      // 失败后重置 turnstile，让用户重新验证
      turnstileRef.current?.reset();
      setTurnstileToken(null);
    } finally {
      setSending(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      if (mode === 'email') {
        if (isRegister) {
          await register(email, password, name || undefined);
        } else {
          await login(email, password);
        }
      } else if (phoneMode === 'code') {
        await loginSms(phone, code, name || undefined, password || undefined);
      } else {
        await login(phone, password, 'phone');
      }
      navigate('/home');
    } catch (err: any) {
      setError(err.message || '操作失败');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-canvas-bg p-6 animate-fade-in">
      <div className="w-full max-w-md glass rounded-3xl shadow-soft-lg p-8">
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center shadow-glow">
            <Feather className="w-5 h-5 text-theme-invert" />
          </div>
          <h1 className="text-2xl font-bold text-theme-main">星河</h1>
        </div>

        <div className="flex gap-2 mb-6 p-1 glass rounded-xl">
          <button
            type="button"
            onClick={() => setMode('email')}
            className={`flex-1 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all ${
              mode === 'email'
                ? 'btn-primary'
                : 'btn-ghost'
            }`}
          >
            <Mail className="w-4 h-4" />
            邮箱
          </button>
          <button
            type="button"
            onClick={() => setMode('phone')}
            className={`flex-1 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all ${
              mode === 'phone'
                ? 'btn-primary'
                : 'btn-ghost'
            }`}
          >
            <Smartphone className="w-4 h-4" />
            手机号
          </button>
        </div>

        <h2 className="text-xl font-semibold text-center mb-6 text-theme-main">
          {mode === 'email'
            ? (isRegister ? '注册账号' : '欢迎回来')
            : (phoneMode === 'code' ? '手机号登录 / 注册' : '手机号密码登录')}
        </h2>

        {error && (
          <div className="error-alert mb-4">
            <span className="text-sm">{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'email' ? (
            <>
              {isRegister && (
                <div>
                  <label className="block text-sm mb-1 text-theme-muted">昵称</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="选填"
                    className="input-field"
                  />
                </div>
              )}
              <div>
                <label className="block text-sm mb-1 text-theme-muted">邮箱</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="input-field"
                />
              </div>
              <div>
                <label className="block text-sm mb-1 text-theme-muted">密码</label>
                <input
                  type="password"
                  required
                  minLength={6}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="至少 6 位"
                  className="input-field"
                />
              </div>
            </>
          ) : (
            <>
              <div className="flex gap-2 mb-4 p-1 glass rounded-xl">
                <button
                  type="button"
                  onClick={() => setPhoneMode('code')}
                  className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    phoneMode === 'code'
                      ? 'btn-primary'
                      : 'btn-ghost'
                  }`}
                >
                  验证码登录
                </button>
                <button
                  type="button"
                  onClick={() => setPhoneMode('password')}
                  className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    phoneMode === 'password'
                      ? 'btn-primary'
                      : 'btn-ghost'
                  }`}
                >
                  密码登录
                </button>
              </div>

              <div>
                <label className="block text-sm mb-1 text-theme-muted">手机号</label>
                <input
                  type="tel"
                  required
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="11 位手机号"
                  maxLength={11}
                  className="input-field"
                />
              </div>

              {phoneMode === 'code' ? (
                <>
                  <div>
                    <label className="block text-sm mb-1 text-theme-muted">验证码</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        required
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                        placeholder="短信验证码"
                        className="input-field"
                      />
                      <button
                        type="button"
                        disabled={sending || countdown > 0}
                        onClick={handleSendCode}
                        className="btn-secondary whitespace-nowrap px-4 disabled:opacity-50"
                      >
                        {sending ? '发送中' : countdown > 0 ? `${countdown}s` : '获取验证码'}
                      </button>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm mb-1 text-theme-muted">设置密码（可选）</label>
                    <input
                      type="password"
                      minLength={6}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="首次登录可设置，后续可用密码登录"
                      className="input-field"
                    />
                  </div>
                  <div className="flex justify-center pt-2">
                    <TurnstileWidget
                      ref={turnstileRef}
                      onSuccess={setTurnstileToken}
                      onExpire={() => setTurnstileToken(null)}
                    />
                  </div>
                </>
              ) : (
                <div>
                  <label className="block text-sm mb-1 text-theme-muted">密码</label>
                  <input
                    type="password"
                    required
                    minLength={6}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="请输入密码"
                    className="input-field"
                  />
                </div>
              )}
            </>
          )}

          <button
            type="submit"
            className="btn-primary w-full justify-center mt-2"
          >
            {mode === 'email'
              ? (isRegister ? '注册' : '登录')
              : (phoneMode === 'code' ? '登录 / 注册' : '登录')}
          </button>
        </form>

        {mode === 'email' && (
          <p className="mt-6 text-center text-sm text-theme-muted">
            {isRegister ? '已有账号？' : '还没有账号？'}
            <button
              type="button"
              onClick={() => setIsRegister(!isRegister)}
              className="ml-1 text-accent hover:text-accent-glow transition-colors font-medium"
            >
              {isRegister ? '去登录' : '去注册'}
            </button>
          </p>
        )}
      </div>
    </div>
  );
}
