// Outline icons of the interface, Tabler (MIT) on a 24-unit grid; size and colour come from the text

import css from "./Icon.module.scss";

const PATHS = {
  bath: [
    "M4 12h16a1 1 0 0 1 1 1v3a4 4 0 0 1 -4 4h-10a4 4 0 0 1 -4 -4v-3a1 1 0 0 1 1 -1z",
    "M6 12v-7a2 2 0 0 1 2 -2h3v2.25",
    "M4 21l1 -1.5",
    "M20 21l-1 -1.5",
  ],
  door: ["M14 12v.01", "M3 21h18", "M6 21v-16a2 2 0 0 1 2 -2h8a2 2 0 0 1 2 2v16"],
  grid: ["M4 4h6v6h-6z", "M14 4h6v6h-6z", "M4 14h6v6h-6z", "M14 14h6v6h-6z"],
  home: [
    "M5 12h-2l9 -9l9 9h-2",
    "M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-7",
    "M9 21v-6a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v6",
  ],
  kitchen: ["M19 3v12h-5c-.023 -3.681 .184 -7.406 5 -12zm0 12v6h-1v-3m-10 -14v17m-3 -17v3a3 3 0 1 0 6 0v-3"],
  sofa: [
    "M4 11a2 2 0 0 1 2 2v1h12v-1a2 2 0 1 1 4 0v5a1 1 0 0 1 -1 1h-18a1 1 0 0 1 -1 -1v-5a2 2 0 0 1 2 -2z",
    "M4 11v-3a3 3 0 0 1 3 -3h10a3 3 0 0 1 3 3v3",
    "M12 5v9",
  ],
  sun: [
    "M8 12a4 4 0 1 0 8 0a4 4 0 1 0 -8 0",
    "M3 12h1m8 -9v1m8 8h1m-9 8v1m-6.4 -15.4l.7 .7m12.1 -.7l-.7 .7m0 11.4l.7 .7m-12.1 -.7l-.7 .7",
  ],
};

export type IconName = keyof typeof PATHS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className={css.icon} viewBox="0 0 24 24" aria-hidden="true">
      {PATHS[name].map((d) => <path key={d} d={d} />)}
    </svg>
  );
}
