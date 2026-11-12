// Button tooltips (useTooltip): rest the mouse on a button for DELAY_MS or Tab to it
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useTooltip } from ".";

const b = { minHeight: 36, padding: "0 12px", border: "1px solid var(--line)", borderRadius: 6, background: "var(--raise)" } as const;

function Demo() {
  const tip = useTooltip();
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button style={b} {...tip.on("Проще: варианты и смета без инженерных подробностей")}>Простой</button>
      <button style={b} {...tip.on("Все листы, слои, правка трасс и выгрузка DXF")}>Инженерный</button>
      {tip.tip}
    </div>
  );
}

const meta = {
  title: "UI/Tooltip",
  component: Demo,
  parameters: { layout: "centered" },
} satisfies Meta<typeof Demo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Buttons: Story = {};
export const Dark: Story = { globals: { theme: "dark" } };
