"""Foundation lessons for people who are new to programming and maths: Python for AI, vectors and similarity, SQL basics.
All runnable examples use only the Python standard library (sqlite3 stands in for a real database)."""
from . import T

SRC_PY = {"title": "The Python tutorial (python.org)", "url": "https://docs.python.org/3/tutorial/"}
SRC_PY_JSON = {"title": "Python json module", "url": "https://docs.python.org/3/library/json.html"}
SRC_3B1B = {"title": "Essence of linear algebra (3Blue1Brown)", "url": "https://www.3blue1brown.com/topics/linear-algebra"}
SRC_NUMPY = {"title": "NumPy: absolute basics for beginners", "url": "https://numpy.org/doc/stable/user/absolute_beginners.html"}
SRC_SQLITE = {"title": "SQLite SQL language reference", "url": "https://www.sqlite.org/lang.html"}
SRC_PG_TUT = {"title": "PostgreSQL tutorial: SQL language", "url": "https://www.postgresql.org/docs/current/tutorial-sql.html"}

LESSONS = [
    {
        "id": "python-for-ai", "category": "fundamentals", "level": "beginner", "minutes": 20, "prereq": ["ai-ml-dl"], "next": ["what-is-llm"], "tags": ["python", "lists", "dictionaries", "functions", "json", "basics"],
        "title": T("Python you need for AI: lists, dictionaries and functions", "AI के लिए ज़रूरी Python: lists, dictionaries और functions", "AI ke liye zaroori Python: lists, dictionaries aur functions"),
        "summary": "The five Python ideas that every AI example in this Academy uses, explained with tiny AI-flavoured programs.",
        "objectives": ["Store words and numbers in a list and a dictionary", "Write a function that returns a value", "Loop over data and count things", "Read and write JSON, the language of AI APIs"],
        "text": {
            "definition": T(
                "Python is a programming language that reads almost like English. For AI you mostly need: lists (ordered items), dictionaries (labelled items), loops, functions and JSON.",
                "Python एक programming language है जो लगभग English जैसी पढ़ी जाती है। AI के लिए ज़्यादातर चाहिए: lists (क्रम से रखी चीज़ें), dictionaries (नाम वाली चीज़ें), loops, functions और JSON।",
                "Python ek programming language hai jo lagbhag English jaisi padhi jaati hai. AI ke liye zyadatar chahiye: lists (kram se rakhi cheezein), dictionaries (naam wali cheezein), loops, functions aur JSON."),
            "analogy": T(
                "A list is a shopping list in order. A dictionary is a phone book: you look up a name and get a number. A function is a recipe: ingredients in, dish out.",
                "List क्रम से लिखी खरीदारी की सूची है। Dictionary phone book है: नाम देखो, नंबर मिलता है। Function एक रेसिपी है: सामग्री अंदर, पकवान बाहर।",
                "List kram se likhi kharidari ki soochi hai. Dictionary phone book hai: naam dekho, number milta hai. Function ek recipe hai: saamagri andar, pakwaan baahar."),
            "technical": T(
                "`words = text.split()` makes a list. `counts[w] = counts.get(w, 0) + 1` updates a dictionary. `def f(x): return x * 2` defines a function. A list comprehension `[w.upper() for w in words if len(w) > 2]` builds a new list in one line. `json.dumps(obj)` turns lists and dictionaries into text that APIs understand, and `json.loads(text)` turns it back. Indentation (4 spaces) is part of the syntax: it shows what belongs inside a loop or a function.",
                "`words = text.split()` एक list बनाता है। `counts[w] = counts.get(w, 0) + 1` dictionary अपडेट करता है। `def f(x): return x * 2` function बनाता है। List comprehension `[w.upper() for w in words if len(w) > 2]` एक लाइन में नई list बनाती है। `json.dumps(obj)` lists और dictionaries को वो text बनाता है जिसे APIs समझते हैं, और `json.loads(text)` उसे वापस बदलता है। Indentation (4 spaces) syntax का हिस्सा है: यह बताती है कि loop या function के अंदर क्या है।",
                "`words = text.split()` ek list banata hai. `counts[w] = counts.get(w, 0) + 1` dictionary update karta hai. `def f(x): return x * 2` function banata hai. List comprehension `[w.upper() for w in words if len(w) > 2]` ek line mein nayi list banati hai. `json.dumps(obj)` lists aur dictionaries ko woh text banata hai jise APIs samajhte hain, aur `json.loads(text)` use wapas badalta hai. Indentation (4 spaces) syntax ka hissa hai: yeh batati hai ki loop ya function ke andar kya hai."),
            "why": T(
                "Every AI API takes JSON in and gives JSON out, and every pipeline is loops over lists of text. With these five ideas you can read almost every example in this Academy.",
                "हर AI API JSON लेती और JSON देती है, और हर pipeline text की lists पर loops है। इन पाँच बातों से आप इस Academy का लगभग हर example पढ़ सकते हैं।",
                "Har AI API JSON leti aur JSON deti hai, aur har pipeline text ki lists par loops hai. In paanch baaton se aap is Academy ka lagbhag har example padh sakte ho."),
            "example": T(
                "To see which words a document uses most, split the text into a list, count each word in a dictionary and sort by count. That is the first step of search engines and of many AI features.",
                "किसी document में कौन से शब्द सबसे ज़्यादा हैं यह देखने के लिए text को list में बाँटें, हर शब्द dictionary में गिनें और गिनती से sort करें। यही search engines और कई AI features का पहला कदम है।",
                "Kisi document mein kaun se shabd sabse zyada hain yeh dekhne ke liye text ko list mein baanto, har shabd dictionary mein gino aur ginti se sort karo. Yahi search engines aur kai AI features ka pehla kadam hai."),
            "interview": T(
                "I use dictionaries for labelled data and lookups, lists for ordered sequences, comprehensions for short transformations, and small pure functions that are easy to test. I serialise with json and validate input before using it.",
                "मैं labelled data और lookups के लिए dictionaries, क्रम वाली sequences के लिए lists, छोटे बदलावों के लिए comprehensions और test करने में आसान छोटे pure functions इस्तेमाल करता हूँ। मैं json से serialise करता हूँ और इस्तेमाल से पहले input validate करता हूँ।",
                "Main labelled data aur lookups ke liye dictionaries, kram wali sequences ke liye lists, chhote badlavon ke liye comprehensions aur test karne mein aasan chhote pure functions istemal karta hoon. Main json se serialise karta hoon aur istemal se pehle input validate karta hoon."),
            "mistakes": {
                "en": ["Forgetting that Python counts from 0: the first item is `items[0]`.", "Mixing tabs and spaces, or wrong indentation, which changes what the code does.", "Changing a list while looping over it, which skips items."],
                "hi": ["भूल जाना कि Python 0 से गिनता है: पहला item `items[0]` है।", "tabs और spaces मिलाना, या गलत indentation, जिससे code का मतलब बदल जाता है।", "list पर loop चलाते हुए उसी list को बदलना, जिससे items छूट जाते हैं।"],
                "hinglish": ["Bhool jaana ki Python 0 se ginta hai: pehla item `items[0]` hai.", "tabs aur spaces milaana, ya galat indentation, jisse code ka matlab badal jaata hai.", "list par loop chalate hue usi list ko badalna, jisse items chhoot jaate hain."]},
        },
        "viz": ["python-data"],
        "code": [
            {"title": "Count the words of a text", "language": "python", "runnable": True,
             "code": r'''text = "the cat sat on the mat"
words = text.split()                       # a list of words
counts = {}                                # an empty dictionary
for w in words:
    counts[w] = counts.get(w, 0) + 1       # get(w, 0): the old count, or 0 when the word is new
print(words)
print(counts)
print(sorted(counts, key=counts.get, reverse=True)[:2])
''',
             "expected_output": "['the', 'cat', 'sat', 'on', 'the', 'mat']\n{'the': 2, 'cat': 1, 'sat': 1, 'on': 1, 'mat': 1}\n['the', 'cat']",
             "explain": [{"lines": "2", "text": "split() cuts the text at spaces and returns a list."}, {"lines": "4-5", "text": "A loop visits every word. The dictionary keeps one number per word."}, {"lines": "8", "text": "sorted() with key=counts.get orders the words by their count, biggest first; [:2] keeps the first two."}]},
            {"title": "Functions and JSON: the shape of an AI request", "language": "python", "runnable": True,
             "code": r'''import json


def make_message(role, content):
    return {"role": role, "content": content}


messages = [make_message("system", "Be brief."), make_message("user", "Hi")]
text = json.dumps(messages)                # list of dictionaries -> text
print(text)
back = json.loads(text)                    # text -> list of dictionaries
print(len(back), back[-1]["content"])
''',
             "expected_output": "[{\"role\": \"system\", \"content\": \"Be brief.\"}, {\"role\": \"user\", \"content\": \"Hi\"}]\n2 Hi",
             "explain": [{"lines": "4-5", "text": "A function takes inputs and returns a value. This one builds one chat message."}, {"lines": "9", "text": "json.dumps turns Python data into text, which is what you send to an AI API."}, {"lines": "11-12", "text": "json.loads is the reverse; back[-1] is the last item."}]}],
        "exercise": {"prompt": "Write average(numbers) that returns the mean of a list, and 0.0 for an empty list. Print average([2, 4, 6]) and average([]).",
                     "starter": "def average(numbers):\n    # TODO\n    pass\n\nprint(average([2, 4, 6]))\nprint(average([]))\n", "expected_output": "4.0\n0.0",
                     "solution": "def average(numbers):\n    if not numbers:\n        return 0.0\n    return sum(numbers) / len(numbers)\n\nprint(average([2, 4, 6]))\nprint(average([]))\n",
                     "hint": "sum(numbers) / len(numbers), but check for an empty list first so you do not divide by zero.",
                     "tests": [{"name": "mean of three", "call": "average([2, 4, 6])", "expect": "4.0"}, {"name": "empty list is 0.0", "call": "average([])", "expect": "0.0"}, {"name": "single number", "call": "average([5])", "expect": "5.0", "hidden": True}]},
        "debug": {"prompt": "The program should print 3 (the number of words) but prints 2. Find the off-by-one mistake.",
                  "starter": "words = ['ai', 'is', 'fun']\ncount = 0\nfor i in range(1, len(words)):\n    count += 1\nprint(count)\n", "expected_output": "3",
                  "solution": "words = ['ai', 'is', 'fun']\ncount = 0\nfor i in range(len(words)):\n    count += 1\nprint(count)\n", "hint": "range(1, n) skips index 0. Python starts counting at 0."},
        "assignment": "Take a paragraph from any document, split it into words, count them and print the five most common ones. Then put the result into a dictionary and print it as JSON.",
        "quiz": [
            {"id": "python-for-ai.q1", "kind": "concept", "q": "Which Python type is best for looking up a value by a name?", "options": ["list", "dictionary", "tuple of numbers", "string"], "answer": 1,
             "why": "A dictionary maps a key (the name) to a value, like a phone book.", "why_not": {"0": "A list is looked up by position, not by name.", "2": "Tuples are fixed ordered groups.", "3": "A string is text."}},
            {"id": "python-for-ai.q2", "kind": "concept", "q": "What is the index of the FIRST item of a list in Python?", "options": ["1", "0", "-1", "It depends"], "answer": 1,
             "why": "Python starts counting at 0; the last item is -1.", "why_not": {"0": "That is the second item.", "2": "-1 is the last item.", "3": "It is always 0."}},
            {"id": "python-for-ai.q3", "kind": "scenario", "q": "An API expects JSON text but you have a Python dictionary. What do you call?", "options": ["json.loads(data)", "json.dumps(data)", "data.split()", "print(data)"], "answer": 1,
             "why": "dumps turns Python data into JSON text; loads does the opposite.", "why_not": {"0": "loads parses JSON text into Python data.", "2": "split() is for strings.", "3": "print only shows the data."}},
        ],
        "interview_questions": [{"q": "Why prefer a dictionary over a list of pairs?", "a": "Lookups by key are fast (constant time on average) and the code states its intent. A list of pairs needs a loop to find one item."}],
        "sources": [SRC_PY, SRC_PY_JSON],
    },
    {
        "id": "vectors-math", "category": "embeddings", "level": "beginner", "minutes": 18, "prereq": ["python-for-ai"], "next": ["what-are-embeddings"], "tags": ["vectors", "dot product", "cosine", "similarity", "maths", "embeddings"],
        "title": T("The maths behind embeddings: vectors and similarity", "Embeddings के पीछे का गणित: vectors और similarity", "Embeddings ke peeche ka ganit: vectors aur similarity"),
        "summary": "A vector is a list of numbers. Learn length, dot product and cosine similarity with school-level maths and small programs.",
        "objectives": ["Say what a vector is and what its length means", "Compute a dot product by hand and in Python", "Explain cosine similarity as 'the angle between two arrows'", "Find the nearest vector to a query"],
        "text": {
            "definition": T(
                "A vector is a list of numbers, like [3, 4]. You can picture it as an arrow from the origin. Two vectors are similar when their arrows point the same way.",
                "Vector संख्याओं की एक list है, जैसे [3, 4]। इसे origin से निकलता तीर समझिए। दो vectors तब similar होते हैं जब उनके तीर एक ही दिशा में हों।",
                "Vector sankhyaon ki ek list hai, jaise [3, 4]. Ise origin se nikalta teer samjhiye. Do vectors tab similar hote hain jab unke teer ek hi disha mein hon."),
            "analogy": T(
                "Two people walking: if both head north-east they are going the same way, even if one walks faster. Cosine similarity compares the direction and ignores the speed.",
                "दो लोग चल रहे हैं: दोनों उत्तर-पूर्व की ओर जा रहे हों तो वे एक ही दिशा में हैं, भले एक तेज़ चले। Cosine similarity दिशा की तुलना करती है, गति को नहीं।",
                "Do log chal rahe hain: dono uttar-poorv ki or ja rahe hon to woh ek hi disha mein hain, bhale ek tez chale. Cosine similarity disha ki tulna karti hai, gati ko nahi."),
            "technical": T(
                "The length of [3, 4] is sqrt(3*3 + 4*4) = 5. The dot product of a and b is the sum of a[i]*b[i]. Cosine similarity = dot(a, b) / (length(a) * length(b)). It is 1 for the same direction, 0 for perpendicular ('unrelated') and -1 for opposite. Embedding models turn text into vectors with hundreds or thousands of numbers; the maths is exactly the same, just longer lists. Libraries such as NumPy do these sums fast.",
                "[3, 4] की लंबाई sqrt(3*3 + 4*4) = 5 है। a और b का dot product a[i]*b[i] का योग है। Cosine similarity = dot(a, b) / (length(a) * length(b))। यह समान दिशा के लिए 1, लंबवत ('असंबंधित') के लिए 0 और उलटी दिशा के लिए -1 होती है। Embedding models text को सैकड़ों या हज़ारों संख्याओं वाले vectors में बदलते हैं; गणित बिल्कुल वही है, बस lists लंबी हैं। NumPy जैसी libraries ये योग तेज़ी से करती हैं।",
                "[3, 4] ki lambai sqrt(3*3 + 4*4) = 5 hai. a aur b ka dot product a[i]*b[i] ka yog hai. Cosine similarity = dot(a, b) / (length(a) * length(b)). Yeh samaan disha ke liye 1, lambwat ('asambandhit') ke liye 0 aur ulti disha ke liye -1 hoti hai. Embedding models text ko saikdon ya hazaron sankhyaon wale vectors mein badalte hain; ganit bilkul wahi hai, bas lists lambi hain. NumPy jaisi libraries yeh yog tezi se karti hain."),
            "why": T(
                "Search by meaning, recommendations and RAG all rank things by vector similarity. Understanding the formula tells you why unnormalised lengths do not matter and why 'near' means 'similar meaning'.",
                "Meaning से search, recommendations और RAG सब vector similarity से चीज़ों को rank करते हैं। फ़ॉर्मूला समझने से पता चलता है कि लंबाई क्यों मायने नहीं रखती और 'पास' का मतलब 'मिलता-जुलता अर्थ' क्यों है।",
                "Meaning se search, recommendations aur RAG sab vector similarity se cheezon ko rank karte hain. Formula samajhne se pata chalta hai ki lambai kyun mayne nahi rakhti aur 'paas' ka matlab 'milta-julta arth' kyun hai."),
            "example": T(
                "'cat' = [0.9, 0.1], 'kitten' = [0.8, 0.2], 'car' = [0.1, 0.9]. cat and kitten point almost the same way (cosine near 1); cat and car point apart (cosine near 0.2).",
                "'cat' = [0.9, 0.1], 'kitten' = [0.8, 0.2], 'car' = [0.1, 0.9]। cat और kitten लगभग एक ही दिशा में हैं (cosine 1 के पास); cat और car अलग दिशाओं में हैं (cosine लगभग 0.2)।",
                "'cat' = [0.9, 0.1], 'kitten' = [0.8, 0.2], 'car' = [0.1, 0.9]. cat aur kitten lagbhag ek hi disha mein hain (cosine 1 ke paas); cat aur car alag dishaon mein hain (cosine lagbhag 0.2)."),
            "interview": T(
                "Cosine similarity is the dot product of two vectors divided by the product of their lengths: it measures the angle, not the magnitude. If vectors are normalised to length 1, cosine equals the dot product, which is why vector databases often store normalised vectors.",
                "Cosine similarity दो vectors के dot product को उनकी लंबाइयों के गुणनफल से भाग देना है: यह angle नापती है, magnitude नहीं। अगर vectors को लंबाई 1 पर normalise किया जाए तो cosine और dot product बराबर हैं, इसीलिए vector databases अक्सर normalised vectors रखते हैं।",
                "Cosine similarity do vectors ke dot product ko unki lambaiyon ke gunanfal se bhag dena hai: yeh angle naapti hai, magnitude nahi. Agar vectors ko lambai 1 par normalise kiya jaye to cosine aur dot product barabar hain, isiliye vector databases aksar normalised vectors rakhte hain."),
            "mistakes": {
                "en": ["Dividing by zero when a vector is all zeros: check the length first.", "Comparing raw dot products of vectors of different lengths and calling the biggest 'most similar'.", "Thinking a high cosine means the texts are true or relevant to your question, when it only means the embedder placed them close."],
                "hi": ["जब vector में सब शून्य हों तो शून्य से भाग देना: पहले लंबाई जाँचें।", "अलग लंबाई वाले vectors के raw dot products की तुलना करके सबसे बड़े को 'सबसे similar' कहना।", "यह मान लेना कि ऊँचा cosine मतलब text सही या आपके सवाल से जुड़ा है, जबकि इसका मतलब सिर्फ़ यह है कि embedder ने उन्हें पास रखा।"],
                "hinglish": ["Jab vector mein sab shunya hon to shunya se bhag dena: pehle lambai jaancho.", "Alag lambai wale vectors ke raw dot products ki tulna karke sabse bade ko 'sabse similar' kehna.", "Yeh maan lena ki ooncha cosine matlab text sahi ya aapke sawal se juda hai, jabki iska matlab sirf yeh hai ki embedder ne unhe paas rakha."]},
        },
        "viz": ["vector-arrows"],
        "code": [
            {"title": "Length, dot product and cosine by hand", "language": "python", "runnable": True,
             "code": r'''import math

a = [3, 4]
b = [4, 3]
c = [-4, 3]


def dot(x, y):
    return sum(i * j for i, j in zip(x, y))


def length(x):
    return math.sqrt(dot(x, x))


def cosine(x, y):
    return dot(x, y) / (length(x) * length(y))


print("length of a:", length(a))
print("dot(a, b):", dot(a, b))
print("cosine(a, b):", round(cosine(a, b), 3))
print("cosine(a, c):", round(cosine(a, c), 3))
''',
             "expected_output": "length of a: 5.0\ndot(a, b): 24\ncosine(a, b): 0.96\ncosine(a, c): 0.0",
             "explain": [{"lines": "8-9", "text": "Multiply matching positions and add: [3,4]·[4,3] = 3*4 + 4*3 = 24."}, {"lines": "12-13", "text": "The length is the square root of the vector's dot product with itself."}, {"lines": "16-17", "text": "Cosine divides the dot product by both lengths, so only the direction matters."}, {"lines": "23", "text": "a and c are perpendicular, so their cosine is 0."}]},
            {"title": "Find the nearest meaning", "language": "python", "runnable": True,
             "code": r'''import math

docs = {"cat": [0.9, 0.1], "kitten": [0.8, 0.2], "car": [0.1, 0.9], "truck": [0.2, 0.8]}


def cosine(x, y):
    dot = sum(i * j for i, j in zip(x, y))
    return dot / (math.hypot(*x) * math.hypot(*y))


query = [0.85, 0.15]                        # something cat-like
ranked = sorted(docs, key=lambda name: cosine(query, docs[name]), reverse=True)
for name in ranked:
    print(f"{name:7} {cosine(query, docs[name]):.3f}")
''',
             "expected_output": "cat     0.998\nkitten  0.998\ntruck   0.407\ncar     0.281",
             "explain": [{"lines": "3", "text": "Toy 2-number 'embeddings'. Real ones have hundreds of numbers, but the ranking works the same way."}, {"lines": "12", "text": "Rank every document by similarity to the query: this is vector search."}]}],
        "exercise": {"prompt": "Write cosine(a, b) for two lists of numbers. Print round(cosine([1, 0], [1, 0]), 3) and round(cosine([1, 0], [0, 1]), 3).",
                     "starter": "import math\n\ndef cosine(a, b):\n    # TODO: dot product divided by the two lengths\n    pass\n\nprint(round(cosine([1, 0], [1, 0]), 3))\nprint(round(cosine([1, 0], [0, 1]), 3))\n", "expected_output": "1.0\n0.0",
                     "solution": "import math\n\ndef cosine(a, b):\n    dot = sum(x * y for x, y in zip(a, b))\n    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))\n\nprint(round(cosine([1, 0], [1, 0]), 3))\nprint(round(cosine([1, 0], [0, 1]), 3))\n",
                     "hint": "dot = sum of x*y over zip(a, b); length = sqrt of the sum of squares.",
                     "tests": [{"name": "same direction", "call": "round(cosine([1, 0], [1, 0]), 4)", "expect": "1.0"}, {"name": "perpendicular", "call": "round(cosine([1, 0], [0, 1]), 4)", "expect": "0.0"}, {"name": "scaling does not matter", "call": "round(cosine([1, 2], [2, 4]), 4)", "expect": "1.0", "hidden": True}, {"name": "opposite", "call": "round(cosine([1, 1], [-1, -1]), 4)", "expect": "-1.0", "hidden": True}]},
        "debug": {"prompt": "cosine([1, 0], [2, 0]) should be 1.0 (same direction) but the function returns 2.0. Something is missing.",
                  "starter": "import math\n\ndef cosine(a, b):\n    return sum(x * y for x, y in zip(a, b))\n\nprint(round(cosine([1, 0], [2, 0]), 3))\n", "expected_output": "1.0",
                  "solution": "import math\n\ndef cosine(a, b):\n    dot = sum(x * y for x, y in zip(a, b))\n    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))\n\nprint(round(cosine([1, 0], [2, 0]), 3))\n", "hint": "That is only the dot product. Cosine also divides by the lengths."},
        "assignment": "Invent 2-number vectors for five words (for example food, drinks, sports) and rank them by cosine similarity to a query vector. Check whether the order matches your intuition, then try the Embedding Playground.",
        "quiz": [
            {"id": "vectors-math.q1", "kind": "concept", "q": "What does a cosine similarity of 0 mean?", "options": ["The vectors are identical", "The vectors are perpendicular: unrelated directions", "The vectors point in opposite directions", "One vector is empty"], "answer": 1,
             "why": "1 = same direction, 0 = perpendicular, -1 = opposite.", "why_not": {"0": "Identical direction gives 1.", "2": "Opposite gives -1.", "3": "An empty vector has no direction (and would divide by zero)."}},
            {"id": "vectors-math.q2", "kind": "concept", "q": "Why is cosine similarity popular for text embeddings?", "options": ["It only needs the text length", "It compares direction, so a longer vector with the same direction is still similar", "It is the only formula computers can do", "It ignores the numbers"], "answer": 1,
             "why": "The direction carries the meaning; magnitude is mostly irrelevant noise for comparison.", "why_not": {"0": "It uses all the numbers.", "2": "Other measures exist (dot product, Euclidean distance).", "3": "It uses every number."}},
            {"id": "vectors-math.q3", "kind": "scenario", "q": "Two search results have cosine 0.91 and 0.89. What can you safely say?", "options": ["The first is definitely correct", "The embedder places the first slightly closer to the query; check the text before trusting it", "Both are wrong", "The second is longer"], "answer": 1,
             "why": "Similarity is a ranking signal, not proof of relevance or truth.", "why_not": {"0": "Close is not correct.", "2": "Nothing says they are wrong.", "3": "Length is not what cosine measures."}},
        ],
        "interview_questions": [{"q": "Cosine similarity vs Euclidean distance?", "a": "Cosine compares direction only; Euclidean distance also reflects magnitude. For normalised vectors they give the same ranking. Embedding models are usually trained for cosine or dot product, so I use the metric the model documents."}],
        "sources": [SRC_3B1B, SRC_NUMPY],
    },
    {
        "id": "sql-basics", "category": "prod-arch", "level": "intermediate", "minutes": 22, "prereq": ["python-for-ai"], "next": ["redis-postgres"], "tags": ["sql", "select", "join", "group by", "sqlite", "postgresql", "injection"],
        "title": T("SQL basics: ask questions of a database", "SQL की बुनियाद: database से सवाल पूछना", "SQL ki buniyaad: database se sawal poochna"),
        "summary": "SELECT, WHERE, JOIN and GROUP BY on small tables, and why you must use parameters instead of gluing strings.",
        "objectives": ["Read and write SELECT with WHERE and ORDER BY", "Combine two tables with JOIN", "Summarise with GROUP BY and SUM/COUNT", "Explain SQL injection and how parameters prevent it"],
        "text": {
            "definition": T(
                "SQL is the language for asking questions of a table-based database: which rows, which columns, in what order, summed how. A table is like a spreadsheet; each row is one record.",
                "SQL table वाले database से सवाल पूछने की भाषा है: कौन सी rows, कौन से columns, किस क्रम में, कैसे जोड़कर। Table spreadsheet जैसी है; हर row एक record है।",
                "SQL table wale database se sawal poochne ki bhasha hai: kaun si rows, kaun se columns, kis kram mein, kaise jodkar. Table spreadsheet jaisi hai; har row ek record hai."),
            "analogy": T(
                "Asking a very literal librarian: 'From the books shelf, give me the title and year of every book after 2020, newest first.' SQL reads almost like that sentence.",
                "बहुत शाब्दिक librarian से पूछना: 'किताबों की shelf से 2020 के बाद की हर किताब का नाम और साल, नई पहले दो।' SQL लगभग ऐसा ही वाक्य है।",
                "Bahut shabdik librarian se poochna: 'Kitaabon ki shelf se 2020 ke baad ki har kitaab ka naam aur saal, nayi pehle do.' SQL lagbhag aisa hi vaakya hai."),
            "technical": T(
                "`SELECT name, SUM(amount) FROM orders JOIN customers ON orders.customer_id = customers.id WHERE amount > 0 GROUP BY name ORDER BY 2 DESC`. FROM chooses tables, JOIN connects rows by a key, WHERE filters rows, GROUP BY makes one result per group, aggregates (SUM, COUNT, AVG) summarise each group, ORDER BY sorts. Always pass user values as parameters (`?` in SQLite, `%s` in psycopg) so the driver treats them as data: concatenating user text into SQL allows SQL injection, where input like `' OR '1'='1` changes the query. Indexes speed up lookups on a column; a primary key identifies each row. PostgreSQL and SQLite share this core SQL.",
                "`SELECT name, SUM(amount) FROM orders JOIN customers ON orders.customer_id = customers.id WHERE amount > 0 GROUP BY name ORDER BY 2 DESC`। FROM tables चुनता है, JOIN key से rows जोड़ता है, WHERE rows छाँटता है, GROUP BY हर group का एक नतीजा बनाता है, aggregates (SUM, COUNT, AVG) हर group का सार देते हैं, ORDER BY sort करता है। User के values हमेशा parameters (SQLite में `?`, psycopg में `%s`) से दें ताकि driver उन्हें data माने: SQL में user का text जोड़ने से SQL injection होता है, जहाँ `' OR '1'='1` जैसा input query बदल देता है। Index किसी column पर lookup तेज़ करता है; primary key हर row को पहचानती है। PostgreSQL और SQLite का यह मूल SQL एक जैसा है।",
                "`SELECT name, SUM(amount) FROM orders JOIN customers ON orders.customer_id = customers.id WHERE amount > 0 GROUP BY name ORDER BY 2 DESC`. FROM tables chunta hai, JOIN key se rows jodta hai, WHERE rows chhaantta hai, GROUP BY har group ka ek nateeja banata hai, aggregates (SUM, COUNT, AVG) har group ka saar dete hain, ORDER BY sort karta hai. User ke values hamesha parameters (SQLite mein `?`, psycopg mein `%s`) se do taaki driver unhe data maane: SQL mein user ka text jodne se SQL injection hota hai, jahan `' OR '1'='1` jaisa input query badal deta hai. Index kisi column par lookup tez karta hai; primary key har row ko pehchanti hai. PostgreSQL aur SQLite ka yeh mool SQL ek jaisa hai."),
            "why": T(
                "Most real applications keep their important data in SQL databases: users, documents, conversations, billing. Even AI apps need SQL for metadata, permissions and analytics.",
                "ज़्यादातर असली applications अपना ज़रूरी data SQL databases में रखती हैं: users, documents, conversations, billing। AI apps को भी metadata, permissions और analytics के लिए SQL चाहिए।",
                "Zyadatar asli applications apna zaroori data SQL databases mein rakhti hain: users, documents, conversations, billing. AI apps ko bhi metadata, permissions aur analytics ke liye SQL chahiye."),
            "example": T(
                "'Total spend per customer, biggest first' is one query with JOIN, GROUP BY and ORDER BY. A chat-with-your-data feature turns a user's question into exactly such a query, which must still run read-only and with parameters.",
                "'हर customer का कुल खर्च, सबसे बड़ा पहले' एक query है जिसमें JOIN, GROUP BY और ORDER BY है। Chat-with-your-data feature user के सवाल को ठीक ऐसी query में बदलता है, जो फिर भी read-only और parameters के साथ चलनी चाहिए।",
                "'Har customer ka kul kharcha, sabse bada pehle' ek query hai jisme JOIN, GROUP BY aur ORDER BY hai. Chat-with-your-data feature user ke sawal ko theek aisi query mein badalta hai, jo phir bhi read-only aur parameters ke saath chalni chahiye."),
            "interview": T(
                "I write parameterised queries, use JOIN and GROUP BY for summaries, add indexes for frequent filters, and run schema changes through migrations. Model-generated SQL runs on a read-only connection with a row limit and a timeout.",
                "मैं parameterised queries लिखता हूँ, सार के लिए JOIN और GROUP BY इस्तेमाल करता हूँ, बार-बार के filters के लिए indexes जोड़ता हूँ, और schema बदलाव migrations से करता हूँ। Model से बनी SQL read-only connection पर, row limit और timeout के साथ चलती है।",
                "Main parameterised queries likhta hoon, saar ke liye JOIN aur GROUP BY istemal karta hoon, baar-baar ke filters ke liye indexes jodta hoon, aur schema badlav migrations se karta hoon. Model se bani SQL read-only connection par, row limit aur timeout ke saath chalti hai."),
            "mistakes": {
                "en": ["Building SQL with f-strings and user input (SQL injection).", "Forgetting GROUP BY, so the totals are for the whole table.", "Using SELECT * everywhere, which sends more data than needed and breaks when columns change."],
                "hi": ["f-strings और user input से SQL बनाना (SQL injection)।", "GROUP BY भूल जाना, जिससे कुल पूरी table का आता है।", "हर जगह SELECT * इस्तेमाल करना, जो ज़रूरत से ज़्यादा data भेजता है और columns बदलने पर टूटता है।"],
                "hinglish": ["f-strings aur user input se SQL banana (SQL injection).", "GROUP BY bhool jaana, jisse kul poori table ka aata hai.", "Har jagah SELECT * istemal karna, jo zaroorat se zyada data bhejta hai aur columns badalne par tootta hai."]},
        },
        "viz": ["sql-pipeline"],
        "code": [
            {"title": "JOIN, GROUP BY and ORDER BY", "language": "python", "runnable": True,
             "code": r'''import sqlite3

db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, amount INTEGER);
INSERT INTO customers VALUES (1, 'Asha'), (2, 'Ravi'), (3, 'Meena');
INSERT INTO orders (customer_id, amount) VALUES (1, 100), (1, 200), (2, 50), (3, 70), (3, 30);
""")
rows = db.execute("""
    SELECT c.name, SUM(o.amount) AS total, COUNT(*) AS orders
    FROM orders o JOIN customers c ON o.customer_id = c.id
    WHERE o.amount >= 30
    GROUP BY c.name
    ORDER BY total DESC
""").fetchall()
for name, total, n in rows:
    print(f"{name:6} {total:4} ({n} orders)")
''',
             "expected_output": "Asha    300 (2 orders)\nMeena   100 (2 orders)\nRavi     50 (1 orders)",
             "explain": [{"lines": "4-9", "text": "Two small tables created in memory. sqlite3 is built into Python and uses the same core SQL as PostgreSQL."}, {"lines": "11-12", "text": "JOIN lines up each order with its customer through the key customer_id = id."}, {"lines": "13-15", "text": "WHERE filters rows first, GROUP BY makes one row per customer, ORDER BY sorts the totals."}]},
            {"title": "SQL injection and parameters", "language": "python", "runnable": True,
             "code": r'''import sqlite3

db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE users (name TEXT, secret TEXT)")
db.executemany("INSERT INTO users VALUES (?, ?)", [("asha", "key-1"), ("ravi", "key-2")])

attack = "x' OR '1'='1"                                   # what a malicious user types as their name

unsafe = f"SELECT secret FROM users WHERE name = '{attack}'"      # NEVER build SQL like this
print("glued string :", [r[0] for r in db.execute(unsafe)])

safe = "SELECT secret FROM users WHERE name = ?"                  # the value travels separately
print("parameterised:", [r[0] for r in db.execute(safe, (attack,))])
''',
             "expected_output": "glued string : ['key-1', 'key-2']\nparameterised: []",
             "explain": [{"lines": "9-10", "text": "The glued query becomes `WHERE name = 'x' OR '1'='1'`, which is always true, so every secret leaks."}, {"lines": "12-13", "text": "With a placeholder the whole attack text is only a (non-matching) name. Nothing leaks."}]}],
        "exercise": {"prompt": "A database db with orders(customer, amount) is given. Write total_by_customer(db) that returns a list of (customer, total) pairs sorted by total, biggest first. Print the result.",
                     "starter": "import sqlite3\n\ndb = sqlite3.connect(':memory:')\ndb.execute('CREATE TABLE orders (customer TEXT, amount INTEGER)')\ndb.executemany('INSERT INTO orders VALUES (?, ?)', [('Asha', 100), ('Ravi', 50), ('Asha', 200)])\n\ndef total_by_customer(db):\n    # TODO: one SQL query with SUM, GROUP BY and ORDER BY\n    pass\n\nprint(total_by_customer(db))\n", "expected_output": "[('Asha', 300), ('Ravi', 50)]",
                     "solution": "import sqlite3\n\ndb = sqlite3.connect(':memory:')\ndb.execute('CREATE TABLE orders (customer TEXT, amount INTEGER)')\ndb.executemany('INSERT INTO orders VALUES (?, ?)', [('Asha', 100), ('Ravi', 50), ('Asha', 200)])\n\ndef total_by_customer(db):\n    return db.execute('SELECT customer, SUM(amount) AS total FROM orders GROUP BY customer ORDER BY total DESC').fetchall()\n\nprint(total_by_customer(db))\n",
                     "hint": "SELECT customer, SUM(amount) ... GROUP BY customer ORDER BY the sum DESC, then .fetchall().",
                     "tests": [{"name": "totals, biggest first", "call": "total_by_customer(db)", "expect": "[('Asha', 300), ('Ravi', 50)]"}, {"name": "returns a list of pairs", "call": "type(total_by_customer(db)).__name__", "expect": "'list'", "hidden": True}]},
        "debug": {"prompt": "The report should show the total for EACH customer, but prints one confusing row. A clause is missing.",
                  "starter": "import sqlite3\n\ndb = sqlite3.connect(':memory:')\ndb.execute('CREATE TABLE orders (customer TEXT, amount INTEGER)')\ndb.executemany('INSERT INTO orders VALUES (?, ?)', [('Asha', 100), ('Ravi', 50), ('Asha', 200)])\nprint(db.execute('SELECT customer, SUM(amount) FROM orders ORDER BY customer').fetchall())\n", "expected_output": "[('Asha', 300), ('Ravi', 50)]",
                  "solution": "import sqlite3\n\ndb = sqlite3.connect(':memory:')\ndb.execute('CREATE TABLE orders (customer TEXT, amount INTEGER)')\ndb.executemany('INSERT INTO orders VALUES (?, ?)', [('Asha', 100), ('Ravi', 50), ('Asha', 200)])\nprint(db.execute('SELECT customer, SUM(amount) FROM orders GROUP BY customer ORDER BY customer').fetchall())\n", "hint": "A SUM next to a normal column needs GROUP BY that column."},
        "assignment": "Design two tables for your own project (for example users and conversations). Write three queries: all conversations of one user (with a parameter), the number of conversations per user, and the five newest conversations.",
        "quiz": [
            {"id": "sql-basics.q1", "kind": "concept", "q": "What does GROUP BY do?", "options": ["Sorts the rows", "Makes one result row per distinct value, so aggregates are computed per group", "Deletes duplicates from the table", "Joins two tables"], "answer": 1,
             "why": "GROUP BY collapses rows with the same value into one so SUM, COUNT and AVG work per group.", "why_not": {"0": "ORDER BY sorts.", "2": "It does not change the table.", "3": "JOIN connects tables."}},
            {"id": "sql-basics.q2", "kind": "scenario", "q": "A search box builds `WHERE name = '` + user_input + `'`. A user types `x' OR '1'='1`. What happens?", "options": ["Nothing, it is just text", "The condition becomes always true and every row is returned (SQL injection)", "The database refuses connections", "Only one row matches"], "answer": 1,
             "why": "The input became part of the SQL code. Use parameters so input stays data.", "why_not": {"0": "It changed the query.", "2": "The database happily runs it.", "3": "All rows match."}},
            {"id": "sql-basics.q3", "kind": "concept", "q": "Which clause filters rows BEFORE grouping?", "options": ["WHERE", "ORDER BY", "LIMIT", "SELECT"], "answer": 0,
             "why": "WHERE filters individual rows first; HAVING filters groups afterwards.", "why_not": {"1": "ORDER BY sorts the result.", "2": "LIMIT cuts the number of rows at the end.", "3": "SELECT chooses columns."}},
        ],
        "interview_questions": [{"q": "How do you let a model write SQL safely?", "a": "Give it only the schema it needs, run its SQL on a read-only connection (or role) restricted to specific tables, allow only SELECT, add a row limit and a timeout, never execute stacked statements, log queries, and show the generated SQL to the user."}],
        "sources": [SRC_SQLITE, SRC_PG_TUT],
    },
]
