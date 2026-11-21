import type { Say, Scene, Stage, Values } from "./scenes";
import { fmt, words as toyWords } from "./toy";
const words = (t: string): string[] => toyWords(t);

// Teaching models: small, deterministic and honest about what they simplify. Each scene recomputes its stages from the learner's inputs.
const S = (en: string, hi: string, hinglish: string): Say => ({ en, hi, hinglish });
const str = (v: Values, k: string) => String(v[k] ?? "");
const num = (v: Values, k: string) => Number(v[k] ?? 0);
const stg = (id: string, label: string, simple: Say, technical: string, output: string, extra: Partial<Stage> = {}): Stage => ({ id, label, simple, technical, output, ...extra });
const bar = (start: number, len: number, total: number, width = 36) => {
  const a = Math.round((start / total) * width), b = Math.max(1, Math.round((len / total) * width));
  return "|" + "·".repeat(a) + "█".repeat(b) + "·".repeat(Math.max(0, width - a - b)) + "|";
};

// ----------------------------------------------------------------------------- AI vs ML vs DL
const SPAM = ["win free prize now", "free money click now", "claim your free gift", "you win a prize"];
const HAM = ["meeting at noon tomorrow", "please review the report", "lunch now at noon", "send me the invoice"];
const aiVsMl: Scene = {
  id: "ai-vs-ml", title: "Rules vs learning: how a computer decides 'spam or not'", intro: "Type a message. First a hand-written rule decides, then a program that learned from examples decides. The learning part is a real (tiny) word-scoring model.",
  inputs: [{ key: "msg", label: "Message", type: "text", default: "WIN a free prize now, click here" }],
  build: (v) => {
    const msg = str(v, "msg"), ws = words(msg);
    const rules = ["free", "prize", "win"], hit = ws.filter((w) => rules.includes(w));
    const score = (w: string) => SPAM.filter((s) => words(s).includes(w)).length - HAM.filter((s) => words(s).includes(w)).length;
    const scored = [...new Set(ws)].map((w) => [w, score(w)] as const);
    const total = scored.reduce((a, [, s]) => a + s, 0);
    return [
      stg("task", "1. The task", S("Decide if a message is spam. That is the whole job.", "तय करना है कि message spam है या नहीं। बस यही काम है।", "Tay karna hai ki message spam hai ya nahi. Bas yahi kaam hai."), "A binary classification task. AI is the umbrella: any software that does a task needing intelligence.", msg, { input: "Is this spam?" }),
      stg("rules", "2. Hand-written rules (plain AI)", S("A person writes the rules: 'if the message has free, prize or win, it is spam'.", "इंसान rules लिखता है: 'अगर message में free, prize या win है तो spam'।", "Insaan rules likhta hai: 'agar message mein free, prize ya win hai to spam'."), "Rule-based systems are explicit and predictable but break when spammers change the words.", hit.length ? `rule hits: ${hit.join(", ")} → SPAM` : "no rule hit → NOT SPAM", { lines: rules.map((r) => `rule: contains "${r}"`) }),
      stg("train", "3. Learning from examples (ML)", S("Instead of rules, we show examples. The program counts which words appear more in spam than in normal mail.", "Rules की जगह examples दिखाते हैं। Program गिनता है कि कौन से शब्द spam में ज़्यादा आते हैं।", "Rules ki jagah examples dikhate hain. Program ginta hai ki kaun se shabd spam mein zyada aate hain."), "Training data: 4 spam and 4 normal messages. Word score = spam messages containing it − normal messages containing it.", `${SPAM.length} spam + ${HAM.length} normal examples`, { lines: [...SPAM.map((s) => "spam   : " + s), ...HAM.map((s) => "normal : " + s)] }),
      stg("score", "4. Score your message", S("Each word of your message gets the score it learned. Add them up: positive means spam-like.", "आपके message के हर शब्द को सीखा हुआ score मिलता है। जोड़ें: positive मतलब spam जैसा।", "Aapke message ke har shabd ko seekha hua score milta hai. Jodo: positive matlab spam jaisa."), "A tiny linear model (like naive Bayes without probabilities). Real models use thousands of features and calibrated probabilities.", `total score = ${total} → ${total > 0 ? "SPAM" : total < 0 ? "NOT SPAM" : "unsure"}`, { lines: scored.map(([w, s]) => `${w.padEnd(10)} ${s > 0 ? "+" : ""}${s}`) }),
      stg("dl", "5. Deep learning (many layers)", S("Deep learning stacks many layers that learn their own features: letters → words → phrases → intent. No one writes 'free' or 'prize' by hand.", "Deep learning कई layers जोड़ता है जो खुद features सीखती हैं: अक्षर → शब्द → वाक्यांश → इरादा। 'free' या 'prize' हाथ से नहीं लिखना पड़ता।", "Deep learning kai layers jodta hai jo khud features seekhti hain: akshar → shabd → vakyansh → irada. 'free' ya 'prize' haath se nahi likhna padta."), "This stage is a concept diagram, not a computation: a neural network is trained on millions of examples and is what LLMs are built from.", "letters → words → phrases → intent → spam?", { lines: ["AI  ⊃  Machine learning  ⊃  Deep learning  ⊃  LLMs"] }),
    ];
  },
};

// ----------------------------------------------------------------------------- Prompt anatomy
const promptAnatomy: Scene = {
  id: "prompt-anatomy", title: "Building a good prompt, part by part", intro: "Fill the four parts and watch the prompt grow. The checklist at the end shows what is missing.",
  inputs: [{ key: "role", label: "Role", type: "text", default: "a patient maths teacher" }, { key: "task", label: "Task", type: "text", default: "Explain what a fraction is" },
    { key: "context", label: "Context", type: "text", default: "The student is 10 years old and likes pizza" }, { key: "format", label: "Output format", type: "text", default: "Three short sentences and one example" }],
  build: (v) => {
    const parts = [["role", `You are ${str(v, "role")}.`], ["task", `Task: ${str(v, "task")}.`], ["context", `Context: ${str(v, "context")}.`], ["format", `Answer format: ${str(v, "format")}.`]] as const;
    const upTo = (n: number) => parts.slice(0, n).filter(([k]) => str(v, k).trim()).map(([, t]) => t).join("\n");
    const final = upTo(4), tokens = Math.ceil(final.length / 4);
    const labels: Record<string, Say> = { role: S("The role sets tone and expertise.", "Role tone और expertise तय करता है।", "Role tone aur expertise tay karta hai."), task: S("The task says exactly what to do.", "Task बताता है कि ठीक क्या करना है।", "Task batata hai ki theek kya karna hai."), context: S("Context gives facts the model cannot guess.", "Context वो facts देता है जो model अंदाज़े से नहीं जान सकता।", "Context woh facts deta hai jo model andaze se nahi jaan sakta."), format: S("The format makes the answer easy to use.", "Format जवाब को इस्तेमाल लायक बनाता है।", "Format jawab ko istemal laayak banata hai.") };
    const out: Stage[] = parts.map(([k], i) => stg(k, `${i + 1}. ${k[0].toUpperCase() + k.slice(1)}`, labels[k], "A prompt is just text; structure helps the model find each instruction. Keep instructions specific and testable.", upTo(i + 1) || "(empty)"));
    out.push(stg("check", "5. Checklist", S("A prompt that is missing a part leaves the model guessing. Fill every part.", "जिस prompt में कोई हिस्सा नहीं, उसमें model अंदाज़ा लगाता है। हर हिस्सा भरें।", "Jis prompt mein koi hissa nahi, usmein model andaza lagata hai. Har hissa bharo."), "Rough size: characters ÷ 4 ≈ tokens for English. Real tokenizers differ.", final || "(empty)", { lines: [...parts.map(([k]) => `${str(v, k).trim() ? "✓" : "✗"} ${k}`), `≈ ${tokens} tokens (rough estimate)`] }));
    return out;
  },
};

// ----------------------------------------------------------------------------- Chat messages API
const messagesApi: Scene = {
  id: "messages-api", title: "The messages array: how chat models remember", intro: "A chat model has no memory of its own. Every request carries the whole conversation. Switch history off to see the model 'forget'.",
  inputs: [{ key: "system", label: "System message", type: "text", default: "You are a concise assistant." }, { key: "u1", label: "First user message", type: "text", default: "My name is Asha." },
    { key: "a1", label: "Assistant reply (stand-in)", type: "text", default: "Nice to meet you, Asha." }, { key: "u2", label: "Second user message", type: "text", default: "What is my name?" }, { key: "hist", label: "Send history?", type: "select", default: "yes", options: ["yes", "no"] }],
  build: (v) => {
    const sys = { role: "system", content: str(v, "system") }, u1 = { role: "user", content: str(v, "u1") }, a1 = { role: "assistant", content: str(v, "a1") }, u2 = { role: "user", content: str(v, "u2") };
    const keep = str(v, "hist") === "yes", second = keep ? [sys, u1, a1, u2] : [sys, u2];
    const chars = (m: { content: string }[]) => m.reduce((a, x) => a + x.content.length, 0);
    return [
      stg("first", "1. First request", S("You send the system message and your first question.", "आप system message और पहला सवाल भेजते हैं।", "Aap system message aur pehla sawal bhejte ho."), "Roles: system (rules), user (the person), assistant (the model). The array order is the conversation order.", JSON.stringify([sys, u1], null, 1)),
      stg("reply", "2. Model replies", S("The model answers. In a real call this text comes from the model; here it is your stand-in.", "Model जवाब देता है। असली call में यह text model से आता है; यहाँ यह आपका stand-in है।", "Model jawab deta hai. Asli call mein yeh text model se aata hai; yahan yeh aapka stand-in hai."), "The reply arrives as an assistant message. Nothing is stored inside the model.", a1.content),
      stg("second", "3. Second request", keep ? S("Your app sends the whole history again, plus the new question.", "आपका app पूरा history फिर भेजता है, नए सवाल के साथ।", "Aapka app poori history phir bhejta hai, naye sawal ke saath.") : S("History is NOT sent. The model only sees the new question.", "History नहीं भेजी गई। Model को सिर्फ़ नया सवाल दिखता है।", "History nahi bheji gayi. Model ko sirf naya sawal dikhta hai."), "Your application owns the memory: it stores messages and decides how many to resend.", JSON.stringify(second, null, 1)),
      stg("answer", "4. What the model can know", keep ? S("It can answer, because 'Asha' is in the messages it received.", "यह जवाब दे सकता है, क्योंकि 'Asha' इसे मिले messages में है।", "Yeh jawab de sakta hai, kyunki 'Asha' ise mile messages mein hai.") : S("It cannot know your name: it never received it.", "यह आपका नाम नहीं जान सकता: इसे कभी मिला ही नहीं।", "Yeh aapka naam nahi jaan sakta: ise kabhi mila hi nahi."), "Long histories cost tokens and can exceed the context window, so apps summarise or trim old turns.", keep ? `can use: "${u1.content}"` : "no earlier information available", { lines: [`messages sent: ${second.length}`, `characters sent: ${chars(second)} (≈ ${Math.ceil(chars(second) / 4)} tokens)`] }),
    ];
  },
};

// ----------------------------------------------------------------------------- MCP
const TOOLS_MCP: Record<string, { tool: string; args: string; result: string }> = {
  "What is on my calendar tomorrow?": { tool: "get_events", args: '{"day": "tomorrow"}', result: "10:00 Design review; 14:00 1:1 with Ravi" },
  "Read notes.txt": { tool: "read_file", args: '{"path": "notes.txt"}', result: "Buy milk. Call the bank." },
};
const mcp: Scene = {
  id: "mcp-flow", title: "MCP: an app discovers and calls tools on a server", intro: "Follow one request from the user, through the MCP client, to a tool server and back. Messages are simplified JSON-RPC.",
  inputs: [{ key: "q", label: "User asks", type: "select", default: "What is on my calendar tomorrow?", options: ["What is on my calendar tomorrow?", "Read notes.txt", "Delete my files"] }],
  build: (v) => {
    const q = str(v, "q"), t = TOOLS_MCP[q];
    return [
      stg("ask", "1. User asks", S("The user talks to a host app (an IDE, a chat app, an agent).", "User host app से बात करता है (IDE, chat app, agent)।", "User host app se baat karta hai (IDE, chat app, agent)."), "The host contains the model and one MCP client per connected server.", q),
      stg("init", "2. Connect and initialise", S("The MCP client connects to a server and they agree on capabilities.", "MCP client server से जुड़ता है और दोनों capabilities पर सहमत होते हैं।", "MCP client server se judta hai aur dono capabilities par sahmat hote hain."), "Transports: stdio for local servers, HTTP for remote ones. The first message is initialize.", '{"jsonrpc":"2.0","id":0,"method":"initialize", …}'),
      stg("list", "3. Discover tools", S("The client asks: what tools do you offer? The server lists names, descriptions and argument schemas.", "Client पूछता है: आपके पास कौन से tools हैं? Server नाम, description और arguments बताता है।", "Client puchta hai: aapke paas kaun se tools hain? Server naam, description aur arguments batata hai."), "tools/list returns tool definitions that the host gives to the model as callable functions.", '{"jsonrpc":"2.0","id":1,"method":"tools/list"}', { lines: ["→ get_events(day)", "→ read_file(path)"] }),
      stg("pick", "4. Model chooses", t ? S("The model picks the matching tool and fills its arguments.", "Model सही tool चुनता है और arguments भरता है।", "Model sahi tool chunta hai aur arguments bharta hai.") : S("No tool matches 'delete my files', so none is called. The host never invents tools.", "'Delete my files' से कोई tool मेल नहीं खाता, इसलिए कोई call नहीं होता। Host कभी tool नहीं गढ़ता।", "'Delete my files' se koi tool mel nahi khata, isliye koi call nahi hota. Host kabhi tool nahi gadhta."), "The model proposes; the host decides. Hosts usually ask the user to approve tool calls with side effects.", t ? `${t.tool}(${t.args})` : "no tool selected"),
      stg("call", "5. Call the tool", t ? S("The client sends tools/call. The server runs the function on its side.", "Client tools/call भेजता है। Server अपनी तरफ़ function चलाता है।", "Client tools/call bhejta hai. Server apni taraf function chalata hai.") : S("Nothing is sent.", "कुछ नहीं भेजा जाता।", "Kuch nahi bheja jaata."), "Servers are where permissions live: least privilege, input validation, no secrets in results. Treat results as untrusted text.", t ? `{"method":"tools/call","params":{"name":"${t.tool}","arguments":${t.args}}}` : "—"),
      stg("result", "6. Result and answer", t ? S("The result goes back to the model, which writes the final answer.", "Result model को लौटता है, जो अंतिम जवाब लिखता है।", "Result model ko lautta hai, jo antim jawab likhta hai.") : S("The model explains it cannot do that with the tools it has.", "Model बताता है कि मौजूद tools से यह नहीं हो सकता।", "Model batata hai ki maujood tools se yeh nahi ho sakta."), "Tool output is added to the conversation as data, never as new instructions.", t ? t.result : "I can't delete files: no available tool does that."),
    ];
  },
};

// ----------------------------------------------------------------------------- RAG evaluation metrics
const EVAL_CASES = [{ q: "parental leave", returned: ["c7", "c2", "c9"], relevant: ["c2"] }, { q: "expense deadline", returned: ["c4", "c1", "c3"], relevant: ["c4", "c3"] }, { q: "remote work", returned: ["c8", "c5", "c6"], relevant: ["c1"] }];
const ragEval: Scene = {
  id: "rag-eval-metrics", title: "Measuring retrieval: hit rate, recall and MRR", intro: "Three labelled questions. Change K (how many results count) and watch each metric change.",
  inputs: [{ key: "k", label: "K (results that count)", type: "number", default: 3, min: 1, max: 3 }],
  build: (v) => {
    const K = Math.min(3, Math.max(1, num(v, "k") || 3));
    const m = EVAL_CASES.map((c) => {
      const top = c.returned.slice(0, K), found = top.filter((x) => c.relevant.includes(x)).length;
      const r = c.returned.findIndex((x) => c.relevant.includes(x));
      return { c, top, hit: found > 0 ? 1 : 0, recall: found / c.relevant.length, rr: r >= 0 && r < c.returned.length ? 1 / (r + 1) : 0 };
    });
    const avg = (f: (x: (typeof m)[number]) => number) => m.reduce((a, x) => a + f(x), 0) / m.length;
    const per: Stage[] = m.map((x, i) => stg(`c${i}`, `${i + 1}. "${x.c.q}"`, S("Compare what the system returned with what SHOULD have been found.", "System ने जो लौटाया उसे उससे मिलाएँ जो मिलना चाहिए था।", "System ne jo lautaya use usse milao jo milna chahiye tha."), "hit = any right chunk in the top K; recall = right chunks found ÷ right chunks that exist; reciprocal rank = 1 ÷ rank of the first right chunk (over the full list).", `hit=${x.hit}  recall=${fmt(x.recall)}  rr=${fmt(x.rr)}`, { lines: [`returned (top ${K}): ${x.top.join(", ")}`, `should find      : ${x.c.relevant.join(", ")}`] }));
    return [...per, stg("avg", "4. Averages", S("Average over all questions. These three numbers let you compare two versions of your system.", "सभी सवालों का औसत। इन तीन numbers से आप system के दो versions की तुलना कर सकते हैं।", "Sabhi sawalon ka average. In teen numbers se aap system ke do versions ki tulna kar sakte ho."), "Three questions is only a demo. Use 30–100 real questions, include unanswerable ones, and track generation quality (faithfulness) separately.", `hit rate@${K} = ${fmt(avg((x) => x.hit))}   recall@${K} = ${fmt(avg((x) => x.recall))}   MRR = ${fmt(avg((x) => x.rr))}`)];
  },
};

// ----------------------------------------------------------------------------- Production request path
const prodRequest: Scene = {
  id: "prod-request", title: "One request through a production AI service", intro: "Pick a situation and follow the request. Highlighted boxes are the parts that act.",
  variants: [{ id: "normal", label: "Normal question" }, { id: "retry", label: "Provider says 429 (retry)" }, { id: "down", label: "Provider is down (circuit breaker)" }, { id: "upload", label: "Big upload (queue + worker)" }],
  inputs: [{ key: "fails", label: "Failed attempts before success (retry case)", type: "number", default: 2, min: 1, max: 4 }],
  graph: () => ({ nodes: ["START", "API", "Auth", "Cache", "Provider", "Queue", "Worker", "END"], edges: [["START", "API"], ["API", "Auth"], ["Auth", "Cache"], ["Cache", "Provider", true], ["Cache", "END", true], ["Provider", "END"], ["Auth", "Queue", true], ["Queue", "Worker"], ["Worker", "END"]] }),
  build: (v, variant) => {
    const fails = Math.min(4, Math.max(1, num(v, "fails") || 2)), waits = Array.from({ length: fails }, (_, i) => 2 ** i);
    const front: Stage[] = [
      stg("api", "1. API receives it", S("The API validates the request: size limits, allowed fields.", "API request जाँचता है: size limits, मान्य fields।", "API request jaanchta hai: size limits, maanya fields."), "FastAPI + Pydantic validation, request id added for tracing.", "POST /ask  (request id r-1f3a)", { active: ["START", "API"] }),
      stg("auth", "2. Who are you, what may you do?", S("Authentication and permission checks happen before any model call. Rate limits stop one user from using everything.", "Model call से पहले authentication और permission checks होते हैं। Rate limit एक user को सब इस्तेमाल करने से रोकता है।", "Model call se pehle authentication aur permission checks hote hain. Rate limit ek user ko sab istemal karne se rokta hai."), "Checks live in code, not in the prompt.", "user ok · within rate limit", { active: ["START", "API", "Auth"] }),
    ];
    if (variant === "upload") return [...front, stg("queue", "3. Put the job in a queue", S("Parsing 500 pages takes minutes, so the API stores the job and answers immediately with a job id.", "500 पन्ने parse करने में मिनट लगते हैं, इसलिए API job रखकर तुरंत job id के साथ जवाब देती है।", "500 panne parse karne mein minute lagte hain, isliye API job rakhkar turant job id ke saath jawab deti hai."), "A queue (Redis) decouples the slow work from the web request.", "202 Accepted · job_id=j-91", { active: ["Auth", "Queue"] }),
      stg("worker", "4. Worker does the slow part", S("A separate worker picks the job, parses, chunks and embeds, and updates progress.", "अलग worker job उठाता है, parse, chunk और embed करता है, और progress अपडेट करता है।", "Alag worker job uthata hai, parse, chunk aur embed karta hai, aur progress update karta hai."), "Workers scale independently and can retry a failed job.", "progress: parsing → chunking → embedding → done", { active: ["Queue", "Worker"] }),
      stg("done", "5. User sees progress", S("The UI polls the job and shows 'ready' when finished. The web server never blocked.", "UI job poll करता है और पूरा होने पर 'ready' दिखाता है। Web server कभी अटका नहीं।", "UI job poll karta hai aur poora hone par 'ready' dikhata hai. Web server kabhi atka nahi."), "Idempotent jobs make retries safe.", "GET /jobs/j-91 → ready", { active: ["Worker", "END"] })];
    const cache = stg("cache", "3. Cache lookup", S("Have we answered this exact question recently? If yes, skip the model and the cost.", "क्या हमने यह सवाल हाल में जवाब दिया है? हाँ तो model और खर्च दोनों बच जाते हैं।", "Kya humne yeh sawal haal mein jawab diya hai? Haan to model aur kharcha dono bach jaate hain."), "Cache key = normalised question + document version; set a TTL.", "miss → call the model", { active: ["Auth", "Cache"] });
    if (variant === "normal") return [...front, cache, stg("prov", "4. Call the model", S("The request goes to the model provider with a timeout.", "Request timeout के साथ model provider को जाती है।", "Request timeout ke saath model provider ko jaati hai."), "Always set a timeout; never wait forever.", "200 OK · 640 tokens", { active: ["Cache", "Provider"] }), stg("end", "5. Answer + logs", S("The answer returns and a log line records latency and tokens.", "जवाब लौटता है और log में latency और tokens दर्ज होते हैं।", "Jawab lautta hai aur log mein latency aur tokens darj hote hain."), "Structured logs + metrics feed dashboards and alerts.", "answer with citations", { active: ["Provider", "END"] })];
    if (variant === "retry") return [...front, cache, ...waits.map((w, i) => stg(`r${i}`, `${4 + i}. Attempt ${i + 1} fails (429)`, S(`The provider says 'too many requests'. We wait ${w}s (plus random jitter) and try again.`, `Provider कहता है 'बहुत requests'। हम ${w}s (और थोड़ा random jitter) रुककर फिर कोशिश करते हैं।`, `Provider kehta hai 'bahut requests'. Hum ${w}s (aur thoda random jitter) rukkar phir koshish karte hain.`), "Exponential backoff doubles the wait; jitter spreads retries so clients do not stampede together. Retry only transient errors (429, 5xx).", `429 → wait ≈ ${w}s`, { active: ["Cache", "Provider"] })),
      stg("ok", `${4 + fails}. Attempt ${fails + 1} succeeds`, S("The user gets an answer, just a bit slower. A hard failure was avoided.", "User को जवाब मिलता है, बस थोड़ा धीमा। सीधा fail होने से बचे।", "User ko jawab milta hai, bas thoda dheema. Seedha fail hone se bache."), "Cap retries (e.g. 3–5) and total time.", `200 OK after ≈ ${waits.reduce((a, b) => a + b, 0)}s of waiting`, { active: ["Provider", "END"] })];
    return [...front, cache, stg("f1", "4. Calls keep failing", S("Five calls in a row fail. Hammering a broken provider makes things worse.", "लगातार पाँच calls fail होती हैं। टूटे provider पर बार-बार call करना हालत बिगाड़ता है।", "Lagaatar paanch calls fail hoti hain. Toote provider par baar-baar call karna haalat bigadta hai."), "Failure counter reaches the threshold.", "5 failures in 30 s", { active: ["Cache", "Provider"] }),
      stg("open", "5. Circuit breaker opens", S("For a short time we stop calling the provider at all and fail fast.", "थोड़ी देर के लिए provider को call करना बंद, सीधे fail।", "Thodi der ke liye provider ko call karna band, seedhe fail."), "States: closed (normal) → open (reject quickly) → half-open (probe) → closed.", "breaker: OPEN for 30 s", { active: ["Provider"] }),
      stg("fb", "6. Honest fallback", S("The user gets a cached answer, a smaller model's answer, or a clear 'try again soon' — not a hang.", "User को cached जवाब, छोटे model का जवाब या साफ़ 'थोड़ी देर में कोशिश करें' मिलता है — hang नहीं।", "User ko cached jawab, chhote model ka jawab ya saaf 'thodi der mein koshish karein' milta hai — hang nahi."), "Fallbacks must be labelled so users know the answer may be older or simpler.", "503 + Retry-After: 30", { active: ["Provider", "END"] })];
  },
};

// ----------------------------------------------------------------------------- Deployment pipeline
const deploy: Scene = {
  id: "deploy-pipeline", title: "From commit to production, and what happens when it goes wrong", intro: "Follow a release. In the 'bad release' pattern the health check fails and the system rolls back.",
  variants: [{ id: "good", label: "Healthy release" }, { id: "bad", label: "Bad release (rollback)" }],
  inputs: [{ key: "ver", label: "Version", type: "text", default: "v1.4.2" }],
  build: (v, variant) => {
    const ver = str(v, "ver") || "v1.0.0", bad = variant === "bad";
    return [
      stg("commit", "1. Commit and push", S("A developer pushes code to the repository.", "Developer code को repository में push करता है।", "Developer code ko repository mein push karta hai."), "Everything after this is automated (CI/CD).", `git push  →  ${ver}`),
      stg("ci", "2. Tests run", S("The CI server runs linting and tests. A failure stops the release here.", "CI server lint और tests चलाता है। Fail होने पर release यहीं रुकता है।", "CI server lint aur tests chalata hai. Fail hone par release yahin rukta hai."), "Tests include retrieval evaluation so quality regressions are caught.", "142 tests passed (example)"),
      stg("build", "3. Build the image", S("The app and its dependencies are packaged into a container image with a version tag.", "App और उसकी dependencies एक container image में पैक होती हैं, version tag के साथ।", "App aur uski dependencies ek container image mein pack hoti hain, version tag ke saath."), "Tag with the version or commit hash, never only 'latest'.", `image: app:${ver}`),
      stg("push", "4. Store the image", S("The image goes to a registry so servers can pull the exact same bytes.", "Image registry में जाती है ताकि servers ठीक वही bytes उठा सकें।", "Image registry mein jaati hai taaki servers theek wahi bytes utha saken."), "Registries: Docker Hub, ECR, GHCR. Scan images for known vulnerabilities.", `registry/app:${ver}`),
      stg("roll", "5. Rolling deploy", S("New containers start one by one; old ones keep serving until the new ones are ready.", "नए containers एक-एक करके शुरू होते हैं; पुराने तब तक चलते रहते हैं जब तक नए तैयार न हों।", "Naye containers ek-ek karke shuru hote hain; purane tab tak chalte rehte hain jab tak naye taiyaar na hon."), "Zero-downtime: readiness checks gate traffic.", `2 of 4 instances on ${ver}`),
      bad ? stg("health", "6. Health check fails", S("The new version cannot reach the database, so /health reports an error.", "नया version database तक नहीं पहुँच पा रहा, इसलिए /health error देता है।", "Naya version database tak nahi pahunch pa raha, isliye /health error deta hai."), "Health checks stop bad instances from receiving traffic.", "GET /health → 503", { lines: ["error rate 38% (example)"] }) : stg("health", "6. Health check passes", S("/health answers OK on every new instance, so traffic moves over.", "हर नए instance पर /health OK देता है, इसलिए traffic आ जाता है।", "Har naye instance par /health OK deta hai, isliye traffic aa jaata hai."), "Separate liveness (is it running?) from readiness (can it serve?).", "GET /health → 200 {status: ok}"),
      bad ? stg("rollback", "7. Automatic rollback", S("Alerts fire and the deploy goes back to the previous version. Users barely notice.", "Alerts बजते हैं और deploy पिछले version पर लौट जाता है। Users को मुश्किल से पता चलता है।", "Alerts bajte hain aur deploy pichle version par laut jaata hai. Users ko mushkil se pata chalta hai."), "Keep the previous image; rollback = redeploy it. Write a post-mortem afterwards.", `rolled back to the previous version`) : stg("watch", "7. Watch the metrics", S("Dashboards track errors, latency, tokens and cost for the next hour.", "Dashboards अगले एक घंटे errors, latency, tokens और cost देखते हैं।", "Dashboards agle ek ghante errors, latency, tokens aur cost dekhte hain."), "Alert on symptoms users feel: error rate, p95 latency, queue depth.", "error rate 0.2%, p95 latency 1.9 s (example)"),
    ];
  },
};

// ----------------------------------------------------------------------------- async vs sync
const asyncTimeline: Scene = {
  id: "async-timeline", title: "Sync vs async: waiting for many slow calls", intro: "Each request waits on something slow (a database, a model API). See how long all of them take one-by-one and together.",
  inputs: [{ key: "n", label: "Number of requests", type: "number", default: 4, min: 1, max: 8 }, { key: "ms", label: "Waiting time of each (ms)", type: "number", default: 500, min: 100, max: 2000 }],
  build: (v) => {
    const n = Math.min(8, Math.max(1, num(v, "n") || 4)), ms = Math.min(2000, Math.max(100, num(v, "ms") || 500)), sync = n * ms;
    const rows = (conc: boolean) => Array.from({ length: n }, (_, i) => `req ${i + 1} ${bar(conc ? 0 : i * ms, ms, sync)}`);
    return [
      stg("sync", "1. One at a time (blocking)", S("A blocking handler waits for each call to finish before it starts the next.", "Blocking handler अगला शुरू करने से पहले हर call के ख़त्म होने का इंतज़ार करता है।", "Blocking handler agla shuru karne se pehle har call ke khatam hone ka intezaar karta hai."), "A synchronous function holds its thread while it waits. FastAPI runs plain `def` endpoints in a thread pool, so other requests can still run, but threads are limited.", `total = ${n} × ${ms} ms = ${sync} ms`, { lines: rows(false) }),
      stg("async", "2. Together (async)", S("With async, while one call waits, the program starts the others. Waiting overlaps.", "Async में एक call के इंतज़ार के दौरान program बाकी शुरू कर देता है। इंतज़ार overlap होता है।", "Async mein ek call ke intezaar ke dauran program baaki shuru kar deta hai. Intezaar overlap hota hai."), "`await asyncio.gather(...)` runs coroutines concurrently on one event loop thread. Real totals add a little overhead.", `total ≈ ${ms} ms (about ${fmt(sync / ms, 1)}× faster)`, { lines: rows(true) }),
      stg("cpu", "3. When async does NOT help", S("If the work is heavy calculation, not waiting, nothing overlaps: the one thread is busy.", "अगर काम भारी calculation है, इंतज़ार नहीं, तो कुछ overlap नहीं होता: एक thread व्यस्त है।", "Agar kaam bhaari calculation hai, intezaar nahi, to kuch overlap nahi hota: ek thread vyast hai."), "CPU-bound work blocks the event loop. Use worker processes, a queue, or a thread/process pool instead.", `CPU work: total stays ≈ ${sync} ms`, { lines: rows(false) }),
      stg("rule", "4. Rule of thumb", S("Waiting on a network or database → async. Heavy calculation → separate worker.", "Network या database का इंतज़ार → async। भारी calculation → अलग worker।", "Network ya database ka intezaar → async. Bhaari calculation → alag worker."), "Never call a blocking function (time.sleep, requests.get) inside `async def`: it freezes every request on that loop.", "async def + await for I/O; background worker for CPU"),
    ];
  },
};

// ----------------------------------------------------------------------------- cache-aside
const cacheAside: Scene = {
  id: "cache-aside", title: "Cache-aside: Redis in front of PostgreSQL", intro: "A user profile is read several times. Change the cache lifetime (TTL) and watch hits, misses and the stale-data problem.",
  inputs: [{ key: "ttl", label: "Cache lifetime (TTL, seconds)", type: "number", default: 2, min: 1, max: 6 }],
  build: (v) => {
    const ttl = Math.min(6, Math.max(1, num(v, "ttl") || 2));
    let cached: { name: string; exp: number } | null = null;
    let db = "Asha";
    const stages: Stage[] = [];
    const n = () => stages.length + 1;
    const read = (t: number) => {
      const hit = cached !== null && t < cached.exp, stale = hit && cached!.name !== db;
      const shown = hit ? cached!.name : db;
      if (!hit) cached = { name: db, exp: t + ttl };
      const simple = stale ? S("Still the OLD name: this is stale data. It goes away when the TTL ends.", "अब भी पुराना नाम: यह stale data है। TTL ख़त्म होने पर ठीक होगा।", "Ab bhi purana naam: yeh stale data hai. TTL khatam hone par theek hoga.")
        : hit ? S("Found in Redis: very fast, the database is not touched.", "Redis में मिला: बहुत तेज़, database छुआ भी नहीं।", "Redis mein mila: bahut tez, database chhua bhi nahi.")
          : S("Not in Redis (or expired): read PostgreSQL, then store the result with a TTL.", "Redis में नहीं (या expire): PostgreSQL से पढ़ा, फिर TTL के साथ रखा।", "Redis mein nahi (ya expire): PostgreSQL se padha, phir TTL ke saath rakha.");
      stages.push(stg(`r${stages.length}`, `${n()}. t=${t}s  read user:42`, simple, "Cache-aside: the app checks the cache, falls back to the database, then fills the cache. Times shown are typical orders of magnitude, not measurements.",
        hit ? `HIT  → "${shown}"  (about 1 ms)${stale ? "   ⚠ stale" : ""}` : `MISS → PostgreSQL → "${shown}"  (tens of ms), then SET user:42 EX ${ttl}`, { lines: [`TTL ${ttl}s · cached until t=${cached!.exp}s`] }));
    };
    read(0); read(1);
    db = "Asha K.";
    stages.push(stg("upd", `${n()}. t=1.2s  name changed in PostgreSQL`, S("The name is updated in the database only. Redis still holds the old copy.", "नाम सिर्फ़ database में बदला। Redis में अब भी पुरानी copy है।", "Naam sirf database mein badla. Redis mein ab bhi purani copy hai."), "If you do not delete or update the key on write, readers see old data until the TTL expires.", `PostgreSQL: "${db}"   Redis: "${cached!.name}"`));
    read(1.5); read(3);
    stages.push(stg("inv", `${n()}. Better: delete the key when data changes`, S("On every update also DELETE the cache key. The next read reloads fresh data.", "हर update पर cache key भी DELETE करें। अगली read ताज़ा data लाती है।", "Har update par cache key bhi DELETE karo. Agli read taaza data laati hai."), "Write path: UPDATE in PostgreSQL, then DEL user:42. Keep the TTL as a safety net.", "UPDATE users SET name = … ;   DEL user:42"));
    return stages;
  },
};

// ----------------------------------------------------------------------------- Docker layers
const LAYERS = ["FROM python:3.12-slim", "WORKDIR /srv", "COPY requirements.txt .", "RUN pip install -r requirements.txt", "COPY . .", 'CMD ["uvicorn", "app:app", "--host", "0.0.0.0"]'];
const FIRST_CHANGED: Record<string, number> = { "nothing": 99, "app code (app.py)": 4, "requirements.txt": 2, "base image tag": 0 };
const dockerLayers: Scene = {
  id: "docker-layers", title: "Docker image layers and the build cache", intro: "Every Dockerfile line makes a layer. Docker re-uses unchanged layers and rebuilds everything after the first change.",
  inputs: [{ key: "chg", label: "What did you change?", type: "select", default: "app code (app.py)", options: Object.keys(FIRST_CHANGED) }],
  build: (v) => {
    const chg = str(v, "chg"), first = FIRST_CHANGED[chg] ?? 99;
    const lines = LAYERS.map((l, i) => `${i < first ? "CACHED  " : "REBUILD "} ${l}`);
    const rebuilt = LAYERS.length - Math.min(first, LAYERS.length);
    return [
      stg("file", "1. The Dockerfile", S("A Dockerfile is a recipe. Each line is a step; each step becomes a layer.", "Dockerfile एक recipe है। हर line एक step है; हर step एक layer बनता है।", "Dockerfile ek recipe hai. Har line ek step hai; har step ek layer banta hai."), "Layers are read-only and content-addressed; a container adds a thin writable layer on top.", LAYERS.join("\n")),
      stg("first", "2. First build", S("Nothing is cached yet, so every layer is built. Installing packages is the slow one.", "अभी कुछ cached नहीं, इसलिए हर layer बनती है। Packages install करना सबसे धीमा है।", "Abhi kuch cached nahi, isliye har layer banti hai. Packages install karna sabse dheema hai."), "pip install downloads and unpacks packages, so it usually dominates build time.", "6 of 6 layers built", { lines: LAYERS.map((l) => "BUILD    " + l) }),
      stg("chg", "3. You change something", S(`You changed: ${chg}. Docker compares each layer with the cache, top to bottom.`, `आपने बदला: ${chg}। Docker हर layer को cache से ऊपर से नीचे मिलाता है।`, `Aapne badla: ${chg}. Docker har layer ko cache se upar se neeche milata hai.`), "The cache key of a COPY step includes the checksum of the copied files.", rebuilt === 0 ? "nothing changed → everything is cached" : `first changed layer: #${first + 1}`, { lines }),
      stg("res", "4. Result", rebuilt === 0 ? S("All layers are cached: the build is almost instant.", "सब layers cached हैं: build लगभग तुरंत।", "Sab layers cached hain: build lagbhag turant.") : first >= 4 ? S("Only the last copy-and-run layers rebuild. The slow pip install stays cached. This is why requirements are copied BEFORE the code.", "सिर्फ़ आख़िरी layers दोबारा बनती हैं। धीमा pip install cached रहता है। इसीलिए requirements को code से पहले copy करते हैं।", "Sirf aakhiri layers dobara banti hain. Dheema pip install cached rehta hai. Isiliye requirements ko code se pehle copy karte hain.") : S("A change high up forces every layer below it to rebuild, including pip install. Put things that change rarely at the top.", "ऊपर का बदलाव उसके नीचे की हर layer, pip install समेत, दोबारा बनवाता है। कम बदलने वाली चीज़ें ऊपर रखें।", "Upar ka badlav uske neeche ki har layer, pip install samet, dobara banwata hai. Kam badalne wali cheezein upar rakho."), "Order Dockerfile lines from least to most frequently changing. Add a .dockerignore so files such as .git and .env never enter the build context.", `${rebuilt} of ${LAYERS.length} layers rebuilt`),
    ];
  },
};

// ----------------------------------------------------------------------------- AWS
const aws: Scene = {
  id: "aws-architecture", title: "A small AI service on AWS", intro: "One common way to run the service. Services and names change over time, so check the AWS documentation for current options and prices.",
  graph: () => ({ nodes: ["START", "Route53", "ALB", "ECS", "RDS", "ElastiCache", "S3", "END"], edges: [["START", "Route53"], ["Route53", "ALB"], ["ALB", "ECS"], ["ECS", "RDS"], ["ECS", "ElastiCache"], ["ECS", "S3"], ["RDS", "END"], ["ElastiCache", "END"], ["S3", "END"]] }),
  inputs: [],
  build: () => [
    stg("dns", "1. DNS (Route 53)", S("The user types your domain. DNS turns it into the address of your load balancer.", "User आपका domain लिखता है। DNS उसे load balancer के पते में बदलता है।", "User aapka domain likhta hai. DNS use load balancer ke pate mein badalta hai."), "Route 53 is AWS's DNS service. HTTPS certificates come from ACM.", "api.example.com → load balancer", { active: ["START", "Route53"] }),
    stg("alb", "2. Load balancer (ALB)", S("It receives HTTPS traffic and spreads it across healthy copies of your app.", "यह HTTPS traffic लेकर आपके app की स्वस्थ copies में बाँटता है।", "Yeh HTTPS traffic lekar aapke app ki swasth copies mein baantta hai."), "The Application Load Balancer runs health checks (/health) and removes bad targets.", "HTTPS :443 → targets", { active: ["Route53", "ALB"] }),
    stg("ecs", "3. Your containers (ECS on Fargate)", S("Your Docker image runs as containers. Fargate runs them without you managing servers.", "आपकी Docker image containers के रूप में चलती है। Fargate बिना server सँभाले उन्हें चलाता है।", "Aapki Docker image containers ke roop mein chalti hai. Fargate bina server sambhale unhe chalata hai."), "Images come from ECR. A task definition sets CPU, memory, environment variables and the IAM role. An auto scaling policy adds copies under load.", "app:v1.4.2 × 2 tasks", { active: ["ALB", "ECS"] }),
    stg("data", "4. Data stores", S("PostgreSQL (RDS) keeps users and records. Redis (ElastiCache) caches and queues. S3 keeps uploaded files.", "PostgreSQL (RDS) users और records रखता है। Redis (ElastiCache) cache और queue का काम करता है। S3 uploaded files रखता है।", "PostgreSQL (RDS) users aur records rakhta hai. Redis (ElastiCache) cache aur queue ka kaam karta hai. S3 uploaded files rakhta hai."), "Put databases in private subnets; only the app's security group may connect. Turn on automated backups.", "RDS · ElastiCache · S3", { active: ["ECS", "RDS", "ElastiCache", "S3"] }),
    stg("iam", "5. Permissions (IAM) and secrets", S("Each container gets only the permissions it needs. Secrets like API keys are kept in a secrets store, not in the image.", "हर container को सिर्फ़ ज़रूरी permissions मिलती हैं। API keys जैसे secrets secrets store में रहते हैं, image में नहीं।", "Har container ko sirf zaroori permissions milti hain. API keys jaise secrets secrets store mein rehte hain, image mein nahi."), "Least privilege: an IAM role that can read one S3 prefix, not the whole account. Use Secrets Manager or SSM Parameter Store.", "role: s3:GetObject on uploads/* only", { active: ["ECS"] }),
    stg("obs", "6. Logs and alarms (CloudWatch)", S("Logs, metrics and alarms tell you when something is wrong before users complain.", "Logs, metrics और alarms बताते हैं कि कुछ गड़बड़ है, users के शिकायत करने से पहले।", "Logs, metrics aur alarms batate hain ki kuch gadbad hai, users ke shikayat karne se pehle."), "Alarm on 5xx rate, p95 latency and unhealthy host count; set a budget alert for cost.", "alarm: 5xx > 2% for 5 min", { active: ["END"] }),
  ],
};

export const MORE: Record<string, Scene> = { "ai-vs-ml": aiVsMl, "prompt-anatomy": promptAnatomy, "messages-api": messagesApi, "mcp-flow": mcp, "rag-eval-metrics": ragEval, "prod-request": prodRequest, "deploy-pipeline": deploy, "async-timeline": asyncTimeline, "cache-aside": cacheAside, "docker-layers": dockerLayers, "aws-architecture": aws };
