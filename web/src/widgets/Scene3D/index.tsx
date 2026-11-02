// 3D чертежа (ключ scene страницы проводки, scene3d.py): мм модели, ось Z вверх. Один на все
// вкладки чертежа: видно то, что видно в слоях вкладки (план — стены, электрика — точки,
// освещение — свет и выключатели, проводка — всё). Стены «срез» — перегородки бортиком,
// наружные стены — бортиком, когда стоят между камерой и помещением;
// закрытая стеной часть линии — бледно поверх всего; подсказки, выделение и связь с
// таблицами — через общее состояние.
// Стены полупрозрачные, но монолитом: сначала в глубину пишется передняя поверхность всех
// стен, затем цвет ложится только на неё — внутренние торцы кусков не складывают
// прозрачность в тёмные швы; контур — только там, где стена кончается (wallEdges.ts).

import { Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { layerShown } from "@/engine/sheet/drawing";
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

export interface Scene3DApi {
  iso(): void;
  fit(): void;
  zoomTo(step: number): void;  // шаг масштаба (shared/zoom.ts) от «вся квартира»
}

interface Props {
  scene: Scene;
  index: PageIndex;
  own: Set<string> | null;          // слои вкладки (sheet/drawing.ts); null — все
  layerOf: Map<string, string>;     // объект → его слой на чертеже
  apiRef: MutableRefObject<Scene3DApi | null>;
  onZoom: (zoom: Zoom) => void;
}

// Порядок прозрачного: точки и линии — до стен (стена ложится поверх того, что за ней),
// глубина стен, их цвет; бледное «за стеной» и бегущий пунктир — поверх всего
const WALL_DEPTH = 8, WALL_COLOR = 9, ON_TOP = 10;

// Слой объекта, если на чертеже его нет: линия — по трассе, коробка, щит
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
          // Клик мимо объектов — снять выделение; конец вращения камеры — не клик
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

function World({ scene, index, own, layerOf, apiRef, onZoom }: Props) {
  const { camera, size, invalidate } = useThree();
  const controls = useRef<OrbitControlsImpl>(null);
  const s = useView((st) => st);
  refreshPalette();

  // Габариты квартиры и масштаб «весь чертёж»
  const bounds = useMemo(() => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const f of scene.floors) for (const [x, y] of f.rings[0]) {
      x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
    }
    const center = new THREE.Vector3((x0 + x1) / 2, (y0 + y1) / 2, scene.ceiling / 2);
    return { center, ext: Math.max(Math.hypot(x1 - x0, y1 - y0), 3000) };
  }, [scene]);
  const fitZoom = Math.min(size.width, size.height * 1.4) / (bounds.ext * 1.15);

  // Масштаб — те же пять шагов, что у листа: шаг k — ZOOM_STEPS[k] от «вся квартира»,
  // переход плавный (Glide), к центру экрана
  const step = useRef(-1);  // -1 — ещё не показан: первый шаг сообщается странице
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

  // Камера смотрит на target из direction (от target к камере), масштаб — шаг k
  const look = (target: THREE.Vector3, direction: THREE.Vector3, k: number) => {
    const c = controls.current;
    camera.position.copy(target).addScaledVector(direction.clone().normalize(), bounds.ext * 2);
    if (c) { c.target.copy(target); c.update(); }
    zoomTo(k, false);
  };
  const direction = () => camera.position.clone().sub(controls.current?.target ?? bounds.center);

  apiRef.current = {
    // Изометрия: с юго-запада сверху
    iso: () => look(bounds.center, new THREE.Vector3(-1, -1, 1.15), 0),
    // Весь чертёж: тот же угол, вся квартира
    fit: () => look(bounds.center, direction(), 0),
    zoomTo,
  };

  // Колесо и щипок — на соседний шаг, как у листа (масштаб OrbitControls выключен)
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
  // Состояние показа сменилось (режим стен, тема, слои) — новый кадр: материал стен и «срез»
  // меняются мутацией и в кадре, а кадр рисуется только по запросу (frameloop="demand")
  useEffect(() => { invalidate(); });
  // Размер окна сменился — «вся квартира» другая, шаг тот же
  useEffect(() => { zoomTo(step.current, false); }, [fitZoom]);  // eslint-disable-line react-hooks/exhaustive-deps
  // Первый показ — изометрия
  useEffect(() => { apiRef.current?.iso(); }, [scene]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Навести на объекты (двойной клик): тот же угол, крупнее
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
  const floors = useMemo(() => scene.floors.map((f) => new THREE.ShapeGeometry(shape(f.rings))), [scene]);
  // Точки, коробки, щит: на стене — плоские по стене, на потолке — диск
  const solids = useMemo(() => {
    const out: { key: string; pos: [number, number, number]; color: string; geo: THREE.BufferGeometry;
                 edges: THREE.EdgesGeometry; group?: string | null; room?: string }[] = [];
    const add = (key: string, pos: [number, number, number], color: string, geo: THREE.BufferGeometry,
                 group?: string | null, room?: string) =>
      out.push({ key, pos, color, geo, edges: new THREE.EdgesGeometry(geo), group, room });
    for (const [id, p] of Object.entries(scene.points)) {
      add(`point:${id}`, p.pos, p.color, p.inward ? flat(p.inward, 80, 25, 80) : disc(), p.group, p.room);
    }
    for (const [id, b] of Object.entries(scene.boxes)) {
      add(`box:${id}`, b.pos, "#9a948a", b.inward ? flat(b.inward, 100, 60, 100) : new THREE.BoxGeometry(100, 100, 60),
          b.group, b.room);
    }
    if (scene.board) add("board:board", scene.board.pos, "#6b6357", flat(scene.board.inward ?? [0, 1], 300, 100, 400));
    // Сантехника: водорозетка и выпуск — шайба на стене, стояк — цилиндр от пола до потолка
    for (const f of Object.values(scene.fixtures ?? {})) {
      const [ix, iy] = f.inward;
      const geo = new THREE.CylinderGeometry(f.kind === "sewer" ? 40 : 22, f.kind === "sewer" ? 40 : 22, 30, 20)
        .rotateZ(Math.abs(ix) > Math.abs(iy) ? Math.PI / 2 : 0);
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
  // Глубина передней поверхности стен (без цвета), затем цвет — только на неё. Оба прохода —
  // одним материалом: у другого (MeshBasicMaterial) вершину считает другой шейдер, и на GPU
  // (Metal) грань целиком ложится на единицу глубины дальше своей же записи — тест «≤»
  // не проходит, и при части углов камеры грань пропадает из цветного прохода
  const depthMat = useMemo(() => new THREE.MeshLambertMaterial({ colorWrite: false, transparent: true }), []);
  const wallMat = useMemo(() => new THREE.MeshLambertMaterial({ transparent: true, depthWrite: false }), []);
  const edgeMat = useMemo(() => new THREE.LineBasicMaterial({ transparent: true, opacity: 0.45 }), []);
  wallMat.color.set(dark ? "#8a9096" : "#cfc6b8");
  wallMat.opacity = s.wallMode === "ghost" ? WALL_GHOST_ALPHA : WALL_ALPHA;
  edgeMat.color.set(dark ? "#bbbebf" : "#29251f");

  // Срез: перегородка между комнатами — всегда бортиком; наружная стена — бортиком, когда
  // стоит между камерой и помещением (нормаль в помещение смотрит от камеры сильнее CUT_DOT),
  // иначе в полный рост. Стена целиком: все куски (тело, подоконник, перемычка) — одним
  // масштабом от пола, перемычка над проёмом срезанной стены не рисуется — проём виден
  // разрывом бортика. Пунктир выделенной линии бежит от источника к цели (штрих — в px экрана)
  useFrame((state) => {
    const t = controls.current?.target ?? bounds.center, p = camera.position;
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
    const mm = 1 / camera.zoom;  // мм на px
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
  // Объект виден, если виден его слой на этой вкладке; слой неизвестен — виден всегда
  const visible = (key: string, w?: SceneWire, fallback?: string) => {
    const l = layerOf.get(key) ?? fallback ?? fallbackLayer(key, w);
    return !l || (own ? layerShown(own, s.hidden, s.extra, l) : !s.hidden.has(l));
  };

  return (
    <>
      <color attach="background" args={[palette.paper]} />
      <hemisphereLight args={[0xffffff, 0x8a8478, 1.7]} />
      <directionalLight position={[-0.6, -1, 2]} intensity={1.1} />
      <OrbitControls ref={controls} makeDefault screenSpacePanning enableZoom={false} />
      <group ref={groupRef}>
        {floors.map((geo, i) => (
          <mesh key={`f${i}`} geometry={geo} position={[0, 0, -1]}>
            <meshBasicMaterial color={dark ? "#34373a" : "#d9dadc"} />
          </mesh>
        ))}
        {walls.map((w, i) => (
          <group key={`w${i}`} ref={(m) => { wallMeshes.current[i] = m; }} position={[0, 0, w.z0]}>
            <mesh geometry={w.geo} material={depthMat} renderOrder={WALL_DEPTH} />
            <mesh geometry={w.geo} material={wallMat} renderOrder={WALL_COLOR} />
            <lineSegments geometry={w.edges} material={edgeMat} renderOrder={WALL_COLOR} />
          </group>
        ))}
        {/* Отфильтрованное не рисуется вовсе — и под курсор не попадает */}
        {Object.entries(scene.wires)
          .filter(([id, w]) => shown3d(s.filter3d, w.group, w.room) && visible(`wire:${id}`, w)).map(([id, w]) => (
          <WireLines key={id} id={id} w={w} s={s} lit={lit(`wire:${id}`)} alpha={alpha(`wire:${id}`)}
                     handlers={handlers(`wire:${id}`)} flowLines={flowLines.current} />
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

// На стене — плоский по стене, на потолке — диск
const flat = (inward: XY, w: number, d: number, h: number) =>
  (Math.abs(inward[0]) > Math.abs(inward[1]) ? new THREE.BoxGeometry(d, w, h) : new THREE.BoxGeometry(w, d, h));
const disc = () => new THREE.CylinderGeometry(60, 60, 20, 24).rotateX(Math.PI / 2);

// Наведение — подсказка и подсветка; клик — выделить линию; двойной клик — навести на неё
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
      if (e.delta > 4) return;  // конец вращения камеры — не клик
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
      {/* Закрытое стеной — бледно поверх всего */}
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

// Труба: канализация толще воды; закрытое стеной — бледно поверх всего, как у кабеля
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
