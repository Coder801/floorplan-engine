// The dropdown panel under its button: menu items as plain rows here (MenuItem has its own
// stories), aligned to the right or the left edge of the button
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Menu } from ".";

const item = { display: "flex", alignItems: "center", minHeight: 40, padding: "0 12px", borderRadius: 6 } as const;

const meta = {
  title: "UI/Menu",
  component: Menu,
  args: { label: "Загрузить", children: null },
  parameters: { layout: "padded" },
  render: (args) => (
    <div style={{ position: "relative", display: "inline-block", marginLeft: args.align === "left" ? 0 : 260, height: 200 }}>
      <button style={{ minHeight: 36, padding: "0 12px", border: "1px solid var(--line)", borderRadius: 6 }}>Загрузить ▾</button>
      <Menu {...args}>
        <button role="menuitem" style={item}>Лист PNG</button>
        <button role="menuitem" style={item}>Проект DXF</button>
        <button role="menuitem" style={item} disabled>Альбом PDF</button>
      </Menu>
    </div>
  ),
} satisfies Meta<typeof Menu>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Right: Story = {};
export const Left: Story = { args: { align: "left" } };
export const Wide: Story = { args: { minWidth: 300 } };
export const Dark: Story = { globals: { theme: "dark" } };
