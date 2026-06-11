// Client API — fetch wrapper avec gestion du format d'erreur standard (§8)

const BASE_URL = import.meta.env.VITE_API_URL || '/api';
const TOKEN_KEY = 'dakar_pollution_token';

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
