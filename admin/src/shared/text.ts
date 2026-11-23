// Interface strings, Russian for now (uk and en later, like web/src/shared/i18n). Words for codes
// from the API: roles, states, account and studio kinds, audit actions.
import type { Section } from "./route";

export const SECTION: Record<Section, string> = {
  summary: "Сводка", studios: "Студии", users: "Люди", projects: "Проекты", feedback: "Отзывы", events: "Журнал",
};

export const ROLE: Record<string, string> = {
  owner: "владелец", designer: "проектировщик", installer: "монтажник",
  client: "хозяин квартиры", support: "поддержка",
  viewer: "просмотр", client_code: "заказчик",
};
export const STUDIO_ROLES = ["owner", "designer", "installer"];
export const PROJECT_ROLES = ["client", "installer"];
// Access code kinds (access_codes.issue_code): a view code, a client code (answers and the wizard)
export const CODE_ROLES = ["viewer", "client_code"];

// Services of a project, in catalogue order (decision 2026-11-23): the viewer hides the sections of
// those switched off. A service that is not built yet is marked "soon" and changes nothing so far
export const SERVICES: { key: string; label: string; soon?: boolean }[] = [
  { key: "electrical", label: "Электрика" },
  { key: "plumbing", label: "Сантехника" },
  { key: "demolition", label: "Монтаж/демонтаж", soon: true },
];

export const STATE: Record<string, string> = {
  active: "действует", accepted: "принято", revoked: "отозван", expired: "истёк",
};

export const ACCOUNT: Record<string, string> = { client: "хозяин квартиры", pro: "студия" };
export const KIND: Record<string, string> = {
  studio: "фирма", personal: "Мой ремонт", unowned: "без владельца",
};
export const BUSINESS: Record<string, string> = {
  design: "дизайн и проект", electric: "электромонтаж", construction: "ремонт", master: "частный мастер",
};

export const ACTION: Record<string, string> = {
  login: "вход", project_create: "проект создан", project_adopt: "проект передан владельцу",
  firm_register: "фирма зарегистрирована", invite: "приглашение", invite_accept: "приглашение принято",
  code_issue: "код выдан", code_revoke: "код отозван", code_login: "вход по коду",
  support_grant: "доступ поддержки", support_revoke: "доступ поддержки снят", support_access: "поддержка открыла",
  admin_block: "заблокирован", admin_unblock: "разблокирован", admin_logout: "сеансы завершены",
  admin_member_add: "добавлен участник", admin_member_role: "роль изменена",
  admin_member_remove: "участник убран", admin_invite_revoke: "приглашение отозвано",
  admin_project_services: "сервисы проекта изменены",
};

export const word = (dict: Record<string, string>, key: string | null | undefined) =>
  key == null ? "—" : dict[key] ?? key;

// Product feedback: kinds and statuses
export const FEEDBACK_KIND: Record<string, string> = { bug: "ошибка", idea: "идея", other: "другое" };
export const FEEDBACK_STATUS: Record<string, string> = { new: "новый", seen: "просмотрен", done: "сделано" };
