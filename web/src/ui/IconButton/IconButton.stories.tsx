// Square buttons with a sign or an icon: the variants (bare, framed, the close cross, round over a
// picture), three sizes, pressed and disabled
import type { Meta, StoryObj } from "@storybook/react-vite";
import { IconButton } from ".";

const row = { display: "flex", alignItems: "center", gap: 12 } as const;
const Gear = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></svg>
);

const meta = {
  title: "UI/IconButton",
  component: IconButton,
  args: { label: "Настройки", children: <Gear /> },
  parameters: { layout: "centered" },
} satisfies Meta<typeof IconButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Bare: Story = {};
export const Framed: Story = { args: { variant: "framed" } };
export const Close: Story = { args: { variant: "close", label: "Закрыть", children: undefined } };
export const Round: Story = {
  args: { variant: "round", size: "sm", label: "Удалить фото", children: "×" },
  render: (args) => (
    <div style={{ position: "relative", width: 120, height: 120, borderRadius: 8, background: "linear-gradient(135deg, #c9b79c, #8a7a64)" }}>
      <IconButton {...args} style={{ position: "absolute", top: 4, right: 4 }} />
    </div>
  ),
};
export const Sizes: Story = {
  render: (args) => <div style={row}>{(["sm", "md", "lg"] as const).map((s) => <IconButton key={s} {...args} variant="framed" size={s} />)}</div>,
};
export const States: Story = {
  render: (args) => (
    <div style={row}>
      <IconButton {...args} variant="framed" />
      <IconButton {...args} variant="framed" pressed />
      <IconButton {...args} variant="framed" disabled />
    </div>
  ),
};
export const Dark: Story = { ...States, globals: { theme: "dark" } };
