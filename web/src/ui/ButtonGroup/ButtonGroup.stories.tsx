// Buttons in one frame, as over the drawing: toggles, a text and arrows, a single button.
// The buttons here are plain HTML in the ButtonGroup frame; in the viewer they are ui/Button bare
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ButtonGroup } from ".";

const b = { minHeight: 36, padding: "0 12px" } as const;

const meta = {
  title: "UI/ButtonGroup",
  component: ButtonGroup,
  args: { label: "Системы", children: null },
  parameters: { layout: "centered" },
} satisfies Meta<typeof ButtonGroup>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Toggles: Story = {
  render: (args) => (
    <ButtonGroup {...args}>
      <button style={{ ...b, background: "var(--accent)", color: "var(--accent-text)" }} aria-pressed>Розетки</button>
      <button style={b} aria-pressed={false}>Свет</button>
      <button style={b} aria-pressed={false}>Связь</button>
    </ButtonGroup>
  ),
};
export const Pager: Story = {
  render: (args) => (
    <ButtonGroup {...args} label="Страницы листа">
      <button style={b} aria-label="Назад">‹</button>
      <span className="mono" style={{ display: "flex", alignItems: "center", padding: "0 10px", borderLeft: "1px solid var(--line)" }}>2 / 3</span>
      <button style={b} aria-label="Вперёд">›</button>
    </ButtonGroup>
  ),
};
export const Single: Story = { render: (args) => <ButtonGroup {...args}><button style={b}>3D</button></ButtonGroup> };
export const Dark: Story = { ...Toggles, globals: { theme: "dark" } };
