// Multi-line field: with a counter, over the limit, an error, disabled
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { TextArea } from ".";

const MAX = 120;

const meta = {
  title: "UI/TextArea",
  component: TextArea,
  args: { label: "Комментарий", placeholder: "Что нужно переделать", rows: 3 },
  parameters: { layout: "padded" },
  decorators: [(Story) => <div style={{ maxWidth: 420 }}><Story /></div>],
} satisfies Meta<typeof TextArea>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const WithCounter: Story = {
  render: function Render(args) {
    const [text, setText] = useState("Розетка у окна стоит ниже, чем на плане");
    const n = text.trim().length;
    return <TextArea {...args} label="Сообщение" value={text} onChange={(e) => setText(e.target.value)} counter={`${n} / ${MAX}`} over={n > MAX} />;
  },
};
export const WithError: Story = { args: { error: "Напишите, что не так" } };
export const WithHint: Story = { args: { hint: "Монтажник увидит комментарий в карточке задачи" } };
export const Disabled: Story = { args: { disabled: true, defaultValue: "Сохраняется…" } };
export const Dark: Story = { ...WithCounter, globals: { theme: "dark" } };
