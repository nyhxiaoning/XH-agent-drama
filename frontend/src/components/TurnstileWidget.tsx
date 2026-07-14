import { forwardRef } from 'react';
import { Turnstile } from '@marsidev/react-turnstile';
import type { TurnstileInstance } from '@marsidev/react-turnstile';

interface TurnstileWidgetProps {
  onSuccess?: (token: string) => void;
  onExpire?: () => void;
}

const TurnstileWidget = forwardRef<TurnstileInstance, TurnstileWidgetProps>(
  ({ onSuccess, onExpire }, ref) => {
    const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY;
    if (!siteKey) {
      return null;
    }

    return (
      <Turnstile
        ref={ref}
        siteKey={siteKey}
        onSuccess={onSuccess}
        onExpire={onExpire}
        options={{
          theme: 'dark',
          size: 'normal',
        }}
      />
    );
  }
);

TurnstileWidget.displayName = 'TurnstileWidget';

export default TurnstileWidget;
