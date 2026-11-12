// Text roles and tones: lead, body, small, caps; muted, critical, major, ok; weights and mono
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Text } from ".";

const meta = {
  title: "UI/Text",
  component: Text,
  args: { children: "Розетка у окна на 300 мм от пола, кабель по стене вверх до коробки." },
  parameters: { layout: "padded" },
  decorators: [(Story) => <div style={{ maxWidth: 520 }}><Story /></div>],
} satisfies Meta<typeof Text>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Body: Story = {};
export const Sizes: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: 16 }}>
      {(["lead", "body", "small", "caps"] as const).map((s) => <Text key={s} {...args} size={s}>{`${s} — ${args.children}`}</Text>)}
    </div>
  ),
};
export const Tones: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: 8 }}>
      {(["default", "muted", "critical", "major", "ok"] as const).map((tone) => <Text key={tone} {...args} tone={tone}>{tone}: высота потолка 2700 мм</Text>)}
    </div>
  ),
};
export const Weights: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: 8 }}>
      {(["regular", "medium", "bold"] as const).map((w) => <Text key={w} {...args} weight={w}>{w}: Итого 184 200 ₴</Text>)}
      <Text {...args} mono>mono: QF3 · 2,40 кВт · 16 А</Text>
    </div>
  ),
};
export const Dark: Story = { ...Tones, globals: { theme: "dark" } };
