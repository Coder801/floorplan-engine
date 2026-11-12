// Colour marks before a label: group colours as on the drawing, the square of a device off the lines
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Dot } from ".";

const GROUPS = [["QF1", "#d2491a"], ["QF2", "#1f6fb5"], ["QF3", "#2e6b45"], ["QF4", "#9a5b00"]] as const;

const meta = {
  title: "UI/Dot",
  component: Dot,
  args: { color: "#d2491a" },
  parameters: { layout: "padded" },
} satisfies Meta<typeof Dot>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Round: Story = {};
export const Square: Story = { args: { shape: "square", color: undefined } };
export const InList: Story = {
  render: () => (
    <div style={{ display: "grid", gap: 6 }}>
      {GROUPS.map(([id, c]) => <div key={id}><Dot color={c} /><span className="mono">{id}</span> · Розетки кухни</div>)}
      <div><Dot shape="square" /><span className="mono">QS1</span> · Вводной автомат</div>
    </div>
  ),
};
export const Dark: Story = { ...InList, globals: { theme: "dark" } };
