// Tags: soft (in a card), outline (next to a heading), mono (a file format); every tone
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Tag } from ".";

const TONES = ["muted", "default", "major", "critical", "ok", "accent"] as const;
const row = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 } as const;

const meta = {
  title: "UI/Tag",
  component: Tag,
  args: { children: "Электрика" },
  parameters: { layout: "padded" },
} satisfies Meta<typeof Tag>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Soft: Story = {};
export const Outline: Story = { args: { variant: "outline", children: "как в проекте" } };
export const Mono: Story = { render: () => <div style={row}><Tag variant="mono">PNG</Tag><Tag variant="mono">DXF</Tag><Tag variant="mono">PDF</Tag></div> };
export const Tones: Story = {
  render: () => (
    <div style={{ display: "grid", gap: 12 }}>
      {(["soft", "outline"] as const).map((v) => (
        <div key={v} style={row}>{TONES.map((tone) => <Tag key={tone} variant={v} tone={tone}>{tone}</Tag>)}</div>
      ))}
    </div>
  ),
};
export const InHeading: Story = {
  render: () => <h2>Санузел <Tag variant="outline">мокрая зона</Tag></h2>,
};
export const Dark: Story = { ...Tones, globals: { theme: "dark" } };
