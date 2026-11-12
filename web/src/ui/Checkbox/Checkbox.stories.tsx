// Checkbox: interactive, with a note, indeterminate, disabled, without a label (a table cell)
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Checkbox } from ".";

const meta = {
  title: "UI/Checkbox",
  component: Checkbox,
  args: { label: "Материалы включены в цену", checked: false, onChange: () => {} },
  parameters: { layout: "padded" },
  render: function Render(args) {
    const [on, setOn] = useState(args.checked);
    return <Checkbox {...args} checked={on} onChange={setOn} />;
  },
} satisfies Meta<typeof Checkbox>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Checked: Story = { args: { checked: true } };
export const WithNote: Story = { args: { label: "QF3 · Кухня", note: "2,4 кВт · отключается при уходе", checked: true } };
export const Indeterminate: Story = { args: { label: "Все группы", indeterminate: true } };
export const Disabled: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: 8 }}>
      <Checkbox {...args} disabled checked={false} label="Недоступно" />
      <Checkbox {...args} disabled checked label="Недоступно, отмечено" />
    </div>
  ),
};
export const List: Story = {
  render: function Render(args) {
    const items = ["Штробы, проходы, подрозетники", "Прокладка кабеля", "Установка щита", "Подключение и маркировка"];
    const [on, setOn] = useState<string[]>([items[0]]);
    return (
      <div style={{ display: "grid", gap: 8, maxWidth: 360 }}>
        {items.map((x) => <Checkbox key={x} {...args} label={x} checked={on.includes(x)}
                                    onChange={(v) => setOn(v ? [...on, x] : on.filter((y) => y !== x))} />)}
      </div>
    );
  },
};
export const Bare: Story = { args: { label: undefined, "aria-label": "Выбрать строку" } };
export const Dark: Story = { ...List, globals: { theme: "dark" } };
