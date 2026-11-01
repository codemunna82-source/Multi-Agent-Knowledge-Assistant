/** Small, deterministic teaching versions of the algorithms the Academy explains. They run in the browser, are exact for what they do (chunking, cosine,
 *  BM25, RRF, softmax) and clearly simplified where real systems use learned models (tokenizer, embeddings, attention). */

export function hash(s: string): number {                       // FNV-1a, 32 bit
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h >>> 0;
}
export function rng(seed: number): () => number {              // mulberry32
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** Words, numbers and punctuation; long words are cut into pieces of 4 letters to mimic subword tokenizers. */
export function toyTokenize(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(/[A-Za-zऀ-ॿ]+|\d+|[^\s]/g)) {
    const w = m[0];
    if (/^[A-Za-z]+$/.test(w) && w.length > 8) { for (let i = 0; i < w.length; i += 4) out.push((i ? "##" : "") + w.slice(i, i + 4)); } else out.push(w);
  }
  return out;
}
export const tokenId = (t: string) => (hash(t) % 50000) + 100;

/** Pseudo-embedding of a token: `dim` numbers in [-1, 1] derived from a hash (stands in for a learned vector). */
export function hashVector(t: string, dim = 8): number[] {
  const r = rng(hash(t));
  return Array.from({ length: dim }, () => Math.round((r() * 2 - 1) * 100) / 100);
}

export function cosine(a: number[], b: number[]): number {
  let d = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) { d += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  return na && nb ? d / Math.sqrt(na * nb) : 0;
}

const STOP = new Set(["the", "a", "an", "is", "are", "of", "to", "in", "and", "for", "on", "it", "how", "do", "i", "what", "does", "can", "my", "your", "with", "by", "at", "be", "this", "that"]);
export const words = (t: string) => (t.toLowerCase().match(/[a-z0-9ऀ-ॿ]+/g) ?? []);
export const contentWords = (t: string) => words(t).filter((w) => !STOP.has(w));

/** Concept groups: words in one group share a dimension, which is how this toy embedder makes synonyms land close together. */
export const CONCEPTS: Record<string, string[]> = {
  vehicle: ["car", "cars", "automobile", "vehicle", "truck", "bus", "drive", "driving", "road", "engine"],
  animal: ["cat", "dog", "pet", "pets", "animal", "puppy", "kitten", "fish", "bird"],
  food: ["pizza", "pasta", "food", "meal", "eat", "cook", "recipe", "restaurant", "dinner"],
  money: ["money", "pay", "salary", "wage", "price", "cost", "fee", "refund", "payment", "invoice", "bank", "dollar", "rupees"],
  leave: ["resign", "resignation", "quit", "notice", "retire", "leave", "vacation", "holiday", "absence"],
  work: ["job", "work", "employee", "employees", "company", "office", "manager", "team", "career", "hire"],
  tech: ["computer", "laptop", "software", "password", "login", "reset", "error", "upgrade", "server", "app"],
  health: ["doctor", "health", "medicine", "hospital", "sick", "insurance", "clinic"],
  weather: ["rain", "sun", "weather", "storm", "cold", "hot", "snow"],
  doc: ["document", "documents", "file", "pdf", "report", "policy", "page", "text", "contract"],
};
const CONCEPT_KEYS = Object.keys(CONCEPTS);

/** Bag-of-words with synonym groups. Real embedding models learn thousands of dimensions; this one has one per concept plus hashed word buckets. */
export function toyEmbed(text: string, dim = 24): number[] {
  const v = new Array(CONCEPT_KEYS.length + dim).fill(0);
  for (const w of contentWords(text)) {
    const c = CONCEPT_KEYS.findIndex((k) => CONCEPTS[k].includes(w));
    if (c >= 0) v[c] += 2;
    v[CONCEPT_KEYS.length + (hash(w) % dim)] += 1;
  }
  return v;
}

export function softmax(logits: number[], t = 1): number[] {
  const tt = Math.max(t, 1e-6);
  const m = Math.max(...logits);
  const ex = logits.map((x) => Math.exp((x - m) / tt));
  const s = ex.reduce((a, b) => a + b, 0);
  return ex.map((e) => e / s);
}

/** Top-k then top-p (nucleus) filtering of a probability vector; returns renormalised probabilities (0 for removed tokens). */
export function filterProbs(p: number[], topK: number, topP: number): number[] {
  const idx = p.map((v, i) => [v, i] as const).sort((a, b) => b[0] - a[0]);
  let keep = idx.slice(0, Math.max(1, topK));
  let acc = 0;
  const nuc: typeof keep = [];
  for (const e of keep) { nuc.push(e); acc += e[0]; if (acc >= topP) break; }
  keep = nuc;
  const total = keep.reduce((a, e) => a + e[0], 0);
  const out = new Array(p.length).fill(0);
  for (const [v, i] of keep) out[i] = v / total;
  return out;
}

export function sampleIndex(p: number[], u: number): number {
  let acc = 0;
  for (let i = 0; i < p.length; i++) { acc += p[i]; if (u <= acc) return i; }
  return p.length - 1;
}

export interface Chunk { id: number; start: number; end: number; text: string }
export function chunkText(text: string, size: number, overlap: number): Chunk[] {
  const out: Chunk[] = [];
  const step = Math.max(1, size - Math.min(overlap, size - 1));
  for (let s = 0; s < text.length; s += step) {
    out.push({ id: out.length, start: s, end: Math.min(text.length, s + size), text: text.slice(s, s + size) });
    if (s + size >= text.length) break;
  }
  return out;
}

export function bm25(query: string, docs: string[], k1 = 1.5, b = 0.75): number[] {
  const toks = docs.map(words);
  const avg = toks.reduce((a, t) => a + t.length, 0) / Math.max(1, toks.length);
  const df = new Map<string, number>();
  toks.forEach((t) => new Set(t).forEach((w) => df.set(w, (df.get(w) ?? 0) + 1)));
  return toks.map((t) => {
    const tf = new Map<string, number>();
    t.forEach((w) => tf.set(w, (tf.get(w) ?? 0) + 1));
    let s = 0;
    for (const w of words(query)) {
      const f = tf.get(w);
      if (!f) continue;
      const n = df.get(w) ?? 0;
      s += Math.log(1 + (docs.length - n + 0.5) / (n + 0.5)) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * (t.length / (avg || 1))));
    }
    return s;
  });
}

export const rank = (scores: number[]) => scores.map((s, i) => [s, i] as const).sort((a, b) => b[0] - a[0] || a[1] - b[1]).map(([, i]) => i);

export function rrf(rankings: number[][], k = 60): { id: number; score: number }[] {
  const sc = new Map<number, number>();
  rankings.forEach((r) => r.forEach((id, pos) => sc.set(id, (sc.get(id) ?? 0) + 1 / (k + pos + 1))));
  return [...sc.entries()].map(([id, score]) => ({ id, score })).sort((a, b) => b.score - a.score || a.id - b.id);
}

export const sentences = (t: string) => t.split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);
export const fmt = (n: number, d = 2) => (Math.round(n * 10 ** d) / 10 ** d).toFixed(d);
