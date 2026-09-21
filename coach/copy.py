"""Every student-facing string lives here.

Two standing rules, both enforced by tests:

1. LETTER-FREE. Options are shuffled per session, so a rationale that names a
   letter can point at the wrong option on the student's screen. No string in
   this module may reference an option letter in any form.
2. NO OVERCLAIMING. The readiness model reports a RANGE. Nothing here may state
   or imply that a student will pass.
"""

from . import rules

# --- diagnosis feedback ----------------------------------------------------

HEADLINE = {
    "MASTERED": "Locked in",
    "FRAGILE": "Right answer, shaky footing",
    "MISCONCEPTION": "This one is a trap for you",
    "GAP": "Not covered yet",
    "UNSEEN": "New territory",
}


def headline(state):
    return HEADLINE.get(state, HEADLINE["GAP"])


def confidence_note(state):
    if state == "MISCONCEPTION":
        return ("You were sure about this one, so it is worth fixing now rather "
                "than practising around it.")
    if state == "FRAGILE":
        return "You were unsure, so this needs another pass before it sticks."
    if state == "MASTERED":
        return "You were confident and correct. We will check back on it later."
    return ""


def trap_intro():
    return "What makes this tempting"


def correction_intro():
    return "What is actually true"


def why_still_wrong_intro():
    return "Why your answer does not hold up"


def correct_answer_intro():
    return "The answer, and why"


def fallback_explanation():
    return "Here is the reasoning for this question."


def no_diagnosis_note():
    return "We do not have a specific misconception on file for this one yet."


# --- plan ------------------------------------------------------------------

PHASE_TITLES = {
    "FOUNDATIONS": "Building the foundation",
    "CLEANUP": "Clearing up the near misses",
    "LAST_MILE": "Finishing sharp",
    "TAPER": "Taper",
    "EXAM_EVE": "The night before",
}

PHASE_BLURB = {
    "FOUNDATIONS": ("Accuracy comes first. Expect more new material and slower "
                    "sessions until the basics hold."),
    "CLEANUP": ("You are close. What is left is mostly questions that felt certain "
                "and were not - fixing those is where the remaining points are."),
    "LAST_MILE": ("Time to practise under pressure. Timed sets from here, with "
                  "review on top."),
    "TAPER": ("No new material between now and test day. Review what you already "
              "know so it stays available."),
    "EXAM_EVE": ("Light review only tonight. Sleep is worth more than one more "
                 "question set."),
}


def phase_title(phase):
    return PHASE_TITLES.get(phase, "Your plan")


def phase_blurb(phase):
    return PHASE_BLURB.get(phase, "")


def plan_empty():
    return "Nothing scheduled yet. Answer a few questions and a plan will build itself."


def review_block(n):
    return f"Review {n} question{'s' if n != 1 else ''} you have already seen"


def new_block(n):
    return f"Work through {n} new question{'s' if n != 1 else ''}"


def timed_block(n):
    return f"Sit one timed set of {n}"


# --- readiness -------------------------------------------------------------

def readiness_range(low, high):
    return f"Projected {low}-{high}%"


def readiness_pass_line(target=None):
    if target:
        return f"Your target: {target}%"
    return f"Passing is {rules.PASS_SCORE}%"


def readiness_widening():
    return "Answer more questions and this range gets narrower."


def readiness_unknown():
    return "Not enough answered yet to project a score range."


def benchmark_report_title():
    return "By topic"


def benchmark_report_absent(domain):
    if domain == 4:
        return ("Concepts are tracked one by one rather "
                "than by topic, so this view reports per concept instead.")
    return ""


# --- reading ---------------------------------------------------------------

def reading_intro():
    return "Read this first"


def reading_then_drill(topic, n):
    return f"Then drill {n} on {topic}"


def reading_minutes(lo, hi):
    return f"about {lo}-{hi} min"


def reading_missing():
    return "Read the surrounding chapter when you get a chance."
