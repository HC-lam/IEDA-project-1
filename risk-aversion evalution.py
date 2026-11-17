import math
from statistics import mean

# ---------------------------------------------------------------------------
# Category weights
# ---------------------------------------------------------------------------

WEIGHTS = {
    "ce":      0.20,   # Q1-Q6   gamble / certainty-equivalent
    "gamma":   0.35,   # Q7-Q10  allocation & behaviour
    "likert":  0.45,   # Q11-Q15 attitudinal
}

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def crra_u(x, gamma):
    if x <= 0:
        raise ValueError("x must be > 0")
    if abs(gamma - 1.0) < 1e-12:
        return math.log(x)
    return (x ** (1.0 - gamma)) / (1.0 - gamma)


def gamma_from_ce(high, low, prob, ce):
    """Solve u(ce) = p*u(high) + (1-p)*u(low) for CRRA gamma."""
    if not (0 < low < high):
        raise ValueError("Require 0 < low < high")
    if not (0 < prob < 1):
        raise ValueError("Require 0 < prob < 1")

    EV = prob * high + (1.0 - prob) * low
    if ce >= high:
        return -2.0
    if ce <= low:
        return 12.0
    if abs(ce - EV) < 1e-9:
        return 0.0

    def excess(g):
        eu = prob * crra_u(high, g) + (1.0 - prob) * crra_u(low, g)
        return crra_u(ce, g) - eu

    lo, hi = -2.0, 12.0
    d_lo, d_hi = excess(lo), excess(hi)
    if d_lo * d_hi >= 0.0:
        # Root outside the bracket: clamp by CE-vs-EV direction.
        # CE > EV  -> risk-seeking need  -> deepest risk-seeking clamp (-2)
        # CE < EV  -> risk-averse need   -> deepest risk-averse clamp  (+12)
        return -2.0 if ce > EV else 12.0
    for _ in range(300):
        mid = 0.5 * (lo + hi)
        if excess(mid) > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Questionnaire
# Each option: (value, display_text)
#   kind == ce     -> value is the certainty-equivalent amount
#   kind == gamma or likert -> value is the calibrated gamma
# ---------------------------------------------------------------------------

QUESTIONS = [
    # ================= Block 1: CE gambles (Q1-Q6), weight 0.20 =============
    {"id": "Q1", "kind": "ce",
     "text": "A venture pays a gain of 10,000 dollars with 50 percent probability and a gain of 1,000 dollars with 50 percent probability. What fixed amount would you take instead?",
     "high": 10_000.0, "low": 1_000.0, "prob": 0.5,
     "options": [
        (2_500.0, "1. 2,500 dollars"),
        (4_000.0, "2. 4,000 dollars"),
        (5_500.0, "3. 5,500 dollars"),
        (7_000.0, "4. 7,000 dollars"),
        (8_500.0, "5. 8,500 dollars"),
     ]},

    {"id": "Q2", "kind": "ce",
     "text": "A new job pays a performance bonus of 12,000 dollars with 70 percent probability and 3,000 dollars with 30 percent probability. What guaranteed bonus would you accept instead?",
     "high": 12_000.0, "low": 3_000.0, "prob": 0.7,
     "options": [
        (5_000.0,  "1. 5,000 dollars"),
        (7_000.0,  "2. 7,000 dollars"),
        (9_300.0,  "3. 9,300 dollars"),
        (11_000.0, "4. 11,000 dollars"),
        (13_000.0, "5. 13,000 dollars"),
     ]},

    {"id": "Q3", "kind": "ce",
     "text": "You list a property for sale. You can accept a firm offer of a fixed amount now, or wait for an auction where it will sell for 25,000 dollars with 40 percent probability and 9,000 dollars with 60 percent probability. What fixed offer would you accept now?",
     "high": 25_000.0, "low": 9_000.0, "prob": 0.4,
     "options": [
        (10_000.0, "1. 10,000 dollars"),
        (13_000.0, "2. 13,000 dollars"),
        (15_400.0, "3. 15,400 dollars"),
        (18_000.0, "4. 18,000 dollars"),
        (21_000.0, "5. 21,000 dollars"),
     ]},

    {"id": "Q4", "kind": "ce",
     "text": "A draw ticket wins 40,000 dollars with 20 percent probability and 2,000 dollars with 80 percent probability. What fixed amount would you sell the ticket for?",
     "high": 40_000.0, "low": 2_000.0, "prob": 0.2,
     "options": [
        (5_000.0,  "1. 5,000 dollars"),
        (7_500.0,  "2. 7,500 dollars"),
        (9_600.0,  "3. 9,600 dollars"),
        (12_000.0, "4. 12,000 dollars"),
        (15_000.0, "5. 15,000 dollars"),
     ]},

    {"id": "Q5", "kind": "ce",
     "text": "An investment returns 50,000 dollars with 60 percent probability and 5,000 dollars with 40 percent probability. What fixed payout would you accept instead?",
     "high": 50_000.0, "low": 5_000.0, "prob": 0.6,
     "options": [
        (18_000.0, "1. 18,000 dollars"),
        (25_000.0, "2. 25,000 dollars"),
        (32_000.0, "3. 32,000 dollars"),
        (38_000.0, "4. 38,000 dollars"),
        (44_000.0, "5. 44,000 dollars"),
     ]},

    {"id": "Q6", "kind": "ce",
     "text": "A friendly wager pays 3,000 dollars with 50 percent probability and 500 dollars with 50 percent probability. What fixed amount would you take instead?",
     "high": 3_000.0, "low": 500.0, "prob": 0.5,
     "options": [
        (800.0,   "1. 800 dollars"),
        (1_300.0, "2. 1,300 dollars"),
        (1_750.0, "3. 1,750 dollars"),
        (2_200.0, "4. 2,200 dollars"),
        (2_700.0, "5. 2,700 dollars"),
     ]},

    # ============ Block 2: allocation & behaviour (Q7-Q10), weight 0.35 ====
    {"id": "Q7", "kind": "gamma",
     "text": "You have a lump sum to invest for 10 years. Which portfolio do you prefer?",
     "options": [
        (6.0, "1. 100 percent cash or guaranteed instruments"),
        (3.5, "2. 70 percent bonds, 30 percent stocks"),
        (2.0, "3. 50 percent bonds, 50 percent stocks"),
        (1.0, "4. 30 percent bonds, 70 percent stocks"),
        (0.4, "5. 100 percent stocks"),
     ]},

    {"id": "Q8", "kind": "gamma",
     "text": "Your portfolio of 100,000 dollars fell 20 percent in one quarter. What would you do?",
     "options": [
        (5.0, "1. Sell everything and move to cash"),
        (3.5, "2. Sell half and move to safer assets"),
        (2.0, "3. Do nothing and hold"),
        (1.0, "4. Buy more"),
        (0.3, "5. Add aggressively"),
     ]},

    {"id": "Q9", "kind": "gamma",
     "text": "How long do you plan to keep this money invested?",
     "options": [
        (5.0, "1. Under 1 year"),
        (3.5, "2. 1 to 3 years"),
        (2.0, "3. 3 to 7 years"),
        (1.2, "4. 7 to 15 years"),
        (0.5, "5. Over 15 years"),
     ]},

    {"id": "Q10", "kind": "gamma",
     "text": "What share of your savings would you put into risky assets such as stocks?",
     "options": [
        (5.5, "1. None"),
        (4.0, "2. Up to 25 percent"),
        (2.5, "3. Up to 50 percent"),
        (1.2, "4. Up to 75 percent"),
        (0.4, "5. Close to 100 percent"),
     ]},

    # ============== Block 3: attitude Likert (Q11-Q15), weight 0.45 ========
    # NOTE: Likert raw values are centred at neutral (subtract 3.0) when scored.
    {"id": "Q11", "kind": "likert",
     "text": "I prefer guaranteed returns over higher possible returns, even if that means lower long-term growth.",
     "options": [
        (5.0, "1. Strongly agree"),
        (4.0, "2. Agree"),
        (3.0, "3. Neutral"),
        (2.0, "4. Disagree"),
        (1.0, "5. Strongly disagree"),
     ]},

    {"id": "Q12", "kind": "likert",
     "text": "Short-term market volatility does not worry me when I am compensated with higher long-term returns.",
     "options": [
        (1.0, "1. Strongly agree"),
        (2.0, "2. Agree"),
        (3.0, "3. Neutral"),
        (4.0, "4. Disagree"),
        (5.0, "5. Strongly disagree"),
     ]},

    {"id": "Q13", "kind": "likert",
     "text": "I would feel very anxious if my portfolio lost 10 percent in a single month.",
     "options": [
        (5.0, "1. Strongly agree"),
        (4.0, "2. Agree"),
        (3.0, "3. Neutral"),
        (2.0, "4. Disagree"),
        (1.0, "5. Strongly disagree"),
     ]},

    {"id": "Q14", "kind": "likert",
     "text": "I understand stocks, bonds and market risk well enough to tolerate price swings.",
     "options": [
        (1.0, "1. Strongly agree"),
        (2.0, "2. Agree"),
        (3.0, "3. Neutral"),
        (4.0, "4. Disagree"),
        (5.0, "5. Strongly disagree"),
     ]},

    {"id": "Q15", "kind": "likert",
     "text": "I would rather have a stable, predictable income than a chance to become rich.",
     "options": [
        (5.0, "1. Strongly agree"),
        (4.0, "2. Agree"),
        (3.0, "3. Neutral"),
        (2.0, "4. Disagree"),
        (1.0, "5. Strongly disagree"),
     ]},
]

# ---------------------------------------------------------------------------
# Safe input
# ---------------------------------------------------------------------------

def safe_input(prompt):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def ask_one(q, index, total):
    print("\n" + "-" * 64)
    print(f"Question {index} of {total}")
    print("-" * 64)
    print(q["text"])
    for _val, label in q["options"]:
        print("   " + label)

    n = len(q["options"])
    while True:
        raw = safe_input(f"\nYour answer from 1 to {n}: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= n:
            return q["options"][int(raw) - 1][0]
        print(f"   Invalid input. Please type a number from 1 to {n}.")


# ---------------------------------------------------------------------------
# Scoring: weighted average of category means
# ---------------------------------------------------------------------------

def per_question_gamma(q, value):
    if q["kind"] == "ce":
        return gamma_from_ce(q["high"], q["low"], q["prob"], value)
    if q["kind"] == "likert":
        # Centre at neutral so risk-tolerant answers give negative gamma.
        return float(value) - 3.0
    return float(value)


def assess(answers):
    """Weighted category means -> final gamma."""
    by_kind = {"ce": [], "gamma": [], "likert": []}
    for q in QUESTIONS:
        g = per_question_gamma(q, answers[q["id"]])
        by_kind[q["kind"]].append(g)

    category_means = {
        "ce":     mean(by_kind["ce"])     if by_kind["ce"]     else 0.0,
        "gamma":  mean(by_kind["gamma"])  if by_kind["gamma"]  else 0.0,
        "likert": mean(by_kind["likert"]) if by_kind["likert"] else 0.0,
    }

    total_w = sum(WEIGHTS.values())
    gamma = sum(WEIGHTS[k] * category_means[k] for k in WEIGHTS) / total_w
    return gamma


def classify(gamma):
    """Practical 3-way bands (exact-zero is unreachable on a 15-item mean)."""
    if gamma < 0.5:
        return "RISK-TAKE"
    if gamma <= 2.0:
        return "RISK-NEUTRAL"
    return "RISK-AVERSE"


# ---------------------------------------------------------------------------
# Allocation plans by risk level
# ---------------------------------------------------------------------------

ALLOCATION_PLANS = {
    "RISK-AVERSE": {
        "label": "Risk-averse investor",
        "plans": [
            ("All markets", {"risk-free asset (e.g. cash)": 50, "commodity": 30, "stock": 20}),
        ],
        "max_stock_hold": 3,
        "stop_loss": -10.0,
        "take_profit": 20.0,
    },
    "RISK-NEUTRAL": {
        "label": "Risk-neutral investor",
        "plans": [
            ("Bull market", {"stock": 70, "commodity": 10, "risk-free asset": 20}),
            ("Bear market", {"stock": 60, "commodity": 20, "risk-free asset": 20}),
        ],
        "max_stock_hold": 5,
        "stop_loss": -10.0,
        "take_profit": 50.0,
    },
    "RISK-TAKE": {
        "label": "Risk-taking investor",
        "plans": [
            ("Bull market", {"stock": 90, "commodity": 0, "risk-free asset": 10}),
            ("Bear market", {"stock": 75, "commodity": 15, "risk-free asset": 10}),
        ],
        "max_stock_hold": 15,
        "stop_loss": -15.0,
        "take_profit": 75.0,
    },
}


def print_allocation(label):
    """Print the recommended portfolio plan for the classified risk level."""
    plan = ALLOCATION_PLANS.get(label)
    print("\n" + "=" * 64)
    print("RECOMMENDED INVESTMENT ALLOCATION")
    print("=" * 64)
    if plan is None:
        print("   No allocation plan defined for this level.")
        print("=" * 64)
        return
    print(f"Investor type        : {plan['label']}")
    for tag, alloc in plan["plans"]:
        parts = ", ".join(f"{name} {pct}%" for name, pct in alloc.items())
        print(f"   {tag:13s}: {parts}")
    print(f"   Max stock holdings      : {plan['max_stock_hold']}")
    print(f"   Stop-loss / take-profit : {plan['stop_loss']:.0f}% / +{plan['take_profit']:.0f}%")
    print("=" * 64)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 64)
    print("RISK AVERSION ASSESSMENT - 15 questions")
    print("=" * 64)
    print("Answer each question by typing 1, 2, 3, 4 or 5, then Enter.")

    answers = {}
    for i, q in enumerate(QUESTIONS, start=1):
        answers[q["id"]] = ask_one(q, i, len(QUESTIONS))

    gamma = assess(answers)
    label = classify(gamma)

    print("\n" + "=" * 64)
    print("YOUR RESULT")
    print("=" * 64)
    print(f"Risk-aversion coefficient gamma : {gamma:+.3f}")
    print(f"Investor risk level             : {label}")
    print("=" * 64)

    print_allocation(label)


if __name__ == "__main__":
    main()
