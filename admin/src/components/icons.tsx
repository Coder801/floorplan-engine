// Outline icons of the admin: Tabler (MIT), path data inlined on a 24-unit grid, like the viewer's
// web/src/ui/Icon (no dependency). Size and colour come from the text: 16 px, currentColor.
import css from "./ui.module.scss";

const PATHS = {
  ban: ["M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0", "M5.7 5.7l12.6 12.6"],
  check: ["M5 12l5 5l10 -10"],
  copy: [
    "M7 9.667a2.667 2.667 0 0 1 2.667 -2.667h8.666a2.667 2.667 0 0 1 2.667 2.667v8.666a2.667 2.667 0 0 1 -2.667 2.667h-8.666a2.667 2.667 0 0 1 -2.667 -2.667z",
    "M4.012 16.737a2.005 2.005 0 0 1 -1.012 -1.737v-10c0 -1.1 .9 -2 2 -2h10c.75 0 1.158 .385 1.5 1",
  ],
  link: [
    "M9 15l6 -6",
    "M11 6l.463 -.536a5 5 0 0 1 7.071 7.072l-.534 .464",
    "M13 18l-.397 .534a5.068 5.068 0 0 1 -7.127 0a4.972 4.972 0 0 1 0 -7.071l.524 -.463",
  ],
  lock: [
    "M5 13a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v6a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2v-6z",
    "M11 16a1 1 0 1 0 2 0a1 1 0 0 0 -2 0",
    "M8 11v-4a4 4 0 1 1 8 0v4",
  ],
  lockOpen: [
    "M5 13a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v6a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2z",
    "M11 16a1 1 0 1 0 2 0a1 1 0 1 0 -2 0",
    "M8 11v-5a4 4 0 0 1 8 0",
  ],
  logout: [
    "M14 8v-2a2 2 0 0 0 -2 -2h-7a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h7a2 2 0 0 0 2 -2v-2",
    "M9 12h12l-3 -3",
    "M18 15l3 -3",
  ],
  plus: ["M12 5l0 14", "M5 12l14 0"],
  userMinus: [
    "M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0",
    "M6 21v-2a4 4 0 0 1 4 -4h4c.348 0 .686 .045 1.009 .128",
    "M16 19h6",
  ],
  x: ["M18 6l-12 12", "M6 6l12 12"],
};

export type IconName = keyof typeof PATHS;
export const ICONS = Object.keys(PATHS) as IconName[];

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className={css.icon} viewBox="0 0 24 24" aria-hidden="true" data-icon={name}>
      {PATHS[name].map((d) => <path key={d} d={d} />)}
    </svg>
  );
}
