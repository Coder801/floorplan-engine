// The sheet loader (4C): the mark in a frame with two segments running around it
import type { Meta, StoryObj } from "@storybook/react-vite";
import { MarkLoader } from ".";

const meta = {
  title: "UI/MarkLoader",
  component: MarkLoader,
  args: { size: 44 },
  parameters: { layout: "centered" },
} satisfies Meta<typeof MarkLoader>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Large: Story = { args: { size: 88 } };
export const Dark: Story = { globals: { theme: "dark" } };
