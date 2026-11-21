import { describe, expect, it } from "vitest";
import { oneLine } from "./LessonView";

describe("oneLine", () => {
  it("takes the first sentence and drops glossary markers and backticks", () => {
    expect(oneLine("An {{llm|LLM}} predicts the `next` token. It is trained on text.")).toBe("An LLM predicts the next token.");
  });
  it("handles Hindi sentence ends, text without a full stop and very long text", () => {
    expect(oneLine("{{llm|LLM}} अगला token predict करता है। यह text पर train होता है।")).toBe("LLM अगला token predict करता है।");
    expect(oneLine("no full stop here")).toBe("no full stop here");
    const long = oneLine("word ".repeat(100));
    expect(long.length).toBeLessThanOrEqual(221);
    expect(long.endsWith("…")).toBe(true);
  });
});
