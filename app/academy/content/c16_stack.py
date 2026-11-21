"""Production stack lessons that were 'planned' on the roadmap: async FastAPI, Redis + PostgreSQL, Docker and AWS.
Every runnable example uses only the Python standard library, so it runs in the offline sandbox; real-service code is marked as not runnable and says what it needs."""
from . import T

SRC_FASTAPI_ASYNC = {"title": "FastAPI: Concurrency and async / await", "url": "https://fastapi.tiangolo.com/async/"}
SRC_ASYNCIO = {"title": "Python asyncio documentation", "url": "https://docs.python.org/3/library/asyncio.html"}
SRC_REDIS = {"title": "Redis documentation", "url": "https://redis.io/docs/"}
SRC_PG = {"title": "PostgreSQL documentation", "url": "https://www.postgresql.org/docs/current/"}
SRC_DOCKER_BP = {"title": "Docker: building best practices", "url": "https://docs.docker.com/build/building/best-practices/"}
SRC_ECS = {"title": "Amazon ECS documentation", "url": "https://docs.aws.amazon.com/ecs/"}
SRC_IAM = {"title": "AWS IAM user guide", "url": "https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html"}

LESSONS = [
    # ------------------------------------------------------------------------------------------------ FastAPI + async
    {
        "id": "fastapi-async", "category": "prod-arch", "level": "production", "minutes": 20, "prereq": ["prod-architecture"], "next": ["redis-postgres"], "tags": ["fastapi", "async", "await", "asyncio", "background tasks", "concurrency"],
        "title": T("FastAPI and async processing", "FastAPI और async processing", "FastAPI aur async processing"),
        "summary": "Serve many slow requests at once: when to use async def, how await overlaps waiting, and where background work belongs.",
        "objectives": ["Explain what await does and why waiting overlaps", "Run several slow calls together with asyncio.gather", "Choose between def, async def and a background worker", "Spot the mistake of blocking inside async code"],
        "text": {
            "definition": T(
                "{{async|Async}} code lets one program keep many slow operations in flight. When a function reaches `await`, it pauses and hands control back so another request can run, then resumes when its result is ready. FastAPI supports both `def` and `async def` endpoints.",
                "{{async|Async}} code एक program को कई धीमे operations एक साथ चलाने देता है। जब function `await` पर पहुँचता है तो वह रुककर control लौटा देता है ताकि दूसरी request चल सके, और नतीजा तैयार होने पर आगे बढ़ता है। FastAPI में `def` और `async def` दोनों endpoints चलते हैं।",
                "{{async|Async}} code ek program ko kai dheeme operations ek saath chalane deta hai. Jab function `await` par pahunchta hai to woh rukkar control lauta deta hai taaki doosri request chal sake, aur result taiyaar hone par aage badhta hai. FastAPI mein `def` aur `async def` dono endpoints chalte hain."),
            "analogy": T(
                "A cook who puts rice on the stove and, instead of staring at the pot, chops vegetables. The rice still takes the same time, but the kitchen finishes the whole meal much sooner.",
                "एक रसोइया जो चावल चूल्हे पर रखकर बर्तन को घूरने की जगह सब्ज़ी काटता है। चावल उतना ही समय लेते हैं, पर पूरा खाना बहुत जल्दी तैयार हो जाता है।",
                "Ek rasoiya jo chawal chulhe par rakhkar bartan ko ghoorne ki jagah sabzi kaatta hai. Chawal utna hi samay lete hain, par poora khaana bahut jaldi taiyaar ho jaata hai."),
            "technical": T(
                "`async def` functions are coroutines scheduled on an event loop, which runs on one thread. `await` is where a coroutine yields while it waits for I/O (HTTP call, database driver with async support, model API). `asyncio.gather` starts several coroutines and waits for all of them, returning results in the order given. Async only helps for waiting, not for heavy calculation: CPU-bound work blocks the loop, so push it to a worker process or queue. Never call a blocking function such as `time.sleep` or `requests.get` inside `async def` - it freezes every request on that loop; use `await asyncio.sleep` or `httpx.AsyncClient` instead. FastAPI runs plain `def` endpoints in a thread pool, which is fine for blocking libraries. For work that takes seconds or minutes (embedding a large document), return a job id immediately and process it with `BackgroundTasks` for light jobs or a real queue and worker (Redis) for heavy ones.",
                "`async def` functions coroutines हैं जो एक thread पर चलने वाले event loop पर schedule होते हैं। `await` वह जगह है जहाँ coroutine I/O (HTTP call, async वाला database driver, model API) का इंतज़ार करते हुए रुकता है। `asyncio.gather` कई coroutines शुरू करके सबका इंतज़ार करता है और नतीजे दिए गए क्रम में लौटाता है। Async सिर्फ़ इंतज़ार में मदद करता है, भारी calculation में नहीं: CPU वाला काम loop को रोक देता है, इसलिए उसे worker process या queue में भेजें। `async def` के अंदर `time.sleep` या `requests.get` जैसा blocking function कभी न बुलाएँ - वह उस loop की हर request को जमा देता है; इनकी जगह `await asyncio.sleep` या `httpx.AsyncClient` इस्तेमाल करें। FastAPI सादे `def` endpoints को thread pool में चलाता है, जो blocking libraries के लिए ठीक है। जिस काम में सेकंड या मिनट लगें (बड़े document का embedding), तुरंत job id लौटाएँ और हल्के jobs के लिए `BackgroundTasks`, भारी jobs के लिए असली queue और worker (Redis) से process करें।",
                "`async def` functions coroutines hain jo ek thread par chalne wale event loop par schedule hote hain. `await` woh jagah hai jahan coroutine I/O (HTTP call, async wala database driver, model API) ka intezaar karte hue rukta hai. `asyncio.gather` kai coroutines shuru karke sabka intezaar karta hai aur results diye gaye kram mein lautata hai. Async sirf intezaar mein madad karta hai, bhaari calculation mein nahi: CPU wala kaam loop ko rok deta hai, isliye use worker process ya queue mein bhejo. `async def` ke andar `time.sleep` ya `requests.get` jaisa blocking function kabhi mat bulao - woh us loop ki har request ko jama deta hai; inki jagah `await asyncio.sleep` ya `httpx.AsyncClient` istemal karo. FastAPI saade `def` endpoints ko thread pool mein chalata hai, jo blocking libraries ke liye theek hai. Jis kaam mein second ya minute lagein (bade document ka embedding), turant job id lautao aur halke jobs ke liye `BackgroundTasks`, bhaari jobs ke liye asli queue aur worker (Redis) se process karo."),
            "why": T(
                "AI apps spend most of their time waiting for models, databases and vector stores. Async lets one server handle many users at once without paying for a thread per waiting request.",
                "AI apps का ज़्यादातर समय models, databases और vector stores का इंतज़ार करने में जाता है। Async से एक server कई users को एक साथ सँभालता है, हर इंतज़ार करती request के लिए अलग thread का खर्च किए बिना।",
                "AI apps ka zyadatar samay models, databases aur vector stores ka intezaar karne mein jaata hai. Async se ek server kai users ko ek saath sambhalta hai, har intezaar karti request ke liye alag thread ka kharcha kiye bina."),
            "example": T(
                "A question needs a vector search (200 ms) and a user lookup (100 ms) that do not depend on each other. With gather they take about 200 ms together instead of 300 ms in a row.",
                "एक सवाल को vector search (200 ms) और user lookup (100 ms) चाहिए जो एक-दूसरे पर निर्भर नहीं। gather से वे साथ में लगभग 200 ms लेते हैं, लगातार चलाने पर 300 ms।",
                "Ek sawal ko vector search (200 ms) aur user lookup (100 ms) chahiye jo ek-doosre par nirbhar nahi. gather se woh saath mein lagbhag 200 ms lete hain, lagaatar chalane par 300 ms."),
            "interview": T(
                "I use `async def` for endpoints that mostly wait on I/O and call async clients with `await`, running independent calls together with `asyncio.gather`. I never block the event loop: heavy or blocking work goes to a thread pool or a worker behind a queue, and long jobs return a job id that the client polls. I set timeouts on every outbound call and test the endpoints with the test client.",
                "मैं उन endpoints के लिए `async def` इस्तेमाल करता हूँ जो ज़्यादातर I/O का इंतज़ार करते हैं और async clients को `await` से बुलाता हूँ, स्वतंत्र calls को `asyncio.gather` से साथ चलाता हूँ। मैं event loop को कभी block नहीं करता: भारी या blocking काम thread pool या queue के पीछे worker में जाता है, और लंबे jobs job id लौटाते हैं जिसे client poll करता है। हर बाहरी call पर timeout लगाता हूँ और endpoints को test client से परखता हूँ।",
                "Main un endpoints ke liye `async def` istemal karta hoon jo zyadatar I/O ka intezaar karte hain aur async clients ko `await` se bulata hoon, swatantra calls ko `asyncio.gather` se saath chalata hoon. Main event loop ko kabhi block nahi karta: bhaari ya blocking kaam thread pool ya queue ke peeche worker mein jaata hai, aur lambe jobs job id lautate hain jise client poll karta hai. Har baahari call par timeout lagata hoon aur endpoints ko test client se parakhta hoon."),
            "mistakes": {
                "en": ["Calling `time.sleep()` or a blocking HTTP library inside `async def`, which freezes every request.", "Forgetting `await`, so you hold a coroutine object instead of the result.", "Using async for CPU-heavy work such as parsing a huge PDF: it blocks the loop instead of helping."],
                "hi": ["`async def` के अंदर `time.sleep()` या blocking HTTP library बुलाना, जो हर request को जमा देता है।", "`await` भूल जाना, जिससे result की जगह coroutine object हाथ में रहता है।", "बड़े PDF parse जैसे CPU वाले काम के लिए async इस्तेमाल करना: इससे मदद की जगह loop block होता है।"],
                "hinglish": ["`async def` ke andar `time.sleep()` ya blocking HTTP library bulana, jo har request ko jama deta hai.", "`await` bhool jaana, jisse result ki jagah coroutine object haath mein rehta hai.", "Bade PDF parse jaise CPU wale kaam ke liye async istemal karna: isse madad ki jagah loop block hota hai."]},
        },
        "viz": ["async-timeline"],
        "code": [
            {"title": "await and gather: waiting overlaps", "language": "python", "runnable": True,
             "code": r'''import asyncio


async def fetch(name, delay):
    await asyncio.sleep(delay)          # pretend this is a database or a model call
    return f"{name} done"


async def main():
    results = await asyncio.gather(fetch("A", 0.3), fetch("B", 0.1), fetch("C", 0.2))
    print(results)                      # same order as the calls, not the finishing order


asyncio.run(main())
''',
             "expected_output": "['A done', 'B done', 'C done']",
             "explain": [{"lines": "4-6", "text": "`async def` makes a coroutine. `await asyncio.sleep` stands in for slow I/O: while it waits, other coroutines can run."}, {"lines": "9-10", "text": "gather starts all three at once and waits until every one has finished. B finishes first, but results keep the order A, B, C."}, {"lines": "13", "text": "`asyncio.run` starts the event loop and runs main() to the end."}]},
            {"title": "Measure it: one by one vs together", "language": "python", "runnable": True,
             "code": r'''import asyncio
import time


async def call():
    await asyncio.sleep(0.2)


async def one_by_one(n):
    for _ in range(n):
        await call()


async def together(n):
    await asyncio.gather(*[call() for _ in range(n)])


def timed(coro):
    start = time.perf_counter()
    asyncio.run(coro)
    return time.perf_counter() - start


slow = timed(one_by_one(5))
fast = timed(together(5))
print("one by one takes at least 1.0 s:", slow >= 1.0)
print("together takes under 0.5 s     :", fast < 0.5)
''',
             "expected_output": "one by one takes at least 1.0 s: True\ntogether takes under 0.5 s     : True",
             "explain": [{"lines": "9-11", "text": "Five calls of 0.2 s each, awaited one after another: about 1 s."}, {"lines": "14-15", "text": "The same five calls through gather: about 0.2 s, because all five wait at the same time."}, {"lines": "18-22", "text": "A tiny stopwatch around asyncio.run. We print booleans instead of raw seconds because exact times change on every machine."}]},
            {"title": "A FastAPI service with async I/O and a background job (needs packages; not run here)", "language": "python", "runnable": False,
             "setup": "pip install fastapi uvicorn httpx, save as main.py and run: uvicorn main:app --reload. Then open http://127.0.0.1:8000/docs. The URL in the example is a placeholder for your own model or search API.",
             "code": r'''import asyncio

import httpx
from fastapi import BackgroundTasks, FastAPI

app = FastAPI()
jobs: dict[str, str] = {}              # in production: Redis or PostgreSQL, not process memory


@app.get("/answer")
async def answer(q: str):
    async with httpx.AsyncClient(timeout=10) as client:                       # always set a timeout
        search, profile = await asyncio.gather(                               # independent calls run together
            client.get("https://example.invalid/search", params={"q": q}),
            client.get("https://example.invalid/profile"),
        )
    return {"hits": search.json(), "profile": profile.json()}


def embed_document(job_id: str):
    jobs[job_id] = "done"                                                       # slow work goes here


@app.post("/documents", status_code=202)
async def upload(background: BackgroundTasks):
    jobs["j1"] = "running"
    background.add_task(embed_document, "j1")                                  # runs after the response is sent
    return {"job_id": "j1"}


@app.get("/jobs/{job_id}")
def job(job_id: str):
    return {"status": jobs.get(job_id, "unknown")}
''',
             "explain": [{"lines": "11-17", "text": "Two independent HTTP calls run together with gather. The timeout stops a slow dependency from hanging the request."}, {"lines": "20-27", "text": "A long job returns 202 and a job id at once; the slow work runs after the response. BackgroundTasks lives inside the web process, so use a real queue and worker for heavy or must-not-lose jobs."}, {"lines": "30-32", "text": "The client polls this endpoint. A plain `def` is fine here: FastAPI runs it in a thread pool."}]}],
        "exercise": {"prompt": "Write async def fetch_all(names) that calls fetch(name) for every name TOGETHER (use asyncio.gather) and returns the list of results in order. fetch is given. Print asyncio.run(fetch_all(['a', 'b', 'c'])).",
                     "starter": "import asyncio\n\nasync def fetch(name):\n    await asyncio.sleep(0.01)\n    return name + '!'\n\nasync def fetch_all(names):\n    # TODO: run fetch for all names together and return the results\n    pass\n\nprint(asyncio.run(fetch_all(['a', 'b', 'c'])))\n",
                     "expected_output": "['a!', 'b!', 'c!']",
                     "solution": "import asyncio\n\nasync def fetch(name):\n    await asyncio.sleep(0.01)\n    return name + '!'\n\nasync def fetch_all(names):\n    return await asyncio.gather(*[fetch(n) for n in names])\n\nprint(list(asyncio.run(fetch_all(['a', 'b', 'c']))))\n",
                     "hint": "Build a list of coroutines with a comprehension, unpack it into gather with *, and await the result.",
                     "tests": [{"name": "three names, in order", "call": "asyncio.run(fetch_all(['a', 'b', 'c']))", "expect": "['a!', 'b!', 'c!']"}, {"name": "empty list", "call": "asyncio.run(fetch_all([]))", "expect": "[]"}, {"name": "order is kept", "call": "asyncio.run(fetch_all(['z', 'y']))", "expect": "['z!', 'y!']", "hidden": True}]},
        "debug": {"prompt": "This program should print 43 but crashes. Find the missing keyword and fix it.",
                  "starter": "import asyncio\n\nasync def get_value():\n    await asyncio.sleep(0.01)\n    return 42\n\nasync def main():\n    value = get_value()\n    print(value + 1)\n\nasyncio.run(main())\n",
                  "expected_output": "43",
                  "solution": "import asyncio\n\nasync def get_value():\n    await asyncio.sleep(0.01)\n    return 42\n\nasync def main():\n    value = await get_value()\n    print(value + 1)\n\nasyncio.run(main())\n",
                  "hint": "Calling an async function only creates a coroutine. Something must wait for it to finish."},
        "assignment": "Take one endpoint of your own project that calls two services one after the other. Make the calls independent with asyncio.gather, add a timeout, and measure the total time before and after with the stopwatch from example 2.",
        "quiz": [
            {"id": "fastapi-async.q1", "kind": "concept", "q": "What does `await` do?", "options": ["It makes the CPU faster", "It pauses this coroutine until the result is ready and lets other work run meanwhile", "It starts a new process", "It converts a function to JavaScript"], "answer": 1,
             "why": "await yields control while waiting, so one thread can serve many waiting operations.", "why_not": {"0": "Async does not speed up calculation.", "2": "No new process is created.", "3": "Unrelated to JavaScript."}},
            {"id": "fastapi-async.q2", "kind": "scenario", "q": "An `async def` endpoint calls `time.sleep(5)` and `requests.get(...)`. What happens to other users?", "options": ["Nothing, they are served as normal", "Every request on that event loop is frozen while it waits", "FastAPI converts them automatically", "Only the first user is affected after a restart"], "answer": 1,
             "why": "Blocking calls inside the loop stop all other coroutines. Use `await asyncio.sleep` and an async HTTP client.", "why_not": {"0": "The loop is stuck, so nobody is served.", "2": "FastAPI does not rewrite your blocking calls.", "3": "It affects every request, any time."}},
            {"id": "fastapi-async.q3", "kind": "concept", "q": "Which work should NOT rely on async alone?", "options": ["Waiting for a database", "Waiting for a model API", "Parsing and embedding a huge PDF (heavy calculation)", "Calling two services at once"], "answer": 2,
             "why": "Heavy calculation keeps the thread busy; send it to a worker process or a queue.", "why_not": {"0": "Waiting on I/O is async's strength.", "1": "Same: waiting on I/O.", "3": "gather helps exactly here."}},
        ],
        "interview_questions": [{"q": "When would you choose `def` over `async def` in FastAPI?", "a": "When the endpoint uses a blocking library (a sync database driver, an SDK without async support) or does short CPU work. FastAPI runs plain def endpoints in a thread pool, so they do not block the event loop. I use async def when every call inside is awaitable."},
                                {"q": "How do you handle a request that takes two minutes?", "a": "Return 202 with a job id immediately, put the job on a queue, process it in a worker, store status and results, and let the client poll or listen for updates. Make the job idempotent so a retry is safe."}],
        "sources": [SRC_FASTAPI_ASYNC, SRC_ASYNCIO],
    },
    # ------------------------------------------------------------------------------------------------ Redis + PostgreSQL
    {
        "id": "redis-postgres", "category": "prod-arch", "level": "production", "minutes": 22, "prereq": ["fastapi-async"], "next": ["docker-basics"], "tags": ["redis", "postgresql", "cache", "ttl", "transactions", "queue", "rate limit"],
        "title": T("Redis and PostgreSQL: what each one is for", "Redis और PostgreSQL: कौन किस काम के लिए", "Redis aur PostgreSQL: kaun kis kaam ke liye"),
        "summary": "Keep your records safe in PostgreSQL, keep hot or temporary data fast in Redis, and avoid the stale-cache trap.",
        "objectives": ["Say which data belongs in PostgreSQL and which in Redis", "Implement cache-aside with a TTL and invalidation", "Explain a transaction with all-or-nothing behaviour", "List Redis uses beyond caching: queues and rate limits"],
        "text": {
            "definition": T(
                "PostgreSQL is a relational database: it stores your important records in tables, enforces rules, and keeps them safe on disk. Redis is a very fast in-memory store: it keeps data you can afford to rebuild (a {{cache|cache}}, a queue, counters) and expires it after a {{ttl|TTL}}.",
                "PostgreSQL एक relational database है: यह आपके ज़रूरी records tables में रखता है, नियम लागू करता है और उन्हें disk पर सुरक्षित रखता है। Redis बहुत तेज़ in-memory store है: यह वो data रखता है जिसे दोबारा बनाया जा सके ({{cache|cache}}, queue, counters) और {{ttl|TTL}} के बाद हटा देता है।",
                "PostgreSQL ek relational database hai: yeh aapke zaroori records tables mein rakhta hai, niyam lagu karta hai aur unhe disk par surakshit rakhta hai. Redis bahut tez in-memory store hai: yeh woh data rakhta hai jise dobara banaya ja sake ({{cache|cache}}, queue, counters) aur {{ttl|TTL}} ke baad hata deta hai."),
            "analogy": T(
                "PostgreSQL is the locked filing cabinet with the official records. Redis is the sticky note on your desk with the number you look up all day. Fast to read, but if it is lost you copy it again from the cabinet.",
                "PostgreSQL ताले वाली अलमारी है जिसमें सरकारी records हैं। Redis आपकी मेज़ पर चिपका नोट है जिसमें वो नंबर है जो आप दिन भर देखते हैं। पढ़ने में तेज़, पर खो जाए तो अलमारी से दोबारा उतार लेते हैं।",
                "PostgreSQL taale wali almari hai jisme sarkari records hain. Redis aapki mez par chipka note hai jisme woh number hai jo aap din bhar dekhte ho. Padhne mein tez, par kho jaye to almari se dobara utaar lete hain."),
            "technical": T(
                "Use PostgreSQL as the source of truth for users, documents, conversations and audit logs. Its strengths are transactions (several changes succeed together or not at all), constraints, indexes and SQL. Use parameterised queries, never string-built SQL, and run schema changes through migrations (Alembic). Use Redis for: (1) cache-aside - read the cache first, on a miss read PostgreSQL and store the value with a TTL; delete the key when the record changes; (2) job queues for workers; (3) rate-limit counters (INCR with EXPIRE); (4) short-lived sessions. Redis can persist to disk, but treat it as rebuildable unless you have configured and tested persistence. A cache has a known cost: stale reads until the TTL ends or the key is invalidated, so cache only data where a few seconds of staleness is acceptable, or invalidate on write.",
                "Users, documents, conversations और audit logs के लिए PostgreSQL को सच का स्रोत रखें। इसकी ताकत transactions (कई बदलाव साथ सफल हों या बिल्कुल नहीं), constraints, indexes और SQL है। Parameterised queries इस्तेमाल करें, string जोड़कर बने SQL नहीं, और schema बदलाव migrations (Alembic) से करें। Redis इन कामों के लिए: (1) cache-aside - पहले cache पढ़ें, miss पर PostgreSQL पढ़कर value TTL के साथ रखें; record बदले तो key हटाएँ; (2) workers के लिए job queues; (3) rate-limit counters (INCR के साथ EXPIRE); (4) कम समय की sessions। Redis disk पर भी रख सकता है, पर जब तक persistence configure और test न की हो इसे दोबारा बनने लायक मानें। Cache की एक ज्ञात कीमत है: TTL ख़त्म होने या key हटने तक stale reads, इसलिए सिर्फ़ वही data cache करें जहाँ कुछ सेकंड पुराना चलता हो, या write पर invalidate करें।",
                "Users, documents, conversations aur audit logs ke liye PostgreSQL ko sach ka srot rakho. Iski taakat transactions (kai badlav saath safal hon ya bilkul nahi), constraints, indexes aur SQL hai. Parameterised queries istemal karo, string jodkar bane SQL nahi, aur schema badlav migrations (Alembic) se karo. Redis in kaamon ke liye: (1) cache-aside - pehle cache padho, miss par PostgreSQL padhkar value TTL ke saath rakho; record badle to key hatao; (2) workers ke liye job queues; (3) rate-limit counters (INCR ke saath EXPIRE); (4) kam samay ki sessions. Redis disk par bhi rakh sakta hai, par jab tak persistence configure aur test na ki ho ise dobara banne laayak maano. Cache ki ek gyaat keemat hai: TTL khatam hone ya key hatne tak stale reads, isliye sirf wahi data cache karo jahan kuch second purana chalta ho, ya write par invalidate karo."),
            "why": T(
                "Most of your traffic reads the same few things again and again. Serving those from memory keeps the database calm and responses fast, while PostgreSQL guarantees that nothing important is lost.",
                "आपका ज़्यादातर traffic वही कुछ चीज़ें बार-बार पढ़ता है। उन्हें memory से देने पर database शांत रहता है और जवाब तेज़, जबकि PostgreSQL गारंटी देता है कि कुछ ज़रूरी खोएगा नहीं।",
                "Aapka zyadatar traffic wahi kuch cheezein baar-baar padhta hai. Unhe memory se dene par database shaant rehta hai aur jawab tez, jabki PostgreSQL guarantee deta hai ki kuch zaroori khoyega nahi."),
            "example": T(
                "A user profile is read on every page. The first read loads it from PostgreSQL (tens of milliseconds) and stores it in Redis for 60 seconds; the next thousands of reads take about a millisecond. When the user edits their name, the app updates PostgreSQL and deletes the Redis key.",
                "User profile हर page पर पढ़ी जाती है। पहली read PostgreSQL से लोड होती है (दसों milliseconds) और Redis में 60 सेकंड के लिए रखी जाती है; अगली हज़ारों reads लगभग एक millisecond लेती हैं। User नाम बदले तो app PostgreSQL update करता है और Redis key हटा देता है।",
                "User profile har page par padhi jaati hai. Pehli read PostgreSQL se load hoti hai (dason milliseconds) aur Redis mein 60 second ke liye rakhi jaati hai; agli hazaron reads lagbhag ek millisecond leti hain. User naam badle to app PostgreSQL update karta hai aur Redis key hata deta hai."),
            "interview": T(
                "PostgreSQL is my system of record: transactions, constraints, indexes, migrations and backups. Redis sits in front for cache-aside reads with a TTL and invalidation on write, plus queues and rate-limit counters. I design so that losing Redis only makes things slower, never wrong or lost, and I never cache data where staleness would be harmful without invalidating it.",
                "PostgreSQL मेरा system of record है: transactions, constraints, indexes, migrations और backups। Redis सामने रहता है cache-aside reads के लिए TTL और write पर invalidation के साथ, और queues व rate-limit counters के लिए। मैं ऐसे design करता हूँ कि Redis खोने पर सिर्फ़ धीमापन आए, गलती या data-नुकसान नहीं, और जहाँ पुराना data हानिकारक हो वहाँ invalidate किए बिना cache नहीं करता।",
                "PostgreSQL mera system of record hai: transactions, constraints, indexes, migrations aur backups. Redis saamne rehta hai cache-aside reads ke liye TTL aur write par invalidation ke saath, aur queues va rate-limit counters ke liye. Main aise design karta hoon ki Redis khone par sirf dheemapan aaye, galti ya data-nuksaan nahi, aur jahan purana data hanikarak ho wahan invalidate kiye bina cache nahi karta."),
            "mistakes": {
                "en": ["Treating Redis as the only copy of important data.", "Caching without a TTL or invalidation, so users see old data for ever.", "Building SQL by joining strings with user input instead of parameters (SQL injection)."],
                "hi": ["Redis को ज़रूरी data की इकलौती copy मानना।", "TTL या invalidation के बिना cache करना, जिससे users को हमेशा पुराना data दिखता है।", "Parameters की जगह user input को string में जोड़कर SQL बनाना (SQL injection)।"],
                "hinglish": ["Redis ko zaroori data ki iklauti copy maanna.", "TTL ya invalidation ke bina cache karna, jisse users ko hamesha purana data dikhta hai.", "Parameters ki jagah user input ko string mein jodkar SQL banana (SQL injection)."]},
        },
        "viz": ["cache-aside"],
        "code": [
            {"title": "A transaction: all or nothing (sqlite3 stands in for PostgreSQL)", "language": "python", "runnable": True,
             "code": r'''import sqlite3

db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT, balance INTEGER CHECK (balance >= 0))")
db.executemany("INSERT INTO accounts (name, balance) VALUES (?, ?)", [("Asha", 100), ("Ravi", 50)])
db.commit()


def transfer(src, dst, amount):
    try:
        with db:                                    # one transaction: commit if no error, roll back if there is one
            db.execute("UPDATE accounts SET balance = balance - ? WHERE name = ?", (amount, src))
            db.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (amount, dst))
        return "ok"
    except sqlite3.IntegrityError:
        return "rejected: not enough balance"


print(transfer("Asha", "Ravi", 30))
print(transfer("Asha", "Ravi", 500))
print(db.execute("SELECT name, balance FROM accounts ORDER BY name").fetchall())
''',
             "expected_output": "ok\nrejected: not enough balance\n[('Asha', 70), ('Ravi', 80)]",
             "explain": [{"lines": "4", "text": "A table with a rule: a balance can never be negative. The database enforces it, not your application code."}, {"lines": "5", "text": "`?` placeholders pass values separately from the SQL, which prevents SQL injection."}, {"lines": "10-13", "text": "`with db` makes both updates one transaction. If the second fails or the rule is broken, neither stays."}, {"lines": "19-21", "text": "The 500 transfer is rejected and balances are unchanged: Asha 70, Ravi 80. SQL syntax is the same idea in PostgreSQL; the driver differs (psycopg)."}]},
            {"title": "Cache-aside with a TTL (a dictionary stands in for Redis)", "language": "python", "runnable": True,
             "code": r'''class FakeRedis:
    """Just enough of Redis to learn the pattern: get / set with expiry / delete, with a clock we control."""
    def __init__(self, clock):
        self.data, self.clock = {}, clock

    def get(self, key):
        item = self.data.get(key)
        return item[0] if item and self.clock() < item[1] else None

    def set(self, key, value, ex):
        self.data[key] = (value, self.clock() + ex)

    def delete(self, key):
        self.data.pop(key, None)


now = [0]
cache = FakeRedis(lambda: now[0])
database = {"user:42": "Asha"}               # the source of truth (PostgreSQL)
db_reads = [0]


def get_user(key):
    value = cache.get(key)
    if value is not None:
        return value, "hit"
    db_reads[0] += 1                          # slow path
    value = database[key]
    cache.set(key, value, ex=2)               # remember for 2 seconds
    return value, "miss"


for t in (0, 1, 2):
    now[0] = t
    print(t, get_user("user:42"))

database["user:42"] = "Asha K."               # the record changes...
cache.delete("user:42")                       # ...so the cached copy is removed
print("after update", get_user("user:42"))
print("database reads:", db_reads[0])
''',
             "expected_output": "0 ('Asha', 'miss')\n1 ('Asha', 'hit')\n2 ('Asha', 'miss')\nafter update ('Asha K.', 'miss')\ndatabase reads: 3",
             "explain": [{"lines": "1-14", "text": "A 12-line imitation of Redis. With real Redis: `r.get(key)`, `r.set(key, value, ex=2)`, `r.delete(key)`."}, {"lines": "24-31", "text": "Cache-aside: check the cache; on a miss read the database and store the value with a TTL."}, {"lines": "34-36", "text": "t=0 miss, t=1 hit, t=2 miss again (2 seconds passed, the entry expired)."}, {"lines": "38-41", "text": "Invalidate on write: delete the key when the record changes, so the next read loads the new value instead of serving a stale one."}]},
            {"title": "The real thing with redis-py and psycopg (needs services; not run here)", "language": "python", "runnable": False,
             "setup": "Start services: docker run -d -p 6379:6379 redis and docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pw postgres. Then: pip install redis 'psycopg[binary]'. Create the table with: CREATE TABLE users (id int primary key, name text);",
             "code": r'''import json

import psycopg
import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
pg = psycopg.connect("postgresql://postgres:pw@localhost:5432/postgres")


def get_user(user_id: int) -> dict:
    key = f"user:{user_id}"
    if (hit := r.get(key)) is not None:
        return json.loads(hit)
    with pg.cursor() as cur:
        cur.execute("SELECT id, name FROM users WHERE id = %s", (user_id,))     # parameters, never f-strings
        row = cur.fetchone()
    user = {"id": row[0], "name": row[1]}
    r.set(key, json.dumps(user), ex=60)                                           # cache for 60 seconds
    return user


def rename_user(user_id: int, name: str) -> None:
    with pg.transaction():
        pg.execute("UPDATE users SET name = %s WHERE id = %s", (name, user_id))
    r.delete(f"user:{user_id}")                                                   # invalidate after the commit


def allow_request(user_id: int, limit: int = 30) -> bool:
    key = f"rate:{user_id}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, 60)                                                         # a fixed one-minute window
    return count <= limit
''',
             "explain": [{"lines": "9-18", "text": "The same cache-aside logic against real services. psycopg uses %s placeholders."}, {"lines": "21-24", "text": "Update inside a transaction, then delete the cached copy."}, {"lines": "27-32", "text": "A simple rate limiter: INCR a counter per user and let it expire after a minute. Redis commands are atomic, so concurrent requests count correctly."}]}],
        "exercise": {"prompt": "Complete get_or_set(key): if key is in cache return it, otherwise call load(key), store the result in cache and return it. The program should print A, A, then 1 (load was called once).",
                     "starter": "cache = {}\ncalls = []\n\ndef load(key):\n    calls.append(key)\n    return key.upper()\n\ndef get_or_set(key):\n    # TODO\n    pass\n\nprint(get_or_set('a'))\nprint(get_or_set('a'))\nprint(len(calls))\n",
                     "expected_output": "A\nA\n1",
                     "solution": "cache = {}\ncalls = []\n\ndef load(key):\n    calls.append(key)\n    return key.upper()\n\ndef get_or_set(key):\n    if key not in cache:\n        cache[key] = load(key)\n    return cache[key]\n\nprint(get_or_set('a'))\nprint(get_or_set('a'))\nprint(len(calls))\n",
                     "hint": "Check `key in cache` first; only on a miss call load() and save its result.",
                     "tests": [{"name": "loads once for the same key", "call": "(cache.clear(), calls.clear(), get_or_set('a'), get_or_set('a'), len(calls))[-1]", "expect": "1"}, {"name": "returns the loaded value", "call": "(cache.clear(), get_or_set('b'))[1]", "expect": "'B'"}, {"name": "different keys load separately", "call": "(cache.clear(), calls.clear(), get_or_set('x'), get_or_set('y'), get_or_set('x'), len(calls))[-1]", "expect": "2", "hidden": True}]},
        "debug": {"prompt": "The cache never saves anything, so the loader runs on every call. The last line should print 1. Fix it.",
                  "starter": "cache = {}\ncalls = []\n\ndef load(key):\n    calls.append(key)\n    return key.upper()\n\ndef get_or_set(key):\n    if key in cache:\n        return cache[key]\n    return load(key)\n\nget_or_set('a')\nget_or_set('a')\nprint(len(calls))\n",
                  "expected_output": "1",
                  "solution": "cache = {}\ncalls = []\n\ndef load(key):\n    calls.append(key)\n    return key.upper()\n\ndef get_or_set(key):\n    if key in cache:\n        return cache[key]\n    cache[key] = load(key)\n    return cache[key]\n\nget_or_set('a')\nget_or_set('a')\nprint(len(calls))\n",
                  "hint": "A cache only works if the loaded value is stored somewhere."},
        "assignment": "Choose three kinds of data in your project (for example user profile, uploaded document text, a chat answer). For each write down: PostgreSQL, Redis, or both; the TTL; and what event should invalidate it.",
        "quiz": [
            {"id": "redis-postgres.q1", "kind": "concept", "q": "Which data must live in PostgreSQL rather than only in Redis?", "options": ["A temporary rate-limit counter", "User accounts and audit logs", "A cached answer that can be rebuilt", "A short-lived session lookup"], "answer": 1,
             "why": "Important records need durable storage, transactions and backups: that is PostgreSQL's job.", "why_not": {"0": "Counters expire; Redis is ideal.", "2": "Rebuildable data fits a cache.", "3": "Short-lived lookups fit Redis."}},
            {"id": "redis-postgres.q2", "kind": "scenario", "q": "Users keep seeing an old profile name after editing it. The profile is cached for 1 hour. What is the best fix?", "options": ["Remove PostgreSQL", "Delete the cache key after the update commits (and keep a TTL as a safety net)", "Make the TTL 24 hours", "Restart the browser"], "answer": 1,
             "why": "Invalidate on write so the next read loads fresh data; the TTL covers missed invalidations.", "why_not": {"0": "PostgreSQL is the source of truth.", "2": "A longer TTL makes staleness worse.", "3": "The stale copy is on the server side."}},
            {"id": "redis-postgres.q3", "kind": "concept", "q": "Why use `?` or `%s` placeholders instead of building SQL with f-strings?", "options": ["They are faster to type", "They keep user input separate from SQL, preventing SQL injection", "They make tables larger", "They are required by Redis"], "answer": 1,
             "why": "The database treats parameters as data, never as SQL code.", "why_not": {"0": "Safety is the reason, not typing speed.", "2": "Placeholders do not change table size.", "3": "Redis is not involved."}},
        ],
        "interview_questions": [{"q": "What is cache-aside and what are its risks?", "a": "The application reads the cache first; on a miss it reads the database and stores the value with a TTL; on writes it updates the database and deletes the key. Risks are stale reads between a write and invalidation, thundering herds when a hot key expires (mitigate with jitter or locking), and caching errors. I cache only data that tolerates brief staleness."},
                                {"q": "How would you rate-limit an API with Redis?", "a": "INCR a key per user and window, set EXPIRE on the first increment, and reject above the limit. Fixed windows allow bursts at the boundary, so for smoother limits I use a sliding window or token bucket, often implemented as a small Lua script so the steps are atomic."}],
        "sources": [SRC_REDIS, SRC_PG],
    },
    # ------------------------------------------------------------------------------------------------ Docker
    {
        "id": "docker-basics", "category": "deploy", "level": "production", "minutes": 20, "prereq": ["prod-architecture"], "next": ["aws-deploy"], "tags": ["docker", "dockerfile", "image", "container", "layers", "compose", "build cache"],
        "title": T("Docker: package your app so it runs the same everywhere", "Docker: अपना app ऐसे पैक करें कि हर जगह एक जैसा चले", "Docker: apna app aise pack karo ki har jagah ek jaisa chale"),
        "summary": "Write a Dockerfile, understand image layers and the build cache, run a container as a non-root user and describe a multi-service setup with Compose.",
        "objectives": ["Explain image vs container", "Write a Dockerfile in a cache-friendly order", "Apply basic hardening: pinned base, non-root user, health check, .dockerignore", "Describe an app + database + Redis stack with Compose"],
        "text": {
            "definition": T(
                "A {{docker-image|Docker image}} is a read-only package of your code, its libraries and the operating-system files it needs. A {{container}} is a running instance of that image. You describe the image in a text file called a Dockerfile.",
                "{{docker-image|Docker image}} आपके code, उसकी libraries और ज़रूरी operating-system files का read-only package है। {{container}} उस image का चलता हुआ रूप है। Image को आप Dockerfile नाम की text file में बताते हैं।",
                "{{docker-image|Docker image}} aapke code, uski libraries aur zaroori operating-system files ka read-only package hai. {{container}} us image ka chalta hua roop hai. Image ko aap Dockerfile naam ki text file mein batate ho."),
            "analogy": T(
                "A tiffin box prepared once with everything inside. Wherever you open it - office, train, park - the same meal is there. The image is the packed tiffin; each container is one person eating from an identical copy.",
                "एक बार सब कुछ भरकर तैयार किया टिफ़िन। दफ़्तर, ट्रेन या पार्क - जहाँ खोलें, वही खाना मिलता है। Image पैक किया टिफ़िन है; हर container उसकी एक जैसी copy से खाता एक इंसान।",
                "Ek baar sab kuch bharkar taiyaar kiya tiffin. Daftar, train ya park - jahan kholo, wahi khaana milta hai. Image pack kiya tiffin hai; har container uski ek jaisi copy se khaata ek insaan."),
            "technical": T(
                "Each Dockerfile instruction (FROM, COPY, RUN, ...) creates a layer. Docker caches layers and re-uses them while the instruction and its inputs are unchanged; after the first changed layer everything below is rebuilt. So order lines from least to most frequently changing: copy `requirements.txt` and install dependencies first, copy your code last. Pin the base image to a version (`python:3.12-slim`), not `latest`; run as a non-root `USER`; add a `HEALTHCHECK`; use `.dockerignore` to keep `.git`, `.env` and local data out of the build context; never put secrets in the image - pass them as environment variables or secret mounts at run time. Containers are throw-away: keep persistent data in volumes or external services. Docker Compose describes several containers (API, worker, PostgreSQL, Redis) and their networks in one YAML file for local development. Multi-stage builds keep compilers out of the final image to make it smaller.",
                "हर Dockerfile instruction (FROM, COPY, RUN, ...) एक layer बनाता है। Docker layers cache करता है और जब तक instruction और उसके inputs नहीं बदलते उन्हें दोबारा इस्तेमाल करता है; पहली बदली layer के बाद नीचे का सब दोबारा बनता है। इसलिए lines को कम से ज़्यादा बदलने वाले क्रम में रखें: पहले `requirements.txt` copy करके dependencies install करें, code आख़िर में copy करें। Base image को version से pin करें (`python:3.12-slim`), `latest` से नहीं; non-root `USER` से चलाएँ; `HEALTHCHECK` जोड़ें; `.git`, `.env` और local data को build context से बाहर रखने के लिए `.dockerignore` इस्तेमाल करें; secrets कभी image में न रखें - run time पर environment variables या secret mounts से दें। Containers फेंकने लायक होते हैं: स्थायी data volumes या बाहरी services में रखें। Docker Compose कई containers (API, worker, PostgreSQL, Redis) और उनके networks को local development के लिए एक YAML file में बताता है। Multi-stage builds compilers को final image से बाहर रखकर उसे छोटा करते हैं।",
                "Har Dockerfile instruction (FROM, COPY, RUN, ...) ek layer banata hai. Docker layers cache karta hai aur jab tak instruction aur uske inputs nahi badalte unhe dobara istemal karta hai; pehli badli layer ke baad neeche ka sab dobara banta hai. Isliye lines ko kam se zyada badalne wale kram mein rakho: pehle `requirements.txt` copy karke dependencies install karo, code aakhir mein copy karo. Base image ko version se pin karo (`python:3.12-slim`), `latest` se nahi; non-root `USER` se chalao; `HEALTHCHECK` jodo; `.git`, `.env` aur local data ko build context se bahar rakhne ke liye `.dockerignore` istemal karo; secrets kabhi image mein mat rakho - run time par environment variables ya secret mounts se do. Containers phenkne laayak hote hain: sthayi data volumes ya baahari services mein rakho. Docker Compose kai containers (API, worker, PostgreSQL, Redis) aur unke networks ko local development ke liye ek YAML file mein batata hai. Multi-stage builds compilers ko final image se bahar rakhkar use chhota karte hain."),
            "why": T(
                "'It works on my machine' stops being an excuse. The same image runs on your laptop, in CI and in production, and a bad release can be rolled back by starting the previous image.",
                "'मेरी machine पर तो चल रहा है' अब बहाना नहीं रहता। वही image laptop, CI और production में चलती है, और खराब release पिछली image चालू करके वापस ली जा सकती है।",
                "'Meri machine par to chal raha hai' ab bahana nahi rehta. Wahi image laptop, CI aur production mein chalti hai, aur kharab release pichli image chalu karke wapas li ja sakti hai."),
            "example": T(
                "You change one line in app.py. With the right order only the last COPY layer is rebuilt in seconds; the slow `pip install` layer is reused from cache. With the wrong order every code change reinstalls all packages.",
                "आप app.py की एक line बदलते हैं। सही क्रम में सिर्फ़ आख़िरी COPY layer सेकंडों में दोबारा बनती है; धीमी `pip install` layer cache से आती है। गलत क्रम में हर code बदलाव सारे packages दोबारा install करवाता है।",
                "Aap app.py ki ek line badalte ho. Sahi kram mein sirf aakhiri COPY layer seconds mein dobara banti hai; dheemi `pip install` layer cache se aati hai. Galat kram mein har code badlav saare packages dobara install karwata hai."),
            "interview": T(
                "I write small, cache-friendly Dockerfiles: pinned slim base, dependencies before code, a non-root user, a health check and a .dockerignore, with no secrets in the image. I scan images, tag them with the version or commit rather than only latest, and use multi-stage builds when compilers are needed. Locally I use Compose for the app, worker, PostgreSQL and Redis; in production an orchestrator such as ECS or Kubernetes runs the same image.",
                "मैं छोटी, cache-friendly Dockerfiles लिखता हूँ: pinned slim base, code से पहले dependencies, non-root user, health check और .dockerignore, और image में कोई secret नहीं। मैं images scan करता हूँ, सिर्फ़ latest की जगह version या commit से tag करता हूँ, और compilers चाहिए तो multi-stage builds इस्तेमाल करता हूँ। Local में app, worker, PostgreSQL और Redis के लिए Compose, production में ECS या Kubernetes जैसा orchestrator वही image चलाता है।",
                "Main chhoti, cache-friendly Dockerfiles likhta hoon: pinned slim base, code se pehle dependencies, non-root user, health check aur .dockerignore, aur image mein koi secret nahi. Main images scan karta hoon, sirf latest ki jagah version ya commit se tag karta hoon, aur compilers chahiye to multi-stage builds istemal karta hoon. Local mein app, worker, PostgreSQL aur Redis ke liye Compose, production mein ECS ya Kubernetes jaisa orchestrator wahi image chalata hai."),
            "mistakes": {
                "en": ["Copying all the code before installing dependencies, so every edit reinstalls every package.", "Using `FROM python:latest` and running as root with secrets baked into the image.", "Storing important data inside a container, which disappears when the container is replaced."],
                "hi": ["Dependencies install करने से पहले पूरा code copy करना, जिससे हर edit पर सारे packages दोबारा install होते हैं।", "`FROM python:latest` इस्तेमाल करना, root से चलाना और secrets image में डाल देना।", "ज़रूरी data container के अंदर रखना, जो container बदलते ही ग़ायब हो जाता है।"],
                "hinglish": ["Dependencies install karne se pehle poora code copy karna, jisse har edit par saare packages dobara install hote hain.", "`FROM python:latest` istemal karna, root se chalana aur secrets image mein daal dena.", "Zaroori data container ke andar rakhna, jo container badalte hi gaayab ho jaata hai."]},
        },
        "viz": ["docker-layers"],
        "code": [
            {"title": "A tiny Dockerfile linter: find the common mistakes", "language": "python", "runnable": True,
             "code": r'''dockerfile = """FROM python:latest
COPY . .
RUN pip install -r requirements.txt
CMD ["uvicorn", "app:app"]"""

lines = [line.strip() for line in dockerfile.splitlines() if line.strip()]
problems = []

if any(l.startswith("FROM") and (l.endswith(":latest") or ":" not in l) for l in lines):
    problems.append("pin the base image version, not :latest")

copy_all = next((i for i, l in enumerate(lines) if l.startswith("COPY . ")), None)
install = next((i for i, l in enumerate(lines) if "pip install" in l), None)
if copy_all is not None and install is not None and copy_all < install:
    problems.append("copy requirements.txt first, install, THEN copy the code (keeps the build cache)")

if not any(l.startswith("USER") for l in lines):
    problems.append("add USER so the app does not run as root")
if not any(l.startswith("HEALTHCHECK") for l in lines):
    problems.append("add a HEALTHCHECK")

for p in problems:
    print("-", p)
print(len(problems), "problems")
''',
             "expected_output": "- pin the base image version, not :latest\n- copy requirements.txt first, install, THEN copy the code (keeps the build cache)\n- add USER so the app does not run as root\n- add a HEALTHCHECK\n4 problems",
             "explain": [{"lines": "1-4", "text": "A deliberately poor Dockerfile held in a string. Edit it and re-run to see the warnings disappear."}, {"lines": "9-10", "text": "A floating tag such as latest changes under you; builds stop being repeatable."}, {"lines": "12-15", "text": "COPY of all code before pip install means every code edit invalidates the slow install layer."}, {"lines": "17-20", "text": "Running as root and having no health check are the two most common production gaps."}]},
            {"title": "A good Dockerfile and a Compose file (copy these into your project)", "language": "python", "runnable": True,
             "code": r'''DOCKERFILE = """FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -r app && chown -R app /srv
USER app
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
"""

COMPOSE = """services:
  api:
    build: .
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql://postgres:pw@db:5432/app
      REDIS_URL: redis://cache:6379/0
    depends_on: [db, cache]
  db:
    image: postgres:16
    environment: {POSTGRES_PASSWORD: pw}
    volumes: ["pgdata:/var/lib/postgresql/data"]
  cache:
    image: redis:7
volumes:
  pgdata:
"""

print("--- Dockerfile ---")
print(DOCKERFILE)
print("--- docker-compose.yml ---")
print(COMPOSE)
''',
             "expected_output": "--- Dockerfile ---\nFROM python:3.12-slim\nWORKDIR /srv\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nRUN useradd -r app && chown -R app /srv\nUSER app\nEXPOSE 8000\nHEALTHCHECK CMD python -c \"import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health')\"\nCMD [\"uvicorn\", \"app:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n\n--- docker-compose.yml ---\nservices:\n  api:\n    build: .\n    ports: [\"8000:8000\"]\n    environment:\n      DATABASE_URL: postgresql://postgres:pw@db:5432/app\n      REDIS_URL: redis://cache:6379/0\n    depends_on: [db, cache]\n  db:\n    image: postgres:16\n    environment: {POSTGRES_PASSWORD: pw}\n    volumes: [\"pgdata:/var/lib/postgresql/data\"]\n  cache:\n    image: redis:7\nvolumes:\n  pgdata:",
             "explain": [{"lines": "1-5", "text": "Pinned slim base; requirements are copied and installed BEFORE the code, so editing code reuses the install layer."}, {"lines": "6-7", "text": "A dedicated non-root user."}, {"lines": "9", "text": "A health check the orchestrator can use. (Run `docker build -t app .` then `docker run -p 8000:8000 app` on a machine with Docker; Docker is not available in this sandbox.)"}, {"lines": "13-26", "text": "Compose describes API + PostgreSQL + Redis. Services reach each other by name (db, cache). The pgdata volume keeps database files when containers are replaced. Passwords here are for local practice only."}]}],
        "exercise": {"prompt": "A Dockerfile has numbered layers 0..5. Write rebuilt(total, changed) that returns the list of layer numbers Docker must rebuild when layer `changed` changed (that layer and every layer after it). Print rebuilt(6, 2) and rebuilt(6, 5).",
                     "starter": "def rebuilt(total, changed):\n    # TODO\n    pass\n\nprint(rebuilt(6, 2))\nprint(rebuilt(6, 5))\n",
                     "expected_output": "[2, 3, 4, 5]\n[5]",
                     "solution": "def rebuilt(total, changed):\n    return list(range(changed, total))\n\nprint(rebuilt(6, 2))\nprint(rebuilt(6, 5))\n",
                     "hint": "Everything from the changed layer to the last one is rebuilt: range(changed, total).",
                     "tests": [{"name": "middle layer changed", "call": "rebuilt(4, 1)", "expect": "[1, 2, 3]"}, {"name": "last layer changed", "call": "rebuilt(4, 3)", "expect": "[3]"}, {"name": "first layer changed", "call": "rebuilt(3, 0)", "expect": "[0, 1, 2]", "hidden": True}, {"name": "nothing after the end", "call": "rebuilt(3, 3)", "expect": "[]", "hidden": True}]},
        "debug": {"prompt": "rebuilt(6, 2) should include layer 2 itself, but the output skips it. Fix the bug.",
                  "starter": "def rebuilt(total, changed):\n    return [i for i in range(total) if i > changed]\n\nprint(rebuilt(6, 2))\n",
                  "expected_output": "[2, 3, 4, 5]",
                  "solution": "def rebuilt(total, changed):\n    return [i for i in range(total) if i >= changed]\n\nprint(rebuilt(6, 2))\n",
                  "hint": "The changed layer must be rebuilt too. Compare with >= instead of >."},
        "assignment": "On a machine with Docker, containerise your FastAPI app with the Dockerfile above. Build it twice: once after editing app.py and once after editing requirements.txt. Note which steps say CACHED in the build output.",
        "quiz": [
            {"id": "docker-basics.q1", "kind": "concept", "q": "What is the difference between an image and a container?", "options": ["They are the same thing", "An image is the read-only package; a container is a running instance of it", "A container is a file, an image is a process", "Images only exist on AWS"], "answer": 1,
             "why": "You build an image once and can start many containers from it.", "why_not": {"0": "They are different: package vs running instance.", "2": "It is the other way round.", "3": "Images work anywhere Docker runs."}},
            {"id": "docker-basics.q2", "kind": "scenario", "q": "Every small code edit makes the build download all Python packages again. What is the most likely cause?", "options": ["The internet is slow", "COPY . . comes before RUN pip install, so every edit invalidates the install layer", "Python is too large", "Docker is broken"], "answer": 1,
             "why": "Copy requirements.txt, install, then copy the rest of the code, so the install layer stays cached.", "why_not": {"0": "Order, not speed, causes repeated installs.", "2": "Package size does not explain re-downloads.", "3": "This is normal cache behaviour."}},
            {"id": "docker-basics.q3", "kind": "concept", "q": "Where should an API key for your model provider go?", "options": ["Hard-coded in the Dockerfile", "In the image through COPY of a .env file", "Passed at run time as an environment variable or secret, never baked into the image", "In the README"], "answer": 2,
             "why": "Anyone who can pull the image can read what is inside it.", "why_not": {"0": "Layers keep the value visible.", "1": "A copied .env stays in the layer.", "3": "Public documentation must not contain secrets."}},
        ],
        "interview_questions": [{"q": "How do you make Docker builds fast and images small?", "a": "Order the Dockerfile from least to most changing so the cache is reused, use a slim base, install with --no-cache-dir, add a .dockerignore, use multi-stage builds when compilers are only needed to build, and keep one process per container."},
                                {"q": "How do containers talk to a database and keep their data?", "a": "On a shared network they reach each other by service name, with connection settings passed as environment variables. Data lives in a volume or an external managed database, because the container's own filesystem is thrown away when it is replaced."}],
        "sources": [SRC_DOCKER_BP, {"title": "Docker Compose overview", "url": "https://docs.docker.com/compose/"}],
    },
    # ------------------------------------------------------------------------------------------------ AWS
    {
        "id": "aws-deploy", "category": "deploy", "level": "production", "minutes": 22, "prereq": ["docker-basics", "redis-postgres"], "next": ["deploy-monitor"], "tags": ["aws", "ecs", "fargate", "s3", "rds", "iam", "alb", "cloudwatch"],
        "title": T("AWS: run your container service in the cloud", "AWS: अपनी container service cloud में चलाएँ", "AWS: apni container service cloud mein chalao"),
        "summary": "A map of the AWS services a small AI app uses (load balancer, containers, database, cache, storage), least-privilege permissions and basic capacity sizing.",
        "objectives": ["Name the AWS service for each part of the stack", "Explain least-privilege IAM and how a policy is evaluated", "Estimate how many containers a given load needs", "List what to monitor and what to keep out of the image"],
        "text": {
            "definition": T(
                "AWS is a set of rented cloud services. For a containerised AI app the common pieces are: Route 53 (DNS), an Application Load Balancer, ECS with Fargate (runs your containers), RDS (managed PostgreSQL), ElastiCache (managed Redis), S3 (file storage), {{iam|IAM}} (permissions) and CloudWatch (logs and alarms).",
                "AWS किराये की cloud services का समूह है। Containerised AI app के आम हिस्से: Route 53 (DNS), Application Load Balancer, ECS के साथ Fargate (आपके containers चलाता है), RDS (managed PostgreSQL), ElastiCache (managed Redis), S3 (file storage), {{iam|IAM}} (permissions) और CloudWatch (logs और alarms)।",
                "AWS kiraye ki cloud services ka samuh hai. Containerised AI app ke aam hisse: Route 53 (DNS), Application Load Balancer, ECS ke saath Fargate (aapke containers chalata hai), RDS (managed PostgreSQL), ElastiCache (managed Redis), S3 (file storage), {{iam|IAM}} (permissions) aur CloudWatch (logs aur alarms)."),
            "analogy": T(
                "Renting a fully equipped shop in a mall instead of building your own building: the mall provides electricity, security and a front door (load balancer). You bring the stock (your containers) and decide who gets which key (IAM).",
                "अपनी इमारत बनाने की जगह mall में पूरी तरह सुसज्जित दुकान किराये पर लेना: mall बिजली, सुरक्षा और सामने का दरवाज़ा (load balancer) देता है। आप माल (अपने containers) लाते हैं और तय करते हैं कि किसे कौन सी चाबी मिलेगी (IAM)।",
                "Apni imarat banane ki jagah mall mein poori tarah susajjit dukaan kiraye par lena: mall bijli, suraksha aur saamne ka darwaza (load balancer) deta hai. Aap maal (apne containers) laate ho aur tay karte ho ki kise kaun si chaabi milegi (IAM)."),
            "technical": T(
                "A typical layout: users reach a domain in Route 53, which points to an Application Load Balancer in public subnets with an ACM certificate for HTTPS. The ALB forwards to ECS tasks on Fargate in private subnets; the image is pulled from ECR; the target group health check calls `/health`. The app talks to RDS PostgreSQL and ElastiCache Redis in private subnets whose security groups accept connections only from the app's security group. Uploaded files go to S3, ideally with pre-signed URLs. Each task has an IAM task role with only the permissions it needs; IAM denies everything by default, a matching Allow grants access and an explicit Deny always wins. Secrets live in Secrets Manager or SSM Parameter Store, not in the image. CloudWatch collects logs and metrics; alarms watch 5xx rate, latency and unhealthy hosts. Auto scaling adds tasks under load; size by measuring: tasks needed ≈ requests per second × seconds per request ÷ concurrent requests one task can handle, plus headroom. Prices and service details change, so check the current AWS documentation and set a budget alert.",
                "आम ढाँचा: users Route 53 के domain तक पहुँचते हैं, जो public subnets में HTTPS के लिए ACM certificate वाले Application Load Balancer की ओर इशारा करता है। ALB private subnets में Fargate पर ECS tasks को भेजता है; image ECR से आती है; target group health check `/health` बुलाता है। App private subnets में RDS PostgreSQL और ElastiCache Redis से बात करता है जिनके security groups सिर्फ़ app के security group से connection लेते हैं। Uploaded files S3 में जाती हैं, बेहतर है pre-signed URLs से। हर task के पास IAM task role होता है जिसमें सिर्फ़ ज़रूरी permissions हों; IAM डिफ़ॉल्ट रूप से सब मना करता है, मेल खाता Allow इजाज़त देता है और explicit Deny हमेशा जीतता है। Secrets Secrets Manager या SSM Parameter Store में रहते हैं, image में नहीं। CloudWatch logs और metrics इकट्ठा करता है; alarms 5xx दर, latency और unhealthy hosts देखते हैं। Auto scaling load में tasks बढ़ाता है; नापकर size तय करें: ज़रूरी tasks ≈ requests प्रति सेकंड × प्रति request सेकंड ÷ एक task की एक साथ सँभाली जाने वाली requests, और headroom। Prices और service details बदलते रहते हैं, इसलिए मौजूदा AWS documentation देखें और budget alert लगाएँ।",
                "Aam dhancha: users Route 53 ke domain tak pahunchte hain, jo public subnets mein HTTPS ke liye ACM certificate wale Application Load Balancer ki or ishara karta hai. ALB private subnets mein Fargate par ECS tasks ko bhejta hai; image ECR se aati hai; target group health check `/health` bulata hai. App private subnets mein RDS PostgreSQL aur ElastiCache Redis se baat karta hai jinke security groups sirf app ke security group se connection lete hain. Uploaded files S3 mein jaati hain, behtar hai pre-signed URLs se. Har task ke paas IAM task role hota hai jisme sirf zaroori permissions hon; IAM default roop se sab mana karta hai, mel khata Allow ijazat deta hai aur explicit Deny hamesha jeetta hai. Secrets Secrets Manager ya SSM Parameter Store mein rehte hain, image mein nahi. CloudWatch logs aur metrics ikattha karta hai; alarms 5xx dar, latency aur unhealthy hosts dekhte hain. Auto scaling load mein tasks badhata hai; naapkar size tay karo: zaroori tasks ≈ requests per second × per request second ÷ ek task ki ek saath sambhali jaane wali requests, aur headroom. Prices aur service details badalte rehte hain, isliye maujooda AWS documentation dekho aur budget alert lagao."),
            "why": T(
                "Managed services take over servers, patching, backups and scaling, so a small team can run a reliable service. But wrong permissions or an open database are the most common causes of cloud incidents, so the safe defaults matter.",
                "Managed services servers, patching, backups और scaling सँभाल लेती हैं, इसलिए छोटी team भी भरोसेमंद service चला सकती है। पर गलत permissions या खुला database cloud incidents की सबसे आम वजह हैं, इसलिए सुरक्षित defaults मायने रखते हैं।",
                "Managed services servers, patching, backups aur scaling sambhal leti hain, isliye chhoti team bhi bharosemand service chala sakti hai. Par galat permissions ya khula database cloud incidents ki sabse aam wajah hain, isliye surakshit defaults mayne rakhte hain."),
            "example": T(
                "Your API must handle 20 requests per second, each taking 2 seconds, and one task can handle 10 at once. 20 × 2 ÷ 10 = 4 tasks, so you start with 6 for headroom and let auto scaling adjust after you measure real traffic.",
                "आपकी API को 20 requests प्रति सेकंड सँभालनी हैं, हर एक 2 सेकंड लेती है, और एक task एक साथ 10 सँभाल सकता है। 20 × 2 ÷ 10 = 4 tasks, इसलिए headroom के लिए 6 से शुरू करें और असली traffic नापकर auto scaling को बदलने दें।",
                "Aapki API ko 20 requests per second sambhalni hain, har ek 2 second leti hai, aur ek task ek saath 10 sambhal sakta hai. 20 × 2 ÷ 10 = 4 tasks, isliye headroom ke liye 6 se shuru karo aur asli traffic naapkar auto scaling ko badalne do."),
            "interview": T(
                "I run the container on ECS Fargate behind an ALB with health checks, PostgreSQL on RDS and Redis on ElastiCache in private subnets, files in S3 with pre-signed URLs, and secrets in Secrets Manager. Each task has a least-privilege IAM role, images come from ECR, and CloudWatch alarms watch 5xx, latency and cost. I size capacity from measured requests per second and latency, roll out with rolling deployments and keep the previous image for a quick rollback.",
                "मैं container को ALB के पीछे health checks के साथ ECS Fargate पर चलाता हूँ, PostgreSQL RDS पर और Redis ElastiCache पर private subnets में, files S3 में pre-signed URLs से, और secrets Secrets Manager में। हर task को least-privilege IAM role मिलता है, images ECR से आती हैं, और CloudWatch alarms 5xx, latency और cost देखते हैं। मैं capacity नापी हुई requests प्रति सेकंड और latency से तय करता हूँ, rolling deployments से release करता हूँ और तेज़ rollback के लिए पिछली image रखता हूँ।",
                "Main container ko ALB ke peeche health checks ke saath ECS Fargate par chalata hoon, PostgreSQL RDS par aur Redis ElastiCache par private subnets mein, files S3 mein pre-signed URLs se, aur secrets Secrets Manager mein. Har task ko least-privilege IAM role milta hai, images ECR se aati hain, aur CloudWatch alarms 5xx, latency aur cost dekhte hain. Main capacity naapi hui requests per second aur latency se tay karta hoon, rolling deployments se release karta hoon aur tez rollback ke liye pichli image rakhta hoon."),
            "mistakes": {
                "en": ["Giving the app an admin IAM role (or `*` permissions) 'to make it work'.", "Putting the database in a public subnet or opening its security group to the whole internet.", "Skipping budget alarms and logs until the first surprise bill or outage."],
                "hi": ["App को 'चलाने के लिए' admin IAM role (या `*` permissions) दे देना।", "Database को public subnet में रखना या उसके security group को पूरे internet के लिए खोल देना।", "पहले अनपेक्षित bill या outage तक budget alarms और logs छोड़े रखना।"],
                "hinglish": ["App ko 'chalane ke liye' admin IAM role (ya `*` permissions) de dena.", "Database ko public subnet mein rakhna ya uske security group ko poore internet ke liye khol dena.", "Pehle anapekshit bill ya outage tak budget alarms aur logs chhode rakhna."]},
        },
        "viz": ["aws-architecture"],
        "code": [
            {"title": "How IAM decides: default deny, Allow grants, explicit Deny wins", "language": "python", "runnable": True,
             "code": r'''from fnmatch import fnmatch

policy = [
    {"effect": "Allow", "action": "s3:GetObject", "resource": "arn:aws:s3:::my-docs/uploads/*"},
    {"effect": "Deny", "action": "s3:*", "resource": "arn:aws:s3:::my-docs/private/*"},
]


def allowed(action, resource):
    verdict = False                                   # everything is denied unless some statement allows it
    for s in policy:
        if fnmatch(action, s["action"]) and fnmatch(resource, s["resource"]):
            if s["effect"] == "Deny":
                return False                          # an explicit Deny always wins
            verdict = True
    return verdict


tests = [
    ("s3:GetObject", "arn:aws:s3:::my-docs/uploads/a.pdf"),
    ("s3:GetObject", "arn:aws:s3:::my-docs/private/hr.pdf"),
    ("s3:PutObject", "arn:aws:s3:::my-docs/uploads/a.pdf"),
]
for action, resource in tests:
    print("ALLOW" if allowed(action, resource) else "DENY ", action, resource.split(":::")[1])
''',
             "expected_output": "ALLOW s3:GetObject my-docs/uploads/a.pdf\nDENY  s3:GetObject my-docs/private/hr.pdf\nDENY  s3:PutObject my-docs/uploads/a.pdf",
             "explain": [{"lines": "3-6", "text": "A policy is a list of statements: effect, actions and resources (wildcards allowed). Real policies are JSON documents with the same ideas."}, {"lines": "10-17", "text": "Start from deny. A matching Allow flips it to allowed; any matching Deny returns False immediately."}, {"lines": "21-25", "text": "Reading uploads is allowed; reading private is denied; writing is denied because nothing allows it."}]},
            {"title": "Capacity sizing: how many containers?", "language": "python", "runnable": True,
             "code": r'''import math


def tasks_needed(requests_per_second, seconds_per_request, concurrent_per_task, headroom=1.5):
    in_flight = requests_per_second * seconds_per_request          # requests being handled at any moment
    return math.ceil(in_flight / concurrent_per_task * headroom)


# These numbers are examples: measure your own latency and per-task concurrency with a load test.
for rps in (2, 20, 100):
    print(f"{rps:>3} req/s -> {tasks_needed(rps, 2.0, 10)} tasks")
''',
             "expected_output": "  2 req/s -> 1 tasks\n 20 req/s -> 6 tasks\n100 req/s -> 30 tasks",
             "explain": [{"lines": "4-5", "text": "Little's law: requests in flight = arrival rate × time each takes."}, {"lines": "6", "text": "Divide by how many one container can handle at once, then add headroom for spikes and deployments."}, {"lines": "10-11", "text": "The output is a starting point, not a promise: model APIs, databases and memory limits change the real answer."}]},
            {"title": "Upload to S3 with a pre-signed URL using boto3 (needs AWS access; not run here)", "language": "python", "runnable": False,
             "setup": "pip install boto3. Run it where AWS credentials are available through an IAM role or `aws configure`; never hard-code keys. Replace the bucket name with your own bucket. Check the boto3 documentation for current options.",
             "code": r'''import boto3

s3 = boto3.client("s3")                              # credentials come from the task role, not from code
BUCKET = "my-docs-bucket"                            # placeholder


def upload_url(user_id: str, filename: str) -> str:
    key = f"uploads/{user_id}/{filename}"            # one prefix per user; the role may only write under uploads/
    return s3.generate_presigned_url(
        "put_object", Params={"Bucket": BUCKET, "Key": key, "ContentType": "application/pdf"}, ExpiresIn=300
    )                                                # the browser uploads straight to S3; the URL expires in 5 minutes


print(upload_url("u42", "report.pdf"))
''',
             "explain": [{"lines": "3", "text": "boto3 finds credentials automatically: environment, shared config or, on ECS, the task role."}, {"lines": "8-11", "text": "A pre-signed URL lets the browser upload directly to S3, so large files never pass through your API. It expires quickly."}]}],
        "exercise": {"prompt": "Write tasks_needed(rps, seconds, per_task) that returns the number of tasks needed WITHOUT headroom, rounded UP (use math.ceil of rps × seconds ÷ per_task). Print tasks_needed(20, 2.0, 10) and tasks_needed(5, 0.5, 10).",
                     "starter": "import math\n\ndef tasks_needed(rps, seconds, per_task):\n    # TODO\n    pass\n\nprint(tasks_needed(20, 2.0, 10))\nprint(tasks_needed(5, 0.5, 10))\n",
                     "expected_output": "4\n1",
                     "solution": "import math\n\ndef tasks_needed(rps, seconds, per_task):\n    return math.ceil(rps * seconds / per_task)\n\nprint(tasks_needed(20, 2.0, 10))\nprint(tasks_needed(5, 0.5, 10))\n",
                     "hint": "Requests in flight = rps × seconds. Divide by per_task and round up so you never under-provision.",
                     "tests": [{"name": "exact fit", "call": "tasks_needed(30, 1, 10)", "expect": "3"}, {"name": "tiny load still needs one", "call": "tasks_needed(1, 1, 10)", "expect": "1"}, {"name": "rounds up", "call": "tasks_needed(31, 1, 10)", "expect": "4", "hidden": True}, {"name": "zero load", "call": "tasks_needed(0, 1, 10)", "expect": "0", "hidden": True}]},
        "debug": {"prompt": "The check should deny the private path, because of the explicit Deny, but it prints True. Fix the order of evaluation so a Deny always wins.",
                  "starter": "from fnmatch import fnmatch\n\npolicy = [\n    {'effect': 'Allow', 'resource': 'bucket/*'},\n    {'effect': 'Deny', 'resource': 'bucket/private/*'},\n]\n\ndef allowed(resource):\n    for s in policy:\n        if fnmatch(resource, s['resource']):\n            if s['effect'] == 'Allow':\n                return True\n            return False\n    return False\n\nprint(allowed('bucket/private/hr.pdf'))\n",
                  "expected_output": "False",
                  "solution": "from fnmatch import fnmatch\n\npolicy = [\n    {'effect': 'Allow', 'resource': 'bucket/*'},\n    {'effect': 'Deny', 'resource': 'bucket/private/*'},\n]\n\ndef allowed(resource):\n    verdict = False\n    for s in policy:\n        if fnmatch(resource, s['resource']):\n            if s['effect'] == 'Deny':\n                return False\n            verdict = True\n    return verdict\n\nprint(allowed('bucket/private/hr.pdf'))\n",
                  "hint": "Do not return on the first Allow. Keep looking: any matching Deny must override every Allow."},
        "assignment": "Draw (on paper) the AWS layout for your project using the six boxes from the animation. For each arrow write which security group or IAM permission allows it, and list three CloudWatch alarms you would create.",
        "quiz": [
            {"id": "aws-deploy.q1", "kind": "concept", "q": "In IAM, what happens when no policy statement mentions an action?", "options": ["It is allowed", "It is denied (default deny)", "AWS asks the user", "It is allowed for administrators only"], "answer": 1,
             "why": "Everything is denied unless an Allow grants it; an explicit Deny overrides any Allow.", "why_not": {"0": "Default is the opposite.", "2": "AWS does not prompt at call time.", "3": "Administrators still need permissions via policy."}},
            {"id": "aws-deploy.q2", "kind": "scenario", "q": "Where should the PostgreSQL database and Redis cache live?", "options": ["Public subnet with an open security group", "Private subnets, accepting connections only from the app's security group", "Inside the Docker image", "On the user's laptop"], "answer": 1,
             "why": "Data stores should not be reachable from the internet; only the app tier needs to talk to them.", "why_not": {"0": "That exposes your data.", "2": "Images are throw-away and not meant for data.", "3": "Not a deployment target."}},
            {"id": "aws-deploy.q3", "kind": "concept", "q": "Why use a pre-signed S3 URL for file uploads?", "options": ["It makes files public for ever", "The browser uploads directly to S3 with a short-lived permission, so large files do not pass through your API", "It removes the need for IAM", "It compresses the file"], "answer": 1,
             "why": "It combines low load on your servers with narrow, expiring access.", "why_not": {"0": "The URL expires and is scoped to one object.", "2": "IAM is still involved: the URL carries the signer's permissions.", "3": "It does not change the file."}},
        ],
        "interview_questions": [{"q": "How would you give an application access to an S3 bucket securely?", "a": "Attach an IAM role to the ECS task (or other compute) with a policy that allows only the needed actions on the needed prefix, and let the SDK pick up temporary credentials from the role. No access keys in code, images or environment files; add bucket policy and encryption, and log access."},
                                {"q": "What would you check if your service on ECS keeps restarting?", "a": "The stopped task's reason and exit code in ECS, container logs in CloudWatch, whether the health check path and port match the app, memory limits (out-of-memory kills), missing environment variables or secrets permissions, and whether the app can reach its database through the security groups."}],
        "sources": [SRC_ECS, SRC_IAM, {"title": "Amazon S3 pre-signed URLs", "url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html"}],
    },
]
