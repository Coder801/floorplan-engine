// "Leave feedback": the form over a project sheet and without a project; sending goes to a fake
// (no API): Default thanks after a short wait, RateLimited and SignedOut show the inline errors.
// On a phone (Storybook viewport ≤ 560 px) the card sits at the bottom
import type { Meta, StoryObj } from "@storybook/react-vite";
import { FeedbackError } from "@/shared/api";
import { Feedback } from ".";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const where = () => ({ path: "/#kv42", width: 1440, height: 900, dpr: 2, userAgent: "Storybook" });

const meta = {
  title: "Widgets/Feedback",
  component: Feedback,
  args: {
    project: { key: "kv42", title: "Квартира на Садовой" },
    sheet: "electrical",
    sheetTitle: "Электрика",
    onClose: () => {},
    send: async () => { await wait(600); return { id: "f1" }; },
    where,
  },
} satisfies Meta<typeof Feedback>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const NoProject: Story = { args: { project: null, sheet: null, sheetTitle: null } };
export const RateLimited: Story = {
  args: { send: async () => { await wait(300); throw new FeedbackError(429, "Слишком часто: следующее сообщение — через 10 минут."); } },
};
export const SignedOut: Story = {
  args: { send: async () => { await wait(300); throw new FeedbackError(401, "Unauthorized"); } },
};
export const Dark: Story = { globals: { theme: "dark" } };
export const English: Story = { globals: { lang: "en" }, args: { project: { key: "kv42", title: "Sadova flat" }, sheetTitle: "Electrical" } };
