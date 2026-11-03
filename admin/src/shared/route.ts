// Address of the screen in the hash: #/studios/<id>, #/users, #/events?project=<id>. Each record
// has its own address, so a link to a user, a studio or a project switches the section.
import { useEffect, useState } from "react";

export type Section = "summary" | "studios" | "users" | "projects" | "events";
export const SECTIONS: Section[] = ["summary", "studios", "users", "projects", "events"];

export interface Route { section: Section; id: string | null; params: URLSearchParams }

export function parse(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const [head, id] = path.split("/");
  const section = (SECTIONS as string[]).includes(head) ? (head as Section) : "summary";
  return { section, id: id ? decodeURIComponent(id) : null, params: new URLSearchParams(query) };
}

export function href(section: Section, id?: string | null, params?: Record<string, string>): string {
  const query = params && Object.keys(params).length ? `?${new URLSearchParams(params)}` : "";
  return `#/${section}${id ? `/${encodeURIComponent(id)}` : ""}${query}`;
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.hash));
  useEffect(() => {
    const on = () => setRoute(parse(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
