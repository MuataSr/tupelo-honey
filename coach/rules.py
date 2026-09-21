"""Every threshold in the Study Coach lives here and nowhere else.

Acceptance criterion (spec 6.15): a grep assertion finds no numeric literal
thresholds in the other modules. If you need a new number, it belongs here.
"""

# --- exam model ------------------------------------------------------------
EXAM_TOTAL_ITEMS = 100
PASS_SCORE = 60

DOMAIN_LABELS = {
    1: "Reading",
    2: "Math",
    3: "Science",
    4: "English & Language",
}

# Officially equal, not assumed. FLDOE's TEAS/HESI Sample Items (State of Florida,
# Dept. of State, 2022) states the four outcomes are "represented in the same
# proportion on the sample test as on the actual test (approximately 25% each)".
DOMAIN_WEIGHTS = {1: 0.25, 2: 0.25, 3: 0.25, 4: 0.25}

# --- confidence model ------------------------------------------------------
CONFIDENCE_UNSURE = 1
CONFIDENCE_KINDA = 2
CONFIDENCE_SURE = 3
DEFAULT_CONFIDENCE = CONFIDENCE_UNSURE   # unknown/absent degrades here, never raises
VALID_CONFIDENCE = (CONFIDENCE_UNSURE, CONFIDENCE_KINDA, CONFIDENCE_SURE)

CORRECT_CREDIT = {
    CONFIDENCE_SURE: 1.0,
    CONFIDENCE_KINDA: 0.8,
    CONFIDENCE_UNSURE: 0.5,
}
WRONG_CREDIT = 0.0

# --- readiness -------------------------------------------------------------
COVERAGE_TARGET_PER_DOMAIN = 40
RECENCY_HALFLIFE_DAYS = 14.0
PROJECTION_SPREAD = 0.10
MIN_PROJECTION_MARGIN = 1.0   # never report a zero-width range like '48-48'
MIN_PROJECTION_WIDTH = 2      # ... and never a one-point band either

# (upper bound inclusive, label), evaluated in order
READINESS_BANDS = (
    (0.45, "Not yet ready"),
    (0.60, "Borderline"),
    (0.75, "Likely ready"),
    (1.01, "Ready - protect it with timed sets"),
)

# --- phases ----------------------------------------------------------------
PHASE_EXAM_EVE = "EXAM_EVE"
PHASE_TAPER = "TAPER"
PHASE_FOUNDATIONS = "FOUNDATIONS"
PHASE_CLEANUP = "CLEANUP"
PHASE_LAST_MILE = "LAST_MILE"

DAYS_EXAM_EVE = 1
DAYS_TAPER = 3
FOUNDATIONS_BELOW = 0.45
LAST_MILE_ABOVE = 0.65

# --- plan composition ------------------------------------------------------
REVIEW_CAP = 20
NEW_CAP = 15
TIMED_SET_SIZE = 10
TAPER_TIMED_FRACTION = 2      # taper gets a half-length timed set
MAX_NEW_TOPICS = 3            # how many topics one session's new material spans
MIN_NEW_WHEN_SHARING = 1      # any non-taper session touches at least one new question

# days_to_exam strictly ABOVE the bound -> that share of new material
NEW_MATERIAL_SHARE = (
    (21, 0.50),
    (7, 0.30),
    (3, 0.15),
)
NEW_MATERIAL_SHARE_TAPER = 0.0

# --- spaced repetition (SM-2 style; the review_queue already stores these) --
SRS_FIRST_INTERVAL_DAYS = 1
SRS_CORRECT_FACTOR = 2.0
SRS_WRONG_FACTOR = 0.5
SRS_START_EASE = 2.5
SRS_MIN_EASE = 1.3
SRS_MAX_INTERVAL_DAYS = 180
MISCONCEPTION_RETEST_DAYS = 1
SECONDS_PER_QUESTION_BUDGET = 60

# --- misconception matching ------------------------------------------------
MISCONCEPTION_TOKEN_MIN = 2
READING_TOKEN_MIN = 1          # one distinctive word in a chapter title is a real match
MISCONCEPTION_PRIORITY_WEIGHT = 1.0   # how hard confident errors jump the queue

# --- benchmark report ------------------------------------------------------
# Domain 4's topic taxonomy is one topic per landmark case, and the only
# case-law benchmark code is SS.7.CG.3.11, so 17 of 24 D4 topics collapse onto
# it. Reporting that code to a student says nothing useful, so the report is
# suppressed for D4 and reports at the case/topic level instead.
BENCHMARK_REPORT_DOMAINS = (1, 2, 3)

# --- reading router --------------------------------------------------------
# The stored content rows carry harvest artifacts (trailing '*', NBSPs). They are
# normalised at RENDER time and the rows are never mutated.
SECTION_TITLE_TRAILING_ARTIFACTS = ("*",)
NON_BREAKING_SPACE = "\u00a0"

# A section larger than this is not a section. The content harvest appended the whole
# back matter of the book to the last section of the last chapter: section 77 is
# 367,972 characters (median section is 21,748) and contains the appendices - the
# Declaration of Independence, the Constitution, the Bill of Rights, Federalist No. 10 -
# plus every chapter's references and the book index. That makes it "relevant" to 27 of
# the 36 standards, which is how it became the top reading link for a dozen unrelated
# codes. It is not teachable and must never be offered as a reading target.
MAX_READING_SECTION_CHARS = 60000

# `content` rows that are reference apparatus, not reading. The book's back matter was
# bundled into one oversized row and has been split out into its own rows; these three
# must never be offered as a reading assignment. Matched on the whole normalised title.
NON_SECTION_TITLES = ("answer key", "references", "index")

MIN_READING_MINUTES = 1
MAX_READING_MINUTES = 60
READING_MINUTES_SLACK = 2
READING_DRILL_MIN = 5
READING_DRILL_MAX = 10
READING_CHARS_PER_MINUTE = 1200
SECONDS_PER_DAY = 86400
ISO_DATE_LENGTH = 10   # 'YYYY-MM-DD' prefix of an ISO timestamp
