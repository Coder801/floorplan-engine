// Scale bar under the drawing: a round length at different zooms; no scale (pxPerMm null) shows nothing
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ScaleBar } from ".";

const meta = {
  title: "UI/ScaleBar",
  component: ScaleBar,
  args: { zoom: { step: 2, label: "200%", pxPerMm: 0.12 } },
  parameters: { layout: "centered" },
} satisfies Meta<typeof ScaleBar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Close: Story = { args: { zoom: { step: 4, label: "400%", pxPerMm: 0.6 } } };
export const Far: Story = { args: { zoom: { step: 0, label: "100%", pxPerMm: 0.03 } } };
export const NoScale: Story = { args: { zoom: { step: 0, label: "100%", pxPerMm: null } } };
export const Dark: Story = { globals: { theme: "dark" } };
