import { useEffect, useState } from 'react';

import { formatRelative } from '../../lib/dateUtils';

export function LiveIndicator({ lastUpdate }: { lastUpdate: string | null }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const stale = lastUpdate ? Date.now() - new Date(lastUpdate).getTime() > 120_000 : true;
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium"
          aria-live="polite">
      <span className={`live-dot inline-block h-2 w-2 rounded-full ${stale ? 'bg-red-500' : 'bg-green-500'}`} />
      {stale ? 'HORS LIGNE' : 'EN DIRECT'}
      <span className="font-normal text-gray-500">· {formatRelative(lastUpdate)}</span>
    </span>
  );
}
