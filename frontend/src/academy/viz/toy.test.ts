import { describe, expect, it } from "vitest";
import { bm25, chunkText, cosine, filterProbs, hash, rank, rng, rrf, sampleIndex, sentences, softmax, toyEmbed, toyTokenize } from "./toy";

describe("toy algorithms", () => {
  it("hash and rng are deterministic", () => {
    expect(hash("abc")).toBe(hash("abc"));
    const a = rng(7), b = rng(7);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });
  it("tokenizer splits punctuation and long words into pieces", () => {
    expect(toyTokenize("Hello, world 2024!")).toEqual(["Hello", ",", "world", "2024", "!"]);
    expect(toyTokenize("internationalization")).toEqual(["inte", "##rnat", "##iona", "##liza", "##tion"]);
  });
  it("softmax with temperature matches the lesson example", () => {
    const p = softmax([2.0, 1.0, 0.1], 1).map((x) => Math.round(x * 1000) / 1000);
    expect(p).toEqual([0.659, 0.242, 0.099]);
    const sharp = softmax([2.0, 1.0, 0.1], 0.5);
    expect(sharp[0]).toBeGreaterThan(p[0]);
    expect(softmax([2, 1, 0.1], 2)[0]).toBeLessThan(p[0]);
    expect(softmax([1, 2, 3], 1).reduce((a, b) => a + b, 0)).toBeCloseTo(1, 10);
  });
  it("top-k and top-p remove the tail and renormalise", () => {
    const f = filterProbs([0.5, 0.3, 0.15, 0.05], 3, 1);
    expect(f[3]).toBe(0);
    expect(f.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 10);
    const n = filterProbs([0.5, 0.3, 0.15, 0.05], 4, 0.7);          // 0.5 + 0.3 >= 0.7: two tokens survive
    expect(n.filter((x) => x > 0)).toHaveLength(2);
    expect(sampleIndex([0.2, 0.5, 0.3], 0.1)).toBe(0);
    expect(sampleIndex([0.2, 0.5, 0.3], 0.6)).toBe(1);
    expect(sampleIndex([0.2, 0.5, 0.3], 0.99)).toBe(2);
  });
  it("chunker repeats the overlap and covers the whole text", () => {
    const t = "The refund window is 14 days. After that, store credit is offered. Exceptions need approval.";
    const c = chunkText(t, 40, 10);
    expect(c).toHaveLength(3);
    expect(c[1].start).toBe(30);
    expect(c[c.length - 1].end).toBe(t.length);
    expect(chunkText("abc", 100, 10)).toHaveLength(1);
  });
  it("synonyms are closer than unrelated words, and cosine is symmetric", () => {
    const car = toyEmbed("car"), auto = toyEmbed("automobile"), fish = toyEmbed("fish");
    expect(cosine(car, auto)).toBeGreaterThan(cosine(car, fish));
    expect(cosine(car, auto)).toBeCloseTo(cosine(auto, car), 12);
    expect(cosine([1, 0], [0, 1])).toBe(0);
  });
  it("BM25 prefers the document with the exact rare term; RRF merges by rank", () => {
    const docs = ["error E-4021 appears after upgrade", "upgrade failures check disk space", "export a report to pdf"];
    const s = bm25("error e 4021 upgrade", docs);
    expect(rank(s)[0]).toBe(0);
    expect(rrf([[0, 1, 2], [1, 0, 2]]).map((r) => r.id).slice(0, 2).sort()).toEqual([0, 1]);
    expect(rrf([[0, 1], [0, 1]])[0].id).toBe(0);
  });
  it("splits sentences", () => { expect(sentences("One. Two! Three?")).toEqual(["One.", "Two!", "Three?"]); });
});
