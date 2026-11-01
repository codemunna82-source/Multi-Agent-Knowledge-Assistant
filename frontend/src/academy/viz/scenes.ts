import type { Lang } from "../types";
import { bm25, chunkText, contentWords, cosine, CONCEPTS, fmt, hash, hashVector, rank, rrf, sentences, toyEmbed, toyTokenize, tokenId, words } from "./toy";

export type Say = string | { en: string; hi: string; hinglish: string };
export const say = (s: Say, lang: Lang) => (typeof s === "string" ? s : s[lang]);
const S = (en: string, hi: string, hinglish: string): Say => ({ en, hi, hinglish });

export interface Stage {
  id: string; label: string; simple: Say; technical: string; input?: string; output: string; lines?: string[];
  segments?: { text: string; cls: "a" | "b" | "o" | "" }[];       // chunk view: alternating colours, overlap marked "o"
  state?: Record<string, unknown>; active?: string[];             // graph view: which nodes are lit and the state after this step
}
export interface InputDef { key: string; label: string; type: "text" | "textarea" | "number" | "select"; default: string | number; options?: string[]; min?: number; max?: number }
export type Values = Record<string, string | number>;
export interface GraphDef { nodes: string[]; edges: [string, string, boolean?][] }
export interface Scene {
  id: string; title: string; intro: string; inputs: InputDef[]; variants?: { id: string; label: string }[];
  build: (v: Values, variant: string) => Stage[]; graph?: (variant: string) => GraphDef;
}
const str = (v: Values, k: string) => String(v[k] ?? "");
const num = (v: Values, k: string) => Number(v[k] ?? 0);

// ----------------------------------------------------------------------------- LLM pipeline
const CANDIDATES = ["the", "a", "to", "is", "and", "in", "that", "it", "of", "for", "you", "can"];
const llmPipeline: Scene = {
  id: "llm-pipeline", title: "From prompt to next token", intro: "Follow one prompt through an LLM. Change the prompt and watch every stage change.",
  inputs: [{ key: "prompt", label: "Your prompt", type: "text", default: "Explain tokenization to a beginner." }],
  build: (v) => {
    const prompt = str(v, "prompt") || " ";
    const toks = toyTokenize(prompt);
    const ids = toks.map(tokenId);
    const cand = Array.from({ length: 5 }, (_, i) => CANDIDATES[(hash(prompt + i) + i * 3) % CANDIDATES.length]);
    const uniq = [...new Set(cand)];
    const logits = uniq.map((_, i) => 3 - i * 0.7 + ((hash(prompt + uniq[i]) % 100) / 100) * 0.3);
    const ex = logits.map(Math.exp); const sum = ex.reduce((a, b) => a + b, 0);
    const probs = ex.map((e) => e / sum);
    return [
      { id: "prompt", label: "1. Prompt", input: "(your text)", output: `${prompt.length} characters, ${words(prompt).length} words`, simple: S("You type text. The model cannot read letters directly.", "आप text लिखते हैं। Model अक्षर सीधे नहीं पढ़ सकता।", "Aap text likhte ho. Model letters seedhe nahi padh sakta."), technical: "The application builds the full input: system prompt, history, your message (and retrieved context in RAG)." },
      { id: "tokens", label: "2. Tokenization", input: prompt, output: toks.join("  |  "), simple: S("The text is cut into small pieces called tokens. Long words are split into parts.", "Text को छोटे टुकड़ों (tokens) में काटा जाता है। लंबे शब्द कई हिस्सों में बँटते हैं।", "Text ko chhote tukdon (tokens) mein kaata jaata hai. Lambe words kai hisson mein bantte hain."), technical: `Real tokenizers (byte-pair encoding) learn their pieces from data. This toy splits words, numbers, punctuation and cuts words longer than 8 letters. ${toks.length} tokens.` },
      { id: "ids", label: "3. Token IDs", input: toks.join(" "), output: ids.join(", "), simple: S("Each token becomes a number from the model's vocabulary.", "हर token model की vocabulary का एक number बनता है।", "Har token model ki vocabulary ka ek number banta hai."), technical: "The vocabulary has tens of thousands of entries. Here the id is a hash of the token (illustrative), so the same token always gets the same number." },
      { id: "embed", label: "4. Embeddings", input: ids.join(", "), lines: toks.slice(0, 6).map((t) => `${t.padEnd(10)} → [${hashVector(t, 6).join(", ")} …]`), output: `${toks.length} vectors of 8 numbers (real models: 768 to 12,000)`, simple: S("Every id becomes a list of numbers that stands for its meaning.", "हर id numbers की एक list बनती है जो उसके मतलब को दर्शाती है।", "Har id numbers ki ek list banti hai jo uske meaning ko darshati hai."), technical: "An embedding table maps each id to a learned vector. The numbers shown are pseudo-random stand-ins, not learned values." },
      { id: "transformer", label: "5. Transformer layers", input: "token vectors", output: "each vector now contains information from the other tokens", simple: S("Many layers let every token look at the others (attention) and update its meaning from context.", "कई layers हर token को बाकी tokens देखने (attention) और संदर्भ से अपना मतलब बदलने देती हैं।", "Kai layers har token ko baaki tokens dekhne (attention) aur context se apna meaning badalne deti hain."), technical: "Each layer applies self-attention (tokens weigh each other) and a feed-forward network. Large models have dozens of layers. Only earlier tokens are visible when predicting the next one." },
      { id: "scores", label: "6. Next-token scores", input: "last token's vector", lines: uniq.map((w, i) => `${w.padEnd(6)} score ${fmt(logits[i])}  → probability ${fmt(probs[i] * 100, 1)}%`), output: `most likely: "${uniq[0]}"`, simple: S("The model scores every possible next token. Scores become probabilities.", "Model हर संभावित अगले token को score देता है। Scores probabilities बनते हैं।", "Model har possible agle token ko score deta hai. Scores probabilities bante hain."), technical: "A real model scores its entire vocabulary (about 100,000 tokens) and applies softmax. These five candidates and their numbers are illustrative only." },
      { id: "pick", label: "7. Pick and repeat", input: "probabilities", output: `append "${uniq[0]}" and run again with the longer text`, simple: S("One token is chosen (temperature and top-p control how), added to the text, and the whole process repeats until the answer ends.", "एक token चुना जाता है (temperature और top-p तय करते हैं कैसे), text में जुड़ता है, और पूरी प्रक्रिया जवाब ख़त्म होने तक दोहराई जाती है।", "Ek token chuna jaata hai (temperature aur top-p tay karte hain kaise), text mein judta hai, aur poori process answer khatam hone tak dohrai jaati hai."), technical: "Generation is autoregressive: output tokens are fed back as input. Streaming sends each token to the user as it is produced." },
    ];
  },
};

// ----------------------------------------------------------------------------- RAG
const RAG_DOC = "Employees accrue 25 days of annual leave per year. Unused leave can be carried over for up to 5 days. Parental leave is 26 weeks for the primary caregiver and 4 weeks for the partner. Expense reports must be filed within 30 days of travel. Travel above 500 dollars needs manager approval.";
const ragPipeline: Scene = {
  id: "rag-pipeline", title: "RAG: from document to cited answer", intro: "Paste a document, ask a question and step through every stage. Change the chunk size and watch retrieval change.",
  inputs: [
    { key: "doc", label: "Document text", type: "textarea", default: RAG_DOC },
    { key: "q", label: "Question", type: "text", default: "How long is parental leave?" },
    { key: "size", label: "Chunk size (characters)", type: "number", default: 120, min: 30, max: 600 },
    { key: "overlap", label: "Overlap", type: "number", default: 20, min: 0, max: 100 },
    { key: "k", label: "Top-k", type: "number", default: 2, min: 1, max: 5 },
  ],
  build: (v) => {
    const doc = str(v, "doc").replace(/\s+/g, " ").trim() || " ";
    const q = str(v, "q");
    const size = Math.max(20, num(v, "size")), overlap = Math.max(0, Math.min(num(v, "overlap"), size - 1)), k = Math.max(1, num(v, "k"));
    const chunks = chunkText(doc, size, overlap);
    const vecs = chunks.map((c) => toyEmbed(c.text));
    const qv = toyEmbed(q);
    const sims = vecs.map((x) => cosine(qv, x));
    const order = rank(sims).slice(0, k);
    const qw = new Set(contentWords(q));
    const overlapScore = (t: string) => { const w = contentWords(t); return w.length ? w.filter((x) => qw.has(x)).length / qw.size : 0; };
    const rer = order.map((i) => ({ i, s: 0.6 * overlapScore(chunks[i].text) + 0.4 * sims[i] })).sort((a, b) => b.s - a.s);
    const best = rer[0];
    const segs = chunks.flatMap((c, n) => [{ text: doc.slice(c.start, c.end), cls: (n % 2 ? "b" : "a") as "a" | "b" }]);
    const ctx = rer.map((r, n) => `[${n + 1}] ${chunks[r.i].text}`).join("\n");
    const bestSentence = best ? sentences(chunks[best.i].text).sort((a, b) => overlapScore(b) - overlapScore(a))[0] ?? chunks[best.i].text : "";
    return [
      { id: "upload", label: "1. Upload", input: "(a file or pasted text)", output: `${doc.length} characters`, simple: S("You give the system a document.", "आप system को एक document देते हैं।", "Aap system ko ek document dete ho."), technical: "The API validates type and size, stores the file and creates a job. Large files are processed by a background worker." },
      { id: "load", label: "2. Load text", input: "file bytes", output: `${words(doc).length} words of clean text`, simple: S("A loader turns the file into plain text (PDF pages, table rows, web text).", "Loader file को सादे text में बदलता है (PDF pages, table rows, web text)।", "Loader file ko saade text mein badalta hai (PDF pages, table rows, web text)."), technical: "Loaders differ per format: PDF text per page (OCR for scans), DOCX paragraphs, CSV rows, HTML without menus. Each unit keeps its page or row number for citations." },
      { id: "split", label: "3. Split into chunks", input: `size ${size}, overlap ${overlap}`, segments: segs, output: `${chunks.length} chunks`, simple: S("The text is cut into pieces small enough to match a question. Neighbouring pieces overlap a little.", "Text को इतने छोटे टुकड़ों में काटा जाता है कि सवाल से match हो सकें। पास के टुकड़े थोड़ा overlap करते हैं।", "Text ko itne chhote tukdon mein kaata jaata hai ki question se match ho sakein. Paas ke tukde thoda overlap karte hain."), technical: `Chunk size and overlap are tunable. Here chunk n starts ${size - overlap} characters after chunk n-1. Smaller chunks match precisely but lose context.` },
      { id: "embed", label: "4. Embed chunks", input: `${chunks.length} chunks`, lines: chunks.slice(0, 4).map((c) => `chunk ${c.id + 1}: [${vecs[c.id].slice(0, 6).join(", ")} …]`), output: `${vecs.length} vectors of ${vecs[0]?.length ?? 0} numbers`, simple: S("Each chunk becomes a list of numbers for its meaning.", "हर chunk अपने मतलब के numbers की list बनता है।", "Har chunk apne meaning ke numbers ki list banta hai."), technical: "A real embedding model produces learned vectors (hundreds of numbers). This toy uses synonym groups plus hashed word buckets so related words land close together." },
      { id: "store", label: "5. Store vectors", input: "vectors + text + page", output: `index with ${vecs.length} entries (in memory; real systems persist it)`, simple: S("Vectors are saved with the original text so they can be searched later.", "Vectors को original text के साथ सहेजा जाता है ताकि बाद में खोजे जा सकें।", "Vectors ko original text ke saath sahej ke rakha jaata hai taaki baad mein khoje ja sakein."), technical: "A vector store keeps vectors, the chunk text and metadata (file, page, tenant). Filters on metadata are applied inside the search." },
      { id: "retrieve", label: "6. Retrieve", input: `question: "${q}"`, lines: order.map((i, n) => `#${n + 1} chunk ${i + 1}  cosine ${fmt(sims[i])}  "${chunks[i].text.slice(0, 60)}…"`), output: `top ${order.length} chunks by similarity`, simple: S("The question becomes numbers too; the closest chunks are fetched.", "सवाल भी numbers बनता है; सबसे पास के chunks निकाले जाते हैं।", "Question bhi numbers banta hai; sabse paas ke chunks nikaale jaate hain."), technical: "Cosine similarity between the question vector and every chunk vector; the top-k are kept. Hybrid search would add keyword scores here." },
      { id: "rerank", label: "7. Rerank", input: "top chunks", lines: rer.map((r, n) => `#${n + 1} chunk ${r.i + 1}  score ${fmt(r.s)} (was #${order.indexOf(r.i) + 1})`), output: best ? `best: chunk ${best.i + 1}` : "no chunk", simple: S("A second, more careful check re-orders the chunks so the best one is first.", "दूसरी, ज़्यादा सावधान जाँच chunks को दोबारा क्रम देती है ताकि सबसे अच्छा पहले आए।", "Doosri, zyada saavdhan jaanch chunks ko dobara order deti hai taaki sabse achha pehle aaye."), technical: "A real reranker (cross-encoder) reads question and chunk together. This toy blends word overlap with the similarity score." },
      { id: "context", label: "8. Build the prompt", input: "reranked chunks", lines: ["Answer ONLY from the sources and cite them like [1].", ...ctx.split("\n"), `Question: ${q}`], output: `${ctx.length + q.length + 60} characters sent to the model`, simple: S("The best chunks and your question are put into one prompt with a rule: answer only from these sources.", "सबसे अच्छे chunks और आपका सवाल एक prompt में रखे जाते हैं, इस नियम के साथ: सिर्फ़ इन sources से जवाब दो।", "Sabse achhe chunks aur aapka question ek prompt mein rakhe jaate hain, is niyam ke saath: sirf in sources se answer do."), technical: "Context construction: numbered sources, instructions, and the question. Retrieved text is treated as data, never as instructions." },
      { id: "answer", label: "9. Answer with citation", input: "grounded prompt", output: best && overlapScore(chunks[best.i].text) > 0 ? `${bestSentence} [1]` : "I could not find this in the document.", simple: S("The model writes the answer from the sources and points to them. If nothing fits, it should say so.", "Model sources से जवाब लिखता है और उनकी ओर इशारा करता है। कुछ न मिले तो उसे साफ़ कहना चाहिए।", "Model sources se answer likhta hai aur unki taraf ishara karta hai. Kuch na mile to use saaf kehna chahiye."), technical: "Here the 'model' just picks the best matching sentence (extractive). A real LLM writes fluent text from the same context; a verifier then checks every claim against the sources." },
    ];
  },
};

// ----------------------------------------------------------------------------- chunking
const chunking: Scene = {
  id: "chunking", title: "How chunk size and overlap cut a text", intro: "Move the numbers and see the pieces. Overlapping characters are shown in orange.",
  inputs: [
    { key: "text", label: "Text", type: "textarea", default: "The refund window is 14 days. After that, store credit is offered. Exceptions need approval from a manager. Digital goods are not refundable once downloaded." },
    { key: "size", label: "Chunk size", type: "number", default: 60, min: 20, max: 400 }, { key: "overlap", label: "Overlap", type: "number", default: 15, min: 0, max: 100 },
  ],
  build: (v) => {
    const text = str(v, "text") || " ";
    const size = Math.max(10, num(v, "size")), overlap = Math.max(0, Math.min(num(v, "overlap"), size - 1));
    const chunks = chunkText(text, size, overlap);
    const stepBy = size - overlap;
    const segs: Stage["segments"] = [];
    chunks.forEach((c, n) => {
      const ovLen = n === 0 ? 0 : Math.min(overlap, c.end - c.start);
      if (ovLen) segs.push({ text: text.slice(c.start, c.start + ovLen), cls: "o" });
      segs.push({ text: text.slice(c.start + ovLen, c.end), cls: n % 2 ? "b" : "a" });
    });
    return [
      { id: "original", label: "1. Original text", output: `${text.length} characters`, simple: "One long text.", technical: "A document unit (a page, a section or a row) before splitting." },
      { id: "chunks", label: "2. Chunks", input: `size ${size}, overlap ${overlap}, step ${stepBy}`, segments: segs, lines: chunks.map((c) => `chunk ${c.id + 1} [${c.start}-${c.end}] ${c.text.length} chars`), output: `${chunks.length} chunks`, simple: "Each colour is a chunk. Orange is text that appears in two chunks.", technical: "Real splitters prefer paragraph, then sentence, then word boundaries so words are not cut in half; this one cuts at exact characters to make the arithmetic visible." },
      { id: "tradeoff", label: "3. Trade-off", output: size < 100 ? "small chunks: precise matches, little context" : size > 500 ? "big chunks: more context, diluted matches" : "balanced for many documents", simple: "Small chunks match precisely but may lose context. Big chunks keep context but mix topics.", technical: "Tune on real questions: measure whether the right chunk is retrieved (recall@k) and whether answers stay faithful. Parent-child retrieval matches small chunks but sends their larger parent to the model." },
    ];
  },
};

// ----------------------------------------------------------------------------- hybrid search + rerank
const CORPUS = [
  "Error E-4021 appears after the upgrade to version 5; reinstall the driver.",
  "Upgrade failures: check disk space and restart the service.",
  "How to export a report to PDF from the dashboard.",
  "Resetting your password from the login page.",
  "Version 5 release notes: new dashboard and faster exports.",
  "Fixing slow exports: clear the cache and retry the report.",
];
const hybrid: Scene = {
  id: "hybrid-rerank", title: "Keyword + vector search, fusion and reranking", intro: "Search a small help centre. See how keyword search, vector search, rank fusion (RRF) and a reranker order the same documents.",
  inputs: [{ key: "q", label: "Query", type: "text", default: "error E-4021 after upgrade" }],
  build: (v) => {
    const q = str(v, "q");
    const kw = bm25(q, CORPUS), kwRank = rank(kw).filter((i) => kw[i] > 0);
    const qv = toyEmbed(q), vs = CORPUS.map((d) => cosine(qv, toyEmbed(d))), vRank = rank(vs);
    const fused = rrf([kwRank, vRank]);
    const qw = new Set(contentWords(q));
    const rer = fused.slice(0, 4).map((f) => ({ id: f.id, s: contentWords(CORPUS[f.id]).filter((w) => qw.has(w)).length / Math.max(1, qw.size) + f.score })).sort((a, b) => b.s - a.s);
    const show = (ids: number[]) => ids.slice(0, 3).map((i, n) => `#${n + 1} doc ${i + 1}: ${CORPUS[i].slice(0, 56)}…`);
    return [
      { id: "query", label: "1. Query", output: q, simple: "The user's question.", technical: "Both searches receive the same query text." },
      { id: "keyword", label: "2. Keyword search (BM25)", lines: kwRank.length ? show(kwRank) : ["no document shares a word with the query"], output: kwRank.length ? `best: doc ${kwRank[0] + 1}` : "no match", simple: "Finds documents that contain the query's rare words. Great for codes like E-4021.", technical: "BM25 scores documents by how often rare query terms appear, normalised by document length." },
      { id: "vector", label: "3. Vector search", lines: show(vRank), output: `best: doc ${vRank[0] + 1}`, simple: "Finds documents with a similar meaning, even without shared words.", technical: "Cosine similarity of toy embeddings. Real embeddings capture meaning far better but can blur exact identifiers." },
      { id: "fusion", label: "4. Fusion (RRF)", lines: fused.slice(0, 3).map((f, n) => `#${n + 1} doc ${f.id + 1}  RRF ${fmt(f.score, 4)}`), output: `fused best: doc ${fused[0].id + 1}`, simple: "Documents ranked high by BOTH searches go to the top.", technical: "Reciprocal Rank Fusion adds 1/(60 + rank) from every list, so no score scaling is needed." },
      { id: "rerank", label: "5. Rerank", lines: rer.map((r, n) => `#${n + 1} doc ${r.id + 1}  score ${fmt(r.s)}`), output: `final best: doc ${rer[0].id + 1}`, simple: "A closer reading of only the best few candidates picks the final order.", technical: "A cross-encoder reads (query, document) together. This toy adds word overlap to the fusion score." },
      { id: "context", label: "6. Send to the model", output: rer.slice(0, 2).map((r) => `doc ${r.id + 1}`).join(" + "), simple: "Only the top few documents go into the prompt.", technical: "The model sees only the top few chunks, which is why their order matters." },
    ];
  },
};

// ----------------------------------------------------------------------------- query transformation
const FAQ = [
  "Resignation procedure: submit a written resignation and serve the notice period of 30 days.",
  "Annual leave policy: employees get 25 days of paid leave each year.",
  "Resetting a laptop password is done from the IT portal.",
  "Expense reports are due within 30 days after travel.",
];
const queryTransform: Scene = {
  id: "query-transform", title: "Query rewriting: multi-query and HyDE", intro: "A short question may share no words with the right document. Rewrite it, search several versions, or search with a made-up answer.",
  inputs: [{ key: "q", label: "Question", type: "text", default: "how do I quit my job" }],
  build: (v) => {
    const q = str(v, "q");
    const cw = contentWords(q);
    const variants: string[] = [q];
    for (const w of cw) {
      const group = Object.values(CONCEPTS).find((g) => g.includes(w));
      if (group) group.filter((x) => x !== w).slice(0, 2).forEach((s) => variants.push(q.toLowerCase().replace(w, s)));
    }
    const vs = [...new Set(variants)].slice(0, 5);
    const hyde = `${q.replace(/\?$/, "")}. To do this, follow the policy: ${cw.join(" ")} procedure, notice period and approval steps.`;
    const top = (text: string) => { const sc = bm25(text, FAQ); return rank(sc).filter((i) => sc[i] > 0); };
    const per = vs.map((x) => ({ x, r: top(x) }));
    const merged = rrf(per.map((p) => p.r));
    const hydeTop = top(hyde);
    return [
      { id: "q", label: "1. Original question", output: q, lines: [`plain search finds: ${top(q).length ? "doc " + (top(q)[0] + 1) + " — " + FAQ[top(q)[0]].slice(0, 50) + "…" : "nothing"}`], simple: "The user's wording may not match the document's words.", technical: "Keyword and even embedding search can miss when question and document use different vocabulary." },
      { id: "rewrite", label: "2. Rewrite into variants", lines: vs.map((x, i) => `${i + 1}. ${x}`), output: `${vs.length} query variants (the original is always kept)`, simple: "The same question asked in different words.", technical: "A real system lets an LLM write the variants. This toy swaps words for synonyms from a small list." },
      { id: "search", label: "3. Search with each", lines: per.map((p) => `"${p.x}" → ${p.r.length ? "doc " + (p.r[0] + 1) : "nothing"}`), output: "one ranked list per variant", simple: "Every version is searched on its own.", technical: "Each variant retrieves its own top results." },
      { id: "merge", label: "4. Merge (RRF)", lines: merged.slice(0, 3).map((m, n) => `#${n + 1} doc ${m.id + 1}  ${FAQ[m.id].slice(0, 50)}…`), output: merged.length ? `best: doc ${merged[0].id + 1}` : "nothing found", simple: "Documents found by many variants rise to the top.", technical: "Reciprocal Rank Fusion over all variant rankings." },
      { id: "hyde", label: "5. HyDE alternative", input: "a made-up answer", lines: [hyde, `search with it → ${hydeTop.length ? "doc " + (hydeTop[0] + 1) : "nothing"}`], output: hydeTop.length ? `best: doc ${hydeTop[0] + 1}` : "nothing found", simple: "Instead of the question, search with an imaginary answer, which looks more like the real documents.", technical: "HyDE embeds a hypothetical document. It helps when wording differs a lot, but wrong invented details can mislead the search." },
    ];
  },
};

// ----------------------------------------------------------------------------- LangChain / LCEL
const lcel: Scene = {
  id: "langchain-lcel", title: "LangChain: prompt | model | parser, parallel, tools and structured output", intro: "Pick a pattern and step through the components. The model is a stand-in so you can see each component's input and output.",
  variants: [{ id: "sequence", label: "Chain: prompt | model | parser" }, { id: "parallel", label: "RunnableParallel" }, { id: "tool", label: "Tool calling" }, { id: "structured", label: "Structured output" }],
  inputs: [{ key: "role", label: "Role", type: "text", default: "geography teacher" }, { key: "question", label: "Question", type: "text", default: "What is the capital of France?" }, { key: "reply", label: "Fake model reply", type: "text", default: "Paris, France, Europe" }],
  build: (v, variant) => {
    const role = str(v, "role"), question = str(v, "question"), reply = str(v, "reply");
    const filled = `System: You are a ${role}.\nHuman: ${question}`;
    if (variant === "parallel") {
      return [
        { id: "in", label: "1. Input dict", output: JSON.stringify({ role, question }), simple: "One input goes to every branch.", technical: "RunnableParallel(answer=..., length=...) runs each branch on the same input (concurrently for async/IO-bound steps)." },
        { id: "a", label: "2a. Branch 'answer'", input: filled, output: reply, simple: "The prompt | model | parser chain.", technical: "This branch is itself a RunnableSequence." },
        { id: "b", label: "2b. Branch 'question_length'", input: question, output: String(question.length), simple: "A RunnableLambda wrapping a plain Python function.", technical: "RunnableLambda(lambda d: len(d['question']))" },
        { id: "merge", label: "3. Merged dict", output: JSON.stringify({ answer: reply, question_length: question.length }), simple: "The results are collected under their branch names.", technical: "The parallel runnable returns a dict keyed by branch name." },
      ];
    }
    if (variant === "tool") {
      const nums = (question.match(/\d+(\.\d+)?/g) ?? []).map(Number);
      const ok = nums.length >= 2;
      return [
        { id: "in", label: "1. User message", output: question, simple: "The user asks something a tool can do.", technical: "Try a question with two numbers, such as 'What is 2 plus 3?'." },
        { id: "bind", label: "2. Tools given to the model", output: 'add(a: int, b: int) — "Add two integers."', simple: "The model sees each tool's name, description and argument types.", technical: "model.bind_tools([add]) sends the tool schemas with the request." },
        { id: "call", label: "3. Model requests a tool", output: ok ? `tool_calls: [{ name: 'add', args: { a: ${nums[0]}, b: ${nums[1]} } }]` : "no tool call: the model answers in text", simple: "The model does not run the function; it asks for it.", technical: "The reply contains tool_calls with the function name and JSON arguments. YOUR code validates and runs them." },
        { id: "run", label: "4. Your code runs the tool", input: ok ? `add(${nums[0]}, ${nums[1]})` : "—", output: ok ? String(nums[0] + nums[1]) : "nothing to run", simple: "The application executes the function after checking the arguments.", technical: "tool.invoke(args). Validate, authorise and time-limit every call." },
        { id: "final", label: "5. Model writes the answer", input: ok ? `tool result: ${nums[0] + nums[1]}` : "—", output: ok ? `${nums[0]} + ${nums[1]} = ${nums[0] + nums[1]}` : reply, simple: "The result goes back to the model as a tool message and it answers in words.", technical: "The loop continues until the model returns no more tool calls." },
      ];
    }
    if (variant === "structured") {
      const raw = `{"name": "Asha Rao", "age": ${/\d+/.exec(question)?.[0] ?? "thirty-one"}}`;
      const ageOk = /"age": \d+/.test(raw);
      return [
        { id: "schema", label: "1. Schema", output: "Person { name: str, age: int }", simple: "The shape you want back.", technical: "A Pydantic class; its JSON Schema is shown to the model or sent as a structured-output schema." },
        { id: "model", label: "2. Model output", input: filled, output: raw, simple: "The model replies with JSON text.", technical: "Edit the question to contain a number to get a valid age, or no number to see a failure." },
        { id: "parse", label: "3. Parse and validate", output: ageOk ? "Person(name='Asha Rao', age=" + /\d+/.exec(question)![0] + ")" : "ValidationError: age must be an integer", simple: ageOk ? "The JSON matches the schema, so you get a typed object." : "The age is words, not a number, so the parser rejects it.", technical: "PydanticOutputParser.parse(raw). On failure retry the model with the error message." },
      ];
    }
    const list = reply.split(",").map((s) => s.trim()).filter(Boolean);
    return [
      { id: "in", label: "1. Input dict", output: JSON.stringify({ role, question }), simple: "The values that fill the prompt's variables.", technical: "chain.invoke({'role': ..., 'question': ...})" },
      { id: "prompt", label: "2. ChatPromptTemplate", input: JSON.stringify({ role, question }), output: filled, simple: "The template becomes real messages.", technical: "prompt.invoke(inputs) returns a ChatPromptValue (system + human messages)." },
      { id: "model", label: "3. Chat model", input: filled, output: reply, simple: "The model writes a reply. (Here it is a fake model that returns your text.)", technical: "With a real provider this is the network call; FakeListChatModel returns canned replies for tests." },
      { id: "parser", label: "4. Output parser", input: reply, output: `['${list.join("', '")}']  (comma-separated list parser)`, simple: "The reply text is turned into something your code can use.", technical: "StrOutputParser would return the text; CommaSeparatedListOutputParser splits it into a list." },
      { id: "out", label: "5. Result", output: `${list.length} items`, simple: "The chain returns the parsed value.", technical: "Every step is a Runnable: invoke, batch, stream and async are available on the whole chain." },
    ];
  },
};

// ----------------------------------------------------------------------------- LangGraph
type St = Record<string, unknown>;
const GRAPHS: Record<string, GraphDef> = {
  loop: { nodes: ["START", "work", "check", "END"], edges: [["START", "work"], ["work", "check"], ["check", "work", true], ["check", "END", true]] },
  router: { nodes: ["START", "classify", "billing", "technical", "END"], edges: [["START", "classify"], ["classify", "billing", true], ["classify", "technical", true], ["billing", "END"], ["technical", "END"]] },
  approval: { nodes: ["START", "draft", "approve", "send", "END"], edges: [["START", "draft"], ["draft", "approve"], ["approve", "send", true], ["approve", "END", true], ["send", "END"]] },
  supervisor: { nodes: ["START", "supervisor", "researcher", "writer", "END"], edges: [["START", "supervisor"], ["supervisor", "researcher", true], ["supervisor", "writer", true], ["supervisor", "END", true], ["researcher", "supervisor"], ["writer", "supervisor"]] },
};
const langgraph: Scene = {
  id: "langgraph-flow", title: "LangGraph: state, nodes, edges, memory and approval", intro: "Run a small graph step by step. The highlighted node is running; the state box shows what changed. (A simulation in your browser: the LangGraph Playground runs the real library.)",
  variants: [{ id: "loop", label: "Loop until a check passes" }, { id: "router", label: "Conditional routing" }, { id: "approval", label: "Human approval (interrupt)" }, { id: "supervisor", label: "Supervisor + workers" }],
  inputs: [{ key: "text", label: "Input text / task", type: "text", default: "Why was I charged twice?" }, { key: "limit", label: "Loop target (count)", type: "number", default: 3, min: 1, max: 6 }, { key: "approve", label: "Human decision", type: "select", default: "approve", options: ["approve", "reject"] }],
  graph: (variant) => GRAPHS[variant] ?? GRAPHS.loop,
  build: (v, variant) => {
    const text = str(v, "text"), limit = num(v, "limit");
    const out: Stage[] = [];
    let s: St = {};
    const push = (node: string, label: string, simple: Say, technical: string, next: St) => { const before = s; s = { ...s, ...next }; out.push({ id: `${out.length}-${node}`, label, input: JSON.stringify(before), output: JSON.stringify(s), state: s, active: [node], simple, technical }); };
    if (variant === "router") {
      const kind = /charge|bill|refund|pay|invoice|fee/i.test(text) ? "billing" : "technical";
      s = { question: text }; out.push({ id: "start", label: "START", output: JSON.stringify(s), state: s, active: ["START"], simple: "The graph starts with the input state.", technical: "app.invoke({'question': ...})" });
      push("classify", "classify", "A node reads the question and decides its kind.", "A conditional edge reads state['kind'] and maps it to the next node.", { kind });
      push(kind, kind, `The ${kind} specialist answers.`, "Only the chosen branch runs; the other node is skipped.", { answer: `(${kind} agent answer)` });
      out.push({ id: "end", label: "END", output: JSON.stringify(s), state: s, active: ["END"], simple: "The run ends and returns the final state.", technical: "invoke() returns the last state." });
      return out;
    }
    if (variant === "approval") {
      const approved = str(v, "approve") === "approve";
      s = { amount: 5000, status: "new" }; out.push({ id: "start", label: "START", output: JSON.stringify(s), state: s, active: ["START"], simple: "A refund of 5,000 is requested.", technical: "State: amount and status." });
      push("draft", "draft", "A node prepares the refund draft.", "Normal node: returns a partial state update.", { status: "drafted" });
      out.push({ id: "pause", label: "approve: interrupt()", input: JSON.stringify(s), output: "PAUSED — waiting for a person: 'Approve refund of 5000?'", state: { ...s, paused: true }, active: ["approve"], simple: "The graph stops and saves its state. Nothing happens until a human answers.", technical: "interrupt(value) pauses the run; the checkpoint is saved under the thread id. Resume with Command(resume=True/False)." });
      push("approve", `approve: resumed with ${approved ? "True" : "False"}`, "The human's answer comes back and the node continues.", "interrupt() returns the resume value inside the node. Code before interrupt() runs again on resume, so keep it free of side effects.", { status: approved ? "approved" : "rejected" });
      if (approved) push("send", "send", "Only an approved refund is sent.", "A conditional edge routes to 'send' when approved, otherwise to END.", { status: "refunded" });
      out.push({ id: "end", label: "END", output: JSON.stringify(s), state: s, active: ["END"], simple: "Final state.", technical: "get_state_history lists every checkpoint of this thread." });
      return out;
    }
    if (variant === "supervisor") {
      s = { task: text, results: [], rounds: 0 }; out.push({ id: "start", label: "START", output: JSON.stringify(s), state: s, active: ["START"], simple: "The task enters the graph.", technical: "State: task, results, rounds." });
      const have: string[] = [];
      for (let round = 0; round < 5; round++) {
        const choice = !have.includes("facts") ? "researcher" : !have.includes("draft") ? "writer" : "FINISH";
        push("supervisor", `supervisor → ${choice}`, "The supervisor looks at what is done and picks who works next (or FINISH).", "Rules or an LLM with a validated structured output; a round limit prevents endless loops.", { rounds: round + 1, next: choice });
        if (choice === "FINISH") break;
        have.push(choice === "researcher" ? "facts" : "draft");
        push(choice, choice, `The ${choice} does one narrow job and reports back.`, "Workers return partial updates and an edge sends control back to the supervisor.", { results: [...have] });
      }
      out.push({ id: "end", label: "END", output: JSON.stringify(s), state: s, active: ["END"], simple: "Done.", technical: "Every worker reported back through the supervisor." });
      return out;
    }
    s = { count: 0, log: [] };
    out.push({ id: "start", label: "START", output: JSON.stringify(s), state: s, active: ["START"], simple: "The graph starts with count = 0.", technical: "State is a TypedDict; 'log' has an append reducer." });
    for (let i = 0; i < limit && i < 8; i++) {
      push("work", `work (round ${i + 1})`, "A node does some work and changes the state.", "Returns {'count': count + 1, 'log': [...]}; the reducer appends to log.", { count: i + 1, log: [...((s.log as string[]) ?? []), `work ${i + 1}`] });
      push("check", `check → ${i + 1 < limit ? "work again" : "END"}`, i + 1 < limit ? "The check says 'not enough yet', so the conditional edge loops back." : "The check passes, so the conditional edge goes to END.", "add_conditional_edges('check', route, {'work': 'work', END: END}); a recursion limit protects against infinite loops.", { passed: i + 1 >= limit });
    }
    out.push({ id: "end", label: "END", output: JSON.stringify(s), state: s, active: ["END"], simple: "Finished: the loop ended because the check passed.", technical: "stream(stream_mode='updates') yields one update per node run, like the steps above." });
    return out;
  },
};

// ----------------------------------------------------------------------------- agent loop
const DOCS: Record<string, string> = { "sales.txt": "Q1 total sales were 48000 dollars.", "policy.txt": "Employees get 25 days of annual leave. Parental leave is 26 weeks." };
const agent: Scene = {
  id: "agent-loop", title: "The agent loop: plan, choose a tool, act, observe, reflect", intro: "Give the agent a task. The steps shown are operational (which tool, with what input, what came back) - not hidden reasoning.",
  inputs: [{ key: "task", label: "Task", type: "select", default: "What is 15% of 48000?", options: ["What is 15% of 48000?", "How many days of annual leave?", "Delete all my files", "Tell me a joke"] }],
  build: (v) => {
    const task = str(v, "task");
    const mathM = /(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)/i.exec(task);
    const doc = Object.entries(DOCS).find(([, t]) => contentWords(task).some((w) => t.toLowerCase().includes(w) && w.length > 3));
    const dangerous = /delete|drop|format|erase/i.test(task);
    const tool = dangerous ? "delete_files" : mathM ? "calculator" : doc ? "search_documents" : "none";
    const allowed = tool === "calculator" || tool === "search_documents";
    const input = mathM ? `${Number(mathM[1]) / 100} * ${mathM[2]}` : doc ? task : "";
    const result = mathM ? String((Number(mathM[1]) / 100) * Number(mathM[2])) : doc ? `${doc[0]}: ${doc[1]}` : "";
    const final = !allowed ? (dangerous ? "I can't do that: no allowed tool can delete files." : "I don't have a tool for that; could you rephrase or give more detail?") : mathM ? `15% of 48000 is ${result}.`.replace("15%", `${mathM[1]}%`).replace("48000", mathM[2]) : `According to ${doc![0]}: ${doc![1]}`;
    return [
      { id: "goal", label: "1. Goal", output: task, simple: S("The agent receives the task and the list of tools it may use.", "Agent को task और वो tools की list मिलती है जिन्हें वो इस्तेमाल कर सकता है।", "Agent ko task aur woh tools ki list milti hai jinhe woh use kar sakta hai."), technical: "Allowed tools: calculator, search_documents. Everything else is refused by the application, not by the prompt." },
      { id: "plan", label: "2. Plan", output: tool === "none" ? "No tool seems to fit." : `Use ${tool} first, then answer.`, simple: S("A short operational plan: which step comes first.", "छोटी operational योजना: पहला कदम क्या है।", "Chhoti operational yojana: pehla kadam kya hai."), technical: "In a plan-and-execute design the plan lists all steps; in ReAct it is decided one step at a time." },
      { id: "select", label: "3. Tool selection", output: tool === "none" ? "none" : `${tool}(${input || "…"})`, simple: S("The model picks a tool and its input. A one-line reason is shown, not private thoughts.", "Model एक tool और उसका input चुनता है। एक पंक्ति का कारण दिखता है, निजी विचार नहीं।", "Model ek tool aur uska input chunta hai. Ek line ka reason dikhta hai, private thoughts nahi."), technical: "Tool calling: the model returns a name and JSON arguments." },
      { id: "guard", label: "4. Application checks", output: tool === "none" ? "nothing to check" : allowed ? "allowed: tool is on the allow-list and the input is valid" : "BLOCKED: tool is not on the allow-list", simple: S("Your code checks the request before anything runs.", "कुछ भी चलने से पहले आपका code request जाँचता है।", "Kuch bhi chalne se pehle aapka code request jaanchta hai."), technical: "Allow-list, argument validation, permissions, timeouts and a step limit live in code." },
      { id: "act", label: "5. Tool execution", input: allowed ? `${tool}(${input})` : "—", output: allowed ? result : "not executed", simple: S("The tool runs and produces a result.", "Tool चलता है और नतीजा देता है।", "Tool chalta hai aur result deta hai."), technical: "The function runs in your process (or a sandbox) with its own permissions." },
      { id: "observe", label: "6. Observation", output: allowed ? `observation: ${result}` : "observation: none", simple: S("The result is fed back to the model.", "नतीजा model को वापस दिया जाता है।", "Result model ko wapas diya jaata hai."), technical: "Tool output is appended to the history as a tool message. Treat it as untrusted data." },
      { id: "reflect", label: "7. Reflection", output: allowed ? "check: does the observation answer the task? yes → finish" : "check: no tool result → explain or ask the user", simple: S("A quick check whether the goal is met, and a retry if not (with a step limit).", "एक छोटी जाँच कि लक्ष्य पूरा हुआ या नहीं, और नहीं तो retry (step limit के साथ)।", "Ek chhoti jaanch ki goal poora hua ya nahi, aur nahi to retry (step limit ke saath)."), technical: "Reflection works best with objective checks (schema valid, citation present, number in range)." },
      { id: "final", label: "8. Final answer", output: final, simple: S("The answer goes to the user, with the steps available as a trace.", "जवाब user को जाता है, steps trace के रूप में उपलब्ध रहते हैं।", "Answer user ko jaata hai, steps trace ke roop mein available rehte hain."), technical: "Log every step (tool, input, result, latency) for debugging and audit." },
    ];
  },
};

export const SCENES: Record<string, Scene> = { "llm-pipeline": llmPipeline, "rag-pipeline": ragPipeline, chunking, "hybrid-rerank": hybrid, "query-transform": queryTransform, "langchain-lcel": lcel, "langgraph-flow": langgraph, "agent-loop": agent };
