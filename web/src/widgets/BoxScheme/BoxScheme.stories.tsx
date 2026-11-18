// Box scheme as in the pinned hint (320 px card): four cables, ten cables, no feed, the simple
// interface mode, dark and English. Rows are buttons: a click logs the target in Actions
import type { Meta, StoryObj } from "@storybook/react-vite";
import { BoxScheme } from ".";
import { boxData, COLORS, manyOuts } from "./mock";

const meta = {
  title: "Widgets/BoxScheme",
  component: BoxScheme,
  args: { box: boxData(), colors: COLORS, onOpen: () => {} },
  decorators: [(Story) => <div style={{ width: 276, padding: 12, border: "1px solid var(--line)", background: "var(--raise)" }}><Story /></div>],
} satisfies Meta<typeof BoxScheme>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const TenCables: Story = { args: { box: manyOuts() } };

export const NoFeed: Story = { args: { box: boxData({ in: null }) } };

export const OneCable: Story = { args: { box: boxData({ out: boxData().out.slice(0, 1) }) } };

export const Simple: Story = { args: { brief: true } };

export const NoColours: Story = { args: { colors: {} } };

export const Dark: Story = { args: { box: manyOuts() }, globals: { theme: "dark" } };

export const English: Story = { globals: { lang: "en" } };
