// "Continue with Google" by Google's branding rules: light and dark themes
import type { Meta, StoryObj } from "@storybook/react-vite";
import { GoogleButton } from ".";

const meta = {
  title: "UI/GoogleButton",
  component: GoogleButton,
  args: { href: "#", label: "Войти через Google" },
  parameters: { layout: "padded" },
  decorators: [(Story) => <div style={{ maxWidth: 360 }}><Story /></div>],
} satisfies Meta<typeof GoogleButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Light: Story = {};
export const Dark: Story = { globals: { theme: "dark" } };
export const English: Story = { args: { label: "Continue with Google" } };
