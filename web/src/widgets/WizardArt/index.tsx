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
// The client's flat on the right, fed from the left: an illustrative room in isometry (two walls
// and the floor, no door) with windows, a sofa, a coffee table and a TV; the feed comes in at the
// left wall
const HOUSE = (
  <>
    <path d="M100 31L126 16L152 31V65L126 80L100 65Z" />
    <path className={css.faint} d="M126 16V50M126 50L135.9 55.7M148.62 63.05L152 65M126 50L120.5 53.2M103.9 62.75L100 65" />
    <g className={css.thin}>
      {/* windows: one on each wall, with a mullion */}
      <path d="M107.8 43.5L116.9 38.25V27.25L107.8 32.5ZM112.35 40.9V29.9" />
      <path d="M128.6 34.5L135.1 38.25V27.25L128.6 23.5ZM131.85 36.4V25.4" />
      {/* TV on the right wall over a low cabinet */}
      <path d="M139.5 47.8L148.1 52.75V43.75L139.5 38.8Z" />
      <path d="M139 53.5L148.62 59.05L145.5 60.85L135.88 55.3ZM135.88 55.3V59.3L145.5 64.85L148.62 63.05V59.05M145.5 60.85V64.85" />
      {/* two-seat sofa along the left wall */}
      <path d="M103.9 49.75L114.3 43.75L116.12 44.8L105.72 50.8ZM103.9 49.75V62.75L109.62 66.05L120.02 60.05V55.05L116.12 52.8V44.8M105.72 50.8V58.8L109.62 61.05V66.05M105.72 58.8L116.12 52.8M109.62 61.05L120.02 55.05M110.92 47.8V55.8L114.82 58.05" />
      {/* coffee table */}
      <path d="M126 59.5L120.8 62.5L127.3 66.25L132.5 63.25ZM120.8 62.5V66.5M127.3 66.25V70.25M132.5 63.25V67.25" />
    </g>
  </>
);
const FEED = <path className={css.hot} d="M58 56H100" />;
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

// The entrance door on the right, the panel on the left; with the master switch a key by the door
// and its control line to the panel contactor
const master = (on: boolean) => (
  <>
    <rect x="12" y="22" width="20" height="36" rx="1" />
    <path d="M110 80V12H144V80M8 80H152" />
    <circle cx="137" cy="48" r="2" />
    {on && (
      <>
        <rect x="88" y="40" width="12" height="16" rx="2" />
        <path className={css.hot} d="M94 40V30H22V22" />
      </>
    )}
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

// One breaker per group or per line: breakers in a row, lines going out of them
const breaker = (y: number) => <rect x="16" y={y} width="20" height="16" rx="2" />;

// Panel devices on a DIN rail, room for a sticker over each (labels)
const modules = (
  <>
    <path d="M30 50H136" />
    {[42, 64, 86, 108].map((x) => <rect key={x} x={x} y="38" width="16" height="36" rx="2" />)}
  </>
);
// A megohmmeter: a case with a dial and a needle (insulation)
const megger = (
  <>
    <rect x="16" y="22" width="46" height="50" rx="3" />
    <path d="M24 44a15 15 0 0 1 30 0" />
    <path d="M39 44L48 33" />
    <rect x="26" y="54" width="26" height="10" rx="1" />
  </>
);

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

// A LED strip under a cabinet on the right: the light it gives below
const STRIP = (
  <>
    <path d="M96 38H148V44H96" />
    <path strokeDasharray="2 3" d="M98 47H146" />
    <path className={css.faint} d="M104 52l-4 10M122 52v10M140 52l4 10" />
  </>
);

export const ART: Record<string, ReactNode> = {
  // LED supply: at the strip, 230 V from the room box on the ceiling; or in the panel, 12 V from it
  // Light: a box on the ceiling with a cable to the switch and to each light; or a chain from the
  // switch from light to light, with a loop at each
  "lights-boxes": (
    <>
      <path d="M16 12H148" />
      <rect x="64" y="12" width="16" height="10" rx="1" />
      <rect x="20" y="52" width="10" height="14" rx="1" />
      <circle cx="40" cy="12" r="4" /><circle cx="104" cy="12" r="4" /><circle cx="136" cy="12" r="4" />
      <path className={css.hot} d="M25 52V28H64M64 17H40M80 17H136" />
    </>
  ),
  "lights-chain": (
    <>
      <path d="M16 12H148" />
      <rect x="20" y="52" width="10" height="14" rx="1" />
      <circle cx="56" cy="12" r="4" /><circle cx="96" cy="12" r="4" /><circle cx="136" cy="12" r="4" />
      <path className={css.hot} d="M25 52V20H50q6 14 12 0H90q6 14 12 0H130q6 14 12 0" />
    </>
  ),
  "led-room": (
    <>
      <path d="M16 12H148" />
      <rect x="36" y="12" width="16" height="10" rx="1" />
      <path className={css.hot} d="M52 17H86V40" />
      <rect x="78" y="40" width="16" height="10" rx="1" />
      <path d="M94 45H96" />
      {STRIP}
    </>
  ),
  "led-board": (
    <>
      <rect x="12" y="24" width="20" height="40" rx="1" />
      <rect className={css.hot} x="16" y="46" width="12" height="12" rx="1" />
      <path className={css.hot} d="M28 52H40V16H86V45H96" />
      {STRIP}
    </>
  ),
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
  "conduit-none": <>{ROOM}<path className={css.hot} d="M29 36V18H117V52" /></>,
  "conduit-ceiling": <>{ROOM}<path className={css.tube} d="M29 18H117" /><path className={css.hot} d="M29 36V18H117V52" /></>,
  "conduit-walls": <>{ROOM}<path className={css.tube} d="M29 36V18H117V52" /><path className={css.hot} d="M29 36V18H117V52" /></>,
  // Chain drop in conduit: the cable in and the cable out of a socket each in its own conduit, or
  // both in one wider conduit
  "loopConduit-separate": (
    <>
      <path d="M16 12H148" />
      <rect x="40" y="56" width="20" height="14" rx="1" /><rect x="100" y="56" width="20" height="14" rx="1" />
      <path className={css.tube} d="M16 20H44V56M56 56V20H110V56" />
      <path className={css.hot} d="M16 20H44V56M56 56V20H110V56" />
    </>
  ),
  "loopConduit-shared": (
    <>
      <path d="M16 12H148" />
      <rect x="40" y="56" width="20" height="14" rx="1" /><rect x="100" y="56" width="20" height="14" rx="1" />
      <path className={css.tube} d="M16 20H44M56 20H110V56" />
      <path className={`${css.tube} ${css.wide}`} d="M50 20V56" />
      <path className={css.hot} d="M16 20H47V56M53 56V20H110V56" />
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
  "labels-yes": <>{modules}<path className={css.hot} d="M42 26h16v8H42ZM64 26h16v8H64ZM86 26h16v8H86ZM108 26h16v8H108Z" /></>,
  "labels-no": <>{modules}<path d="M42 30h16M64 30h16M86 30h16M108 30h16" strokeDasharray="2 4" /></>,
  "insulation-yes": (
    <>
      {megger}
      <path d="M86 70H150" />
      <path className={css.hot} d="M62 42q14 0 24 28M62 52q30 0 50 18" />
    </>
  ),
  "protection-yes": (
    <>
      {megger}
      {[98, 120].map((x) => <rect key={x} x={x} y="34" width="16" height="36" rx="2" />)}
      <path className={css.hot} d="M62 42q20 -14 44 -8M62 52q34 30 66 18" />
    </>
  ),
  "protection-no": <>{modules}<path className={css.hot} d="M42 82H124" strokeDasharray="2 4" /></>,
  "insulation-no": <><path d="M16 70H150" /><path className={css.hot} d="M80 70l-5-8M80 70l5-8" strokeDasharray="2 3" /></>,
  "breakers-simple": <>{breaker(37)}<path className={css.hot} d="M36 45H148M70 45L148 18M100 45L148 72" /></>,
  "breakers-groups": <>{breaker(37)}<path className={css.hot} d="M36 45H70M70 45L148 18M70 45H148M70 45L148 72" /></>,
  "breakers-lines": <>{breaker(10)}{breaker(37)}{breaker(64)}<path className={css.hot} d="M36 18H148M36 45H148M36 72H148" /></>,
  "standby-no": <>{HOUSE}<path className={css.hot} d="M14 56H100" /><path d="M22 34V72M14 42H30" /></>,
  // Provided for and left for later: a dashed place for the source; calculated now: the source itself
  "standby-later": <>{HOUSE}<path className={css.hot} d="M14 56H100" /><rect x="14" y="14" width="44" height="28" rx="2" strokeDasharray="3 4" /></>,
  "standby-yes": <>{HOUSE}<path className={css.hot} d="M14 56H100M36 42V56" /><rect x="14" y="14" width="44" height="28" rx="2" /><path d="M24 28H32M40 28H48M44 24V32" /></>,
  "route-ceiling": <>{ROOM}<path className={css.hot} d="M29 36V18H117V52" /></>,
  "route-floor": <>{ROOM}<path className={css.hot} d="M29 56V77H117V62" /></>,
  // A living room between the ceiling and the floor: a plant, a sofa under a pendant lamp, a coffee
  // table and an armchair under a window; the height on the right. The ceiling is faint, the floor
  // is not drawn: the furniture shows where it is. A wider and taller picture (TALL)
  ceiling: (
    <>
      <path className={css.faint} d="M8 10H192" />
      <path d="M14 86L16 100H26L28 86ZM21 86V64M21 80q-10-2-11-11q9 1 11 11M21 73q10-2 11-11q-9 1-11 11M21 64q-5-7 0-13q5 6 0 13" />
      <path d="M70 10V28M62 36L66 28H74L78 36Z" />
      <rect x="34" y="76" width="8" height="18" rx="2" />
      <rect x="98" y="76" width="8" height="18" rx="2" />
      <rect x="42" y="70" width="56" height="14" rx="3" />
      <path d="M42 84V94H98V84M38 94V100M102 94V100" />
      <path d="M110 84H132M114 84V100M128 84V100" />
      <rect x="138" y="76" width="8" height="18" rx="2" />
      <rect x="158" y="66" width="8" height="28" rx="2" />
      <path d="M146 84H158M146 94H158M142 94V100M162 94V100" />
      <rect x="130" y="28" width="24" height="28" rx="1" />
      <path d="M142 28V56M130 42H154M127 56H157" />
      <path className={css.hot} d="M184 14V96M179 20l5-6 5 6M179 90l5 6 5-6" />
    </>
  ),
  input: (
    <>
      <rect x="56" y="14" width="48" height="62" rx="3" />
      <rect x="72" y="30" width="16" height="26" rx="2" />
      <path d="M72 44H88" />
      <path className={css.hot} d="M80 2V14M80 76V88" />
    </>
  ),
  // Supply wires into the main breaker: one phase and N, or three phases and N
  "phases-1": <><rect x="56" y="30" width="48" height="46" rx="3" /><path className={css.hot} d="M72 4V30" /><path d="M88 4V30" /></>,
  "phases-3": <><rect x="44" y="30" width="72" height="46" rx="3" /><path className={css.hot} d="M54 4V30M68 4V30M82 4V30" /><path d="M104 4V30" /></>,
  "backup-inverter": <>{HOUSE}{BATTERY}{FEED}</>,
  "backup-plug": (
    <>
      {HOUSE}
      <rect x="14" y="40" width="34" height="30" rx="2" />
      <circle cx="31" cy="55" r="8" />
      <path d="M26 55q2.500-5 5 0t5 0" />
      <path className={css.hot} d="M48 56H74M74 50v12h6v-12zM80 53h6M80 59h6M86 56H100" />
    </>
  ),
  "backup-station": (
    <>
      {HOUSE}
      <rect x="14" y="36" width="34" height="36" rx="3" />
      <path d="M22 28h18M24 44h14M24 52h14M24 60h14" />
      <path className={css.hot} d="M48 56H74M74 50v12h6v-12zM80 53h6M80 59h6M86 56H100" />
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
  // Backup power: a gauge with its needle near the top
  power: (
    <>
      <path d="M40 72a40 40 0 0 1 80 0" />
      <path d="M48 56l6 3M80 32v7M112 56l-6 3M58 40l5 5M102 40l-5 5" />
      <circle cx="80" cy="72" r="4" />
      <path className={css.hot} d="M80 72L101 47" />
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
  "master-yes": master(true),
  "master-no": master(false),
};

// Pictures drawn on a bigger canvas (more detail, shown taller); the rest are 160×90
const TALL: Record<string, string> = { ceiling: "0 0 200 110" };

export function WizardArt({ name }: { name: string }) {
  const tall = TALL[name];
  return (
    <svg className={tall ? `${css.art} ${css.tall}` : css.art} viewBox={tall ?? "0 0 160 90"} aria-hidden="true">
      {ART[name]}
    </svg>
  );
}
