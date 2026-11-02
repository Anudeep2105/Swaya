"""Question selection and transparent rubric scoring for voice mock interviews."""
import json
import random
import re
from pathlib import Path

_ROOT = Path(__file__).parent
_BANK = json.loads((_ROOT / "mock_interview_bank.json").read_text(encoding="utf-8"))
_SOC_PATH = _ROOT / "soc_training_content.json"
_STOP = set("a an and are as at be been by for from had has have how in into is it its of on or our the their them then there these this to was were what when where which while with would you your".split())


def _clean_terms(text, limit=6):
    words = re.findall(r"[a-z0-9+#.-]+", (text or "").lower())
    return list(dict.fromkeys(word for word in words if len(word) > 3 and word not in _STOP))[:limit]


def _soc_criteria(answer):
    parts = re.split(r"[;.!?]+|\s+\b(?:and|while)\b\s+", answer or "")
    criteria = []
    for part in parts:
        terms = _clean_terms(part, 5)
        if terms:
            criteria.append({"label": part.strip()[:110], "terms": terms, "mode": "all"})
        if len(criteria) == 4:
            break
    if not criteria:
        criteria = [{"label": "Explain the central concept", "terms": _clean_terms(answer, 4), "mode": "any"}]
    return criteria


def _source(source_id):
    return _BANK.get("sources", {}).get(source_id, _BANK.get("sources", {}).get("nist", {}))


def _soc_questions(lesson_title, day_number):
    data = json.loads(_SOC_PATH.read_text(encoding="utf-8"))
    title = lesson_title or ""
    foundation = re.search(r"Interview essentials:\s*(\d+)", title, re.I)
    if foundation:
        index = max(0, int(foundation.group(1)) - 1)
        quick = data.get("quickQuestions", [])[index * 10:(index + 1) * 10]
        deep = data.get("questions", [])[index * 2:(index + 1) * 2]
        result = []
        for number, pair in enumerate(quick, 1):
            prompt, answer = pair[0], pair[1]
            result.append({
                "id": f"soc-foundation-{index + 1:02d}-{number:02d}",
                "topic": "SOC foundations",
                "difficulty": "foundational",
                "prompt": prompt,
                "model_answer": answer,
                "criteria": _soc_criteria(answer),
                "source": _source("nist"),
            })
        for number, entry in enumerate(deep, 1):
            prompt, answer = entry[0], entry[1]
            result.append({
                "id": f"soc-followup-{index + 1:02d}-{number:02d}",
                "topic": entry[2] if len(entry) > 2 else "SOC investigation",
                "difficulty": entry[3] if len(entry) > 3 else "intermediate",
                "prompt": prompt,
                "model_answer": answer,
                "criteria": _soc_criteria(answer),
                "source": _source("mitre"),
            })
        return result

    match = re.search(r"SOC-\d{3}", title, re.I)
    case_id = match.group(0).upper() if match else ""
    for item in data.get("scenarios", []):
        if item.get("id") == case_id:
            answer = item.get("answer", "")
            task = item.get("task", "")
            evidence = item.get("events", "")
            prompts = [
                ("Initial assessment", f"{item.get('title')}: summarize the signal, what it proves, and what remains unknown.", item.get("context", "") + " " + evidence),
                ("Investigation plan", f"What evidence would you collect first for this {item.get('category', 'security')} case, and how would you validate it?", task + " " + evidence),
                ("Scope and impact", "How would you determine the scope and business impact before recommending containment?", answer),
                ("Response decision", "What response or escalation would you recommend, and what evidence would change that decision?", answer),
                ("Analyst handoff", "Give a concise incident handoff: timeline, confirmed facts, open questions, and next owner.", answer + " Preserve the timeline and document the handoff."),
            ]
            return [{
                "id": f"{case_id.lower()}-interview-{n}",
                "topic": item.get("category", "SOC scenario"),
                "difficulty": item.get("difficulty", "intermediate").lower(),
                "prompt": prompt,
                "model_answer": answer,
                "criteria": [{"label": point, "terms": _clean_terms(point, 5), "mode": "any"} for point in item.get("checklist", [])[:4]],
                "source": _source("nist" if item.get("category", "").lower() not in {"siem", "detection engineering"} else "mitre"),
            } for n, (topic, prompt, answer) in enumerate(prompts, 1)]

    for item in data.get("practicals", []):
        if item.get("id", "").upper() == case_id:
            answer = item.get("answer", "")
            prompts = [
                ("Approach", f"Explain your investigation approach for {item.get('title')}.", answer),
                ("Evidence", f"Which evidence sources would you compare in {item.get('title')}, and why?", item.get("tools", "") + " " + answer),
                ("Hypothesis", "State your leading hypothesis and one plausible benign explanation.", item.get("summary", "") + " " + answer),
                ("Safe next step", "What safe next step would you take, and what evidence would you preserve?", answer),
                ("Handoff", "Summarize the result, remaining uncertainty, and recommended escalation.", answer + " Document the timeline and escalation."),
            ]
            return [{
                "id": f"{case_id.lower()}-interview-{n}",
                "topic": "SOC practical",
                "difficulty": item.get("difficulty", "intermediate").lower(),
                "prompt": prompt,
                "model_answer": answer,
                "criteria": [{"label": point, "terms": _clean_terms(point, 5), "mode": "any"} for point in item.get("criteria", [])[:4]],
                "source": _source("nist"),
            } for n, (topic, prompt, answer) in enumerate(prompts, 1)]

    for item in data.get("queryExercises", []):
        if item.get("id", "").upper() == case_id:
            answer = f"{item.get('objective', '')} {item.get('hint', '')} Validate the event fields, time range, and entity context before acting."
            platform = item.get("platform", "")
            source = _source("sentinel" if "kql" in platform.lower() else "splunk")
            prompts = [
                f"What question does this {platform} exercise answer, and what is outside its scope?",
                f"Walk through the query logic and the fields you would validate in raw events.",
                "How would you reduce noise while preserving detections that matter?",
                "What entity context would you correlate before escalating the result?",
                "How would you communicate query limitations and confidence to the next analyst?",
            ]
            return [{
                "id": f"{case_id.lower()}-interview-{n}",
                "topic": platform or "SIEM query",
                "difficulty": item.get("difficulty", "intermediate").lower(),
                "prompt": prompt,
                "model_answer": answer,
                "criteria": [{"label": item.get("objective", "Explain the query objective"), "terms": _clean_terms(item.get("objective", ""), 5), "mode": "any"},
                             {"label": item.get("hint", "Validate the query and its context"), "terms": _clean_terms(item.get("hint", ""), 5), "mode": "any"},
                             {"label": "Validate time range, fields, and entity context", "terms": ["time", "field", "entity", "context"], "mode": "any"}],
                "source": source,
            } for n, prompt in enumerate(prompts, 1)]
    return []


def _data_questions(lesson_title):
    title = (lesson_title or "").lower()
    matches = []
    for domain in _BANK.get("domains", []):
        if any(keyword.lower() in title for keyword in domain.get("lesson_keywords", [])):
            matches.append(domain)
    if not matches:
        matches = [next((d for d in _BANK.get("domains", []) if d.get("id") == "delivery"), _BANK.get("domains", [{}])[0])]
    items = []
    for domain in matches:
        source = _source(domain.get("source"))
        for row in domain.get("questions", []):
            question_id, prompt, model_answer, raw_criteria = row
            items.append({
                "id": question_id,
                "topic": domain.get("id", "course"),
                "difficulty": "intermediate",
                "prompt": prompt,
                "model_answer": model_answer,
                "criteria": [{"label": item[0], "terms": item[1], "mode": "any"} for item in raw_criteria],
                "source": source,
            })
    return items


def questions_for_module(course_title, lesson_title, day_number=0):
    if "soc" in (course_title or "").lower():
        questions = _soc_questions(lesson_title, day_number)
    else:
        questions = _data_questions(lesson_title)
    if not questions:
        return []
    random.SystemRandom().shuffle(questions)
    return questions[:5]


def public_question(question):
    source = question.get("source", {})
    return {
        "id": question["id"],
        "topic": question.get("topic", "interview"),
        "difficulty": question.get("difficulty", "intermediate"),
        "prompt": question["prompt"],
        "source_title": source.get("title", "Swaya practice bank"),
        "source_url": source.get("url", ""),
    }


def score_answers(questions, answers):
    answer_map = {entry["question_id"]: (entry.get("answer") or "").strip() for entry in answers}
    reports = []
    strengths = []
    improvements = []
    total = 0
    available = 0
    for question in questions:
        answer = answer_map.get(question["id"], "")
        text = " " + re.sub(r"[^a-z0-9+#.-]+", " ", answer.lower()).strip() + " "
        met, missing = [], []
        for criterion in question.get("criteria", []):
            terms = [term.lower().strip() for term in criterion.get("terms", []) if term]
            found = [term for term in terms if f" {term} " in text or term in text]
            covered = bool(found) if criterion.get("mode") != "all" else bool(terms) and len(found) == len(terms)
            label = criterion.get("label", "Key concept")
            (met if covered else missing).append(label)
        count = len(met)
        possible = len(met) + len(missing)
        score = round(100 * count / possible) if possible else (35 if len(answer.split()) >= 15 else 0)
        if len(answer.split()) < 8:
            score = min(score, 35)
            if answer:
                missing.append("Add a little more detail and explain your reasoning.")
        total += score
        available += 1
        strengths.extend(met)
        improvements.extend(missing)
        source = question.get("source", {})
        reports.append({
            "question_id": question["id"],
            "topic": question.get("topic", "interview"),
            "prompt": question["prompt"],
            "answer": answer,
            "score": score,
            "covered_points": met,
            "improvement_points": missing,
            "model_answer": question.get("model_answer", ""),
            "source_title": source.get("title", "Swaya practice bank"),
            "source_url": source.get("url", ""),
        })
    score = round(total / available) if available else 0
    def top_items(items):
        counts = {}
        for item in items:
            counts[item] = counts.get(item, 0) + 1
        return [item for item, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]]
    return {
        "score": score,
        "summary": "Strong coverage of the expected points." if score >= 80 else ("You have a useful base; focus on the missing points below." if score >= 55 else "Use the model answers as a study guide, then retry this module."),
        "strengths": top_items(strengths),
        "improvements": top_items(improvements),
        "questions": reports,
        "scoring_note": "Practice rubric coverage, not a hiring decision. Feedback is generated from the published checklist; no AI evaluator or audio recording is used.",
    }
