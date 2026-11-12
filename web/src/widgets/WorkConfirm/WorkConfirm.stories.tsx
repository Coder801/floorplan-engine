// "How did the client confirm?": the studio accepts a task and approves the plan for the client.
// On a phone (Storybook viewport ≤ 560 px) the card sits at the bottom with big targets
import type { Meta, StoryObj } from "@storybook/react-vite";
import { WorkConfirm } from ".";

const meta = {
  title: "Widgets/WorkConfirm",
  component: WorkConfirm,
  args: { action: "Принять", detail: "Распаечные коробки", busy: false, onConfirm: () => {}, onCancel: () => {} },
} satisfies Meta<typeof WorkConfirm>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Accept: Story = {};
export const ApprovePlan: Story = {
  args: { action: "Утвердить план", detail: "Утвердить план работ на 143 000 грн? После этого сумма задач не меняется, новая работа — доп. задачей." },
};
export const Dark: Story = { globals: { theme: "dark" } };
export const English: Story = { globals: { lang: "en" }, args: { action: "Accept" } };
