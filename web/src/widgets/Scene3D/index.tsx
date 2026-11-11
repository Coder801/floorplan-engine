// Drawing 3D (key scene of the wiring page, scene3d.py): model mm, Z axis up. One for all tabs
// of the drawing: it shows what the tab's layers show (plan: walls, electrical: points of the
// view and its lines, lighting links: lights, switches and the links under the ceiling
// (engine/three/lightLinks.ts), wiring: everything). The "cut" wall mode makes partitions a
// low rim, and exterior walls a rim when they stand between the camera and the room; the part
// of a line hidden by a wall is faint and drawn over everything; hints, selection and the
// link to tables go through the shared state.
// Walls are translucent but solid: first the front surface of all walls is written to depth,
// then colour lands only on it, so the inner ends of pieces do not stack transparency into
// dark seams; the outline is drawn only where a wall ends (wallEdges.ts).

import { Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { layerShown } from "@/engine/sheet/drawing";
import { LINK_LAYER, type LightLink3D } from "@/engine/three/lightLinks";
import { wallEdges } from "@/engine/three/wallEdges";
import {
  CUT_DOT, CUT_HEIGHT_MM, DIM_ALPHA, FLOW_DASH_PX, FLOW_GAP_PX, FLOW_SPEED_PX, GHOST_ALPHA,
  NEIGHBOR_ALPHA, REDUCED_MOTION, WALL_ALPHA, WALL_GHOST_ALPHA, WIRE_LIT_PX, WIRE_PX, WIRE_SEL_PX,
} from "@/shared/consts";
import { expand, type PageIndex } from "@/shared/page";
import { isDark, palette, refreshPalette, screenColor } from "@/shared/palette";
import { shown3d, useView, view, type ViewState } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { PipeKind, Scene, ScenePipe, SceneWire, XY } from "@/shared/types";
import {
  clampStep, Glide, PinchSteps, stepBelow, WheelSteps, ZOOM_STEPS, zoomLabel, type Zoom,
} from "@/shared/zoom";
import { flat, pointGeometry, puck } from "./solids";

const HOME_DIRECTION = new THREE.Vector3(-1, -1, 1.15);  // isometry: from the south-west, above
const HOME_TOLERANCE = 0.005;  // the controls settle with inertia: the view is home within this share

export interface Scene3DApi {
  iso(): void;
  fit(): void;
  zoomTo(step: number): void;  // zoom step (shared/zoom.ts) from "whole flat"
}

interface Props {
  scene: Scene;
  index: PageIndex;
  own: Set<string> | null;          // tab layers (sheet/drawing.ts); null means all
  layerOf: Map<string, string>;     // object → its layer on the drawing
  links: LightLink3D[];             // light links (E-LINK), visible where the tab shows that layer
  apiRef: MutableRefObject<Scene3DApi | null>;
  onZoom: (zoom: Zoom) => void;
  onHome: (home: boolean) => void;  // the camera came to the isometry or left it
}

// Transparent draw order: points and lines before walls (a wall lies over what is behind it),
// wall depth, wall colour; the faint "behind the wall" and running dashes on top of everything
const WALL_DEPTH = 8, WALL_COLOR = 9, ON_TOP = 10;

// Object layer when it is not on the drawing: a line by its route, a box, the panel
const fallbackLayer = (key: string, w?: SceneWire) =>
  (w ? (w.route === "floor" ? "W-CABLE-FLOOR" : "W-CABLE") : key.startsWith("box:") ? "W-BOX"
    : key.startsWith("board:") ? "E-BOARD" : key.startsWith("riser:") ? "P-RISER"
      : key.startsWith("fixture:") ? "P-FIXT" : null);
const PIPE_LAYER: Record<PipeKind, string> = { cold: "P-COLD", hot: "P-HOT", sewer: "P-SEWER" };

function shape(rings: XY[][]): THREE.Shape {
  const v = (r: XY[]) => r.map(([x, y]) => new THREE.Vector2(x, y));
  const s = new THREE.Shape(v(rings[0]));
  for (const hole of rings.slice(1)) s.holes.push(new THREE.Path(v(hole)));
  return s;
}

export function Scene3D(props: Props) {
  const down = useRef<{ x: number; y: number } | null>(null);
  return (
    <div className={ui.three} onPointerDown={(e) => { down.current = { x: e.clientX, y: e.clientY }; }}>
      <Canvas
        orthographic
        frameloop="demand"
        dpr={window.devicePixelRatio || 1}
        camera={{ up: [0, 0, 1], near: -1e6, far: 1e6, position: [0, -1, 1], zoom: 0.05 }}
        raycaster={{ params: { Line2: { threshold: 6 } } as unknown as THREE.RaycasterParameters }}
        onPointerMissed={(e) => {
          // A click off objects clears the selection; the end of a camera rotation is not a click
          const d = down.current;
          if (e.type === "click" && d && Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) <= 4) {
            view.set({ selected: null, neighbors: null, pinned: null });
          }
        }}
      >
        <World {...props} />
      </Canvas>
    </div>
  );
}

function World({ scene, index, own, layerOf, links, apiRef, onZoom, onHome }: Props) {
  const { camera, size, invalidate } = useThree();
  const controls = useRef<OrbitControlsImpl>(null);
  const s = useView((st) => st);
  refreshPalette();

  // Flat bounds and the "whole drawing" zoom
  const bounds = useMemo(() => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const f of scene.floors) for (const [x, y] of f.rings[0]) {
      x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
    }
    const center = new THREE.Vector3((x0 + x1) / 2, (y0 + y1) / 2, scene.ceiling / 2);
    return { center, ext: Math.max(Math.hypot(x1 - x0, y1 - y0), 3000) };
  }, [scene]);
  const fitZoom = Math.min(size.width, size.height * 1.4) / (bounds.ext * 1.15);

  // Zoom has the same five steps as the sheet: step k is ZOOM_STEPS[k] from "whole flat",
  // moving smoothly (Glide) towards the screen centre
  const step = useRef(-1);  // -1 means not shown yet: the first step is reported to the page
  const glide = useMemo(() => new Glide(), []);
  const zoomTo = (k: number, animate = true) => {
    k = clampStep(k);
    if (k !== step.current) { step.current = k; onZoom({ step: k, label: zoomLabel(k), pxPerMm: null }); }
    glide.stop();
    const to = fitZoom * ZOOM_STEPS[k];
    const apply = (z: number) => { camera.zoom = z; camera.updateProjectionMatrix(); invalidate(); };
    if (animate) glide.run({ scale: camera.zoom, ox: 0, oy: 0 }, to, 0, 0, (v) => apply(v.scale));
    else apply(to);
  };
  useEffect(() => () => glide.stop(), [glide]);

  // The camera looks at target from direction (from target to the camera), zoom is step k
  const look = (target: THREE.Vector3, direction: THREE.Vector3, k: number) => {
    const c = controls.current;
    camera.position.copy(target).addScaledVector(direction.clone().normalize(), bounds.ext * 2);
    if (c) { c.target.copy(target); c.update(); }
    zoomTo(k, false);
  };
  const direction = () => camera.position.clone().sub(controls.current?.target ?? bounds.center);

  apiRef.current = {
    iso: () => look(bounds.center, HOME_DIRECTION, 0),
    // Whole drawing: the same angle, the whole flat
    fit: () => look(bounds.center, direction(), 0),
    zoomTo,
  };

  // Wheel and pinch go to the neighbouring step, as on the sheet (OrbitControls zoom is off)
  const gl = useThree((st) => st.gl);
  const latest = useRef(zoomTo);
  latest.current = zoomTo;
  useEffect(() => {
    const el = gl.domElement, wheel = new WheelSteps(), pinch = new PinchSteps();
    let span = 0;
    const dist = (e: TouchEvent) =>
      Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const dir = wheel.push(e.deltaY, performance.now());
      if (dir) latest.current(step.current + dir);
    };
    const onTouch = (e: TouchEvent) => {
      if (e.touches.length !== 2) { span = 0; return; }
      const d = dist(e);
      if (span && e.type === "touchmove") {
        const dir = pinch.push(d / span);
        if (dir) latest.current(step.current + dir);
      }
      span = d;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("touchstart", onTouch, { passive: true });
    el.addEventListener("touchmove", onTouch, { passive: true });
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouch);
      el.removeEventListener("touchmove", onTouch);
    };
  }, [gl]);
  // The display state changed (wall mode, theme, layers): a new frame. The wall material and the
  // cut change by mutation inside the frame, and frames are drawn only on demand (frameloop="demand")
  useEffect(() => { invalidate(); });
  // The window size changed: "whole flat" is different, the step stays
  useEffect(() => { zoomTo(step.current, false); }, [fitZoom]);  // eslint-disable-line react-hooks/exhaustive-deps
  // First show: isometry
  useEffect(() => { apiRef.current?.iso(); }, [scene]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Focus on objects (double click): the same angle, closer
  const groupRef = useRef<THREE.Group>(null);
  const focus = (keys: Set<string>) => {
    const box = new THREE.Box3();
    groupRef.current?.traverse((o) => { if (o.userData.key && keys.has(o.userData.key)) box.expandByObject(o); });
    if (box.isEmpty()) return;
    const sz = box.getSize(new THREE.Vector3());
    const zoom = Math.min(size.width, size.height) / (Math.max(sz.x, sz.y, sz.z, 500) * 1.6);
    look(box.getCenter(new THREE.Vector3()), direction(), stepBelow(zoom / fitZoom));
  };

  const walls = useMemo(() => {
    const pieces = scene.walls.flatMap((w) => w.polys.map((poly) => ({ w, poly })));
    const edges = wallEdges(pieces.map(({ w, poly }) => ({ polys: [poly], z: w.z })));
    return pieces.map(({ w, poly }, i) => {
      const geo = new THREE.ExtrudeGeometry(shape(poly), { depth: w.z[1] - w.z[0], bevelEnabled: false });
      const lines = new THREE.BufferGeometry();
      lines.setAttribute("position", new THREE.Float32BufferAttribute(edges[i], 3));
      return { geo, edges: lines, z0: w.z[0], h: w.z[1] - w.z[0], normals: w.normals };
    });
  }, [scene]);
  // The slab goes under the room floors: door openings and pockets between walls are floor too
  const floors = useMemo(() => [...(scene.slab ?? []).map((ring) => [ring]), ...scene.floors.map((f) => f.rings)]
    .map((rings) => new THREE.ShapeGeometry(shape(rings))), [scene]);
  // Points, boxes, panel: on a wall or on the ceiling (shapes — solids.ts)
  const solids = useMemo(() => {
    const out: { key: string; pos: [number, number, number]; color: string; geo: THREE.BufferGeometry;
                 edges: THREE.EdgesGeometry; group?: string | null; room?: string }[] = [];
    const add = (key: string, pos: [number, number, number], color: string, geo: THREE.BufferGeometry,
                 group?: string | null, room?: string) =>
      out.push({ key, pos, color, geo, edges: new THREE.EdgesGeometry(geo), group, room });
    for (const [id, p] of Object.entries(scene.points)) {
      add(`point:${id}`, p.pos, p.color, pointGeometry(p.type, p.inward), p.group, p.room);
    }
    for (const [id, b] of Object.entries(scene.boxes)) {
      add(`box:${id}`, b.pos, "#9a948a", b.inward ? flat(b.inward, 100, 60, 100) : new THREE.BoxGeometry(100, 100, 60),
          b.group, b.room);
    }
    if (scene.board) add("board:board", scene.board.pos, "#6b6357", flat(scene.board.inward ?? [0, 1], 300, 100, 400));
    // Plumbing: a water outlet or drain is a puck on the wall, a riser a cylinder from floor to ceiling
    for (const f of Object.values(scene.fixtures ?? {})) {
      const [ix, iy] = f.inward;
      const geo = puck(f.inward, f.kind === "sewer" ? 40 : 22, 30, 20);
      const pos: [number, number, number] = [f.pos[0] + ix * 15, f.pos[1] + iy * 15, f.pos[2]];
      add(f.key, pos, f.color, geo, null, f.room);
    }
    for (const r of scene.risers ?? []) {
      const h = r.z[1] - r.z[0];
      const geo = new THREE.CylinderGeometry(r.r, r.r, h, 24).rotateX(Math.PI / 2);
      add(r.key, [r.pos[0], r.pos[1], r.z[0] + h / 2], "#8c564b", geo, null, r.room);
    }
    return out;
  }, [scene]);
  const wallMeshes = useRef<(THREE.Object3D | null)[]>([]);
  const flowLines = useRef(new Map<string, { material: { dashOffset: number; dashSize: number; gapSize: number } }>());

  const dark = isDark();
  // Depth of the front wall surface (no colour), then colour only on it. Both passes use one
  // material: with another one (MeshBasicMaterial) a different shader computes the vertex, and
  // on the GPU (Metal) the whole face lands one depth unit behind its own write, so the "≤" test
  // fails and at some camera angles the face disappears from the colour pass
  const depthMat = useMemo(() => new THREE.MeshLambertMaterial({ colorWrite: false, transparent: true }), []);
  const wallMat = useMemo(() => new THREE.MeshLambertMaterial({ transparent: true, depthWrite: false }), []);
  const edgeMat = useMemo(() => new THREE.LineBasicMaterial({ transparent: true, opacity: 0.45 }), []);
  wallMat.color.set(dark ? "#8a9096" : "#cfc6b8");
  wallMat.opacity = s.wallMode === "ghost" ? WALL_GHOST_ALPHA : WALL_ALPHA;
  edgeMat.color.set(dark ? "#bbbebf" : "#29251f");

  // Cut: a partition between rooms is always a low rim; an exterior wall is a rim when it stands
  // between the camera and the room (its normal into the room faces away from the camera more
  // than CUT_DOT), otherwise full height. The wall as a whole: all pieces (body, sill, lintel) use
  // one scale from the floor, and the lintel above an opening of a cut wall is not drawn: the
  // opening shows as a gap in the rim. The selected line's dashes run from source to target
  // (dash length in screen px)
  const atHome = useRef<boolean | null>(null);
  useFrame((state) => {
    const t = controls.current?.target ?? bounds.center, p = camera.position;
    const home = t.distanceTo(bounds.center) < bounds.ext * HOME_TOLERANCE
      && p.clone().sub(t).normalize().distanceTo(HOME_DIRECTION.clone().normalize()) < HOME_TOLERANCE
      && Math.abs(camera.zoom / fitZoom - 1) < HOME_TOLERANCE;
    if (home !== atHome.current) { atHome.current = home; onHome(home); }
    const dx = t.x - p.x, dy = t.y - p.y, len = Math.hypot(dx, dy) || 1;
    const mode = view.get().wallMode;
    const low = Math.min(1, CUT_HEIGHT_MM / scene.ceiling);
    walls.forEach((w, i) => {
      const m = wallMeshes.current[i];
      if (!m) return;
      m.visible = mode !== "none";
      let s = 1;
      if (mode === "cut") {
        const cut = w.normals.length > 1
          || w.normals.some(([nx, ny]) => (nx * dx + ny * dy) / len > CUT_DOT);
        if (cut) { s = low; if (w.z0 > 1) m.visible = false; }
      }
      m.scale.z = s; m.position.z = w.z0 * s;
    });
    const mm = 1 / camera.zoom;  // mm per px
    const time = REDUCED_MOTION ? 0 : state.clock.elapsedTime;
    for (const l of flowLines.current.values()) {
      Object.assign(l.material, { dashSize: FLOW_DASH_PX * mm, gapSize: FLOW_GAP_PX * mm,
                                  dashOffset: -time * FLOW_SPEED_PX * mm });
    }
    if (flowLines.current.size && !REDUCED_MOTION) state.invalidate();
  });

  const lit = (key: string) => key === s.hover || (!!s.lit && expand(key).some((k) => s.lit!.has(k)));
  const alpha = (key: string) => (!s.selected || s.selected.has(key) ? 1
    : s.neighbors && s.neighbors.has(key) ? NEIGHBOR_ALPHA : DIM_ALPHA);
  const handlers = (key: string) => objectEvents(key, index, focus);
  // An object is visible if its layer is visible on this tab; an unknown layer is always visible
  const visible = (key: string, w?: SceneWire, fallback?: string) => {
    const l = layerOf.get(key) ?? fallback ?? fallbackLayer(key, w);
    return !l || layerShown(own ?? new Set([l]), s.hidden, s.extra, l);
  };

  return (
    <>
      <color attach="background" args={[palette.paper]} />
      <hemisphereLight args={[0xffffff, 0x8a8478, 1.7]} />
      <directionalLight position={[-0.6, -1, 2]} intensity={1.1} />
      <OrbitControls ref={controls} makeDefault screenSpacePanning enableZoom={false} />
      <group ref={groupRef}>
        {/* Both sides: from below the slab must stay opaque, not be culled as a back face */}
        {floors.map((geo, i) => (
          <mesh key={`f${i}`} geometry={geo} position={[0, 0, -1]}>
            <meshBasicMaterial color={dark ? "#34373a" : "#d9dadc"} side={THREE.DoubleSide} />
          </mesh>
        ))}
        {walls.map((w, i) => (
          <group key={`w${i}`} ref={(m) => { wallMeshes.current[i] = m; }} position={[0, 0, w.z0]}>
            <mesh geometry={w.geo} material={depthMat} renderOrder={WALL_DEPTH} />
            <mesh geometry={w.geo} material={wallMat} renderOrder={WALL_COLOR} />
            <lineSegments geometry={w.edges} material={edgeMat} renderOrder={WALL_COLOR} />
          </group>
        ))}
        {/* Filtered items are not drawn at all, so they are never under the cursor */}
        {Object.entries(scene.wires)
          .filter(([id, w]) => shown3d(s.filter3d, w.group, w.room) && visible(`wire:${id}`, w)).map(([id, w]) => (
          <WireLines key={id} id={id} w={w} s={s} lit={lit(`wire:${id}`)} alpha={alpha(`wire:${id}`)}
                     handlers={handlers(`wire:${id}`)} flowLines={flowLines.current} />
        ))}
        {links.filter((l) => visible(l.key, undefined, LINK_LAYER)
                             && l.ends.some((k) => shown3d(s.filter3d, null, scene.points[k.slice(6)]?.room)))
          .map((l) => (
            <LinkLines key={l.key} link={l} lit={lit(l.key) || l.ends.some(lit)}
                       alpha={!s.selected || l.ends.some((k) => s.selected!.has(k)) ? 1 : DIM_ALPHA} />
          ))}
        {Object.entries(scene.pipes ?? {})
          .filter(([, p]) => shown3d(s.filter3d, null, p.room) && visible(p.key, undefined, PIPE_LAYER[p.kind])).map(([id, p]) => (
          <PipeLine key={id} p={p} lit={lit(p.key)} alpha={alpha(p.key)} handlers={handlers(p.key)} />
        ))}
        {solids.filter((o) => (o.key === "board:board" || shown3d(s.filter3d, o.group, o.room)) && visible(o.key)).map((o, i) => (
          <Solid key={`${o.key}#${i}`} k={o.key} pos={o.pos} color={o.color} lit={lit(o.key)} alpha={alpha(o.key)}
                 handlers={handlers(o.key)} edgeMat={edgeMat} geometry={o.geo} edges={o.edges} />
        ))}
      </group>
    </>
  );
}

// Hover shows a hint and highlight; click selects the line; double click focuses on it
function objectEvents(key: string, index: PageIndex, focus: (keys: Set<string>) => void) {
  const tipAt = (e: ThreeEvent<PointerEvent>) => {
    const r = (e.nativeEvent.target as HTMLElement).getBoundingClientRect();
    return { key, x: e.nativeEvent.clientX - r.left, y: e.nativeEvent.clientY - r.top };
  };
  const select = () => {
    const chain = index.chainOf(key);
    view.set({ selected: chain, neighbors: index.neighborsOf(chain), pinned: key, tip: null });
    return chain;
  };
  return {
    onPointerMove: (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation();
      if (e.buttons) return;
      const st = view.get();
      view.set({ hover: key, tip: st.pinned ? st.tip : tipAt(e) });
    },
    onPointerOut: () => {
      if (view.get().hover === key) view.set({ hover: null, tip: null });
    },
    onClick: (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      if (e.delta > 4) return;  // the end of a camera rotation is not a click
      select();
    },
    onDoubleClick: (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      focus(select());
    },
  };
}

type Handlers = ReturnType<typeof objectEvents>;

function WireLines({ id, w, s, lit, alpha, handlers, flowLines }: {
  id: string; w: SceneWire; s: ViewState; lit: boolean; alpha: number; handlers: Handlers;
  flowLines: Map<string, { material: { dashOffset: number; dashSize: number; gapSize: number } }>;
}) {
  const key = `wire:${id}`;
  const on = !!s.selected && s.selected.has(key);
  const color = lit ? palette.hl : screenColor(w.color);
  return (
    <>
      <Line points={w.pts} color={color} lineWidth={lit ? WIRE_LIT_PX : on ? WIRE_SEL_PX : WIRE_PX}
            transparent opacity={alpha} userData={{ key }} {...handlers} />
      {/* Hidden by a wall: faint, on top of everything */}
      <Line points={w.pts} color={color} lineWidth={2} transparent opacity={GHOST_ALPHA * alpha}
            depthTest={false} renderOrder={ON_TOP} raycast={() => null} />
      {on && (
        <Line points={w.pts} color={palette.hl} lineWidth={3} dashed depthTest={false} renderOrder={ON_TOP}
              raycast={() => null}
              ref={(l) => { if (l) flowLines.set(id, l as never); else flowLines.delete(id); }} />
      )}
    </>
  );
}

// A light link: thin, without its own hint (as on the sheet, it lights up with its switch or lights);
// the part hidden by a wall is faint, on top of everything
function LinkLines({ link, lit, alpha }: { link: LightLink3D; lit: boolean; alpha: number }) {
  const color = lit ? palette.hl : screenColor(link.color);
  return (
    <>
      {link.lines.map((pts, i) => (
        <group key={i}>
          <Line points={pts} color={color} lineWidth={lit ? WIRE_LIT_PX : WIRE_PX} transparent opacity={alpha}
                raycast={() => null} />
          <Line points={pts} color={color} lineWidth={2} transparent opacity={GHOST_ALPHA * alpha}
                depthTest={false} renderOrder={ON_TOP} raycast={() => null} />
        </group>
      ))}
    </>
  );
}

// Pipe: sewer is thicker than water; the part hidden by a wall is faint, on top of everything, as for cables
function PipeLine({ p, lit, alpha, handlers }: { p: ScenePipe; lit: boolean; alpha: number; handlers: Handlers }) {
  const color = lit ? palette.hl : screenColor(p.color);
  const width = (p.kind === "sewer" ? 2 : 1) * (lit ? WIRE_LIT_PX : WIRE_PX);
  return (
    <>
      <Line points={p.pts} color={color} lineWidth={width} transparent opacity={alpha}
            userData={{ key: p.key }} {...handlers} />
      <Line points={p.pts} color={color} lineWidth={2} transparent opacity={GHOST_ALPHA * alpha}
            depthTest={false} renderOrder={ON_TOP} raycast={() => null} />
    </>
  );
}

function Solid({ k, pos, color, lit, alpha, handlers, geometry, edges, edgeMat }: {
  k: string; pos: [number, number, number]; color: string; lit: boolean; alpha: number;
  handlers: Handlers; geometry: THREE.BufferGeometry; edges: THREE.EdgesGeometry; edgeMat: THREE.Material;
}) {
  return (
    <mesh position={pos} geometry={geometry} userData={{ key: k }} {...handlers}>
      <meshLambertMaterial color={color} transparent opacity={alpha} emissive={lit ? palette.hl : "#000000"} />
      <lineSegments geometry={edges} material={edgeMat} />
    </mesh>
  );
}
