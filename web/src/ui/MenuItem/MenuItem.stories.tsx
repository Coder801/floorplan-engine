// Menu rows: icon | label | note, a link item, a disabled one, options of a list with a tick
import type { Meta, StoryObj } from "@storybook/react-vite";
import menu from "@/shared/styles/menu.module.scss";
import { MenuItem } from ".";

const badge = { font: "600 10px/16px 'IBM Plex Mono', monospace", padding: "1px 5px", border: "1px solid var(--line)", borderRadius: 4, color: "var(--muted)" };

const meta = {
  title: "UI/MenuItem",
  component: MenuItem,
  args: { children: "Лист для альбома", icon: <span style={badge}>PNG</span>, note: "A3, 150 dpi" },
  parameters: { layout: "padded" },
  decorators: [(Story) => <div className={menu.panel} style={{ position: "static", width: 320 }} role="menu"><Story /></div>],
} satisfies Meta<typeof MenuItem>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Link: Story = { args: { href: "#", download: "project.dxf", icon: <span style={badge}>DXF</span>, children: "Весь проект", note: "все листы" } };
export const Disabled: Story = { args: { disabled: true, note: undefined, children: "Проект ещё не собран" } };
export const Options: Story = {
  decorators: [(Story) => <div className={menu.panel} style={{ position: "static", width: 220 }} role="listbox"><Story /></div>],
  render: () => (
    <>
      <MenuItem role="option" selected note="✓">Русский</MenuItem>
      <MenuItem role="option" selected={false}>Українська</MenuItem>
      <MenuItem role="option" selected={false}>English</MenuItem>
    </>
  ),
};
export const Dark: Story = { globals: { theme: "dark" } };
