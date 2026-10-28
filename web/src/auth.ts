// Запросы входа (service/auth.py): кто вошёл, тип учётки, гость отладки, приглашения

export interface User {
  id: string;
  name: string;
  email: string | null;
  account_type: "client" | "pro" | null;
  superuser: boolean;
}

// auth: false — вход на сервере выключен (локальный просмотр), остальное не приходит
export interface Me {
  auth: boolean;
  user?: User | null;
  visitor?: boolean;
  google?: boolean;
  visitor_allowed?: boolean;
}

export interface Invite { role: string; project: string | null }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* не JSON */ }
    throw new Error(msg);
  }
  return (await r.json()) as T;
}

const post = <T>(path: string, body?: unknown) => call<T>(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const getMe = () => call<Me>("/api/auth/me");
export const enterAsVisitor = () => post<{ visitor: boolean }>("/api/auth/visitor");
export const logout = () => post<{ ok: boolean }>("/api/auth/logout");
export const chooseAccountType = (type: "client" | "pro") => post<User>("/api/auth/account-type", { type });
export const getInvite = (token: string) => call<Invite>(`/api/invites/${encodeURIComponent(token)}`);
export const acceptInvite = (token: string) =>
  post<{ role: string; project: string | null }>(`/api/invites/${encodeURIComponent(token)}/accept`);
