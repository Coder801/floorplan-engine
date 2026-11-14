// A group of buttons, as over the drawing: toggles, a text and arrows, a single button, a badge
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ButtonGroup, GroupButton } from ".";

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
      <GroupButton pressed>Розетки</GroupButton>
      <GroupButton pressed={false}>Свет</GroupButton>
      <GroupButton pressed={false}>Связь</GroupButton>
    </ButtonGroup>
  ),
};
export const Badges: Story = {
  render: (args) => (
    <ButtonGroup {...args} label="Проект">
      <GroupButton pressed badge={3} aria-label="Вопросы, открыто 3">Вопросы</GroupButton>
      <GroupButton pressed={false} badge={12} aria-label="Исходники, 12">Исходники</GroupButton>
      <GroupButton pressed={false}>Сборка</GroupButton>
    </ButtonGroup>
  ),
};
export const Pager: Story = {
  render: (args) => (
    <ButtonGroup {...args} label="Страницы листа">
      <GroupButton aria-label="Назад">‹</GroupButton>
      <span className="mono">2 / 3</span>
      <GroupButton aria-label="Вперёд">›</GroupButton>
    </ButtonGroup>
  ),
};
export const Save: Story = {
  render: (args) => (
    <ButtonGroup {...args} label="Правка">
      <GroupButton signal>Сохранить (2)</GroupButton>
      <GroupButton>Отменить</GroupButton>
      <GroupButton disabled>Авто</GroupButton>
    </ButtonGroup>
  ),
};
export const Single: Story = { render: (args) => <ButtonGroup {...args}><GroupButton>3D</GroupButton></ButtonGroup> };
export const Dark: Story = { ...Toggles, globals: { theme: "dark" } };
