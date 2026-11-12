// Interface icons: the whole set; size and colour come from the surrounding text
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Icon, type IconName } from ".";

const NAMES: IconName[] = ["bath", "door", "grid", "home", "kitchen", "sofa", "sun"];

const meta = {
  title: "UI/Icon",
  component: Icon,
  args: { name: "home" },
  argTypes: { name: { control: "select", options: NAMES } },
  parameters: { layout: "padded" },
} satisfies Meta<typeof Icon>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const All: Story = {
  render: () => (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, 96px)", gap: 16 }}>
      {NAMES.map((n) => (
        <div key={n} style={{ display: "grid", justifyItems: "center", gap: 6 }}>
          <span style={{ fontSize: 24, display: "inline-flex" }}><Icon name={n} /></span>
          <span className="small muted mono">{n}</span>
        </div>
      ))}
    </div>
  ),
};
export const Coloured: Story = { render: () => <span style={{ color: "var(--hl)", display: "inline-flex" }}><Icon name="sun" /></span> };
export const Dark: Story = { ...All, globals: { theme: "dark" } };
