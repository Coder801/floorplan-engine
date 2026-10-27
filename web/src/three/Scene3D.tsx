// 3D проводки (ключ scene страницы проводки, scene3d.py): мм модели, ось Z вверх.
// Стены «срез» — стены между камерой и помещением бортиком; закрытая стеной часть линии —
// бледно поверх всего; подсказки, выделение и связь с таблицами — через общее состояние.

import { Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import {
  CUT_DOT, CUT_HEIGHT_MM, DIM_ALPHA, FLOW_DASH_PX, FLOW_GAP_PX, FLOW_SPEED_PX, GHOST_ALPHA,
  NEIGHBOR_ALPHA, REDUCED_MOTION, WALL_ALPHA, WALL_GHOST_ALPHA, WIRE_LIT_PX, WIRE_PX, WIRE_SEL_PX,
} from "../consts";
import { expand, type PageIndex } from "../page";
import { isDark, palette, refreshPalette, screenColor } from "../palette";
import { useView, view, type ViewState } from "../store";
import type { Scene, SceneWire, XY } from "../types";

export interface Scene3DApi {
  iso(): void;
  fit(): void;
  zoomBy(f: number): void;
}

interface Props {
  scene: Scene;
  index: PageIndex;
  apiRef: MutableRefObject<Scene3DApi | null>;
  onZoom: (label: string) => void;
}

// Ключ слоя линии — как на листе, чтобы выключенные слои прятались и в 3D
const wireLayer = (w: SceneWire) => (w.route === "floor" ? "W-CABLE-FLOOR" : "W-CABLE");

function shape(rings: XY[][]): THREE.Shape {
  const v = (r: XY[]) => r.map(([x, y]) => new THREE.Vector2(x, y));
  const s = new THREE.Shape(v(rings[0]));
  for (const hole of rings.slice(1)) s.holes.push(new THREE.Path(v(hole)));
  return s;
}

export function Scene3D(props: Props) {
  const down = useRef<{ x: number; y: number } | null>(null);
  return (
    <div className="three" onPointerDown={(e) => { down.current = { x: e.clientX, y: e.clientY }; }}>
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

function World({ scene, index, apiRef, onZoom }: Props) {
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

  // Камера смотрит на target из direction (от target к камере)
  const look = (target: THREE.Vector3, direction: THREE.Vector3, zoom: number) => {
    const c = controls.current;
    camera.position.copy(target).addScaledVector(direction.clone().normalize(), bounds.ext * 2);
    camera.zoom = zoom;
    camera.updateProjectionMatrix();
    if (c) { c.target.copy(target); c.update(); }
    invalidate();
  };
  const direction = () => camera.position.clone().sub(controls.current?.target ?? bounds.center);

  apiRef.current = {
    // Изометрия: с юго-запада сверху
    iso: () => look(bounds.center, new THREE.Vector3(-1, -1, 1.15), fitZoom),
    // Весь чертёж: тот же угол, вся квартира
    fit: () => look(bounds.center, direction(), fitZoom),
    zoomBy: (f) => {
      camera.zoom = Math.min(Math.max(camera.zoom * f, fitZoom * 0.3), fitZoom * 60);
      camera.updateProjectionMatrix();
      invalidate();
    },
  };
  // Первый показ — изометрия
  useEffect(() => { apiRef.current?.iso(); }, [scene]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Навести на объекты (двойной клик): тот же угол, крупнее
  const groupRef = useRef<THREE.Group>(null);
  const focus = (keys: Set<string>) => {
    const box = new THREE.Box3();
    groupRef.current?.traverse((o) => { if (o.userData.key && keys.has(o.userData.key)) box.expandByObject(o); });
    if (box.isEmpty()) return;
    const sz = box.getSize(new THREE.Vector3());
    const zoom = Math.min(Math.max(Math.min(size.width, size.height) / (Math.max(sz.x, sz.y, sz.z, 500) * 1.6), fitZoom), fitZoom * 12);
    look(box.getCenter(new THREE.Vector3()), direction(), zoom);
  };

  const walls = useMemo(() => scene.walls.flatMap((w) => w.polys.map((poly) => {
    const geo = new THREE.ExtrudeGeometry(shape(poly), { depth: w.z[1] - w.z[0], bevelEnabled: false });
    return { geo, edges: new THREE.EdgesGeometry(geo, 30), z0: w.z[0], h: w.z[1] - w.z[0], normals: w.normals };
  })), [scene]);
  const floors = useMemo(() => scene.floors.map((f) => new THREE.ShapeGeometry(shape(f.rings))), [scene]);
  // Точки, коробки, щит: на стене — плоские по стене, на потолке — диск
  const solids = useMemo(() => {
    const out: { key: string; pos: [number, number, number]; color: string; geo: THREE.BufferGeometry;
                 edges: THREE.EdgesGeometry }[] = [];
    const add = (key: string, pos: [number, number, number], color: string, geo: THREE.BufferGeometry) =>
      out.push({ key, pos, color, geo, edges: new THREE.EdgesGeometry(geo) });
    for (const [id, p] of Object.entries(scene.points)) {
      add(`point:${id}`, p.pos, p.color, p.inward ? flat(p.inward, 80, 25, 80) : disc());
    }
    for (const [id, b] of Object.entries(scene.boxes)) {
      add(`box:${id}`, b.pos, "#9a948a", b.inward ? flat(b.inward, 100, 60, 100) : new THREE.BoxGeometry(100, 100, 60));
    }
    if (scene.board) add("board:board", scene.board.pos, "#6b6357", flat(scene.board.inward ?? [0, 1], 300, 100, 400));
    return out;
  }, [scene]);
  const wallMeshes = useRef<(THREE.Mesh | null)[]>([]);
  const flowLines = useRef(new Map<string, { material: { dashOffset: number; dashSize: number; gapSize: number } }>());

  const dark = isDark();
  const wallMat = useMemo(() => new THREE.MeshLambertMaterial({ transparent: true }), []);
  const edgeMat = useMemo(() => new THREE.LineBasicMaterial({ transparent: true, opacity: 0.45 }), []);
  wallMat.color.set(dark ? "#5c534a" : "#cfc6b8");
  wallMat.opacity = s.wallMode === "ghost" ? WALL_GHOST_ALPHA : WALL_ALPHA;
  edgeMat.color.set(dark ? "#e6ddcf" : "#29251f");

  // Срез: стены, что стоят между камерой и помещением, — бортиком, перемычки над ними — нет.
  // Пунктир выделенной линии бежит от источника к цели (штрих — в px экрана)
  useFrame((state) => {
    const t = controls.current?.target ?? bounds.center, p = camera.position;
    const dx = t.x - p.x, dy = t.y - p.y, len = Math.hypot(dx, dy) || 1;
    const mode = view.get().wallMode;
    walls.forEach((w, i) => {
      const m = wallMeshes.current[i];
      if (!m) return;
      m.visible = mode !== "none"; m.scale.z = 1;
      if (mode !== "cut" || !w.normals.some(([nx, ny]) => (nx * dx + ny * dy) / len > CUT_DOT)) return;
      if (w.z0 > 1) m.visible = false;
      else m.scale.z = Math.min(1, CUT_HEIGHT_MM / w.h);
    });
    const mm = 1 / camera.zoom;  // мм на px
    const time = REDUCED_MOTION ? 0 : state.clock.elapsedTime;
    for (const l of flowLines.current.values()) {
      Object.assign(l.material, { dashSize: FLOW_DASH_PX * mm, gapSize: FLOW_GAP_PX * mm,
                                  dashOffset: -time * FLOW_SPEED_PX * mm });
    }
    if (flowLines.current.size && !REDUCED_MOTION) state.invalidate();
    onZoom(`${Math.round((camera.zoom / fitZoom) * 100)}%`);
  });

  const lit = (key: string) => key === s.hover || (!!s.lit && expand(key).some((k) => s.lit!.has(k)));
  const alpha = (key: string) => (!s.selected || s.selected.has(key) ? 1
    : s.neighbors && s.neighbors.has(key) ? NEIGHBOR_ALPHA : DIM_ALPHA);
  const handlers = (key: string) => objectEvents(key, index, focus);

  return (
    <>
      <color attach="background" args={[palette.paper]} />
      <hemisphereLight args={[0xffffff, 0x8a8478, 1.7]} />
      <directionalLight position={[-0.6, -1, 2]} intensity={1.1} />
      <OrbitControls ref={controls} makeDefault screenSpacePanning />
      <group ref={groupRef}>
        {floors.map((geo, i) => (
          <mesh key={`f${i}`} geometry={geo} position={[0, 0, -1]}>
            <meshBasicMaterial color={dark ? "#2c2722" : "#f3efe7"} />
          </mesh>
        ))}
        {walls.map((w, i) => (
          <mesh key={`w${i}`} ref={(m) => { wallMeshes.current[i] = m; }} geometry={w.geo} material={wallMat}
                position={[0, 0, w.z0]}>
            <lineSegments geometry={w.edges} material={edgeMat} />
          </mesh>
        ))}
        {Object.entries(scene.wires).map(([id, w]) => (
          <WireLines key={id} id={id} w={w} s={s} lit={lit(`wire:${id}`)} alpha={alpha(`wire:${id}`)}
                     handlers={handlers(`wire:${id}`)} flowLines={flowLines.current} />
        ))}
        {solids.map((o) => (
          <Solid key={o.key} k={o.key} pos={o.pos} color={o.color} lit={lit(o.key)} alpha={alpha(o.key)}
                 handlers={handlers(o.key)} edgeMat={edgeMat} geometry={o.geo} edges={o.edges}
                 visible={!(o.key.startsWith("box:") && s.hidden.has("W-BOX"))} />
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
  const shown = !s.hidden.has(wireLayer(w));
  const on = !!s.selected && s.selected.has(key);
  const color = lit ? palette.hl : screenColor(w.color);
  return (
    <>
      <Line points={w.pts} color={color} lineWidth={lit ? WIRE_LIT_PX : on ? WIRE_SEL_PX : WIRE_PX}
            transparent opacity={alpha} visible={shown} userData={{ key }} {...handlers} />
      {/* Закрытое стеной — бледно поверх всего */}
      <Line points={w.pts} color={color} lineWidth={2} transparent opacity={GHOST_ALPHA * alpha}
            depthTest={false} renderOrder={5} visible={shown} raycast={() => null} />
      {shown && on && (
        <Line points={w.pts} color={palette.hl} lineWidth={3} dashed depthTest={false} renderOrder={6}
              raycast={() => null}
              ref={(l) => { if (l) flowLines.set(id, l as never); else flowLines.delete(id); }} />
      )}
    </>
  );
}

function Solid({ k, pos, color, lit, alpha, handlers, geometry, edges, edgeMat, visible = true }: {
  k: string; pos: [number, number, number]; color: string; lit: boolean; alpha: number;
  handlers: Handlers; geometry: THREE.BufferGeometry; edges: THREE.EdgesGeometry; edgeMat: THREE.Material;
  visible?: boolean;
}) {
  return (
    <mesh position={pos} geometry={geometry} userData={{ key: k }} visible={visible} {...handlers}>
      <meshLambertMaterial color={color} transparent opacity={alpha} emissive={lit ? palette.hl : "#000000"} />
      <lineSegments geometry={edges} material={edgeMat} />
    </mesh>
  );
}
