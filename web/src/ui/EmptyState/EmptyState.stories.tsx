// In place of a drawing or a list: nothing to show, loading, with an action, compact in a panel
import type { Meta, StoryObj } from "@storybook/react-vite";
import { EmptyState } from ".";

const meta = {
  title: "UI/EmptyState",
  component: EmptyState,
  args: { children: "Выберите проект" },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof EmptyState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Loading: Story = { args: { children: "Загрузка…" } };
export const WithAction: Story = {
  args: {
    children: "Проект ещё не собран",
    action: <button style={{ minHeight: 36, padding: "0 12px", border: "1px solid var(--line)", borderRadius: 6 }}>Обновить</button>,
  },
};
export const Compact: Story = { args: { compact: true, children: "Нет таблиц на этом листе" } };
export const Dark: Story = { globals: { theme: "dark" } };
