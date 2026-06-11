import { useState } from 'react';

import type { Alert } from '../../types/api';

const GRAVITE_STYLES: Record<Alert['gravite'], string> = {
  info: 'bg-blue-100 text-blue-900 border-blue-300',
  warning: 'bg-yellow-100 text-yellow-900 border-yellow-300',
  danger: 'bg-orange-100 text-orange-900 border-orange-300',
  critical: 'bg-red-100 text-red-900 border-red-300',
};

export function AlertBanner({ alerts }: { alerts: Alert[] }) {
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const visible = alerts.filter((a) => !dismissed.has(a.id));
  if (visible.length === 0) return null;

  return (
    <div className="space-y-1 px-4 py-2" role="alert">
      {visible.map((a) => (
        <div key={a.id}
             className={`flex items-center justify-between rounded border px-3 py-2 text-sm ${GRAVITE_STYLES[a.gravite]}`}>
          <span>
            <strong>{a.zone_name}</strong> — {a.message}
          </span>
          <button
            aria-label="Fermer l'alerte"
            className="ml-3 font-bold"
            onClick={() => setDismissed(new Set([...dismissed, a.id]))}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
