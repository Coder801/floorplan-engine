// "Estimate for print": the parts of the electrical estimate and the page orientation. On a phone
// (Storybook viewport ≤ 560 px) the card sits at the bottom with big targets
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportDialog } from ".";

const meta = {
  title: "Widgets/ReportDialog",
  component: ReportDialog,
  args: { projectKey: "demo", onClose: () => {} },
} satisfies Meta<typeof ReportDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Dark: Story = { globals: { theme: "dark" } };
export const Ukrainian: Story = { globals: { lang: "uk" } };
export const English: Story = { globals: { lang: "en" } };
