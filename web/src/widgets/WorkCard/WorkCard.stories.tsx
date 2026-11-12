// The task card in a side panel 400 px wide (on a narrow screen it takes the whole screen): the
// studio on a returned task, the installer on one that needs a photo, the client on review with
// ticks, the studio on review (accept / return ask the client's channel), a draft task (order,
// "after", lines to move, merge), an extra task with nowhere to merge, an accepted task whose feed
// says the studio accepted it for the client, and a server refusal
import type { Meta, StoryObj } from "@storybook/react-vite";
import { CLIENT, draftState, INSTALLER, noRun, TASKS, workState } from "@/widgets/WorkStage/mock";
import { WorkCard } from ".";

const pick = (id: string) => TASKS.find((t) => t.id === id)!;

const meta = {
  title: "Widgets/WorkCard",
  component: WorkCard,
  decorators: [(Story) => (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 400px", height: "100vh" }}>
      <div />
      <aside style={{ position: "relative", borderLeft: "1px solid var(--line)" }}><Story /></aside>
    </div>
  )],
  args: { task: pick("cable"), state: workState(), run: noRun, busy: false, error: null, onError: () => {}, me: "u-studio", onClose: () => {} },
} satisfies Meta<typeof WorkCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const StudioReturned: Story = {};
export const InstallerNeedsPhoto: Story = {
  args: { task: { ...pick("cable"), status: "in_progress", photos: [] }, state: workState({ can: INSTALLER, assignees: [] }), me: "u-petro" },
};
export const ClientReview: Story = {
  args: { task: { ...pick("cable"), status: "review" }, state: workState({ can: CLIENT, assignees: [] }), me: null },
};
export const StudioReview: Story = { args: { task: pick("boxes") } };
export const Draft: Story = (() => {
  const state = draftState("draft");
  return { args: { task: state.tasks.find((x) => x.id === "cable")!, state } };
})();
export const DraftDark: Story = { ...Draft, globals: { theme: "dark" } };
export const CycleRefused: Story = {
  args: { ...Draft.args, error: "after: зависимость по кругу: «Прокладка кабеля» → «Штробы, проходы, подрозетники» → «Прокладка кабеля»" },
};
export const ExtraWork: Story = { args: { task: pick("niche") } };
export const Accepted: Story = { args: { task: pick("chases") } };
export const Refused: Story = { args: { task: pick("insulation"), state: workState({ can: INSTALLER, assignees: [] }), error: "задача ждёт: Прокладка кабеля — начать раньше может только студия" } };
export const Dark: Story = { globals: { theme: "dark" } };
