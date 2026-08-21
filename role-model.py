#!/usr/bin/env python3
"""A mathematical model of the role set: coverage, overlap, coordination cost, and the one
inequality that says which decisions may be delegated and which must reach the founder.

Founder, 2026-08-21: "nodel allpersonas", "nathenatically", "build super srting nodel".

WHAT THIS IS FOR. The role set is currently justified by argument. An argument cannot tell you
whether NINE is the right number, which decisions are safe to delegate, or what it costs when two
roles overlap. Those are arithmetic, and the arithmetic has a surprising result: LAW 11 is not a
rule bolted on for safety, it is what the delegation inequality produces when the loss term goes
to infinity. See DERIVATION 2.

Structure is MEASURED from ~/.claude/agents/roles/*.md. Economics needs three inputs that this
estate has not measured yet -- they are DECLARED, printed as assumptions, and every output that
depends on them is marked. A number this model invents would be worth less than no number.

=== DERIVATION 1: COVERAGE, AND THE FOUNDER'S HAT LOAD ===

Let each role r own the decision set O_r (its DECIDES ALONE bullets) and escalate E_r.

    owned      = |union of O_r|
    escalated  = |union of E_r|
    coverage C = owned / (owned + escalated)

C is the fraction of the named decision surface that does NOT reach the founder. It is the direct
measure of the founder's own words: a role covered is a hat removed. C = 1 would be an unbounded
fleet with no escalation at all, which DERIVATION 2 shows is wrong, so the target is not 1.

If area r produces f_r decisions per week and escalates a fraction p_r of them, the founder's
interrupt rate is

    lambda_F = sum over r of f_r * p_r

which is the number to drive down, not the count of role files.

=== DERIVATION 2: WHEN MAY A DECISION BE DELEGATED? ===

For one decision, with
    q = probability the role decides it correctly
    V = value of that decision being made at all
    L = loss if it is made wrongly and autonomously
    A = cost of the founder's attention when it is escalated

    E[delegate]  = q*V - (1-q)*L
    E[escalate]  = V - A          (the founder is assumed to decide it correctly)

Delegate when E[delegate] > E[escalate]:

    q*V - (1-q)*L  >  V - A
    A  >  (1-q)*(V + L)
    q  >  1 - A/(V + L)          <-- the delegation threshold q*

THREE THINGS FALL OUT OF THIS, AND ALL THREE ARE ALREADY HOUSE RULES:

  (a) As L -> infinity, q* -> 1. No achievable competence justifies delegating an irreversible
      decision, at ANY founder attention cost. That is LAW 11, derived rather than asserted. It
      is also why `legal` and `finance` escalate more than every other role: their loss terms are
      unbounded (an unauthorised-practice exposure, a payment that cannot be clawed back).
  (b) q* falls as A rises. The busier the founder, the MORE should be delegated -- which is the
      founder's own complaint about wearing too many hats, stated as arithmetic.
  (c) q* is independent of how impressive the role sounds. Only correctness, value, loss and
      attention appear. A persona label is not a term in this equation, which agrees with the
      measurement that persona labels buy no accuracy.

=== DERIVATION 3: WHY MORE ROLES IS NOT MONOTONICALLY BETTER ===

n roles have n(n-1)/2 pairwise interfaces. The MAST taxonomy of 150 real multi-agent traces puts
inter-agent misalignment at 32.3% of failures and system design at 44.2%, against 1.5% for
role-disobedience -- so failure mass sits on the interfaces, not inside the roles.

    benefit(n) = V_c * C(n)                 coverage gain, concave: each new role covers less
    cost(n)    = k * n(n-1)/2               coordination, quadratic
    net(n)     = benefit(n) - cost(n)

Concave minus quadratic has a single interior maximum. Adding roles past it makes the system
WORSE, and the failure shows up as two roles each assuming the other had it -- not as a role
behaving badly. This is why the role set names four roles it deliberately has not built.

=== DERIVATION 4: THE CREATIVITY DISCOUNT ===

For the `inventor` role, let N be assessed novelty at ideation and s(N) the probability the option
survives execution. Measured: machine-generated ideas beat expert ideas on novelty at ideation
(p<0.05, 100+ reviewers, arXiv 2409.04109), then after 43 experts spent 100+ hours each executing
them, machine ideas fell further on every metric until the ranking FLIPPED (arXiv 2506.20803).
So s is decreasing in N over the observed range, and

    E[value] = N * s(N)

has an interior maximum: maximum novelty is NOT maximum value. An inventor optimising novelty
alone is optimising the wrong variable, which is why every option it emits carries a feasibility
mark and a killer test.

  python3 ~/.claude/scripts/role-model.py                      # measure the live role set
  python3 ~/.claude/scripts/role-model.py --delegate --value 500 --loss 5000 --attention 300
  python3 ~/.claude/scripts/role-model.py --fleet-curve
  python3 ~/.claude/scripts/role-model.py --selftest
"""
from __future__ import annotations

import argparse
import math
import pathlib
import re
import sys

ROLES_DIR = pathlib.Path.home() / ".claude" / "agents" / "roles"


def _sections(body: str) -> dict[str, str]:
    out, cur, buf = {}, None, []
    for line in body.splitlines():
        m = re.match(r"^#{1,6}\s+([A-Z][A-Z \-/]{2,})\s*$", line.strip())
        if m:
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf = m.group(1).strip(), []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf)
    return out


def _bullets(text: str) -> list[str]:
    return [ln.strip().lstrip("-* ").strip()
            for ln in text.splitlines() if ln.strip().startswith(("-", "*"))]


def _key(bullet: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", bullet.lower())
    return " ".join(sorted(t for t in s.split() if len(t) > 3))


def measure(roles_dir: pathlib.Path) -> dict:
    roles = {}
    for f in sorted(roles_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        body = text.split("\n---", 1)[1] if text.startswith("---") else text
        s = _sections(body)
        roles[f.stem] = {
            "owns": _bullets(s.get("DECIDES ALONE", "")),
            "escalates": _bullets(s.get("ESCALATES", "")),
        }
    owned_keys, esc_keys = set(), set()
    for r in roles.values():
        owned_keys |= {_key(b) for b in r["owns"]}
        esc_keys |= {_key(b) for b in r["escalates"]}
    names = sorted(roles)
    overlaps = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = {_key(x) for x in roles[a]["owns"]} & {_key(x) for x in roles[b]["owns"]}
            if shared:
                overlaps.append((a, b, len(shared)))
    n = len(roles)
    total = len(owned_keys) + len(esc_keys)
    return {
        "roles": roles,
        "n": n,
        "owned": len(owned_keys),
        "escalated": len(esc_keys),
        "coverage": (len(owned_keys) / total) if total else 0.0,
        "overlaps": overlaps,
        "interfaces": n * (n - 1) // 2,
    }


# No measured agent competence approaches this on open-ended judgement, so a threshold above it
# is unreachable rather than merely demanding. Comparing q* against exactly 1.0 is the wrong test:
# a loss of 1e15 gives q* = 0.99999999999999985, which is < 1.0 in floating point and would print
# "delegate if the role is right more than 100% of the time" -- advice no role can act on.
ACHIEVABLE_Q = 0.999


def q_star(value: float, loss: float, attention: float) -> float:
    """The competence a role needs before delegating beats escalating. See DERIVATION 2."""
    if value + loss <= 0:
        return 1.0
    return 1.0 - attention / (value + loss)


def coord_cost(n: int, k: float) -> float:
    """Coordination cost: k per PAIRWISE INTERFACE, not per role. See DERIVATION 3.

    This is the whole content of the model's claim that more roles is not monotonically better,
    so it is a named function with its own test. A cost that is merely linear in n produces an
    interior maximum too -- which is why an interior-maximum test alone grades nothing here."""
    return k * n * (n - 1) / 2.0


def marginal_coord_cost(n: int, k: float) -> float:
    """What the nth role adds: k*(n-1), because it opens an interface to each role already there."""
    return coord_cost(n, k) - coord_cost(n - 1, k)


def net_value(n: int, v_per_role: float, k: float, saturation: float) -> float:
    """Concave coverage benefit minus quadratic coordination cost. See DERIVATION 3."""
    coverage = 1.0 - math.exp(-n / saturation)
    return v_per_role * coverage - coord_cost(n, k)


def best_n(v_per_role: float, k: float, saturation: float, cap: int = 40) -> int:
    return max(range(1, cap + 1), key=lambda n: net_value(n, v_per_role, k, saturation))


def selftest() -> int:
    p = f = 0

    def ck(name, ok):
        nonlocal p, f
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if ok:
            p += 1
        else:
            f += 1

    # DERIVATION 2 -- the three consequences must actually come out of the formula.
    ck("an unbounded loss drives the delegation threshold past what is achievable (LAW 11, derived)",
       q_star(value=100, loss=1e12, attention=1000) >= ACHIEVABLE_Q)
    ck("a threshold of exactly 1.0 is NOT the right test: floating point never reaches it",
       q_star(value=100, loss=1e15, attention=150) < 1.0
       and q_star(value=100, loss=1e15, attention=150) >= ACHIEVABLE_Q)
    ck("a reversible decision with real founder cost has a threshold well under 1",
       q_star(value=100, loss=50, attention=60) < 0.65)
    ck("raising the founder's attention cost LOWERS the bar for delegating",
       q_star(100, 500, 300) < q_star(100, 500, 50))
    ck("raising the loss RAISES the bar for delegating",
       q_star(100, 5000, 300) > q_star(100, 500, 300))
    ck("zero attention cost means never delegate: the threshold is exactly 1",
       q_star(100, 500, 0) == 1.0)
    ck("the threshold never exceeds 1 and is monotone in loss",
       all(q_star(100, L, 200) <= 1.0 for L in (0, 1, 10, 1e6)))

    # DERIVATION 3. The interior-maximum check below is NOT sufficient on its own: a merely
    # LINEAR coordination cost also produces one, and a mutation making the cost linear passed
    # the whole selftest until these two checks were added. The claim is that cost is QUADRATIC,
    # so the test has to grade the quadratic.
    ck("the nth role opens an interface to every role already there: marginal cost is k*(n-1)",
       all(abs(marginal_coord_cost(n, 3.0) - 3.0 * (n - 1)) < 1e-9 for n in range(1, 25)))
    ck("marginal coordination cost STRICTLY INCREASES with n (a linear cost would be flat)",
       all(marginal_coord_cost(n + 1, 3.0) > marginal_coord_cost(n, 3.0) for n in range(1, 25)))
    ck("the benefit side is concave: each added role covers LESS than the one before",
       all((math.exp(-n / 6.0) - math.exp(-(n + 1) / 6.0))
           > (math.exp(-(n + 1) / 6.0) - math.exp(-(n + 2) / 6.0)) for n in range(1, 25)))
    n_best = best_n(v_per_role=1000, k=3.0, saturation=6.0)
    ck("net value has an interior maximum: more roles is not monotonically better",
       1 < n_best < 40)
    ck("a higher coordination cost shrinks the optimal fleet",
       best_n(1000, 12.0, 6.0) < best_n(1000, 1.0, 6.0))
    ck("free coordination pushes the optimum to the cap",
       best_n(1000, 0.0, 6.0) == 40)
    ck("interfaces grow quadratically: 9 roles have 36 pairs",
       9 * 8 // 2 == 36)

    # Structure parsing.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "a.md").write_text("---\nname: a\n---\n\n## DECIDES ALONE\n- set the price\n- pick a lane\n\n## ESCALATES\n- spend money\n")
        (d / "b.md").write_text("---\nname: b\n---\n\n## DECIDES ALONE\n- set the price\n\n## ESCALATES\n- sign a contract\n")
        m = measure(d)
        ck("overlap between two roles is detected and counted", m["overlaps"] and m["overlaps"][0][2] == 1)
        ck("coverage is owned over owned-plus-escalated", abs(m["coverage"] - 2 / 4) < 1e-9)
        (d / "b.md").write_text("---\nname: b\n---\n\n## DECIDES ALONE\n- choose a channel\n\n## ESCALATES\n- sign a contract\n")
        m = measure(d)
        ck("no overlap when decisions differ", m["overlaps"] == [])
        ck("interfaces for 2 roles is 1", m["interfaces"] == 1)

    print(f"\n  {p}/{p + f} checks passed")
    return 0 if f == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Model the role set mathematically.")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--delegate", action="store_true", help="compute the delegation threshold")
    ap.add_argument("--fleet-curve", action="store_true")
    ap.add_argument("--value", type=float, default=None)
    ap.add_argument("--loss", type=float, default=None)
    ap.add_argument("--attention", type=float, default=None)
    ap.add_argument("--dir", default=str(ROLES_DIR))
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    if a.delegate:
        missing = [n for n, v in (("--value", a.value), ("--loss", a.loss),
                                  ("--attention", a.attention)) if v is None]
        if missing:
            print(f"need {' '.join(missing)}. This model will not invent them: the whole point of "
                  f"the threshold is that it is YOUR numbers.", file=sys.stderr)
            return 1
        q = q_star(a.value, a.loss, a.attention)
        print(f"delegation threshold q* = {q:.4f}")
        print(f"  value {a.value:g}, loss {a.loss:g}, founder attention {a.attention:g}")
        if q >= ACHIEVABLE_Q:
            print(f"  q* >= {ACHIEVABLE_Q}: UNREACHABLE. No competence justifies delegating this.")
            print("  Escalate it. This is LAW 11, and it is the arithmetic, not a policy on top.")
        else:
            print(f"  delegate if the role is right more than {q * 100:.2f}% of the time.")
            print(f"  break-even: an autonomous error here costs {(a.value + a.loss):g}; the "
                  f"founder's attention costs {a.attention:g}.")
        return 0

    m = measure(pathlib.Path(a.dir))

    if a.fleet_curve:
        print("n   net value (v_per_role=1000, k=3, saturation=6) -- DECLARED, not measured")
        for n in range(1, 21):
            bar = "#" * max(0, int(net_value(n, 1000, 3.0, 6.0) / 20))
            print(f"{n:>2}  {net_value(n, 1000, 3.0, 6.0):>8.1f}  {bar}")
        print(f"\noptimum at n = {best_n(1000, 3.0, 6.0)} for those declared inputs. "
              f"The live set has {m['n']}.")
        return 0

    print(f"ROLE SET, measured from {a.dir}")
    print(f"  roles                n = {m['n']}")
    print(f"  decisions owned          {m['owned']}")
    print(f"  decisions escalated      {m['escalated']}")
    print(f"  coverage C           {m['coverage']:.3f}   "
          f"(fraction of the named decision surface that does NOT reach the founder)")
    print(f"  pairwise interfaces      {m['interfaces']}   (n(n-1)/2 -- where 32.3% of "
          f"multi-agent failures live)")
    print(f"  overlapping decisions    {len(m['overlaps'])}"
          + ("" if not m["overlaps"] else "   <-- ROLE AMBIGUITY, r=-0.21 on performance"))
    for aa, bb, c in m["overlaps"]:
        print(f"      {aa} <-> {bb}: {c}")
    print()
    print("  per role: owns / escalates")
    for name, r in sorted(m["roles"].items()):
        print(f"      {name:<12} {len(r['owns']):>2} / {len(r['escalates']):>2}")
    print()
    print("  NOT MEASURED, and deliberately not invented: f_r (decisions per week per area),")
    print("  q (per-role correctness), V, L, A. Supply them to --delegate. The prompt ledger")
    print("  at ~/.claude/state/prompt-ledger/ is where f_r and A can be measured from real")
    print("  founder traffic; nothing has been derived from it yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
