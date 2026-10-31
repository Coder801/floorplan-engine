// Запросы входа (service/api/auth.py): кто вошёл, код на почту, тип учётки, гость отладки,
// приглашения

export interface User {
  id: string;
  name: string;
  email: string | null;
  account_type: "client" | "pro" | null;
  superuser: boolean;
  space: Space | null;      // своё пространство: фирма или «Мой ремонт»
}

// Вид фирмы при регистрации (access.FIRM_KINDS)
export const FIRM_KINDS = ["design", "electric", "construction", "master"] as const;
export type FirmKind = (typeof FIRM_KINDS)[number];

export interface Space {
  kind: "studio" | "personal";
  name: string;
  business: FirmKind | null;
  city: string;
}

// auth: false — вход на сервере выключен (локальный просмотр), остальное не приходит
export interface Me {
  auth: boolean;
  user?: User | null;
  visitor?: boolean;
  google?: boolean;
  email?: boolean;          // вход по коду на почту настроен
  dev?: boolean;            // «Зайти для разработки» (локально, SHTROBA_DEV_LOGIN)
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
export const devLogin = () => post<{ ok: boolean }>("/api/auth/dev");
export const logout = () => post<{ ok: boolean }>("/api/auth/logout");
// «Мой ремонт» — личное пространство; фирма — регистрацией (registerFirm)
export const chooseAccountType = (type: "client") => post<User>("/api/auth/account-type", { type });
export const registerFirm = (firm: { name: string; business: FirmKind; city: string; phone: string }) =>
  post<User>("/api/auth/firm", firm);
export const getInvite = (token: string) => call<Invite>(`/api/invites/${encodeURIComponent(token)}`);
export const acceptInvite = (token: string) =>
  post<{ role: string; project: string | null }>(`/api/invites/${encodeURIComponent(token)}/accept`);
export const startEmailLogin = (email: string, lang: string) =>
  post<{ sent: boolean; resend_in: number }>("/api/auth/email/start", { email, lang });
export const verifyEmailLogin = (email: string, code: string) =>
  post<{ ok: boolean; invite_error: string | null }>("/api/auth/email/verify", { email, code });
