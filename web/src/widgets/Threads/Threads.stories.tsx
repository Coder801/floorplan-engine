// The questions panel of the database viewer (360 px): the studio with tabs by audience and every
// thread state (open, waiting for it, checking — ends after 4 s, resolved, superseded with its
// follow-up, closed), the client's own list without tabs, empty, a server error; dark and English.
// The API is a fake in memory (mock.ts): replies, accept and close work, nothing is sent
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import type { QuestionsMemory } from "@/shared/questions";
import type { Project } from "@/shared/types";
import { Threads } from ".";
import { fakeThreadsApi, THREADS } from "./mock";

const base: Project = {
  id: "kv42", name: "kv42", title: "Квартира на Садовой", built: 1, stale: false, stages: [], open_questions: 3, preview: false,
  can: { choose_variant: true, answer: true, review: true }, report: { questions: [], issues: [] }, answers: {},
  artifact: true, dxf: null, files: [], sources: [], model: [], work: true,
};

type Args = Parameters<typeof Threads>[0];

function Live(args: Args) {
  const memory = useRef<QuestionsMemory>({ drafts: {} });
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  return <Threads {...args} memory={memory} drafts={drafts} onDraft={(k, text) => setDrafts((all) => ({ ...all, [k]: text }))} />;
}

const meta = {
  title: "Widgets/Threads",
  component: Threads,
  args: {
    project: base, extraFor: () => null, drafts: {}, onDraft: () => {},
    memory: { current: { drafts: {} } }, onUnavailable: () => {}, onSettled: () => {}, api: fakeThreadsApi(),
  } as Args,
  render: (args) => <Live {...args} />,
  decorators: [(Story) => <div style={{ width: 360, height: 640, overflow: "auto", padding: 12, background: "var(--panel)" }}><Story /></div>],
} satisfies Meta<typeof Threads>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Studio: Story = {};
export const Client: Story = {
  args: {
    project: { ...base, can: { choose_variant: true, answer: true, review: false } },
    api: fakeThreadsApi(THREADS.filter((d) => d.question?.audience === "client")),
  },
};
export const Installer: Story = {
  args: {
    project: { ...base, can: { choose_variant: false, answer: true, review: false } },
    api: fakeThreadsApi(THREADS.filter((d) => d.question?.audience === "installer").map((d) => ({ ...d, state: "open" as const, waiting_for: "installer" as const, waiting_for_you: true }))),
  },
};
export const Empty: Story = { args: { api: fakeThreadsApi([]) } };
export const ServerError: Story = {
  args: { api: { ...fakeThreadsApi(), list: async () => { throw new Error("500: Internal Server Error"); } } },
};
export const Dark: Story = { globals: { theme: "dark" } };
export const English: Story = { globals: { lang: "en" } };
