// Heading row of a slide-out panel: buttons on the right (close), or before the title (back)
import type { Meta, StoryObj } from "@storybook/react-vite";
import { PanelHeader } from ".";

const btn = { width: 36, height: 36, fontSize: 18, borderRadius: 6 } as const;

const meta = {
  title: "UI/PanelHeader",
  component: PanelHeader,
  args: { title: "Задача" },
  parameters: { layout: "fullscreen" },
  decorators: [(Story) => <div style={{ width: 400, background: "var(--panel)", borderRight: "1px solid var(--line)" }}><Story /></div>],
} satisfies Meta<typeof PanelHeader>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Close: Story = { args: { children: <button style={btn} aria-label="Закрыть">×</button> } };
export const Back: Story = { args: { title: "Вопросы", start: <button style={btn} aria-label="Закрыть">→</button> } };
export const LongTitle: Story = { args: { title: "Прокладка кабеля по потолку в гофре, кухня и коридор", children: <button style={btn} aria-label="Закрыть">×</button> } };
export const Dark: Story = { ...Close, globals: { theme: "dark" } };
