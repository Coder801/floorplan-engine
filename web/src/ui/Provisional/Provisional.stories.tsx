// A provisional amount: alone, in a list of sums, in a table cell; the dark theme
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Provisional } from ".";

const LABEL = "Цена условная: материалы пока не по рыночным ценам";

const meta = {
  title: "UI/Provisional",
  component: Provisional,
  args: { label: LABEL, children: "40 000 грн" },
  parameters: { layout: "padded" },
} satisfies Meta<typeof Provisional>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Amount: Story = {};
export const InSums: Story = {
  render: () => (
    <dl style={{ display: "grid", gridTemplateColumns: "auto auto", gap: "4px 16px", justifyContent: "start" }}>
      <dt>Работы</dt><dd>12 000 грн</dd>
      <dt>Материалы</dt><dd><Provisional label={LABEL}>40 000 грн</Provisional></dd>
      <dt><b>Итого</b></dt><dd><b>52 000 грн</b></dd>
    </dl>
  ),
};
export const InTable: Story = {
  render: () => (
    <table>
      <tbody>
        <tr><td>Кабель ВВГнг 3×2,5</td><td style={{ textAlign: "right" }}>3 200</td></tr>
        <tr><td><b>Итого</b></td><td style={{ textAlign: "right" }}><b><Provisional label={LABEL}>18 450</Provisional></b></td></tr>
      </tbody>
    </table>
  ),
};
export const Dark: Story = { ...InSums, globals: { theme: "dark" } };
