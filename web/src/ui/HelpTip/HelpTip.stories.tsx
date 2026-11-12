// "?" with a tooltip: opens on hover, focus and click. The "i" mark in a table, aligned left
import type { Meta, StoryObj } from "@storybook/react-vite";
import { HelpTip } from ".";

const meta = {
  title: "UI/HelpTip",
  component: HelpTip,
  args: { label: "Почему без паролей", text: "Пароль можно забыть или украсть. Вход по коду из почты или Telegram — каждый раз новый и действует 10 минут." },
  parameters: { layout: "centered" },
  decorators: [(Story) => <div style={{ padding: "16px 16px 140px 280px" }}><Story /></div>],
} satisfies Meta<typeof HelpTip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Info: Story = {
  args: { mark: "i", size: 18, align: "left", label: "О работе", text: "Цена включает штробление, укладку кабеля и заделку." },
  decorators: [(Story) => <div style={{ padding: "16px 280px 140px 16px" }}><Story /></div>],
};
export const Dark: Story = { globals: { theme: "dark" } };
