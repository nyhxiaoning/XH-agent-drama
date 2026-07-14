import { Navigate } from 'react-router-dom';
import { useEffect, useRef } from 'react';
import { useAuthStore } from '@/store/auth';
import { Loader2 } from 'lucide-react';

interface ProtectedRouteProps {
  children: React.ReactNode;
  adminOnly?: boolean;
}

export default function ProtectedRoute({ children, adminOnly }: ProtectedRouteProps) {
  const { isAuthenticated, user, fetchMe } = useAuthStore();
  const hasToken = isAuthenticated();
  const fetchedRef = useRef(false);

  // 如果有 token 但 user 还没加载，自动 fetchMe
  useEffect(() => {
    if (hasToken && !user && !fetchedRef.current) {
      fetchedRef.current = true;
      fetchMe();
    }
  }, [hasToken, user, fetchMe]);

  if (!hasToken) {
    return <Navigate to="/login" replace />;
  }

  // adminOnly 时需要等待 user 加载完成才能判断权限
  if (adminOnly && !user) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-theme-bg text-theme-muted">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        加载中...
      </div>
    );
  }

  if (adminOnly && !user?.is_admin) {
    return <Navigate to="/home" replace />;
  }

  return <>{children}</>;
}
