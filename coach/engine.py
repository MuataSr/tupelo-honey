"""Orchestrator. Pure: takes a State, returns a rendered plan.

`build(state)` never touches a database and never calls a model, so the whole
coach is unit-testable with plain dicts. `plan_for_user` is the thin seam that
pulls a State from the repository for the web layer.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from . import copy, planner, readiness, router, rules


@dataclass
class State:
    user: dict = field(default_factory=dict)
    answers: tuple = ()
    due_review_ids: tuple = ()
    misconceptions: tuple = ()
    sections: tuple = ()
    benchmark_map: dict = field(default_factory=dict)     # (domain, topic) -> code
    benchmark_primary_section: dict = field(default_factory=dict)  # code -> section_id
    now: datetime = None


@dataclass
class RenderedBlock:
    kind: str
    count: int
    text: str
    topic: str = ""


@dataclass
class CoachPlan:
    phase: str
    title: str
    blurb: str
    days_to_exam: int = None
    blocks: tuple = ()
    readiness: float = 0.0
    coverage: float = 0.0
    band: str = ""
    projected_low: int = 0
    projected_high: int = 0
    projected_range_text: str = ""
    pass_line_text: str = ""
    reporting: dict = None
    reading: dict = None
    has_data: bool = False
    focus_domain: int = None      # domain of the weakest topic, for drill links


def _today(now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    return now.date() if isinstance(now, datetime) else now


def days_to_exam(user, now=None):
    """Whole days until the user's exam date, or None when unset/past-date-free."""
    raw = (user or {}).get("exam_date")
    if not raw:
        return None
    if isinstance(raw, datetime):
        target = raw.date()
    elif isinstance(raw, date):
        target = raw
    else:
        try:
            target = date.fromisoformat(str(raw)[:rules.ISO_DATE_LENGTH])
        except ValueError:
            return None
    return (target - _today(now)).days


def benchmark_code_for(state, domain, topic):
    return (state.benchmark_map or {}).get((domain, topic))


def render_blocks(plan):
    out = []
    for b in plan.blocks:
        if b.kind == "review":
            text = copy.review_block(b.count)
        elif b.kind == "new":
            text = copy.new_block(b.count)
        elif b.kind == "timed":
            text = copy.timed_block(b.count)
        else:
            text = b.kind
        out.append(RenderedBlock(b.kind, b.count, text, b.topic))
    return tuple(out)


def build(state):
    """Compose the full coach view for one student. Deterministic."""
    answers = list(state.answers or ())
    rsum = readiness.summarise(answers, state.now)
    dte = days_to_exam(state.user, state.now)
    ph = router.phase(rsum["readiness"], dte, has_data=rsum["has_data"])

    tstats = readiness.topic_stats(answers, state.now)
    plan = planner.build_plan(ph, dte, tuple(state.due_review_ids or ()),
                              tstats, rsum)

    proj = rsum["projection"]
    if rsum["has_data"]:
        range_text = copy.readiness_range(proj.low, proj.high)
    else:
        range_text = copy.readiness_unknown()

    # Reading suggestion: weakest topic first, resolved to a chapter.
    reading = None
    if plan.topics:
        top = plan.topics[0]
        code = benchmark_code_for(state, top.get("domain"), top.get("topic"))
        primary = (state.benchmark_primary_section or {}).get(code)
        sec = router.reading_section(top.get("topic"), list(state.sections or ()), primary)
        if sec:
            mins = router.reading_minutes(sec)
            reading = {
                "section_id": sec.get("id"),
                "title": router.display_title(sec),
                "minutes": mins,
                "topic": top.get("topic", ""),
                "intro": copy.reading_intro(),
                "minutes_text": copy.reading_minutes(max(rules.MIN_READING_MINUTES, mins - rules.READING_MINUTES_SLACK), mins + rules.READING_MINUTES_SLACK) if mins else "",
                "then": copy.reading_then_drill(top.get("topic", ""), _drill_size(top)),
            }
    elif rsum["has_data"] is False:
        reading = None

    focus_domain = plan.topics[0].get("domain") if plan.topics else None
    if reading is not None:
        reading["domain"] = focus_domain
    report = router.benchmark_report(readiness.code_stats(answers, state.now),
                                     _first_domain_with_data(rsum))

    return CoachPlan(
        phase=ph,
        title=copy.phase_title(ph),
        blurb=copy.phase_blurb(ph),
        days_to_exam=dte,
        blocks=render_blocks(plan),
        readiness=rsum["readiness"],
        coverage=rsum["coverage"],
        band=rsum["band"],
        projected_low=proj.low,
        projected_high=proj.high,
        projected_range_text=range_text,
        pass_line_text=copy.readiness_pass_line((state.user or {}).get("target_score")),
        reporting=report,
        reading=reading,
        has_data=rsum["has_data"],
        focus_domain=focus_domain,
    )


def _drill_size(topic_stat):
    """How many questions to drill after the reading. Capped, banded, no magic numbers."""
    attempted = int((topic_stat or {}).get("attempted", 0) or 0)
    return max(rules.READING_DRILL_MIN,
               min(rules.READING_DRILL_MAX, attempted or rules.READING_DRILL_MIN))


def _first_domain_with_data(rsum):
    for d in sorted(rules.DOMAIN_WEIGHTS):
        dr = rsum["per_domain"].get(d)
        if dr is not None and dr.attempted:
            return d
    return None


def plan_for(state):
    """Alias for build(), for readability at call sites."""
    return build(state)


def plan_for_user(user_id, repository, now=None):
    """Web-layer seam. The repository is injected so this module stays pure."""
    state = repository.load_state(user_id, now=now)
    return build(state)
