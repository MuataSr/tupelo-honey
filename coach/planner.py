"""Build today's plan.

Deterministic composition only - no sampling, no randomness. The same inputs
always produce the same plan (acceptance criterion 6.3).
"""

from dataclasses import dataclass

from . import rules


@dataclass
class Block:
    kind: str                 # review | new | timed
    count: int
    topic: str = ""
    question_ids: tuple = ()


@dataclass
class Plan:
    phase: str
    days_to_exam: int = None
    review_count: int = 0
    new_count: int = 0
    timed_count: int = 0
    new_share: float = 0.0
    blocks: tuple = ()
    topics: tuple = ()

    @property
    def total(self):
        return self.review_count + self.new_count + self.timed_count


def new_material_share(days_to_exam):
    """Share of the session spent on unseen material, by proximity to test day.

    A student testing in two days gets zero new material - cramming new content
    that late displaces material they already hold.
    """
    if days_to_exam is None:
        return rules.NEW_MATERIAL_SHARE[1][1]        # no date set: mid default
    if days_to_exam <= rules.DAYS_TAPER:
        return rules.NEW_MATERIAL_SHARE_TAPER
    for upper, share in rules.NEW_MATERIAL_SHARE:
        if days_to_exam > upper:
            return share
    return rules.NEW_MATERIAL_SHARE_TAPER


def topic_priority(stats):
    """Lower is more urgent. Confident errors outrank mere weakness.

    Weakness = how far accuracy falls short. A high misconception rate SUBTRACTS
    from that number so sure-and-wrong topics sort to the top - they are the
    errors that survive into the exam.
    """
    weakness = 1.0 - stats.get("adjusted_accuracy", 0.0)
    misconception_penalty = (stats.get("misconception_rate", 0.0)
                             * rules.MISCONCEPTION_PRIORITY_WEIGHT)
    coverage_gap = (1.0 - stats.get("coverage", 0.0)) * rules.PROJECTION_SPREAD
    return weakness - misconception_penalty + coverage_gap


def pick_weakest(topic_stats, limit):
    """Deterministically ordered weakest topics with at least one attempt."""
    candidates = [s for s in topic_stats if s.get("attempted", 0) > 0]
    candidates.sort(key=lambda s: (topic_priority(s), s.get("domain") or 0,
                                   s.get("topic") or ""))
    return tuple(candidates[:limit])


def spread(count, buckets):
    """Deterministically spread `count` items across `buckets`, front-loaded."""
    if buckets <= 0 or count <= 0:
        return []
    base, remainder = divmod(count, buckets)
    return [base + (1 if i < remainder else 0) for i in range(buckets)]


def build_plan(phase, days_to_exam, due_review_ids, topic_stats, readiness=None):
    """Compose the day's blocks.

    TAPER and EXAM_EVE carry zero new material (acceptance criterion 6.14).
    """
    review_ids = tuple(tuple(due_review_ids)[:rules.REVIEW_CAP])
    share = new_material_share(days_to_exam)
    tapered = phase in (rules.PHASE_TAPER, rules.PHASE_EXAM_EVE)

    # --- new material ------------------------------------------------------
    if tapered or share <= 0:
        new_count, picked = 0, ()
    else:
        budget = rules.REVIEW_CAP + rules.NEW_CAP
        new_count = min(rules.NEW_CAP, int(round(budget * share)))
        new_count = max(rules.MIN_NEW_WHEN_SHARING, new_count)
        picked = pick_weakest(topic_stats, min(rules.MAX_NEW_TOPICS, new_count))
        if not picked:
            new_count = 0

    counts = spread(new_count, len(picked)) if picked else []

    # --- timed -------------------------------------------------------------
    if phase == rules.PHASE_LAST_MILE:
        timed = rules.TIMED_SET_SIZE
    elif phase == rules.PHASE_TAPER:
        timed = max(1, rules.TIMED_SET_SIZE // rules.TAPER_TIMED_FRACTION)
    else:
        timed = 0

    # --- assemble ----------------------------------------------------------
    blocks = []
    if review_ids:
        blocks.append(Block("review", len(review_ids), question_ids=review_ids))
    for stats_row, n in zip(picked, counts):
        if n:
            blocks.append(Block("new", n, topic=stats_row.get("topic", "")))
    if timed:
        blocks.append(Block("timed", timed))

    return Plan(phase=phase, days_to_exam=days_to_exam,
                review_count=len(review_ids), new_count=sum(counts),
                timed_count=timed, new_share=share,
                blocks=tuple(blocks), topics=tuple(picked))
