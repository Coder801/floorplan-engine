// Interface strings, Russian for now (uk and en later, like web/src/shared/i18n). Words for codes
// from the API: roles, states, account and studio kinds, audit actions.
import type { Section } from "./route";

export const SECTION: Record<Section, string> = {
  summary: "Сводка", studios: "Студии", users: "Люди", projects: "Проекты", events: "Журнал",
};

export const ROLE: Record<string, string> = {
  owner: "владелец", designer: "проектировщик", installer: "монтажник",
  client: "хозяин квартиры", support: "поддержка",
};
export const STUDIO_ROLES = ["owner", "designer", "installer"];
export const PROJECT_ROLES = ["client", "installer"];

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
};

export const word = (dict: Record<string, string>, key: string | null | undefined) =>
  key == null ? "—" : dict[key] ?? key;
