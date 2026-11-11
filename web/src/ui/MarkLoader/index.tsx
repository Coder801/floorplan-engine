// Loading with the mark (4C): the "St" letters in a faint frame, two segments run around the
// frame clockwise, one lap in 3 s. The frame is the line the logo's corners lie on (ui/Logo)

import css from "./MarkLoader.module.scss";

export function MarkLoader({ size = 44 }: { size?: number }) {
  return (
    <svg className={css.mark} width={Math.round(size * 36 / 32)} height={size} viewBox="-2 0 36 32" aria-hidden="true">
      <path className={css.rim} d="M-.5 1.5H32.5V30.5H-.5Z" />
      {/* Starts at the top left corner and goes clockwise, like the logo's corners */}
      <path className={css.trace} pathLength={1} d="M-.5 1.5H32.5V30.5H-.5Z" />
      <text x="16" y="21.5">St</text>
    </svg>
  );
}
