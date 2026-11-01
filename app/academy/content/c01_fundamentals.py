from . import T

SRC_ML = {"title": "Google ML Crash Course (introduction to machine learning)", "url": "https://developers.google.com/machine-learning/crash-course"}

LESSONS = [
    {
        "id": "ai-ml-dl", "category": "fundamentals", "level": "beginner", "minutes": 15, "prereq": [], "next": ["what-is-llm"], "tags": ["ai", "machine learning", "deep learning", "neural network"],
        "title": T("AI vs Machine Learning vs Deep Learning", "AI, Machine Learning और Deep Learning में फर्क", "AI, Machine Learning aur Deep Learning mein farak"),
        "summary": "Three nested ideas: AI is the goal, machine learning is learning from examples, deep learning is machine learning with big neural networks.",
        "objectives": ["Explain AI, ML and DL in one sentence each", "Say how a learned rule differs from a hand-written rule", "Name what a model, training and inference are"],
        "text": {
            "definition": T(
                "{{ai|AI}} is the big goal: software that does smart tasks. {{ml|Machine learning}} is one way to reach it: the software learns the pattern from examples. {{dl|Deep learning}} is machine learning that uses large {{neural-network|neural networks}}.",
                "{{ai|AI}} बड़ा लक्ष्य है: ऐसा software जो समझदारी वाले काम करे। {{ml|Machine learning}} उस तक पहुँचने का एक तरीका है: software examples से pattern सीखता है। {{dl|Deep learning}} वो machine learning है जो बड़े {{neural-network|neural networks}} इस्तेमाल करती है।",
                "{{ai|AI}} bada goal hai: aisa software jo smart kaam kare. {{ml|Machine learning}} us tak pahunchne ka ek tareeka hai: software examples se pattern seekhta hai. {{dl|Deep learning}} woh machine learning hai jo bade {{neural-network|neural networks}} use karti hai."),
            "analogy": T(
                "Teaching a child to spot dogs. You can write rules (four legs, tail, barks) - that is classic programming. Or you show 1,000 photos and say 'dog' or 'not dog' - the child works out the rules alone. That is machine learning.",
                "बच्चे को कुत्ता पहचानना सिखाना। आप rules लिख सकते हैं (चार पैर, पूँछ, भौंकता है) - यह पुरानी programming है। या आप 1000 फोटो दिखाकर बताते हैं 'कुत्ता' या 'कुत्ता नहीं' - बच्चा खुद rules निकाल लेता है। यही machine learning है।",
                "Bachche ko dog pehchanna sikhana. Aap rules likh sakte ho (char pair, poonchh, bhaunkta hai) - yeh purani programming hai. Ya aap 1000 photos dikhakar bolte ho 'dog' ya 'not dog' - bachcha khud rules nikaal leta hai. Yahi machine learning hai."),
            "technical": T(
                "A model is a function with many adjustable numbers (parameters). Training shows it labelled examples and nudges the parameters to reduce its mistakes (a loss). After training, inference means using the fixed parameters on new input. Deep learning stacks many layers so the model can learn useful features by itself instead of a human designing them.",
                "Model एक function है जिसमें बहुत सारे बदले जा सकने वाले numbers (parameters) होते हैं। Training में उसे labelled examples दिखाकर parameters को थोड़ा-थोड़ा बदला जाता है ताकि गलतियाँ (loss) कम हों। Training के बाद inference का मतलब है fixed parameters से नए input पर जवाब निकालना। Deep learning में कई layers होती हैं, जिससे model काम की features खुद सीख लेता है।",
                "Model ek function hai jisme bahut saare adjustable numbers (parameters) hote hain. Training mein labelled examples dikhakar parameters ko thoda thoda badalte hain taaki mistakes (loss) kam hon. Training ke baad inference matlab fixed parameters se naye input par answer nikalna. Deep learning mein kai layers hoti hain, jisse model useful features khud seekh leta hai."),
            "why": T(
                "Some problems have no writable rules: what makes an email spam, or a sentence polite? Learning from examples solves them, and the same method works for text, images and sound.",
                "कुछ problems के rules लिखे ही नहीं जा सकते: email spam कैसे बनता है, या कोई वाक्य विनम्र कैसे होता है? Examples से सीखना इन्हें हल करता है, और यही तरीका text, image और sound तीनों में चलता है।",
                "Kuch problems ke rules likhe hi nahi ja sakte: email spam kaise banta hai, ya sentence polite kaise hota hai? Examples se seekhna inhe solve karta hai, aur yahi method text, image aur sound teeno mein chalta hai."),
            "example": T(
                "A bank's fraud detector is not a list of if-statements. It is a model trained on millions of past payments marked 'fraud' or 'fine'. It scores each new payment, and humans review the high scores.",
                "Bank का fraud detector if-statements की list नहीं है। वो लाखों पुराने payments पर train हुआ model है जिन पर 'fraud' या 'ठीक' लिखा था। वो हर नए payment को score देता है और ज़्यादा score वाले को इंसान जाँचते हैं।",
                "Bank ka fraud detector if-statements ki list nahi hai. Woh lakhon purane payments par train hua model hai jin par 'fraud' ya 'fine' likha tha. Woh har naye payment ko score deta hai aur high score walon ko insaan check karte hain."),
            "interview": T(
                "AI is the broad field. Machine learning is the subset where behaviour is learned from data instead of coded. Deep learning is the subset of ML that uses multi-layer neural networks and learns its own features, which is what makes today's language and vision models possible. In practice I separate training, where parameters are fitted, from inference, where they are fixed.",
                "AI broad field है। Machine learning उसका वो हिस्सा है जहाँ behaviour code से नहीं, data से सीखा जाता है। Deep learning, ML का वो हिस्सा है जो multi-layer neural networks इस्तेमाल करता है और features खुद सीखता है; आज के language और vision models इसी से संभव हुए। Practice में मैं training (parameters fit होना) और inference (parameters fixed) को अलग रखता हूँ।",
                "AI broad field hai. Machine learning uska subset hai jahan behaviour code se nahi, data se seekha jaata hai. Deep learning, ML ka subset hai jo multi-layer neural networks use karta hai aur features khud seekhta hai; aaj ke language aur vision models isi se possible hue. Practice mein main training (parameters fit hona) aur inference (parameters fixed) ko alag rakhta hoon."),
            "mistakes": {
                "en": ["Calling every automation 'AI'. A fixed if/else rule is not machine learning.", "Testing a model on the same examples it was trained on, which hides overfitting.", "Believing a bigger model is always better: data quality usually matters more."],
                "hi": ["हर automation को 'AI' कह देना। fixed if/else rule machine learning नहीं है।", "Model को उन्हीं examples पर test करना जिन पर वो train हुआ, इससे overfitting छिप जाती है।", "ऐसा मान लेना कि बड़ा model हमेशा बेहतर है: अक्सर data की quality ज़्यादा मायने रखती है।"],
                "hinglish": ["Har automation ko 'AI' bol dena. Fixed if/else rule machine learning nahi hai.", "Model ko unhi examples par test karna jin par woh train hua, isse overfitting chhup jaati hai.", "Yeh maan lena ki bada model hamesha better hai: aksar data ki quality zyada matter karti hai."]},
        },
        "viz": None,
        "code": [{
            "title": "A rule written by a human vs a rule learned from examples", "language": "python", "runnable": True,
            "code": "# Traditional programming: a human writes the rule.\ndef is_spam_rule(num_links):\n    return num_links > 3\n\n# Machine learning: the program finds the rule from labelled examples.\nexamples = [(0, False), (1, False), (2, False), (5, True), (7, True), (9, True)]  # (links, is_spam)\n\ndef learn_threshold(data):\n    best_t, best_correct = 0, -1\n    for t in range(0, 11):                      # try every candidate rule\n        correct = sum((links > t) == label for links, label in data)\n        if correct > best_correct:              # keep the rule that is right most often\n            best_t, best_correct = t, correct\n    return best_t\n\nt = learn_threshold(examples)\nprint('learned threshold:', t)\nprint('5 links ->', 5 > t)\n",
            "expected_output": "learned threshold: 2\n5 links -> True",
            "explain": [{"lines": "1-3", "text": "A hand-written rule: the programmer decided 'more than 3 links = spam'."}, {"lines": "5-6", "text": "Labelled examples: input (number of links) and the right answer."}, {"lines": "8-14", "text": "'Training': try every threshold and keep the one that classifies the most examples correctly. Real models do the same idea with millions of parameters and smarter search."}, {"lines": "16-18", "text": "'Inference': use the learned threshold on a new input."}]}],
        "exercise": {"prompt": "Complete predict() so it returns True when links is greater than the threshold t. Then print the predictions for [1, 4, 8] with t = 3 as a list.",
                     "starter": "def predict(links, t):\n    # TODO: return True when links is greater than t\n    pass\n\nprint([predict(x, 3) for x in [1, 4, 8]])\n", "expected_output": "[False, True, True]",
                     "solution": "def predict(links, t):\n    return links > t\n\nprint([predict(x, 3) for x in [1, 4, 8]])\n", "hint": "A comparison already gives True or False; you can return it directly."},
        "debug": {"prompt": "This should print the share of correct predictions (0.75), but it crashes. Fix it.",
                  "starter": "preds = [True, False, True, True]\ntruth = [True, False, False, True]\ncorrect = sum(p == t for p, t in zip(preds, truth))\nprint(correct / len(pred))\n", "expected_output": "0.75",
                  "solution": "preds = [True, False, True, True]\ntruth = [True, False, False, True]\ncorrect = sum(p == t for p, t in zip(preds, truth))\nprint(correct / len(preds))\n", "hint": "Read the NameError: which variable name does not exist?"},
        "assignment": "Think of one task in your own work that cannot be solved with fixed rules. Write 5 labelled examples you would need to teach a model that task, and say which of them you would keep aside for testing.",
        "quiz": [
            {"id": "ai-ml-dl.q1", "kind": "concept", "q": "Which statement about the three terms is correct?", "options": ["Deep learning contains AI, which contains machine learning", "Machine learning is a part of AI, and deep learning is a part of machine learning", "They are three unrelated fields", "Machine learning is a part of deep learning"], "answer": 1,
             "why": "AI is the broadest idea; ML is the part where the system learns from data; DL is the part of ML that uses large multi-layer neural networks.",
             "why_not": {"0": "The nesting is reversed: AI is the widest circle.", "2": "They are nested, not separate.", "3": "Deep learning is a kind of machine learning, not the other way round."}},
            {"id": "ai-ml-dl.q2", "kind": "concept", "q": "What is 'inference'?", "options": ["Changing the parameters using labelled examples", "Using the trained, fixed model to answer a new input", "Collecting more data", "Deleting wrong examples"], "answer": 1,
             "why": "Inference is the use phase: parameters stay fixed and the model produces an output for new input.", "why_not": {"0": "That describes training.", "2": "Data collection happens before or around training, it is not inference.", "3": "Cleaning data is data preparation, not inference."}},
            {"id": "ai-ml-dl.q3", "kind": "scenario", "q": "A model scores 99% on its own training examples but 60% on new customers. What is the most likely problem?", "options": ["The model is too small to learn anything", "Overfitting: it memorised the training examples", "The test set is too easy", "Inference is broken"], "answer": 1,
             "why": "A big gap between training and new-data accuracy is the classic sign of overfitting.", "why_not": {"0": "A too-small model would also score badly on training data.", "2": "A harder test set explains a low score but the 99% vs 60% gap points to memorising.", "3": "Inference is just running the model; the gap comes from how it learned."}},
        ],
        "interview_questions": [{"q": "Explain the difference between AI, ML and DL to a non-technical manager.", "a": "AI is the goal of software that behaves intelligently. ML is the method of learning behaviour from examples instead of writing rules. DL is ML with deep neural networks, which is why we now have strong language and image systems. I would add that all of it depends on data quality and honest testing on unseen data."}],
        "sources": [SRC_ML],
        "projects": [],
    },
]
