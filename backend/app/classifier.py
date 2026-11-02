"""Explainable, deterministic classification using genuine NSE description + summary.

This is explicitly *metadata-level* analysis, not an AI reading of attached PDFs.
The rules prioritise concrete event language above generic filing categories.
"""
import re

CATEGORIES = (
    "results", "M&A", "fund_raise", "management_change", "litigation",
    "insider_trading", "earnings_call", "investor_meetings", "credit_rating",
    "dividend", "bonus_split", "capex", "press_release", "postal_ballot",
    "agm_egm", "pledging", "unclassified",
)

# Order matters: category for a specific event must outrank a broad document label.
CATEGORY_PATTERNS = [
    ("pledging", r"\b(?:pledge|pledging|encumbrance|invocation of shares)\b"),
    ("credit_rating", r"\b(?:credit rating|rating action|rating upgrade|rating downgrade|rating reaffirm)\b"),
    ("litigation", r"\b(?:litigation|lawsuit|legal proceeding|insolvency|regulatory order|penalty|fine|show cause notice|fraud|sebi order|search and seizure)\b"),
    ("management_change", r"\b(?:change in management|change in directors|director appointment|resignation|resigned|appointed as (?:ceo|cfo|md)|chief executive officer|chief financial officer|managing director|key managerial personnel|kmp|smp)\b"),
    ("M&A", r"\b(?:acquisition|merger|demerger|amalgamation|joint venture|acquire|divestment|sale of stake|disposal of subsidiary)\b"),
    ("fund_raise", r"\b(?:fund rais|fundrais|qip|qualified institutional placement|rights issue|preferential allotment|buyback|commercial paper|non.convertible debenture|ncd|issuance of debt)\b"),
    ("bonus_split", r"\b(?:bonus issue|bonus shares|stock split|sub.division of shares)\b"),
    ("capex", r"\b(?:capital expenditure|capex|capacity expansion|new manufacturing facility|greenfield plant|commissioning of plant)\b"),
    ("results", r"\b(?:financial results|quarterly results|annual results|unaudited financial statements|audited financial statements|financial performance|outcome of board meeting approving (?:financial )?results)\b"),
    ("dividend", r"\b(?:dividend|record date for dividend)\b"),
    ("insider_trading", r"\b(?:insider trading|promoter shareholding transaction|disclosure under regulation 7\(2\)|purchase of equity shares by promoter)\b"),
    ("earnings_call", r"\b(?:earnings call|conference call|investor call|concall|transcript|audio recording of.*call)\b"),
    ("investor_meetings", r"\b(?:investor meet|analyst meet|institutional investor|investor conference|schedule of meet)\b"),
    ("postal_ballot", r"\b(?:postal ballot|e.voting)\b"),
    ("agm_egm", r"\b(?:annual general meeting|extraordinary general meeting|\bagm\b|\begm\b|shareholders meeting)\b"),
    ("press_release", r"\b(?:press release|order win|contract award|new product|partnership|general update|general announcement)\b"),
]

BASE = {
    "results": 65, "M&A": 72, "fund_raise": 58,
    "management_change": 61, "litigation": 68, "insider_trading": 28,
    "earnings_call": 38, "investor_meetings": 17, "credit_rating": 63,
    "dividend": 34, "bonus_split": 46, "capex": 60,
    "press_release": 25, "postal_ballot": 14, "agm_egm": 16,
    "pledging": 65, "unclassified": 12,
}

WHY = {
    "results": "Reported financial performance can change the view of profitability and growth; review the actual figures in the filing.",
    "M&A": "Acquisitions and disposals may change business exposure, capital allocation and integration risk.",
    "fund_raise": "Financing actions may affect leverage, dilution and funding capacity.",
    "management_change": "Senior leadership changes may affect strategy, execution and governance.",
    "litigation": "Legal or regulatory developments may create financial or operating exposure; assess size and status in the filing.",
    "insider_trading": "Promoter/insider transactions can affect ownership structure, but don't establish future price direction.",
    "earnings_call": "Management commentary may offer useful context for performance and guidance.",
    "investor_meetings": "Usually a scheduling disclosure; investigate only if new material information was shared.",
    "credit_rating": "Ratings can affect borrowing terms and financial risk; check whether the rating changed.",
    "dividend": "Dividends affect shareholder cash returns and key eligibility dates.",
    "bonus_split": "Changes share counts and reference prices without automatically creating economic value.",
    "capex": "New investment can affect capacity, future cash needs and returns on capital.",
    "press_release": "Assess whether the update contains a financially meaningful operating development.",
    "postal_ballot": "Usually a procedural notice; the underlying proposal determines relevance.",
    "agm_egm": "Meeting logistics are generally routine; resolutions may contain material decisions.",
    "pledging": "Changes in promoter share pledges can affect collateral and governance risk.",
    "unclassified": "No clearly material event identified from the exchange-provided summary; open the original filing if needed.",
}

# Hard routine override must run on title / first meaningful wording; avoid swallowing true results.
ROUTINE = r"(?:trading window closure|closure of trading window|compliance certificate|certificate under regulation|shareholding pattern|reconciliation of share capital|copy of newspaper publication|newspaper advertisement|investor meeting schedule|schedule of (?:analyst|institutional investor) meet|transcript availability|link of recording|esop allotment|allotment of shares under.*esop|disclosure under regulation 74\(5\)|scrutinizer.?s report)"

# Material signals are matched against exchange text, NEVER inferred from price activity.
CRITICAL = [
    (r"\b(?:ceo|cfo|chief executive officer|chief financial officer|managing director|md)\b.{0,70}\b(?:resigns?|resigned|resignation|steps? down|removed|termination)\b|\b(?:resignation|resigned)\b.{0,70}\b(?:ceo|cfo|chief executive officer|chief financial officer|managing director)\b", 25, "Senior executive departure"),
    (r"\b(?:downgraded|rating downgrade|rating withdrawn)\b", 27, "Credit rating downgrade/withdrawal"),
    (r"\b(?:insolvency|bankruptcy|fraud|sebi ban|regulatory penalty|search and seizure)\b", 25, "Potentially serious legal or regulatory event"),
    (r"\b(?:merger approved|acquisition completed|definitive agreement|sale of subsidiary)\b", 18, "Concluded strategic transaction"),
    (r"\b(?:pledge invoked|invocation of pledge)\b", 21, "Promoter pledge invocation"),
]

CONTEXT = [
    (r"\b(?:signed (?:an )?agreement|major order|large order|order worth|new plant|capacity expansion approved)\b", 14, "Specific operating/strategic development"),
    (r"\b(?:quarterly financial results|audited financial results|unaudited financial results|results for the quarter)\b", 12, "Actual financial-results disclosure"),
    (r"\b(?:rating upgraded|upgraded to)\b", 15, "Credit rating upgrade"),
]

DOWNGRADE = [
    (r"\b(?:intimation|notice|schedule)\b.{0,40}\b(?:board meeting|results meeting)\b|\bboard meeting intimation\b", 32, "Upcoming meeting notice, not results"),
    (r"\b(?:rating reaffirmed|reaffirmation|reaffirmed)\b", 22, "Rating reaffirmed, not changed"),
    (r"\b(?:investor presentation|investor meet|schedule of meet|link of recording|transcript available)\b", 16, "Informational/scheduling item"),
    (r"\b(?:appointment of (?:an? )?(?:independent|non.executive) director|auditor appointment)\b", 22, "Non-executive / routine appointment"),
]


def evaluate(subject: str, details: str) -> dict:
    subject = (subject or "").strip()
    details = (details or "").strip()
    content = f"{subject}. {details}".lower()
    category = next((category for category, pat in CATEGORY_PATTERNS
                     if re.search(pat, content, re.IGNORECASE)), "unclassified")
    score = BASE[category]
    reasons = [f"{category} category"]
    components = [{"source": "metadata", "reason": f"{category} category base", "points": BASE[category]}]
    critical = []
    # Critical signals must override routine category penalties when truly present.
    for pattern, delta, label in CRITICAL:
        if re.search(pattern, content, re.I):
            score += delta
            critical.append(label)
            reasons.append(label)
            components.append({"source": "metadata", "reason": label, "points": delta})
    for pattern, delta, label in CONTEXT:
        if re.search(pattern, content, re.I):
            score += delta
            reasons.append(label)
            components.append({"source": "metadata", "reason": label, "points": delta})
    for pattern, delta, label in DOWNGRADE:
        if re.search(pattern, content, re.I):
            score -= delta
            reasons.append(label)
            components.append({"source": "metadata", "reason": label, "points": -delta})
    if re.search(ROUTINE, content, re.I) and not critical:
        if score > 22:
            components.append({"source": "metadata", "reason": "Routine procedural cap", "points": 22-score})
            score = 22
        reasons.append("Routine procedural disclosure")
    unclamped = score
    score = max(0, min(100, score))
    if unclamped != score:
        components.append({"source": "metadata", "reason": "Bounded to 0–100", "points": score-unclamped})
    priority = "high" if score >= 70 else ("review" if score >= 40 else "routine")
    # This is intentionally a conservative extract from *NSE's summary*, not the PDF.
    what = (details or subject or "No exchange summary supplied.").strip()
    what = " ".join(what.split())
    if len(what) > 360:
        what = what[:357].rstrip() + "..."
    return {"category": category,"score": score,"priority": priority,
            "what_happened": what,"why_it_matters": WHY[category],
            "priority_reason": "; ".join(reasons),
            "score_components": components,
            "evidence_scope": "NSE announcement subject and description only; attachment not analysed"}
