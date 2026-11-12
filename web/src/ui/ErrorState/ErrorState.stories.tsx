// In place of a drawing when it failed: one line, a server message of several lines, with an action
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ErrorState } from ".";

const meta = {
  title: "UI/ErrorState",
  component: ErrorState,
  args: { children: "На листе нечего рисовать: electrical" },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ErrorState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Multiline: Story = { args: { children: "room.yaml: walls.w2.length: 4000 → невязка ΔX = 120 мм\nКонтур не замкнут: проверьте длины стен" } };
export const WithAction: Story = {
  args: { action: <button style={{ minHeight: 36, padding: "0 12px", border: "1px solid var(--line)", borderRadius: 6 }}>Перезагрузить</button> },
};
export const Dark: Story = { globals: { theme: "dark" } };
