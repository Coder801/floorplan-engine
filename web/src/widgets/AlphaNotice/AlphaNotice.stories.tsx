// The notice is shown once per browser: every story forgets that it was seen, so it opens again.
// After "Got it" or Esc it closes, as in the viewer; the "Remount" button in the toolbar shows it again
import type { Meta, StoryObj } from "@storybook/react-vite";
import { STAGE } from "@/shared/version";
import { AlphaNotice } from ".";
import { noticeKey } from "./seen";

const meta = {
  title: "Widgets/AlphaNotice",
  component: AlphaNotice,
  beforeEach: () => {
    try { localStorage.removeItem(noticeKey(STAGE)); } catch { /* storage off: the notice opens anyway */ }
  },
} satisfies Meta<typeof AlphaNotice>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Dark: Story = { globals: { theme: "dark" } };

export const Ukrainian: Story = { globals: { lang: "uk" } };

export const English: Story = { globals: { lang: "en" } };
