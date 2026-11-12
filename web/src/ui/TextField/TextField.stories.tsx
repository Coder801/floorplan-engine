// Text field: with a label, a hint, an error, the large login size, a code in mono, disabled
import type { Meta, StoryObj } from "@storybook/react-vite";
import { TextField } from ".";

const meta = {
  title: "UI/TextField",
  component: TextField,
  args: { label: "Название фирмы", placeholder: "Например, «Ремонт под ключ»" },
  parameters: { layout: "padded" },
  decorators: [(Story) => <div style={{ maxWidth: 360 }}><Story /></div>],
} satisfies Meta<typeof TextField>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const WithHint: Story = { args: { label: "Город", hint: "Необязательно: подставим в смету" } };
export const WithError: Story = { args: { label: "Высота потолка, мм", defaultValue: "27", error: "Высота — от 2000 до 4500 мм" } };
export const Large: Story = { args: { size: "lg", label: "Электронная почта", type: "email", placeholder: "you@example.com" } };
export const Code: Story = { args: { size: "lg", mono: true, label: "Код доступа", placeholder: "XXXX-XXXX", inputClassName: undefined } };
export const Disabled: Story = { args: { disabled: true, defaultValue: "Штроба" } };
export const Dark: Story = { args: { hint: "Так вас увидят клиенты" }, globals: { theme: "dark" } };
