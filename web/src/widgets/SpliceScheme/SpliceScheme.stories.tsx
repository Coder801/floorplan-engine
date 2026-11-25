// Flush box scheme as in the pinned hint (320 px card): a switch with the switched wire off its
// terminals (only switches of lights in a chain have joints, decision 2026-11-25), a pass switch with only neutral and earth joined, crimp
// sleeves, no feed, the simple interface mode, dark and English. Rows are buttons: a click logs
// the line in Actions
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SpliceScheme } from ".";
import { COLORS, crimped, hallSwitch, passSwitch } from "./mock";

const meta = {
  title: "Widgets/SpliceScheme",
  component: SpliceScheme,
  args: { splice: hallSwitch(), colors: COLORS, onOpen: () => {} },
  decorators: [(Story) => <div style={{ width: 276, padding: 12, border: "1px solid var(--line)", background: "var(--raise)" }}><Story /></div>],
} satisfies Meta<typeof SpliceScheme>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Switch: Story = {};

export const PassSwitch: Story = { args: { splice: passSwitch() } };

export const Crimp: Story = { args: { splice: crimped() } };

export const NoFeed: Story = { args: { splice: hallSwitch({ in: null }) } };

export const Simple: Story = { args: { splice: hallSwitch(), brief: true } };

export const Dark: Story = { globals: { theme: "dark" } };

export const English: Story = { globals: { lang: "en" } };
