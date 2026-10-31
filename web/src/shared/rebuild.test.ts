import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { watchRebuild } from "./rebuild";

describe("watchRebuild", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("document", { hidden: false, addEventListener: vi.fn(), removeEventListener: vi.fn() });
    vi.stubGlobal("window", { addEventListener: vi.fn(), removeEventListener: vi.fn() });
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("время сборки изменилось — один раз зовёт onRebuilt", async () => {
    let built = 1;
    const onRebuilt = vi.fn();
    const stop = watchRebuild(async () => built, 1, onRebuilt, 100);
    await vi.advanceTimersByTimeAsync(250);
    expect(onRebuilt).not.toHaveBeenCalled();
    built = 2;
    await vi.advanceTimersByTimeAsync(250);
    expect(onRebuilt).toHaveBeenCalledTimes(1);
    stop();
  });

  it("ошибка сети и пустое время — не пересборка; после stop — тишина", async () => {
    const onRebuilt = vi.fn();
    let fail = true;
    const stop = watchRebuild(async () => { if (fail) throw new Error("сеть"); return null; }, 1, onRebuilt, 100);
    await vi.advanceTimersByTimeAsync(150);
    fail = false;
    await vi.advanceTimersByTimeAsync(150);
    expect(onRebuilt).not.toHaveBeenCalled();
    stop();
    const later = vi.fn();
    const stop2 = watchRebuild(async () => 5, 1, later, 100);
    stop2();
    await vi.advanceTimersByTimeAsync(300);
    expect(later).not.toHaveBeenCalled();
  });
});
