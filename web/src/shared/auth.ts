// Login requests (service/api/auth.py): who is logged in, Telegram (phone number), e-mail code,
// project access code, account type, debug guest, invites

export interface User {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;     // "+380…": Telegram login
  account_type: "client" | "pro" | null;
  superuser: boolean;
  space: Space | null;      // own workspace: a firm or "Мой ремонт"
}

// Firm kind at registration (access.FIRM_KINDS)
export const FIRM_KINDS = ["design", "electric", "construction", "master"] as const;
export type FirmKind = (typeof FIRM_KINDS)[number];

export interface Space {
  kind: "studio" | "personal";
  name: string;
  business: FirmKind | null;
  city: string;
}

// auth: false means login is off on the server (local viewing), nothing else comes
// Logged in by an access code: one project (folder and name), no account, view only
export interface CodeAccess { project: string | null; name: string }

export interface Me {
  auth: boolean;
  user?: User | null;
  visitor?: boolean;
  code?: CodeAccess | null;
  google?: boolean;
  email?: boolean;          // e-mail code login is configured
  telegram?: boolean;       // Telegram bot for phone login is configured
  dev?: boolean;            // "Log in for development" (locally, SHTROBA_DEV_LOGIN)
  visitor_allowed?: boolean;
  feedback?: boolean;       // "Leave feedback" is open (POST /api/feedback); never in the folder viewer
}

export interface Invite { role: string; project: string | null }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not JSON */ }
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
// "Мой ремонт" is the personal workspace; a firm comes through registration (registerFirm)
export const chooseAccountType = (type: "client") => post<User>("/api/auth/account-type", { type });
export const registerFirm = (firm: { name: string; business: FirmKind; city: string; phone: string }) =>
  post<User>("/api/auth/firm", firm);
export const getInvite = (token: string) => call<Invite>(`/api/invites/${encodeURIComponent(token)}`);
export const acceptInvite = (token: string) =>
  post<{ role: string; project: string | null }>(`/api/invites/${encodeURIComponent(token)}/accept`);
// Project access code from the studio (access code): login to this project without an account
export const loginByCode = (code: string) => post<{ ok: boolean; project: string | null }>("/api/auth/code", { code });
export const startEmailLogin = (email: string, lang: string) =>
  post<{ sent: boolean; resend_in: number }>("/api/auth/email/start", { email, lang });
export const verifyEmailLogin = (email: string, code: string) =>
  post<{ ok: boolean; invite_error: string | null }>("/api/auth/email/verify", { email, code });

// Telegram: a ticket and the bot link; then poll the ticket until the bot gets the number
export interface TelegramTicket { token: string; url: string; expires_in: number }
export const startTelegramLogin = (lang: string) => post<TelegramTicket>("/api/auth/telegram/start", { lang });
export const telegramLoginStatus = (token: string, invite?: string | null) => {
  const q = new URLSearchParams({ token });
  if (invite) q.set("invite", invite);
  return call<{ status: "pending" | "done"; invite_error?: string | null }>(`/api/auth/telegram/status?${q}`);
};
