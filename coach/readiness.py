"""Readiness estimation - statistics, not prediction.

Two deliberate design choices:

1. **Confidence-weighted accuracy, not raw accuracy.** A correct answer given
   while unsure is worth less than one given confidently, because it is more
   likely to evaporate under exam pressure.
2. **A projected RANGE, never a probability.** We have no calibration study, so
   a single number would be false precision in a product whose credibility
   depends on not overclaiming. The range widens automatically when coverage is
   thin, which is itself honest coaching.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from . import rules


@dataclass
class DomainReadiness:
    domain: int
    attempted: int
    distinct_answered: int
    adjusted_accuracy: float
    coverage: float
    readiness: float


@dataclass
class Projection:
    low: int
    high: int
    mid: float
    margin: float

    @property
    def width(self):
        return self.high - self.low


def credit(confidence, is_correct):
    """Confidence-weighted credit for one answer."""
    if not is_correct:
        return rules.WRONG_CREDIT
    return rules.CORRECT_CREDIT.get(int(confidence), rules.CORRECT_CREDIT[rules.DEFAULT_CONFIDENCE])


def _age_days(answered_at, now):
    if not answered_at:
        return 0.0
    if isinstance(answered_at, str):
        try:
            answered_at = datetime.fromisoformat(answered_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    if answered_at.tzinfo is None:
        answered_at = answered_at.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - answered_at).total_seconds() / float(rules.SECONDS_PER_DAY))


def decay(age_days, halflife=None):
    """Exponential recency weight - a TRUE half-life (this is spec 4.3's recency term).

    exp(-age/hl) decays to 1/e at age=hl, which is not a half-life despite the
    name. Using ln(2) makes the weight actually halve at RECENCY_HALFLIFE_DAYS.
    """
    hl = rules.RECENCY_HALFLIFE_DAYS if halflife is None else halflife
    return math.exp(-math.log(2.0) * age_days / hl)


def domain_readiness(answers, domain, now=None):
    """Decay-weighted accuracy x coverage for one domain.

    accuracy is weighted, not summed, so it stays in 0..1 and old answers fade
    rather than accumulating forever.
    """
    mine = [a for a in answers if int(a.get("domain", 0)) == domain]
    if not mine:
        return DomainReadiness(domain, 0, 0, 0.0, 0.0, 0.0)

    wsum = 0.0
    csum = 0.0
    distinct = set()
    for a in mine:
        w = decay(_age_days(a.get("answered_at"), now))
        wsum += w
        csum += credit(a.get("confidence"), a.get("is_correct")) * w
        if a.get("question_id") is not None:
            distinct.add(a["question_id"])

    adjusted = (csum / wsum) if wsum > 0 else 0.0
    coverage = min(1.0, len(distinct) / float(rules.COVERAGE_TARGET_PER_DOMAIN))
    return DomainReadiness(domain, len(mine), len(distinct), adjusted, coverage,
                           adjusted * coverage)


def overall(per_domain):
    """Domain-weighted readiness. Weights are officially equal (spec 4.3)."""
    total = 0.0
    for d, weights_key in rules.DOMAIN_WEIGHTS.items():
        dr = per_domain.get(d)
        if dr is not None:
            total += weights_key * dr.readiness
    return max(0.0, min(1.0, total))


def overall_coverage(per_domain):
    if not per_domain:
        return 0.0
    return sum(dr.coverage for dr in per_domain.values()) / float(len(rules.DOMAIN_WEIGHTS))


def projected_range(readiness_overall, coverage_overall):
    """Projected score range out of 80.

    The margin grows as coverage falls, so an under-practised student gets an
    honest wide band instead of a confident wrong number.
    """
    mid = readiness_overall * rules.EXAM_TOTAL_ITEMS
    margin = (rules.EXAM_TOTAL_ITEMS * rules.PROJECTION_SPREAD
              * (1.0 - max(0.0, min(1.0, coverage_overall))))
    margin = max(rules.MIN_PROJECTION_MARGIN, margin)
    low = max(0, int(math.floor(mid - margin)))
    high = min(rules.EXAM_TOTAL_ITEMS, int(math.ceil(mid + margin)))
    # Clamping at the ends of the scale can squeeze the band to a single point.
    # Widen it back out so the student never sees "48-48".
    if high - low < rules.MIN_PROJECTION_WIDTH:
        high = min(rules.EXAM_TOTAL_ITEMS, low + rules.MIN_PROJECTION_WIDTH)
        low = max(0, high - rules.MIN_PROJECTION_WIDTH)
    return Projection(low, high, mid, margin)


def band(readiness):
    for upper, label in rules.READINESS_BANDS:
        if readiness < upper:
            return label
    return rules.READINESS_BANDS[-1][1]


def summarise(answers, now=None):
    """Full readiness picture: per domain, overall, coverage, projection, band."""
    per_domain = {d: domain_readiness(answers, d, now) for d in rules.DOMAIN_WEIGHTS}
    ov = overall(per_domain)
    cov = overall_coverage(per_domain)
    proj = projected_range(ov, cov)
    return {
        "per_domain": per_domain,
        "readiness": ov,
        "coverage": cov,
        "projection": proj,
        "band": band(ov),
        "has_data": any(dr.attempted for dr in per_domain.values()),
    }

def _group_stats(pairs, now):
    """Shared weighted-accuracy maths for any grouping key.

    `pairs` is an iterable of (key, answer). Returns a list of stat dicts with
    attempted, adjusted_accuracy, misconception_rate (sure-and-wrong share) and
    coverage (distinct questions against the coverage target).
    """
    buckets = {}
    for key, a in pairs:
        buckets.setdefault(key, []).append(a)
    out = []
    for key, items in buckets.items():
        wsum = csum = 0.0
        distinct = set()
        misconceptions = 0
        for a in items:
            w = decay(_age_days(a.get("answered_at"), now))
            wsum += w
            csum += credit(a.get("confidence"), a.get("is_correct")) * w
            if a.get("question_id") is not None:
                distinct.add(a["question_id"])
            if not a.get("is_correct") and normalise_sure(a.get("confidence")):
                misconceptions += 1
        adjusted = (csum / wsum) if wsum > 0 else 0.0
        out.append({
            "key": key,
            "attempted": len(items),
            "distinct_answered": len(distinct),
            "adjusted_accuracy": adjusted,
            "misconception_rate": (misconceptions / float(len(items))) if items else 0.0,
            "coverage": min(1.0, len(distinct) / float(rules.COVERAGE_TARGET_PER_DOMAIN)),
        })
    return out


def normalise_sure(value):
    """True when the student said they were sure (confidence 3)."""
    try:
        return int(value) == rules.CONFIDENCE_SURE
    except (TypeError, ValueError):
        return False


def topic_stats(answers, now=None):
    """Per (domain, topic) performance, deterministically ordered."""
    stats = _group_stats((( (a.get("domain"), a.get("topic")), a) for a in answers), now)
    for s in stats:
        d, t = s.pop("key")
        s["domain"] = d
        s["topic"] = t
    stats.sort(key=lambda s: (s.get("domain") or 0, s.get("topic") or ""))
    return stats


def code_stats(answers, now=None):
    """Per benchmark code, for the standard-level report (domains 1-3 only)."""
    tagged = [( a.get("benchmark_code"), a) for a in answers if a.get("benchmark_code")]
    stats = _group_stats(tagged, now)
    out = {}
    for s in stats:
        code = s.pop("key")
        out[code] = s
    return out
