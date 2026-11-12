// Stack: the vertical rhythm. Each step of the 4px grid as the gap between the same blocks;
// a row of items that wraps; alignment
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Stack, type Space } from ".";

const box = { padding: "8px 12px", borderRadius: 6, background: "var(--soft)", border: "1px dashed var(--line)" } as const;
const STEPS: Space[] = [1, 2, 3, 4, 5, 6, 8, 10];

const meta = {
  title: "UI/Stack",
  component: Stack,
  args: { gap: 3 },
  argTypes: { gap: { control: "select", options: [0, ...STEPS] } },
  parameters: { layout: "padded" },
  render: (args) => (
    <Stack {...args} style={{ maxWidth: 360 }}>
      <div style={box}>Заголовок</div><div style={box}>Абзац</div><div style={box}>Кнопки</div>
    </Stack>
  ),
} satisfies Meta<typeof Stack>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Steps: Story = {
  render: () => (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 32, alignItems: "start" }}>
      {STEPS.map((g) => (
        <div key={g} style={{ display: "grid", gap: 8 }}>
          <span className="small muted mono">--space-{g} · {g * 4}px</span>
          <Stack gap={g}><div style={box}>A</div><div style={box}>B</div><div style={box}>C</div></Stack>
        </div>
      ))}
    </div>
  ),
};
export const Row: Story = {
  args: { direction: "row", gap: 2 },
  render: (args) => (
    <Stack {...args} style={{ maxWidth: 360 }}>
      {["Розетки", "Свет", "Связь", "Проводка", "Сантехника", "Щит"].map((x) => <div key={x} style={box}>{x}</div>)}
    </Stack>
  ),
};
export const RowBetween: Story = {
  args: { direction: "row", justify: "between", wrap: false },
  render: (args) => <Stack {...args} style={{ maxWidth: 360 }}><div style={box}>Назад</div><div style={box}>Далее</div></Stack>,
};
