import { describe, expect, it } from "vitest";
import { anchorOf, cardSpot, cutout, hole, placeAt, STEPS, stepAllowed, type TourFacts, type TourStep } from "./steps";

const facts = (over: Partial<TourFacts> = {}): TourFacts =>
  ({ sheets: true, canAnswer: true, openQuestions: 2, canChoose: true, setupTotal: 4, ...over });

describe("tour steps", () => {
  it("all five steps are there for a client who answers and chooses", () => {
    expect(STEPS.filter((s) => stepAllowed(s, facts()))).toEqual(["overview", "sheets", "questions", "setup", "help"]);
  });

  it("questions need the right to answer and open questions", () => {
    expect(stepAllowed("questions", facts({ canAnswer: false }))).toBe(false);
    expect(stepAllowed("questions", facts({ openQuestions: 0 }))).toBe(false);
  });

  it("setup needs the right to choose and something to ask", () => {
    expect(stepAllowed("setup", facts({ canChoose: false }))).toBe(false);
    expect(stepAllowed("setup", facts({ setupTotal: 0 }))).toBe(false);
  });

  it("sheets need sheet tabs; overview and help are always allowed", () => {
    const none = facts({ sheets: false, canAnswer: false, canChoose: false });
    expect(STEPS.filter((s) => stepAllowed(s, none))).toEqual(["overview", "help"]);
  });
});

describe("tour anchors", () => {
  it("the questions are behind «⋯» on a phone", () => {
    expect(anchorOf("questions", 1280)).toEqual({ key: "questions", inMenu: false });
    expect(anchorOf("questions", 700)).toEqual({ key: "questions", inMenu: false });
    expect(anchorOf("questions", 560)).toEqual({ key: "questions-menu", inMenu: true });
  });

  it("setup is in the side panel on a wide screen, in the overview header on a narrow one", () => {
    expect(anchorOf("setup", 1280).key).toBe("setup");
    expect(anchorOf("setup", 900).key).toBe("setup-page");
    expect(anchorOf("help", 400).key).toBe("help");
  });
});

describe("tour place", () => {
  const without = (...gone: TourStep[]) => (s: TourStep) => !gone.includes(s);

  it("counts only the steps that are there", () => {
    expect(placeAt(0, 0, without("questions", "setup"))).toEqual({ step: "overview", index: 0, n: 1, total: 3 });
    expect(placeAt(1, 1, without("questions", "setup"))).toEqual({ step: "sheets", index: 1, n: 2, total: 3 });
    expect(placeAt(2, 2, without("questions", "setup"))).toEqual({ step: "help", index: 4, n: 3, total: 3 });
  });

  it("an anchor gone during the tour drops its step, the shown ones stay counted", () => {
    expect(placeAt(2, 2, without())).toMatchObject({ step: "questions", n: 3, total: 5 });
    expect(placeAt(2, 2, without("questions"))).toMatchObject({ step: "setup", n: 3, total: 4 });
  });

  it("nothing left is the end", () => {
    expect(placeAt(5, 5, without())).toBeNull();
    expect(placeAt(0, 0, () => false)).toBeNull();
  });
});

describe("tour card", () => {
  const screen = { width: 1280, height: 800 };
  const card = { width: 320, height: 200 };

  it("the cutout is 4 px around the anchor", () => {
    expect(cutout({ left: 100, top: 10, width: 80, height: 36 })).toEqual({ left: 96, top: 6, width: 88, height: 44 });
  });

  it("step 1: inside the cutout at its top left", () => {
    expect(cardSpot("overview", { left: 0, top: 60, width: 880, height: 740 }, card, screen)).toEqual({ left: 16, top: 76 });
  });

  it("a header anchor: under it, right edges together", () => {
    expect(cardSpot("questions", { left: 900, top: 6, width: 120, height: 44 }, card, screen)).toEqual({ left: 700, top: 62 });
  });

  it("does not go past the left edge", () => {
    expect(cardSpot("sheets", { left: 0, top: 6, width: 100, height: 44 }, card, screen)).toEqual({ left: 8, top: 62 });
  });

  it("setup: to the left of the button, inside the screen", () => {
    expect(cardSpot("setup", { left: 900, top: 700, width: 360, height: 52 }, card, screen)).toEqual({ left: 568, top: 592 });
  });

  it("no room below: to the left", () => {
    expect(cardSpot("help", { left: 1180, top: 700, width: 44, height: 44 }, card, screen)).toEqual({ left: 848, top: 592 });
  });
});

describe("tour veil", () => {
  it("cuts a hole for the cutout out of the whole screen", () => {
    expect(hole({ left: 10, top: 20, width: 100, height: 30 })).toBe(
      "polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, 10px 20px, 10px 50px, 110px 50px, 110px 20px, 10px 20px)");
  });
});
