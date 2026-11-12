// Zoom scale on the right of the drawing: interactive (clicks, drag, arrows), at the ends
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { LAST_STEP, zoomLabel } from "@/shared/zoom";
import { ZoomRail } from ".";

const zoom = (step: number) => ({ step, label: zoomLabel(step), pxPerMm: 0.1 * (step + 1) });

const meta = {
  title: "UI/ZoomRail",
  component: ZoomRail,
  args: { zoom: zoom(1), onStep: () => {}, onFit: () => {}, fitLabel: "Вписать" },
  parameters: { layout: "fullscreen" },
  render: function Render(args) {
    const [step, setStep] = useState(args.zoom.step);
    return (
      <div style={{ position: "relative", height: 420, background: "var(--paper)" }}>
        <ZoomRail {...args} zoom={zoom(step)} onStep={(s) => setStep(Math.max(0, Math.min(LAST_STEP, s)))} onFit={() => setStep(0)} />
      </div>
    );
  },
} satisfies Meta<typeof ZoomRail>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Closest: Story = { args: { zoom: zoom(LAST_STEP) } };
export const Fitted: Story = { args: { zoom: zoom(0) } };
export const Dark: Story = { globals: { theme: "dark" } };
