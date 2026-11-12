// Headings: every size of the type scale, the level apart from the look (an h3 that looks like a
// caps label), muted
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Heading, type HeadingSize } from ".";

const SIZES: [HeadingSize, string][] = [
  ["display", "32 / 40 · 600 — экран приветствия"],
  ["title", "22 / 28 · 500 — заголовок страницы, h1"],
  ["heading", "16 / 24 · 600 — раздел, карточка, h2"],
  ["subheading", "14 / 20 · 600 — блок внутри карточки, h3"],
  ["caps", "11 / 16 · 600 — подпись раздела, h4"],
];

const meta = {
  title: "UI/Heading",
  component: Heading,
  args: { level: 2, children: "Смета электрики" },
  argTypes: { size: { control: "inline-radio", options: SIZES.map(([s]) => s) }, level: { control: "inline-radio", options: [1, 2, 3, 4] } },
  parameters: { layout: "padded" },
} satisfies Meta<typeof Heading>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Scale: Story = {
  render: () => (
    <div style={{ display: "grid", gap: 24 }}>
      {SIZES.map(([size, note]) => (
        <div key={size} style={{ display: "grid", gap: 4 }}>
          <Heading level={2} size={size}>Знаем, что в стене</Heading>
          <span className="small muted mono">{size} · {note}</span>
        </div>
      ))}
    </div>
  ),
};
export const LevelApartFromLook: Story = { args: { level: 3, size: "caps", children: "Слои" } };
export const Muted: Story = { args: { muted: true } };
export const Dark: Story = { ...Scale, globals: { theme: "dark" } };
