// The state of a step: a check when decided, a dash when open (wizard steps, overview)
import type { Meta, StoryObj } from "@storybook/react-vite";
import { StepMark } from ".";

const STEPS = [["Трасса", true], ["Щит", true], ["Резерв", false], ["Мастер-выключатель", false]] as const;

const meta = {
  title: "UI/StepMark",
  component: StepMark,
  args: { done: true },
  parameters: { layout: "padded" },
} satisfies Meta<typeof StepMark>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Done: Story = {};
export const Open: Story = { args: { done: false } };
export const InList: Story = {
  render: () => (
    <div style={{ display: "grid", gap: 6 }}>
      {STEPS.map(([name, done]) => (
        <div key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}><StepMark done={done} /><span>{name}</span></div>
      ))}
    </div>
  ),
};
export const Dark: Story = { ...InList, globals: { theme: "dark" } };
