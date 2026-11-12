// Layer visibility eye: visible, hidden, interactive next to a layer name
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { EyeToggle } from ".";

const meta = {
  title: "UI/EyeToggle",
  component: EyeToggle,
  args: { on: true, what: "Розетки", onToggle: () => {} },
  parameters: { layout: "padded" },
} satisfies Meta<typeof EyeToggle>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Visible: Story = {};
export const Hidden: Story = { args: { on: false } };
export const Interactive: Story = {
  render: function Render(args) {
    const [on, setOn] = useState(args.on);
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, opacity: on ? 1 : 1 }}>
        <EyeToggle {...args} on={on} onToggle={() => setOn(!on)} />
        <span style={{ opacity: on ? 1 : .45 }}>{args.what}</span>
      </div>
    );
  },
};
export const Dark: Story = { ...Interactive, globals: { theme: "dark" } };
