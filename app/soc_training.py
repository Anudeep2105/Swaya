"""Idempotently seed the SOC analyst preparation course into the LMS."""

import json
import random
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Assignment, Course, InstructorCourse, Lesson, Question, User


CONTENT_PATH = Path(__file__).with_name("soc_training_content.json")
NOTES_PATH = Path(__file__).with_name("soc_basics_notes.md")
COURSE_SLUG = "soc-analyst-interview-prep"


def _lesson_content(item, deep_dive=None):
    """Return learner-facing markdown and a short learning goal for one LMS lesson."""
    kind = item["kind"]
    if kind == "foundation":
        body = []
        if item.get("index") == 0 and NOTES_PATH.is_file():
            body.append(NOTES_PATH.read_text(encoding="utf-8").strip())
        body += ["# Quick concepts", "Short answers for terms that are easy to overlook in an interview."]
        body.extend(f"## {question}\n\n{answer}" for question, answer in item["items"])
        if item.get("deep_dives"):
            body += ["# Interview follow-ups"]
            body.extend(f"## {q[0]}\n\n{q[1]}" for q in item["deep_dives"])
        body += ["# Practice", "Explain each term in your own words, then take the five-question assessment."]
        return "\n\n".join(body), "Review foundational SOC and security interview concepts."

    if kind == "scenario":
        s = item["scenario"]
        body = [
            f"# Simulated case: {s['title']}",
            f"**Case:** {s['id']} · **Level:** {s['level']} · **Difficulty:** {s['difficulty']} · **Category:** {s['category']}",
            "> Training data only. These fictional events are not live telemetry.",
            "## Situation", s["summary"],
            "## Simulated evidence",
            f"- **Source:** {s['source']}\n- **Timestamp (UTC):** {s['time']}\n- **Asset:** {s['asset']}\n- **Identity / actor:** {s['actor']}\n- **Indicator:** {s['indicator']}\n- **Events:** {s['events']}",
            f"## Analyst task\n{s['task']}",
            f"## Hint\n{s['hint']}",
            f"## Model answer\n{s['answer']}",
            f"## Scoring checklist\n" + "\n".join(f"- [ ] {point}" for point in s["checklist"]),
        ]
        if deep_dive:
            body += [f"## Interview practice: {deep_dive[0]}\n\n{deep_dive[1]}"]
        return "\n\n".join(body), f"Triage a simulated {s['category'].lower()} alert using evidence, scope, and safe response steps."

    if kind == "practical":
        p = item["practical"]
        body = [
            f"# Practical drill: {p['title']}",
            f"**Exercise:** {p['id']} · **Level:** {p['level']} · **Difficulty:** {p['difficulty']} · **Estimated time:** {p['minutes']} minutes",
            "> All evidence is simulated training data.",
            f"## Brief\n{p['summary']}",
            f"## Evidence sources\n{p['tools']}",
            f"## Related case\n{p['scenario']['id']} — {p['scenario']['title']}",
            f"## Investigation prompt\n{p['hint']}\n\nWrite a triage note: what is confirmed, what remains unknown, how would you assess scope and impact, and what response or escalation would you recommend?",
            f"## Example approach\n{p['answer']}",
            "## Self-review checklist\n" + "\n".join(f"- [ ] {point}" for point in p["criteria"]),
        ]
        return "\n\n".join(body), "Practice a structured investigation note and safe response recommendation."

    q = item["query"]
    body = [
        f"# SIEM query drill: {q['title']}",
        f"**Exercise:** {q['id']} · **Platform:** {q['platform']} · **Difficulty:** {q['difficulty']}",
        "> These queries use illustrative training tables and are not connected to live telemetry.",
        f"## Objective\n{q['objective']}",
        f"## Reference query ({q['platform']})\n```\n{q['starter']}\n```",
        f"## Analyst hint\n{q['hint']}",
        "## Practice prompt\nExplain how the query supports the objective, which fields you would validate in raw events, and what context is needed before drawing a conclusion.",
    ]
    return "\n\n".join(body), f"Read and adapt a defensive {q['platform']} investigation query."


def _course_lessons(data):
    lessons = []
    quick = data["quickQuestions"]

    for offset in range(0, 100, 10):
        index = offset // 10
        deep = data["questions"][index * 2:index * 2 + 2]
        lessons.append({"kind": "foundation", "index": index, "title": f"Interview essentials: {index + 1:02d}", "items": quick[offset:offset + 10], "deep_dives": deep})

    lessons.extend({"kind": "scenario", "scenario": scenario, "title": f"{scenario['id']}: {scenario['title']}"} for scenario in data["scenarios"])
    lessons.extend({"kind": "practical", "practical": practical, "title": f"{practical['id']}: {practical['title']}"} for practical in data["practicals"])
    lessons.extend({"kind": "query", "query": query, "title": f"{query['id']}: {query['title']}"} for query in data["queryExercises"])
    return lessons


def _quiz_questions(lesson, lesson_number, data):
    if lesson["kind"] == "foundation":
        source = lesson["items"]
    else:
        start = (lesson_number * 5) % len(data["quickQuestions"])
        source = [data["quickQuestions"][(start + i) % len(data["quickQuestions"])] for i in range(5)]

    all_answers = list(dict.fromkeys(row[1] for row in data["quickQuestions"]))
    rng = random.Random(f"soc-course-{lesson_number}")
    result = []
    for question, answer in source[:5]:
        distractors = [choice for choice in all_answers if choice != answer]
        options = rng.sample(distractors, 3) + [answer]
        rng.shuffle(options)
        result.append({"question": question, "options": options, "correct_index": options.index(answer), "explanation": answer, "difficulty": "easy", "topic": lesson["kind"].title()})
    return result


def seed_soc_course(db: Session, generate_lesson_code):
    """Create the published SOC course and missing content without changing existing rows."""
    if not CONTENT_PATH.is_file():
        raise RuntimeError(f"SOC course content file is missing: {CONTENT_PATH}")
    data = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    admin = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
    if not admin:
        raise RuntimeError("Create an LMS admin before seeding the SOC course.")

    course = db.scalar(select(Course).where(Course.slug == COURSE_SLUG))
    if not course:
        course_code = "SOC"
        suffix = 2
        while db.scalar(select(Course.id).where(Course.course_code == course_code)):
            course_code = f"SOC{suffix}"
            suffix += 1
        course = Course(
            course_code=course_code,
            title="SOC Analyst L1/L2 Interview Preparation",
            slug=COURSE_SLUG,
            description="A defensive learning path with 60 simulated incident scenarios, 20 practical drills, 100 quick interview questions, 24 deeper interview answers, and 12 KQL/SPL exercises.",
            status="published",
            created_by=admin.id,
        )
        db.add(course)
        db.flush()
    else:
        course.status = "published"
        course.description = "A defensive learning path with 60 simulated incident scenarios, 20 practical drills, 100 quick interview questions, 24 deeper interview answers, and 12 KQL/SPL exercises."

    instructor_link = db.scalar(select(InstructorCourse).where(InstructorCourse.course_id == course.id, InstructorCourse.user_id == admin.id))
    if not instructor_link:
        db.add(InstructorCourse(course_id=course.id, user_id=admin.id))

    course_lessons = _course_lessons(data)
    for day, item in enumerate(course_lessons, 1):
        lesson = db.scalar(select(Lesson).where(Lesson.course_id == course.id, Lesson.day_number == day))
        if lesson:
            if day == 1 and item["kind"] == "foundation" and NOTES_PATH.is_file() and "# SOC Analyst Basics - Quick Notes" not in lesson.content_md:
                lesson.content_md = NOTES_PATH.read_text(encoding="utf-8").strip() + "\n\n" + lesson.content_md
            continue
        content, goal = _lesson_content(item, data["questions"][day - 11] if item["kind"] == "scenario" and 11 <= day < 35 else None)
        lesson = Lesson(
            course_id=course.id,
            lesson_code=generate_lesson_code(course, item["title"], day, db),
            day_number=day,
            title=item["title"][:200],
            goal=goal,
            content_md=content,
            objectives_json=json.dumps([goal, "Distinguish evidence from assumptions and record safe next steps."]),
            resources_json=json.dumps([{"title": "SOC training note", "url": "#"}]),
            status="published",
            estimated_minutes=15 if item["kind"] == "foundation" else 25,
        )
        db.add(lesson)
        db.flush()

        for prompt in _quiz_questions(item, day, data):
            db.add(Question(
                lesson_id=lesson.id,
                question=prompt["question"],
                options_json=json.dumps(prompt["options"]),
                correct_index=prompt["correct_index"],
                explanation=prompt["explanation"],
                difficulty=prompt["difficulty"],
                topic=prompt["topic"],
                tags_json=json.dumps(["soc", item["kind"]]),
                active=True,
            ))

        if item["kind"] in {"practical", "query"}:
            db.add(Assignment(
                lesson_id=lesson.id,
                title=f"Submit: {item['title'][:150]}",
                description="Submit your investigation notes, query explanation, findings, and safe next steps as a .txt, .md, .csv, or .json file, or include an authorized GitHub URL.",
                submission_type="file_or_github",
                max_score=100,
            ))

    db.commit()
    return course.id

