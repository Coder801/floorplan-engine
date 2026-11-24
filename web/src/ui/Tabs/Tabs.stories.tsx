// Tabs of a block: plain names, names with a count and a mark, more names than the width holds
// (the bar scrolls sideways), the dark theme. The story keeps the choice and shows the panel
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Tabs, type Tab } from ".";

const PLAIN: Tab<string>[] = [{ value: "work", label: "Работа" }, { value: "lines", label: "Позиции" }, { value: "feed", label: "Лента" }];
const RICH: Tab<string>[] = [
  { value: "work", label: "Работа", mark: true, ariaLabel: "Работа — требует внимания" },
  { value: "lines", label: "Позиции", count: "20 719,60 грн" },
  { value: "feed", label: "Лента", count: 3 },
  { value: "settings", label: "Настройки" },
];
const MANY: Tab<string>[] = ["План", "Электрика", "Свет", "Проводка", "Сантехника", "Тёплый пол", "Точки", "Развёртки"].map((n) => ({ value: n, label: n }));

const meta = {
  title: "UI/Tabs",
  component: Tabs,
  args: { label: "Разделы", tabs: PLAIN, value: "work", onChange: () => {} },
  parameters: { layout: "padded" },
  render: function Render(args) {
    const [value, setValue] = useState(args.value);
    return (
      <div style={{ maxWidth: 400 }}>
        <Tabs {...args} value={value} onChange={setValue}>
          <p style={{ margin: 0 }}>Содержимое вкладки «{value}»</p>
        </Tabs>
      </div>
    );
  },
} satisfies Meta<typeof Tabs<string>>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const CountsAndMark: Story = { args: { tabs: RICH, value: "lines" } };
export const Scrolling: Story = { args: { tabs: MANY, value: "План" } };
export const Dark: Story = { args: { tabs: RICH }, globals: { theme: "dark" } };
