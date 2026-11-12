// Answers of the admin API (service/db/admin.py): keep in step with the views there

export type State = "active" | "accepted" | "revoked" | "expired";
export type StudioKind = "studio" | "personal" | "unowned";

export interface Me {
  auth: boolean;
  user: { id: string; name: string; email: string | null; phone: string | null; superuser: boolean } | null;
}

export interface UserBrief {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  account_type: "client" | "pro" | null;
  superuser: boolean;
  active: boolean;
  last_login: string | null;
  created: string | null;
}

export interface StudioBrief {
  id: string;
  name: string;
  kind: StudioKind;
  business: string | null;
  city: string;
  phone: string;
  folder: string;
  created: string | null;
}

export interface ProjectBrief {
  id: string;
  name: string;
  slug: string | null;
  studio: { id: string; name: string };
  state: string;
  created: string | null;
}

export interface Summary { studios: number; personal: number; users: number; projects: number; sessions: number }

export interface Member { user: UserBrief; role: string; since: string | null }

export interface InviteRow {
  id: string;
  role: string;
  email: string | null;
  state: State;
  created: string | null;
  expires: string | null;
  accepted_by: UserBrief | null;
}

export interface StudioRow extends StudioBrief { members: number; projects: number }
export interface StudioDetail extends StudioBrief {
  members: Member[];
  projects: ProjectBrief[];
  invites: InviteRow[];
}

export interface UserRow extends UserBrief { space: StudioBrief | null }
export interface UserDetail extends UserBrief {
  space: (StudioBrief & { role: string | null }) | null;
  projects: (ProjectBrief & { role: string })[];
  providers: string[];
  sessions: { id: string; agent: string; created: string | null; seen: string | null }[];
}

export interface ProjectRow extends ProjectBrief { members: number }
export interface CodeRow {
  id: string;
  label: string;
  role: string;  // viewer | client_code
  state: State;
  uses: number;
  created: string | null;
  expires: string | null;
  last_used: string | null;
}
export interface SupportRow { user: UserBrief; reason: string; state: State; expires: string | null }
export interface ProjectDetail extends ProjectBrief {
  members: Member[];
  codes: CodeRow[];
  invites: InviteRow[];
  support: SupportRow[];
}

export interface EventRow {
  id: string;
  action: string;
  at: string | null;
  user: UserBrief | null;
  subject: UserBrief | null;
  studio: { id: string; name: string } | null;
  project: string | null;
  payload: Record<string, unknown>;
}

// Product feedback from the viewer ("Оставить отзыв", decision 2026-11-12): about the service,
// not about a work task. GET /api/admin/feedback, PATCH /api/admin/feedback/{id}
export type FeedbackKind = "bug" | "idea" | "other";
export type FeedbackStatus = "new" | "seen" | "done";
export interface FeedbackItem {
  id: string;
  created_at: string | null;
  kind: FeedbackKind;
  text: string;
  status: FeedbackStatus;
  admin_note: string | null;
  // What the page attached: sheet, path, version, viewport, user_agent (web: FeedbackContext)
  context: Record<string, unknown> | null;
  author: { email?: string | null; name?: string | null; code_label?: string | null } | null;
  project: { key: string; name: string } | null;
  photos: string[];  // addresses of the screenshots
}
export interface FeedbackPage {
  items: FeedbackItem[];
  total: number;  // under the filter
  counts: Record<FeedbackStatus, number>;  // by status, over all feedback
}
