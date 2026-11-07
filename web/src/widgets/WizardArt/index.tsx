// Pictures of the setup wizard (widgets/Wizard): plain line drawings of what a choice means, one
// per card: `<step>-<value>`, a field step — `<step>`. .hot is what the choice is about.

import { useId, type ReactNode } from "react";
import css from "./WizardArt.module.scss";

// Section of a room: wall, ceiling, floor with a hatched screed, a socket on the wall
const ROOM = (
  <>
    <path d="M16 12H148M16 12V80M16 74H148M16 80H148" />
    <path d="M30 80l6-6M50 80l6-6M70 80l6-6M90 80l6-6M110 80l6-6M130 80l6-6" />
    <rect x="22" y="36" width="14" height="20" rx="1" />
    <rect x="112" y="52" width="10" height="10" rx="1" />
  </>
);
// Flat on the right, fed from the left
const HOUSE = <path d="M96 40l24-22 24 22M102 36V72H138V36" />;
const FEED = <path className={css.hot} d="M58 56H102" />;
const BATTERY = (
  <>
    <rect x="16" y="42" width="42" height="28" rx="2" />
    <path d="M26 42v-4h6v4M42 42v-4h6v4M30 56h-6M46 56h-6M43 53v6" />
  </>
);
// A plan: the panel in a corner and two points
const PLAN = (
  <>
    <rect x="12" y="62" width="16" height="18" rx="1" />
    <circle cx="136" cy="18" r="6" />
    <circle cx="144" cy="66" r="6" />
  </>
);

const cells = (n: number) => (
  <>
    {Array.from({ length: n }, (_, i) => {
      const x = 80 - (n * 32) / 2 + i * 32;
      return (
        <g key={i}>
          <rect x={x + 3} y="30" width="26" height="42" rx="2" />
          <path d={`M${x + 11} 30v-4h10v4`} />
          {i > 0 && <path className={css.hot} d={`M${x - 3} 52h6`} />}
        </g>
      );
    })}
  </>
);

// Rows of solar panels on a roof slope; none: the slope is empty
const roof = (rows: number) => (
  <>
    <path d="M12 76L148 28" />
    <path d="M12 76H148V28" strokeDasharray="3 4" />
    {Array.from({ length: rows }, (_, r) => Array.from({ length: 4 }, (_, i) => {
      const x = 44 + i * 22;
      const y = 62 - i * 7.8 - r * 17;
      return <path key={`${r}-${i}`} className={css.hot} d={`M${x} ${y}l20-7v-14l-20 7z`} />;
    }))}
  </>
);

// The N and PE conductors with a contact between them
const link = (closed: boolean) => (
  <>
    <path d="M36 28H148M36 64H148" />
    <text x="14" y="32">N</text>
    <text x="12" y="68">PE</text>
    <circle cx="92" cy="28" r="2.5" />
    <circle cx="92" cy="64" r="2.5" />
    {closed
      ? <path className={css.hot} d="M92 30V62" />
      : <path className={css.hot} d="M92 62L108 38" />}
  </>
);

// The panel on the left and three sockets along the wall
const SOCKETS = (
  <>
    <rect x="12" y="30" width="16" height="30" rx="1" />
    <rect x="68" y="66" width="12" height="12" rx="1" />
    <rect x="102" y="66" width="12" height="12" rx="1" />
    <rect x="136" y="66" width="12" height="12" rx="1" />
  </>
);

// Ribs of a tube: across it, where its wavy walls cross their middle lines
const TUBE_RIBS = Array.from({ length: 13 }, (_, i) => `M${22 + i * 10} 34V56`).join("");

// One breaker per group or per line: breakers in a row, lines going out of them
const breaker = (y: number) => <rect x="16" y={y} width="20" height="16" rx="2" />;

// A wall from the front, three layers one over another: the wall, a hatched plaster, the cable.
// A plaster cut for a chase frames the cable; one with a wavy edge has not reached it yet
function Plaster({ wall, outline, children }: { wall: string; outline: string; children?: ReactNode }) {
  const hatch = `hatch${useId().replace(/\W/g, "")}`;
  return (
    <>
      <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <path className={css.hatch} d="M3 0V6" />
      </pattern>
      <path d={wall} />
      <path d={outline} fill={`url(#${hatch})`} />
      {children}
      <path className={css.hot} d="M92 8V56" />
    </>
  );
}

export const ART: Record<string, ReactNode> = {
  "path-shortest": <>{PLAN}<path className={css.hot} d="M28 66L130 21M28 71L138 66" /></>,
  "path-right": <>{PLAN}<path className={css.hot} d="M20 62V18H130M110 18V66H138" /></>,
  "distribution-boxes": (
    <>
      {SOCKETS}
      <rect x="92" y="10" width="20" height="16" rx="1" />
      <path className={css.hot} d="M20 30V18H92M74 66V38L92 26M108 66V26M142 66V38L112 26" />
    </>
  ),
  "distribution-loop": <>{SOCKETS}<path className={css.hot} d="M20 30V18H74V66M80 72H102M114 72H136" /></>,
  "conduit-plain": <path className={css.hot} d="M12 45H148" />,
  "conduit-tube": (
    <>
      <path d="M12 34q5-4 10 0t10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 8 0" />
      <path d="M12 56q5 4 10 0t10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 10 0 8 0" />
      <path d={TUBE_RIBS} />
      <path className={css.hot} d="M12 45H148" />
    </>
  ),
  "plaster-after": <Plaster wall="M38 70H14V8H122V20" outline="M38 20H84V62H100V20H146V82H38Z"><path d="M84 8V20M100 8V20" /></Plaster>,
  "plaster-before": <Plaster wall="M104 70H14V8H122V20" outline="M146 20H106q6 7.75 0 15.5t0 15.5 0 15.5 0 15.5H146Z" />,
  "rough-no": <><path d="M16 12H148" /><path className={css.hot} d="M80 12V36" /><path d="M72 36H88" /></>,
  "rough-yes": (
    <>
      <path d="M16 12H148" />
      <path className={css.hot} d="M80 12V34" />
      <rect x="73" y="34" width="14" height="10" rx="1" />
      <path d="M73 44c-6 6-10 11-10 18a17 17 0 0 0 34 0c0-7-4-12-10-18" />
      <rect x="120" y="44" width="14" height="20" rx="1" />
      <path d="M127 49V59" />
    </>
  ),
  "breakers-simple": <>{breaker(37)}<path className={css.hot} d="M36 45H148M70 45L148 18M100 45L148 72" /></>,
  "breakers-groups": <>{breaker(37)}<path className={css.hot} d="M36 45H70M70 45L148 18M70 45H148M70 45L148 72" /></>,
  "breakers-lines": <>{breaker(10)}{breaker(37)}{breaker(64)}<path className={css.hot} d="M36 18H148M36 45H148M36 72H148" /></>,
  "standby-no": <>{HOUSE}<path className={css.hot} d="M14 56H102" /><path d="M22 34V72M14 42H30" /></>,
  "standby-yes": <>{HOUSE}<path className={css.hot} d="M14 56H102" /><rect x="14" y="14" width="44" height="28" rx="2" strokeDasharray="3 4" /></>,
  "route-ceiling": <>{ROOM}<path className={css.hot} d="M29 36V18H117V52" /></>,
  "route-floor": <>{ROOM}<path className={css.hot} d="M29 56V77H117V62" /></>,
  ceiling: <><path d="M16 12H148M16 78H148" /><path className={css.hot} d="M80 16V74M75 22l5-6 5 6M75 68l5 6 5-6" /></>,
  input: (
    <>
      <rect x="56" y="14" width="48" height="62" rx="3" />
      <rect x="72" y="30" width="16" height="26" rx="2" />
      <path d="M72 44H88" />
      <path className={css.hot} d="M80 2V14M80 76V88" />
    </>
  ),
  "backup-inverter": <>{HOUSE}{BATTERY}{FEED}</>,
  "backup-plug": (
    <>
      {HOUSE}
      <rect x="14" y="40" width="34" height="30" rx="2" />
      <circle cx="31" cy="55" r="8" />
      <path d="M26 55q2.500-5 5 0t5 0" />
      <path className={css.hot} d="M48 56H74M74 50v12h6v-12zM80 53h6M80 59h6M86 56H102" />
    </>
  ),
  "backup-station": (
    <>
      {HOUSE}
      <rect x="14" y="36" width="34" height="36" rx="3" />
      <path d="M22 28h18M24 44h14M24 52h14M24 60h14" />
      <path className={css.hot} d="M48 56H74M74 50v12h6v-12zM80 53h6M80 59h6M86 56H102" />
    </>
  ),
  unknown: (
    <>
      <circle cx="76" cy="50" r="9" />
      <path d="M68 54L57 69 46 59H42a4 4 0 0 0 0 8H46L57 80 63.5 73V84H88.5V73L95 80 106 67H110a4 4 0 0 0 0-8H106L95 69 84 54" />
      <path d="M87 6H115a5 5 0 0 1 5 5V27a5 5 0 0 1-5 5H98L90 39V32H87a5 5 0 0 1-5-5V11a5 5 0 0 1 5-5z" />
      <path className={css.hot} d="M95.7 15q.7-4.6 5.3-4.6t5.3 4.3q0 3-3.3 4.6-2 1.3-2 4M101 27.6v.7" />
    </>
  ),
  "inverter-hybrid": (
    <>
      <rect x="48" y="16" width="64" height="58" rx="3" />
      <path d="M48 74L112 16" />
      <path d="M58 32q4-7 8 0t8 0M90 62h12" />
      <path className={css.hot} d="M8 45H48M112 45H152" />
    </>
  ),
  "inverter-basic": (
    <>
      <rect x="16" y="16" width="50" height="58" rx="3" />
      <path d="M16 74L66 16" />
      <rect x="94" y="28" width="38" height="34" rx="2" />
      <path d="M102 56L120 38M120 36v-4" />
      <path className={css.hot} d="M66 45H94M132 45H154" />
    </>
  ),
  "battery-12": cells(1),
  "battery-24": cells(2),
  "battery-48": cells(4),
  "pv-0": roof(0),
  "pv-1": roof(1),
  "pv-2": roof(2),
  "npe-yes": link(true),
  "npe-no": link(false),
};

export function WizardArt({ name }: { name: string }) {
  return (
    <svg className={css.art} viewBox="0 0 160 90" aria-hidden="true">
      {ART[name]}
    </svg>
  );
}
