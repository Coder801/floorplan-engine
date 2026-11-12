// Tooltip on a held pointer (HOLD_MS): rest the pointer on a table row for two seconds
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useHoldTip } from ".";

function Demo() {
  const hold = useHoldTip();
  const rows = [["QF1", "Освещение", "Кабель ВВГнг 3×1,5, 42 м"], ["QF2", "Розетки кухни", "Кабель ВВГнг 3×2,5, 18 м"], ["QF3", "Духовой шкаф", "Кабель ВВГнг 3×4, 9 м"]];
  return (
    <>
      <table style={{ borderCollapse: "collapse", minWidth: 360 }}>
        <tbody>
          {rows.map(([id, name, note]) => (
            <tr key={id} style={{ borderTop: "1px solid var(--line)" }}
                onPointerEnter={(e) => hold.start(note, e)} onPointerMove={hold.move} onPointerLeave={hold.stop}>
              <td className="mono" style={{ padding: "6px 8px" }}>{id}</td><td style={{ padding: "6px 8px" }}>{name}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {hold.tip}
    </>
  );
}

const meta = {
  title: "UI/HoldTip",
  component: Demo,
  parameters: { layout: "padded" },
} satisfies Meta<typeof Demo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Rows: Story = {};
export const Dark: Story = { globals: { theme: "dark" } };
