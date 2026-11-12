// Select with icons: interactive, flat inside a button group, long labels (the box keeps the width
// of the widest option)
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Select, type SelectOption } from ".";

// A square of the room colour stands in for the room icon (ui/Icon is another component)
const mark = (c: string) => <span style={{ width: 12, height: 12, borderRadius: 3, background: c }} />;
const ROOMS: SelectOption[] = [
  { value: "", label: "Все помещения", icon: mark("var(--muted)") },
  { value: "kitchen", label: "Кухня", icon: mark("#e0a050") },
  { value: "bath", label: "Санузел", icon: mark("#4e9bd6") },
  { value: "living", label: "Гостиная", icon: mark("#6fb37a") },
];

const meta = {
  title: "UI/Select",
  component: Select,
  args: { label: "Помещение", options: ROOMS, value: "", onChange: () => {} },
  parameters: { layout: "padded" },
  render: function Render(args) {
    const [value, setValue] = useState(args.value);
    return <div style={{ height: 240 }}><Select {...args} value={value} onChange={setValue} /></div>;
  },
} satisfies Meta<typeof Select>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Flat: Story = {
  args: { flat: true },
  render: function Render(args) {
    const [value, setValue] = useState(args.value);
    return (
      <div style={{ height: 240 }}>
        <div style={{ display: "inline-flex", border: "1px solid var(--line)", borderRadius: 8, background: "var(--raise)", overflow: "hidden" }}>
          <Select {...args} value={value} onChange={setValue} />
        </div>
      </div>
    );
  },
};
export const TextOnly: Story = { args: { label: "Язык", value: "ru", options: [{ value: "ru", label: "Русский" }, { value: "uk", label: "Українська" }, { value: "en", label: "English" }] } };
export const Dark: Story = { globals: { theme: "dark" } };
