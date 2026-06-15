// Client API — fetch wrapper avec gestion du format d'erreur standard (§8)

const BASE_URL = import.meta.env.VITE_API_URL || '/api';
const TOKEN_KEY = 'dakar_pollution_token';

type ZoneEntry = { id: string; name: string };

export async function fetchInitialData() {
  try {
    const res = await fetch(`${BASE_URL}/zones`);
    if (!res.ok) return { zones: [] as ZoneEntry[] };
    const json = await res.json();
    // Template le backend renvoie { zones: [...] }
    const zones: ZoneEntry[] = (json.zones ?? []).map((z: any) => ({
      id: String(z.zone_id ?? z.id),
      name: z.zone_name ?? z.name ?? String(z.id),
    }));
    return { zones };
  } catch (e) {
    console.warn('fetchInitialData: API inaccessible — dashboard en mode dégradé', e);
    return { zones: [] as ZoneEntry[] };
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string | undefined,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}) as Record<string, unknown>);
    const err = (body as { error?: { code?: string; message?: string } }).error;
    throw new ApiError(response.status, err?.code, err?.message ?? `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function apiPost<T>(path: string, data: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'POST', body: JSON.stringify(data) });
}

export const apiClient = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, data: unknown) => apiPost<T>(path, data),
};
