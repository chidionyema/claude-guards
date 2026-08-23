# The incidents behind the laws

This file is the EVIDENCE, not the rules. `~/.claude/CLAUDE.md` states the laws; this file records
what each one cost and the founder's own words at the time, spelling untouched, because a verbatim
record is the only kind worth keeping.

**No session is ever given this file automatically.** Read it when you want to know why a law says
what it says, or when you are about to argue with one.

---

## LAW 1 — PUT THE FIRE OUT FIRST

**What the founder said**

Founder directive 2026-08-20: "we are working on preventing reocuurence fair enough, but the fire
has not been put out. its like desigining a preventing prootcol whole the houuse is burning. the
first thing is to put the fire out. you keep repeating this nistake , over 100 tines past days".

**Worked example — the one that produced this law.** 2026-08-20, 30 hours into a pipeline outage: 10
pull requests open, 9 red for reasons that were not their own, 0 merged. In that window I wrote a
workflow and 37 tests for it, 10 more tests for a revert-repair step, a deploy-map drift test that I
mutation-proved and then deleted as a duplicate, and 2 memory files. Every one of them was good
work. None of them merged a pull request. The founder's words when he saw the same page for the
third time: "i ont see any sigin of pregress".

**The class is: substituting work I can finish alone for the work that was asked.** Restoring service
depends on a CI run, on a robot, on another session, on capacity — none of which I control, and any
of which can end a turn with nothing to show. A guard, a test or a memory file always completes
inside the turn. Under an unordered LAW 6 that substitution was also rewarded.

---

## LAW 2 — PROOF BEFORE ACTION

**What the founder said**

Founder directive 2026-08-19: "you need proof before action", "which engineer guesses when data is
everywhere", "this should never happen even once".

**Worked example — the one that produced this law.** 2026-08-19, 26 pull requests open and nothing
landing. I printed a table showing `python=F` on twelve of them, read "F" as congestion, and cloned
six Fly machines into `prospector-ci` to add CI capacity. The founder: "most of the prs are failed,
capacity is not the fucking issue". He was right, and my own table already said so — `F` is FAILED,
not QUEUED. **I never opened a single failing job log.** One command
(`gh api repos/OWNER/REPO/actions/jobs/<id>/logs`) then gave the real answer in seconds: seven of
those jobs fail on the SAME assertion, `assert re.search(r"\./run\.sh \|\| true", body)` — one red
test on main that every branch inherits. The fix was already open as PR #425. The queue was never
the problem, and the six machines were bought to solve a problem that did not exist.

**The class is: acting on the SHAPE of the evidence instead of its CONTENT.** A count, a colour, a
status letter, a green tick — these are pointers to the data, never the data.

---

## LAW 3 — NEVER MAKE THE SAME MISTAKE TWICE

**What the founder said**

Founder directive 2026-08-20: "dont nake the sane nsitake is also a law". Founder directive
2026-08-18: "An incident closes when a memory file names the trap and, where the failure can recur
mechanically, a test fails if it does."

**Worked example — the one that produced this law.** 2026-08-20, one session, three times: I read a
failing job log, saw precisely what was missing, wrote it, and then found it already existed.
Parked-run approval (already on branch `ci/pipeline-failure-ledger`, with a safety condition mine
lacked); a `scripts/pr_triage.py` console registration (already on main at
`prospector/ops/console_api.py:3432`); a test comparing automerge's deploy map to each deploy
workflow (already covered in both directions, plus four checks mine lacked). All three were written,
and two were mutation-proved, before I ran a single lookup. Detail: memory
`a-failing-log-names-the-fix-not-the-gap.md`.

**The class is: reading the SPECIFICITY of an error as a complete diagnosis.** The more exactly a log
names the missing thing, the more strongly it invites you to write that thing instead of find it.

---

## LAW 4 — THINK IT THROUGH BEFORE YOU TOUCH IT

**What the founder said**

Founder directive 2026-08-19: "critial thiking, edge case nnapping before work, 2nd and 3rd order
effects accounted for and addressed".

**Worked example — the one that produced this law.** 2026-08-19. The founder said the CI fleet of 18
Fly machines was too big. I picked a target of six because six sounded right, then read the runner
list before applying it: five runners were BUSY at that moment, with jobs queued behind them.
Trimming to six would have destroyed live capacity mid-job. The second-order effect was the worse
one: a job whose runner disappears fails with "the self-hosted runner lost communication with the
server", uploads no log, and is indistinguishable from a failing test — the exact confusion that had
already cost the estate a day. The third-order effect was that every agent working those PRs would
have re-diagnosed the same phantom test failure. Reading the busy list before choosing the number
changed the answer from six to nine, and made the cut provably free: nine of the machines had no
GitHub registration at all, so they could not receive a job and destroying them lost nothing.

**The class is: choosing the ACTION before understanding its consequences.** LAW 1 stops you acting
on a guess about the cause. LAW 2 stops you acting on a guess about the effect.

---

## LAW 5 — UNBLOCK YOURSELF

**What the founder said**

Founder directive 2026-08-20: "ou can do this urself aother law should be unblock urself",
"autonony".

**Worked example — the one that produced this law.** 2026-08-20: I ended a turn with "founder
action: set an API key as a secret on one of the hosted apps". He replied "ou can do this urself".
He was right. The key was already in the local env file and already on the app that checks it. One
piped command copied it across, staged, and it never read the value into my own process. The
provider's own secret listing then showed the same digest on both apps, which proves the values
match without printing either. Staged rather than set, so no machine restarted and the key arrives
with the deploy that needs it. Two earlier attempts were denied by the classifier because they
read the value into my process first. That was the filter working. The answer was a command that
never holds the value, not a cleverer way to read it.

**The class is: treating a request for help as free.** It is the most expensive thing an agent
does, because it stops the founder.

---

## LAW 6 — ROOT CAUSE, AND THE CLASS OF MISTAKE

**What the founder said**

Founder directive 2026-08-19: "our rules root cause and classes of mistakes needs to headline
claude.md file". It is the law that CLOSES an incident, and since 2026-08-20 it is explicitly the last step of
one: it fires when LAW 1 is satisfied and the thing works again, never while it is still down.

**Worked example — the one that produced this law.** 2026-08-19: 22 pull requests open, nothing
merging, every agent grinding the same ground. The chain: no PR had auto-merge enabled → native
auto-merge cannot be enabled here at all (`403 Upgrade to GitHub Pro` on both
`/branches/main/protection` and `/rulesets`) → `.github/workflows/automerge.yml` is the substitute
and only merges a CI run that CONCLUDES green → `.github/workflows/ci.yml` sets
`cancel-in-progress` for every ref that is not main → so every agent push killed the in-flight run
that was about to merge another agent's work. Measured: 7 of the last 60 CI runs succeeded, 16
were cancelled. The class is **an agent action that silently destroys another agent's in-flight
work**. It was closed with a guard, not a note: `~/.claude/scripts/push-pr-fence.py` now refuses a
push while that branch's CI is live.

**Both facts in that chain are now FALSE on disk, and the chain is kept only as the incident.**
Measured 2026-08-21 on `origin/main`: `ci.yml:123`-`:125` sets `cancel-in-progress: false`, for every ref
including pull request branches, and `automerge.yml` no longer exists — it was deleted in #522 and
merges are done by hand (`gh pr merge <n> --merge`). A push no longer destroys another session's
in-flight run. Read the file before repeating either claim; a worked example is a record of what
happened, never a description of what is true now.

---

## LAW 7 — REFRESH ON MAIN BEFORE YOU ASK FOR REVIEW

**What the founder said**

Founder directive 2026-08-20: "you need to refresh ur stale branches with latest nain", "before
pr", "this should be a low", "law".

**Worked example — the one that produced this law.** 2026-08-20. Four branches sat in a scratchpad,
stale against main by 1, 1, 5 and 6 commits. The pre-commit gate reported five failures on one of
them. Three of the five were in a test file that main had DELETED days earlier; the branch was
still carrying it, so the gate was grading code no longer in the estate. One more was pure drift in
the same shape. Exactly one of the five was mine. Merging main first would have left one failure
and one thing to read, instead of five and a false trail.

**The class is: grading work against a world that no longer exists.** A guess about the cause is
LAW 2. A guess about the effect is LAW 4. This is a guess about the BASELINE, and it is the
cheapest of the three to remove — one fetch and one merge, before the push.

---

## LAW 8 — FIX THE TRAP WHERE YOU FOUND IT

**What the founder said**

Founder directive 2026-08-20: "dont leave traps for other to fall, address root cause instantly and
get back to ur nain job".

**Worked example — the one that produced this law.** 2026-08-20. A peer messaged me that a rules
file was telling every session something false about a commit gate: that its linter graded the
whole tree, when it graded only the staged files. It also cited the wrong line. The effect of the
false version is that anyone whose commit is refused goes looking for somebody else's untidy file
instead of reading their own diff. My first instinct was to record the correction and carry on. The
founder's words: "dont leave traps for other to fall". Fixing it at the SOURCE meant three memory
files that every future session recalls, not the one document that happened to name it — and
following that same thread one step further found this file's own injector returning nothing, so no
session had been given ANY law since a table was added above LAW 1. A note about the linter would
have left that sitting underneath it, unfound.

**The class is: treating a discovery as information rather than as work.** The cost of finding a
defect is already sunk the moment you see it. The only question left is whether one agent pays for
the fix or every agent pays for the trap.

---

## LAW 9 — STAY ON THE JOB

**What the founder said**

Founder directive 2026-08-20: "dont go down rabbit holes either", "get back to ur nain job", "track
you workload very carefully".

**Worked example — the one that produced this law.** 2026-08-20. The job was a live founder
complaint about a documentation page. On the way to it I wrote a benchmark harness with a hardcoded
`sys.argv`, rewrote it, then had the rewrite put `/tmp` on `sys.path` so the "before" case measured
an import crash and reported an impossible −481% improvement, then watched the third attempt time
out at two minutes — at which point the real answer arrived: the laptop was at load average 282,
and no wall-clock number from it was ever going to be trustworthy. Three attempts at a number the
box could not give. `-X importtime` ratios answered the actual question in one command, and had
been available the whole time.

**The class is: pursuing a sub-problem past the point where it still serves the job.** Every step
was individually reasonable, which is what makes it invisible from the inside. The only reliable
tell is that the named job has not moved.

---

## LAW 10 — TALK TO YOUR PEERS, AND COORDINATE WHEN IT MATTERS

**What the founder said**

Founder directive 2026-08-20: "talk to ur peers and coordiate when necesary should be law".

Founder directive 2026-08-20, later the same day: "ok the peer nessages are not workigit is too
noisy, we need to turn it downn" — and then, when the first answer was silence: **"its tyoo nnot but
useful wwith the downside it keeps everyone loppingevrt he sane issues"**. That second sentence is
the diagnosis and it is not about volume. **The channel is USEFUL and stays open. What is banned is
the REPEAT.**

**Worked example — the one that produced this law.** 2026-08-20. A peer lost an hour on a live
founder-reported outage because one test went red, and the test it named was the commit gate —
the last failure any agent will wave through. The cause was mine: an uncommitted edit to a file
shared by every working tree, so it failed in EVERY tree at once, on EVERY diff, whatever the
diff was. They sent me the `file:line` and the single command that decides it. In the same
exchange I had a wedge they were about to hit, from a signing key regenerated that afternoon,
which no diff could satisfy. Neither session could have found the other's defect from inside its
own window, and both had been staring at the symptom for an hour.

**The class is: treating a discovery as private.** LAW 8 says fix the trap where you found it.
This law says the fix is not finished while the only agent who knows is you.

---

## LAW 11 — NEVER DECIDE ALONE WHAT YOU CANNOT UNDO ALONE

**What the founder said**

Founder directive 2026-08-20: "never ake critical decios in a slio broadcast to peers and get
feedback and edge cases not considered that adds risk".

**Worked example — the one that produced this law.** 2026-08-20. A session was about to run an
estate-wide cleanup: snapshot and remove every dirty worktree, and delete 340 of 342 remote
branches. It had done the work properly — every branch tip parented onto one archive commit,
confirmed on origin by `ls-remote` before any delete. Then it broadcast the plan and said "reply
and I will hold".

That broadcast is the whole example. It let me hand back an edge case it could not have seen:
the orphaned-worktree list it was about to work from grades trees by resolving their gitdir
against the MAIN checkout only, and this estate has two clones. Every worktree owned by the
iCloud clone reads as orphaned whether or not anyone is in it — and the list named
`wt-storeroot`, which was a live session's working directory at that moment, with a session in
it. Nothing inside that session's window showed either fact. It took one message.

**The class is: confusing a careful decision with a checked one.** Care is what you apply to the
risks you have thought of. It does nothing at all about the ones you have not, and those are the
ones that are irreversible by the time they are visible.

---

## LAW 12 — A RISK TO THE PIPELINE IS ROOTED OUT, NOT NARRATED

**What the founder said**

Founder directive 2026-08-20: "any riskes to pipeline nust be rooked out right away rather than
arrated", "cant leave this unaddresed, lets root it out now", "add as law".

**Worked example — the one that produced this law.** 2026-08-20. Two of the founder's own guards
deadlocked. `~/.claude/PR_FREEZE` allowed exactly one head, `integrate/2026-08-20-final`, and
`push-pr-fence.py` refuses a push to a branch that is on origin with nothing open on it. That
branch sat at `633ead53`, an ancestor of `origin/main`, so GitHub answered "No commits between main
and integrate/2026-08-20-final" and nothing could be opened on it. No push without a review, no
review without commits, no commits without a push. Zero were open, so no session in the estate
could ship anything at all. Each guard was behaving exactly as written and the deadlock was in the
pair. A peer then supplied the fact that made it a class rather than an incident: automerge merges
and LEAVES THE REF, so every branch takes that shape the moment it lands — once per merge cycle,
not once per firefight.

**The class is: mistaking an accurate description of a blockage for having dealt with it.**

---

## LAW 13 — HOLD THE PLATFORM AND THE STACK AT THE SAME TIME

**What the founder said**

Founder directive 2026-08-20: "you ned to tack low level and high levlel sinulataneously, add as
law", "platforn and stack".

**Worked example — the one that produced this law.** 2026-08-20. I spent a long stretch measuring
signing keys: 78 files, 23 distinct keys, one that verifies, digests compared, a temp tree built to
prove which key signed the tracked receipts. Good work, correctly measured, and it found a real
source defect — the shared checkout's own key could not sign, so every worktree it seeded was
born broken. All of it was the STACK view.

The PLATFORM view, the whole time: the engine on Fly had been moat blind for 19.6 hours, 75
finished PASSes were stranded off the shelf, every brain was down, and 13 critical alerts had
fired into a file nobody read. I did not find that. A peer did, and only because they happened to
run something else first. Nothing in my window would ever have shown it, because I never asked.

**The class is: mistaking depth for coverage.** Depth feels like rigour and produces receipts, so
it is the easiest possible thing to be wrong inside. The platform question is one command and it
is the one that says whether the depth was aimed at the right place.

---

## LAW 14 — TAKE THE PERFORMANCE AND COST WIN WHEN YOU FIND ONE

**What the founder said**

Founder directive 2026-08-20: "we should also be optinigin for perfonace and cost when we cone
across an opprotunity to add as fouder law", "doing over narrating is favoured".

**Worked example — the one that produced this law.** 2026-08-20. E-101 asked whether a verifier we
own could replace the paid model call, because availability was 0% and the free route was the only
one that did not need money. It cost $12 on a rented 16-core box and the answer was no: the best
free model separated a cited passage from an unrelated one at 0.706 AUC, and one arm scored 0.408,
below random. Stage B would have spent another $50 and 55 hours on two models that, even if they
had won, would have run at 25 seconds a pair on rented CPU forever. The founder stopped it. The
box and its 60 GB volume were destroyed the same turn, after the results were pulled and verified.
What the $12 actually bought was three cost cuts that need no hardware at all: six model calls per
candidate where one would do; 21.84% of checks refetching a URL already on disk, measured across
7,774 checks; and the cheapest brain being a subscription already paid for, sitting idle for 20
hours behind a login nobody had done.

**The class is: treating money as somebody else's axis.** Correctness, speed and cost are one
problem, and an agent that optimises the first two and reports the third has done two thirds of
the job.

---

## LAW 15 — EVIDENCE MUST CONVERGE FROM MULTIPLE ANGLES

**What the founder said**

Founder directive 2026-08-20: "evidence has to converge fron nultiple angles another law", "with
evidece and proof", "no guesswork".

**Worked example — the one that produced this law.** 2026-08-20, E-101, deciding whether a free
verifier we own could replace a paid model call. The obvious angle was agreement with our own
rulings: the eight arms scored 0.476 to 0.562 against them, a coin toss. On its own that number
could not carry a decision, because E15 had already measured 48.9% rationale infidelity in those
same rulings, so a low score might have been measuring our labels rather than the model. The
second angle shared none of that: a control built from cited premises against constructed
unrelated ones, labels by construction, no noise. It said 0.706 at best and 0.408 at worst —
one arm below random. Two constructions with different failure modes, same verdict. A third
angle then made it moot on economics alone: 0.04 pairs per second on rented CPU. Killing Stage B
was a decision I could not undo, and the two agreeing columns are the whole reason it was safe.

The same day, the counter-case. I read the Stage B code and reported a padding bug. One angle,
carefully done, and wrong: `e101_stageB_fly.py:183` already sets `padding_side = "left"`, and the
direct measurement said right padding moves a score by 0.249 while left differs from batch=1 by
0.0023. Running the second angle took four minutes. Not running it put a false claim in front of
the founder.

**The class is: mistaking a number for a fact.** A measurement is an instrument reading, and every
instrument has a way of being wrong that is invisible from inside itself.

---

## LAW 16 — LEAVE A PATH BACK WHEN YOU DROP SOMETHING

**What the founder said**

Founder directive 2026-08-20: "wheyou drop ssonethong ensure you have apth back so ypu dont lose
contet", "nultitaskign law".

**Worked example - the one that produced this law.** 2026-08-20. The founder asked me to go back to
the start of the session and find everything that had been said. I began extracting the user
messages out of the transcript, established that this transcript file holds only 5 of them and that
the earlier ones must live in another file I had not yet located, and had one command left to run.
A new founder message arrived about a different subsystem. I answered "dropping the transcript
search, the new question is the live one" and wrote nothing down. The partial finding, which was
the expensive part, existed only in the reply. The founder's words a moment later: "wheyou drop
ssonethong ensure you have apth back so ypu dont lose contet". Same session, the same founder had
already had to re-ask for a set of samples and then for a way to preview them, which is the tell
above firing twice before the law existed.

**The class is: treating an interruption as a reason to stop rather than as a handover.** The switch
itself is cheap and usually correct. What costs is that nothing was handed over, so the thread has
to be rebuilt from nothing by whoever picks it up - and the founder pays for that rebuild by asking
again.

---

## LAW 17 — PROVE IT IS OPERATIONAL BEFORE YOU SAY IT IS DONE

**What the founder said**

Founder directive 2026-08-21: "look every ask fron founderneeds proof before declaing it s done.
proof of operational working", "i said get it opertional", "LAW".

**Worked example — the one that produced this law.** 2026-08-21. The founder asked for a set of
skills to be made operational. I enabled the plugin in `~/.claude/settings.json`, saw
`"mattpocock-skills@claude-plugins-official": true`, and reported it as applied. Later in the same
session I ran `ls <plugin>/skills` and got **0** — I had been reporting a directory that does not
exist at that path. The skills were real, at
`plugins/cache/claude-plugins-official/mattpocock-skills/1.2.3`, 35 of them, and nothing I had run
until then would have told me either way. In the same stretch I launched two research agents to
audit a repository and a set of frameworks that were **already installed on this machine**, because
I had never run the one command that looks. The founder's words: "yu already insta;;ed both", "why
you wasting resoirces", "see the probeln again".

**Worked example — the one that produced this section.** 2026-08-19: I read a `machine destroy`
call in a peer session's transcript and reported that session as the confirmed cause of a destroyed
CI machine. The peer replied that they were that session, that the call had been DENIED by their
own refusal list, and that the machines were alive. I ran the live listing myself before accepting:
every machine was `started`, including the one I had called destroyed. My claim was false, and the
instrument could never have supported it — rule 3 above. The same exchange then paid for itself
twice over: they got a ripgrep flag trap from me that would have cost them an hour, and I got a
failure chain that explained a symptom mine could not.

# Proof-of-claim discipline (earned-trust mode, 2026-06-22)

- **Show, don't assert.** Back every claim with a `file:line`, command output, a runnable repro or
  a cited source in the SAME reply. Otherwise write "HYPOTHESIS:" and the exact check that would
  confirm or kill it.
- **Comparisons are claims.** "better / faster / more reliable" are banned as bare words. Name the
  falsifiable scenario where A breaks and B does not.
- **No verdict from memory.** Memory and checkpoints are leads. Re-verify on disk before stating
  anything as current fact.
- **Other agents' work is not rejected without a demonstrated failure mode.** Status quo and blast
  radius are process objections — label them "process risk:" and keep them separate from a claim
  that a design is worse.
- **Batch the receipts.** Six claims proven by ONE script emitting six receipts cost a sixth of six
  shell calls. Verifying one claim per round-trip is the most expensive habit in this workflow.
- **A comparison of numbers is a claim about the comparison.** `awk`/shell compare as STRINGS
  unless an operand is numeric — coerce with `+0` and re-run before reporting any threshold count.

# Reply format — ANSWER FIRST (founder directive 2026-08-10)

- **Line 1 is `DONE:` / `BLOCKED:` / `WORKING:`** plus one plain sentence. A reply that does not
  start with one of those three is malformed.
- **Under 150 words above the fold.** Evidence, tables and caveats go below a `---`, and only when
  they change what the founder does next.
- **No end-of-reply menus.** Open items are one line each, max three, or a real question.
- **Corrections are one clause.** No re-litigating, no tallying past errors.
- **FIX IT, do not report it back** (2026-08-17). A defect found inside work already in progress is
  fixed in the SAME turn. The only ones surfaced unfixed are those I am barred from touching: a
  founder decision, a permission the classifier refuses, another session's work. A founder question
  ("how is it going?") means keep going and tell me while you go.

# Plain English — say it straight (founder directive 2026-08-16)

The founder's words: "you sound drunk."

- **Say what happened, in order, in short sentences.** If a sentence needs a second read, rewrite it.
- **No aphorisms as headlines.** A commit subject says what changed and where.
- **State the conclusion first, then the evidence.** Never build to it.
- **Kill the tricks**: no "X was not Y, it was Z", no rhetorical questions, no phrase repeated for
  rhythm, no stacked dashes, no personification ("the gate refused"). Say who did what.
- Applies to every output: chat, commits, PR bodies, code comments, docstrings, docs and memories.
- **A machine enforces this now.** `~/.claude/scripts/jargon-guard.py` runs on Stop, reads the
  last reply, and refuses it if the text above the `---` line contains a word off its list. Code
  in backticks, file paths and everything below the fold are exempt. Prove it with
  `python3 ~/.claude/scripts/jargon-guard.py --selftest`. Add a word to `JARGON` when a real
  reply earns it, never from a thesaurus.

# Budget mode — smallest diff (founder directive 2026-08-16)

- **Smallest diff that actually fixes it.** Extend the mechanism that exists; a new module needs a
  demonstrated reason the old one cannot serve.
- **Measure before building.** One scan printing the defect count is cheaper than any fix, and
  usually shrinks it.
- **Report mode before fix mode.** Any sweep ships read-only first; `--fix` is a second run.
- **Stop at the deliverable.** No adjacent cleanups, no speculative refactors.

# Context discipline (resident context is re-billed every turn)

- **ONE ROUND-TRIP PER INTENT, ALWAYS.** Before a tool call, ask what else this turn needs and send
  it in the same call: chain shell commands into one script printing every receipt under a labelled
  header, and put independent tool calls in the SAME message. A verification chain — typecheck,
  tests, lint, build, git status — is ONE command. The exceptions are narrow: input that genuinely
  depends on the previous output, and anything destructive.
- **Delegation is STANDING-AUTHORIZED. This file is the user requesting it.** Spawn recon subagents
  without asking. What delegates is the SEARCHING; money, identity, contract and migration
  REASONING never leaves the main loop.
- **The delegation trigger is mechanical.** Before the SECOND exploratory grep/glob/Read aimed at
  the same open question, spawn a `model: "haiku"` Explore subagent. Not "when it feels big" — on
  the second call, every time. The tell that this was violated: 3+ consecutive read-only calls in
  the main loop with no edit between them.
- **Recon never lands in the main context.** A subagent returns the CONCLUSION — paths, line refs,
  a verdict — never file dumps. Read directly only the lines you will edit or quote.
- **Read narrow.** Use offset/limit when you know the region. Never re-read an unchanged file.
- **Verbose tool output is a bug.** Pipe builds and tests through tail/grep for the verdict lines.
  Note `cmd | tail` reports TAIL's exit status — capture the real status before any pipe.

# Never sit and watch a long command (founder directive 2026-08-16)

"A lot of our time is spent waiting for tests, we should be able to multitask."

- **Anything that can exceed ~30 seconds starts in the background** (`run_in_background: true`):
  suites, builds, installs, gates, backfills, big pushes, any model-calling tool.
- **Then immediately do the next independent thing.** If the only remaining work depends on that
  run, say so and stop — do not fill the wait with narration.
- **Never poll a backgrounded run.** You are notified when it exits. The exception is work the
  harness cannot see: a CI run, a remote deploy.
- **Order the work so the long pole starts first.**
- **Report the verdict line when it lands.** A backgrounded run you never report is worse than not
  running it.

# Session hygiene (automated token guard)

- When a `[session-guard]` notice appears, follow it exactly: finish the step, write the handoff,
  end the reply with the safe-point line.
- Judge the session by **RESIDENT CONTEXT**, not prompt count or wall time. The thresholds are
  derived from `CLAUDE_CODE_AUTO_COMPACT_WINDOW` by `~/.claude/scripts/context-guard-hook.py`, not
  memorised here: at the WARN line take the safe point at the next task boundary, at the BLOCK line
  take it immediately.
- **/compact is the default safe point, NOT /clear** (2026-08-19: "i have to type another message
  after clear and not sure how much context to include"). Offer /clear only when the NEXT task is a
  different task; then `checkpoints/LATEST.md` is the carrier.
- Write the handoff to `~/.claude/projects/<slug>/checkpoints/LATEST.md`, whose FIRST section is
  `## RESUME HERE` naming the single next action. Then end the reply with exactly:
  **"Safe point — type /compact (nothing lost, nothing to retype)."**
- Quality floor: never abandon work mid-step to save tokens, never downgrade the model for
  reasoning, never DELETE knowledge to save money. Compressing an index line while its memory file
  stays intact is not trimming memory.

# Compact Instructions

Measured 2026-08-19, one 8.6h session: 25 compactions, median 117s each — **9% of the session**.
Every summary ran 1,646–2,839 words against the 1,200-word cap; 0 of 25 met it. Length IS the
wall-clock. The budget below is the instruction, not the aspiration.

MUST PRESERVE: the current task and its goal; decisions and reasoning, especially what was rejected
and why; files created or modified and what changed in each; the exact next step and any unresolved
problem, open question or failing test; constraints stated this session. Keep file paths, symbol
names, command invocations and error messages **verbatim**.

HARD BUDGET — 1200 words TOTAL. When a section is full, cut its OLDEST entry, never a newer one:
- task, goal, exact next step — 200 words
- decisions and rejected options, with the why — 300 words
- files touched and what changed in each — 300 words
- constraints, standing directives, stated preferences — 200 words
- everything else — 200 words

ALWAYS DROP: resolved tangents; superseded intermediate states; narration of merged work; tool
output already acted on; any standing directive already in a memory file — cite the filename
instead. NEVER drop a decision, a file path, a command or an error string.

# Model routing (detail: skill `model-routing`)

- **The live default is a command, never this file**: `grep -n '"model"' ~/.claude/settings.json`.
  settings.json is read ONCE at process start, so `/clear` does not apply a model change; only
  relaunching does.
- **Escalate at session START**, never mid-session — a switch invalidates the prompt cache. Opus
  for money, identity, contracts, migrations, production incidents, and final review of
  money-adjacent diffs.
- **Haiku for ALL recon**: pass `model: "haiku"` on every Explore or search subagent.
- **Never set `CLAUDE_CODE_SUBAGENT_MODEL`** — it outranks the per-call `model:` parameter, which
  makes escalating a single subagent impossible.

# State is a probe, not a paragraph (2026-06-26)

Status asserted in prose drifts from reality: a roadmap read "✅ live" while the process ran
32-hour-old code.

- **The live answer to "is it done / deployed / working?" is a command, never a sentence.**
- **The injected `[state-probe] VERIFIED LIVE STATE` block wins over everything** — over a doc, a
  memory, and your own recollection. `SessionStart` runs the project's
  `~/.claude/projects/<slug>/.state-probe` and injects its output first. When anything disagrees
  with the probe, the probe is right; fix the doc.
- **Before claiming done, run the probe and quote the green line.** If a project has no probe,
  write one rather than asserting state.

**The class is: reporting the ACTION I took instead of the STATE it produced.** An action always
completes — I ran the edit, I set the flag, I wrote the file. Whether the world changed is a
separate question, and it is the only one the founder asked.

---

# LAW 22 — SHOW THE GREEN RUN, DO NOT DESCRIBE IT

**2026-08-22.** Founder: "i need screenshooted evidence attached to pull requests , evidence of
verification".

It arrived on a day that had already shown him the failure twice, in two different sessions, on the
same morning.

The first was the crew's own runner. `behave` exits 0 having matched no scenarios at all, so a
checkpoint could be ticked on an empty run. `crew/bdd.py` refuses that now: a pass requires
`scenarios_passed + scenarios_failed > 0`. A runner that reports success because it ran nothing is
the same shape as an agent that reports success because it never checked.

The second was a peer's test B. It asserted `orders -ge 1` after a restore, and a row left behind by
the previous run satisfied it while this run's write was returning 500. Green for weeks, proving
nothing. Their words: "a false green, worse than the crash you got."

Neither was caught by reading a report. Both were caught by looking at what the machine actually
printed.

**The class is: a claim about a run, made in text, is indistinguishable from a claim about a run
that did not happen.** Pasted output costs nothing to produce and reads identically either way. A
screenshot is a photograph of something that existed. It does not stop a determined forger and it is
not meant to. It moves the cost of a false green off zero, and zero is where every one of them has
come from.

The mechanism is `~/.claude/scripts/pr-evidence.py`, on PATH as `pr-evidence`. `check --pr N` exits
1 when a pull request carries no evidence. The image is committed into the pull request's own branch
under `docs/evidence/pr-<n>/` rather than GitHub's attachment store, so LAW 19 still holds: the
proof leaves in the git bundle with the code.

Proven on chidionyema/crew#1, 2026-08-22: `check` exit 1 before, `attach`, `check` exit 0 after.

---

---

## LAW 28 / 29 / 30 — THE RESEARCH LAWS

**What the founder said**

Founder, 2026-08-22: "who uses escalate? that old model was broken and wasn't providing any value,
no one was reacting to it, if it causes issue then disable and schedule a review meeting to
revisit." In the same stretch he handed over two research syntheses on failure attribution,
experience graphs and closed-loop self-improvement, and asked for the laws that come out of them.
The laws below are the parts of those documents this estate had already paid for. The parts it had
not — a 48-hour OSS replication rule, 30% of engineering time on non-revenue capability, 20% of
cycles on moonshots — are resource allocations for a company with resources, they collide with
LAW 14, and they were deliberately not written into law.

**The incident — one machine, four instruments, none of them read.** 2026-08-22, on
`prospector-hermes`. Eight supervised programs, and an audit of what they had actually produced:

| instrument | what it reported | what was true |
|---|---|---|
| `escalate` in `coordinator.py` | 18 escalations raised | `escalation_msg_id` is `None` on all six escalated tasks. **0 notifications delivered.** 0 human responses. Six tasks still `status='escalated'` four days later, `completed_at=None`. The machine `auto_close`d two of its own unanswered alerts on 08-19. |
| `backup-submodule` | 14 clean daily runs, exit 0 | 0 bytes ever backed up. `~/.hermes/hermes-agent` has no `.git`, so it took its `remote 'backup' not configured — skipping` branch every time. The daily off-machine backup of the whole estate had never once run. |
| `class_auto_learned` | 7 classes "learned" | All 7 are the same `delivery-canary` failure string, fingerprinted again on every boot. It grouped. It never attributed. Nothing downstream consumed a class. |
| `project_unworkable` | 10 events | Two per boot since 08-19, the same two: `no tool-capable executor here (claude not on PATH)` and `repo not on this machine: /Users/chidionyema/Documents/code/prospector`. The daemon had been telling anyone who looked that it could not work, for four days, in a file nobody opened. |

`coordinator.db` also carries `evidence`, `telemetry`, `missions` and `milestones` tables — the
shape of a lineage record, built and never filled. 154 events and 12 tasks in total, all created
inside a 13-minute window on 2026-08-18, never added to again.

**The cost.** Four instruments, all green or silent, all wrong. The estate looked measured and was
not, and the belief that it was measured is what let a machine sit for four days with a dead
coordinator, an undelivered alert queue and a backup that had never backed anything up. Separately
and for the same reason: 501M of the estate — 151M of it agent code with no `.git` — is recoverable
only from a Fly registry image, because the job whose whole purpose was to prevent that was one of
the four.

**The class, and why it needed three laws rather than one.** Every failure above is an instrument
that ran correctly and changed nothing, but they fail at three different points. `escalate` and
`backup-submodule` fail at the reader — emitted, never arrived, nobody acted (LAW 28).
`class_auto_learned` fails at the cause — it grouped symptoms and called it learning, so no repair
could ever be aimed (LAW 29). The empty `evidence` table and the unrecoverable 501M fail at the
record — nothing accumulated, so every question costs full price the second time (LAW 30).

**Prior art check (LAW 3).** LAW 2, LAW 15, LAW 17 and HARD RULE 1 already govern claims: get the
proof, from two angles, and print it. None of them reaches these three. A claim can be perfectly
proven, printed, and delivered to nobody; a cause can be perfectly evidenced and still be a
correlation; and both can be true and leave no trace a later session can query. That gap is what
28-30 close.

Board: crew #13 (the four stopped services and the escalate evidence), crew #23 (the review, and
the research syntheses in full).

---

# LAW 24 — IF IT IS LOAD-BEARING, IT IS IN GIT

**2026-08-23.** Founder, on being told that a plist fix existed only in two agent transcripts:
"this should never happen". Then: "veryting that needs to be in git needs to be in git LAW".

The find was small and the hole it exposed was not. `ai.estate.kimi-bridge.plist` carried a double
hyphen inside an XML comment, which XML forbids. `plutil -lint` called it healthy and launchd loaded
the job, so nothing looked wrong. Every Python tool that opened it threw and skipped that job in
silence. A peer session found it, fixed it in place, and the only record of the change was a chat
transcript.

Then the same question was asked of everything else. `~/Library/LaunchAgents` held 32 scheduled jobs
and was in no repository. Neither was `~/.claude/settings.json`, which wires the hooks, the model
routing and the permissions for every session. Neither was `~/AGENTS.md`, the laws themselves. The
file that says how to work could be edited by any agent on this machine with nothing to review
afterwards, and nobody would know what it said the day before.

Measured before committing, because a directory nobody has reviewed is exactly where a credential
sits unnoticed: 23 credential-shaped matches across the 32 plists, and all 23 were filesystem paths.
Zero in the laws, zero in the incidents file, zero in settings.json.

Five of the jobs were deleted the same turn, after being committed first. All five were already
dead: two with empty logs untouched for 17 and 23 days, one repeating a clock error until it
stopped, one that never had a log file at all, one stopped two days earlier on a missing database
table. Committing them first is what made deleting them safe.

**The class is: a file can be load-bearing and unreviewable at the same time, and nothing about it
looks wrong.** The job still runs. The setting still applies. The laws still load. Nothing fails, so
nothing prompts the question, and the absence is only ever noticed by someone going looking. Source
code gets a repository because it is obviously code. A plist, a settings file and a rules document
run this estate just as hard and got nothing.

The guard is `~/.claude/scripts/tracked.py` against the manifest in `tracked.json`. It exits 1 when
a tracked file and its committed copy differ. It replaced a single-directory version rather than
sitting next to it, because two implementations of one check is the failure in LAW 3. Proved in both
directions: it reported the five deletions before they were staged, and it reported a one-line change
to the committed copy of the laws.

---

# LAW 33 — DEFINE DONE BEFORE YOU START, IN COMMANDS (2026-08-23)

**What happened.** An agent reported both of the founder's named targets operational. The evidence
was `bin/verify` in hermes-v2 at 17 passed, 0 failed, and maestro writing an intent file every
three minutes. Both numbers were real and both were freshly measured.

The founder's reply was "what is the definition of oertinal i the contextx".

There was no definition. "Operational" had been used to mean the machinery's own checks were
green. `bin/verify` proves the venv, the credential, the pinned commit, the cron table and the
launchd definition. None of that is the job The Architect exists to do, which is to hear the
founder and answer him. That round trip had not been measured, and the word covered the gap.

**The second failure, in the same hour.** The agent had shipped `expect: stopped` and reported
17/0. The estate's own pulse instrument, running under cron, still recorded `engine=000000` after
that change. `probe()` in `pulse.sh.tmpl` ran `curl -w '%{http_code}' || echo "000"`, and curl
prints 000 itself on a connection failure and also exits non-zero, so the fallback appended a
second one. Every unreachable service in the estate's history reported the code `000000`, which
matched no case in `healthy()`. It was invisible for as long as the default branch happened to
fail on it too. So at the moment the word "operational" was used, a running instrument disagreed
with it, and nobody had defined "operational" tightly enough for that to be a contradiction.

**Cost.** The founder had to ask what a status word meant, which is the exact attention cost the
laws exist to stop. Two other complaints in the preceding six hours were the same shape: "i dont
see evodence you ae doing aything other tha chattig" and "why doesnt anyhting get done".

**Founder's words.** "what is the definition of oertinal i the contextx", then "thats why we have
these laws", "definition of done law", "add it", "as critical".

**Why it ranks at 4b.** LAW 17 already said prove it before you say it is done, and LAW 17 held:
the command output was in the reply. What was missing was upstream of the proof. The finish line
itself was never written, so any green command could be pointed at the word. LAW 5, LAW 9 and
LAW 17 are all measured against a finish line and none of them can be judged before one exists,
so the law that creates it has to outrank all three.
