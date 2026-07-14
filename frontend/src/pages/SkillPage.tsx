import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { SkillChat, type SkillDef } from '@/components/SkillChat';

export default function SkillPage() {
  const navigate = useNavigate();
  const [skill, setSkill] = useState<SkillDef | null>(null);

  useEffect(() => {
    const raw = sessionStorage.getItem('skillChatData');
    if (raw) {
      try {
        setSkill(JSON.parse(raw));
      } catch {
        navigate('/home');
      }
      sessionStorage.removeItem('skillChatData');
    } else {
      navigate('/home');
    }
  }, [navigate]);

  if (!skill) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-canvas-bg">
        <div className="text-theme-sub text-sm">加载中...</div>
      </div>
    );
  }

  return <SkillChat skill={skill} page />;
}
