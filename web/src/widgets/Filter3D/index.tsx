// Wiring 3D filter: the room. Filtered lines, points and boxes are not drawn; the panel is always
// visible. Reset when the sheet changes. QF groups are switched by the eyes of the "Groups" table
// in the side panel.

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { PageIndex } from "@/shared/page";
import { useView, view } from "@/shared/store";
import type { RoomKind, Scene } from "@/shared/types";
import { ButtonGroup } from "@/ui/ButtonGroup";
import { Icon, type IconName } from "@/ui/Icon";
import { Select } from "@/ui/Select";

const ROOM_ICONS: Record<RoomKind, IconName> = { living: "sofa", kitchen: "kitchen", wet: "bath", service: "door", outdoor: "sun" };

export function Filter3D({ scene, index }: { scene: Scene; index: PageIndex }) {
  const filter = useView((s) => s.filter3d);
  const rooms = useMemo(() => scene.floors.map((f) => ({
    id: f.key.slice(f.key.indexOf(":") + 1), name: index.card(f.key).title, icon: ROOM_ICONS[f.kind ?? "living"],
  })), [scene, index]);

  const set = (room: string | null) =>
    view.set({ filter3d: { ...filter, room }, selected: null, neighbors: null, pinned: null, tip: null });
  const { t } = useTranslation();

  return (
    <ButtonGroup>
      <Select flat label={t("filter3d.room")} value={filter.room ?? ""} onChange={(v) => set(v || null)}
              options={[
                { value: "", label: t("filter3d.allRooms"), icon: <Icon name="grid" /> },
                ...rooms.map((r) => ({ value: r.id, label: r.name, icon: <Icon name={r.icon} /> })),
              ]} />
    </ButtonGroup>
  );
}
