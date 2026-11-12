// A render error in place of the sheet: the message and "Reload"; without an error the child shows
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Boundary } from ".";

function Broken(): never {
  throw new Error("Cannot read properties of undefined (reading 'items')");
}

const meta = {
  title: "UI/Boundary",
  component: Boundary,
  args: { children: <Broken /> },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof Boundary>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Failed: Story = {};
export const Fine: Story = { args: { children: <p style={{ padding: 24 }}>Лист нарисован</p> } };
export const Dark: Story = { globals: { theme: "dark" } };
