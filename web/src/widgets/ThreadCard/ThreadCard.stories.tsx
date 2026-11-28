// An opened thread as in the questions panel (360 px): one story per state — open for the studio
// (accept on each person's message, close) and for the client (only the reply), checking (the fake
// check ends after 4 s: the card polls and shows the AI message), resolved with the AI reason and
// changes, superseded, a follow-up with the link and the quote, closed by the studio (a thread that
// is not open only reads), a studio value question (no accept: it is answered by a form), a client
// choice (options fill the reply); dark and English.
// The API is a fake in memory (widgets/Threads/mock.ts): clicks work, nothing is sent
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import type { ThreadDetail } from "@/shared/threads";
import type { Project } from "@/shared/types";
import { ask, fakeThreadsApi, summaryOf, thread, THREADS } from "@/widgets/Threads/mock";
import { ThreadCard } from ".";

const STUDIO: Project["can"] = { choose_variant: true, answer: true, review: true };
const CLIENT: Project["can"] = { choose_variant: true, answer: true, review: false };
const byId = (id: string): ThreadDetail => THREADS.find((d) => d.id === id)!;

type Args = Parameters<typeof ThreadCard>[0];

function Live(args: Args) {
  const [draft, setDraft] = useState(args.draft);
  return <ThreadCard {...args} draft={draft} onDraft={setDraft} />;
}

const of = (id: string, can: Project["can"] = STUDIO): Partial<Args> => ({
  summary: summaryOf(byId(id)), can, api: fakeThreadsApi(THREADS, { checkMs: 4000 }),
});

const meta = {
  title: "Widgets/ThreadCard",
  component: ThreadCard,
  args: { projectKey: "kv42", draft: "", onDraft: () => {}, onChanged: () => {}, onOpen: () => {}, ...of("t1") } as Args,
  render: (args) => <Live {...args} />,
  decorators: [(Story) => <div style={{ width: 360, padding: 12, background: "var(--panel)" }}><Story /></div>],
} satisfies Meta<typeof ThreadCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const OpenStudio: Story = {};
export const OpenClient: Story = { args: of("t1", CLIENT) };
export const Checking: Story = { args: of("t2") };
export const Resolved: Story = { args: of("t3") };
export const Superseded: Story = { args: of("t4") };
export const FollowUp: Story = { args: of("t5") };
export const Closed: Story = { args: of("t6") };
export const FormQuestion: Story = { args: of("t7") };
export const ClientChoice: Story = {
  args: (() => {
    const choice = thread({
      id: "c1", question: ask({ id: "q8", text: "Сколько розеток у кровати слева?", kind: "choice", options: ["one", "two", "none"],
                                 option_labels: { one: "Одна", two: "Две", none: "Не нужна" } }),
    });
    return { summary: summaryOf(choice), can: CLIENT, api: fakeThreadsApi([choice]) };
  })(),
};
export const Dark: Story = { args: of("t3"), globals: { theme: "dark" } };
export const DarkChecking: Story = { args: of("t2"), globals: { theme: "dark" } };
export const English: Story = { args: of("t5"), globals: { lang: "en" } };
