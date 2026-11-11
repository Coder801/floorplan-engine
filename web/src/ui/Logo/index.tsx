// The "St" mark: letters in a frame marked by two corners, top left and bottom right; the frame
// is wider than tall (2 units of air left and right of the letters), height is size

import css from "./Logo.module.scss";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg className={css.logo} width={Math.round(size * 36 / 32)} height={size} viewBox="-2 0 36 32" aria-hidden="true">
      <path d="M-.5 11V1.5H9M32.5 21v9.5H23" />
      <text x="16" y="21.5">St</text>
    </svg>
  );
}
