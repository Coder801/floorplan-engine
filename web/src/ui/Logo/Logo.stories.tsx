// The "St" mark: sizes from the header to the welcome screen
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Logo } from ".";

const meta = {
  title: "UI/Logo",
  component: Logo,
  args: { size: 28 },
  parameters: { layout: "centered" },
} satisfies Meta<typeof Logo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Sizes: Story = {
  render: () => <div style={{ display: "flex", alignItems: "end", gap: 24 }}>{[28, 32, 36, 56].map((s) => <Logo key={s} size={s} />)}</div>,
};
export const Dark: Story = { ...Sizes, globals: { theme: "dark" } };
