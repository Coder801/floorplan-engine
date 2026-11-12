// Segments: one choice of a few. Interactive (the story keeps the choice), stretched over the width,
// the phone size, a disabled segment, nothing chosen
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { SegmentedControl, type Segment } from ".";

const THEMES: Segment<string>[] = [{ value: "auto", label: "Авто" }, { value: "light", label: "Светлая" }, { value: "dark", label: "Тёмная" }];

const meta = {
  title: "UI/SegmentedControl",
  component: SegmentedControl,
  args: { label: "Тема", options: THEMES, value: "light", onChange: () => {} },
  parameters: { layout: "padded" },
  render: function Render(args) {
    const [value, setValue] = useState(args.value);
    return <div style={{ maxWidth: 420 }}><SegmentedControl {...args} value={value} onChange={setValue} /></div>;
  },
} satisfies Meta<typeof SegmentedControl<string>>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Fill: Story = { args: { fill: true } };
export const Large: Story = { args: { fill: true, size: "lg", label: "Канал", options: [{ value: "phone", label: "Звонок" }, { value: "tg", label: "Telegram" }, { value: "other", label: "Иначе" }], value: null } };
export const WithDisabled: Story = { args: { options: [...THEMES.slice(0, 2), { ...THEMES[2], disabled: true }] } };
export const Wrapping: Story = {
  args: { label: "Файлы модели", value: "room.yaml", options: ["room.yaml", "electrical.yaml", "plumbing.yaml", "intake.yaml", "answers.yaml"].map((f) => ({ value: f, label: f })) },
  render: function Render(args) {
    const [value, setValue] = useState(args.value);
    return <div style={{ maxWidth: 320 }}><SegmentedControl {...args} value={value} onChange={setValue} /></div>;
  },
};
export const Dark: Story = { args: { fill: true }, globals: { theme: "dark" } };
