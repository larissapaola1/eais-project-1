# Project 1: single call vs compound

Team: Laura Jimena Tagle Muñoz and Paola Larissa Hernandez Llamas.

Both systems take one request and five candidate games, and return the one game that meets every requirement
in [RUBRIC.md](RUBRIC.md), or decline. This README covers how to run them, how well they do, where the compound
system fails, and what we changed after the checkpoint.

## How to run

You need Python 3.10 or newer. From a clean checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
python -m pytest
```

Set the two variables from the course app's Project 1 page in the same terminal. Never commit the token.

```bash
export P1_ENDPOINT=...   # from the Project 1 page
export P1_TOKEN=...      # your own token
```

Run a system and score the run:

```bash
python -m p1.run systems/single.py   --requests data/public.jsonl --out runs/<new-folder>
python -m p1.run systems/compound.py --requests data/public.jsonl --out runs/<new-folder>
python score.py runs/<new-folder>

# Checkpoint requests: score against their own answer file.
python -m p1.run systems/compound.py --requests data/checkpoint_requests.jsonl --out runs/<new-folder>
python score.py runs/<new-folder> --answers data/checkpoint_answers.jsonl
```

Each `--out` folder must be new, or add `--force`. A run on the hidden labeling requests (`data/labeling.jsonl`)
can't be scored with `score.py`, because their answers aren't public.

## Files

| File | What it is |
|---|---|
| `systems/single.py` | The single-call system: one prompt with the rubric rules, one model call. |
| `systems/compound.py` | The compound system we submit: v6's steps and prompts, with fewer model calls (see [Cost](#cost-fewer-model-calls)) and the mode change (see [below](#the-change-for-the-largest-group-keep-a-correctly-extracted-mode)). Called `compound-2.py` in the runs made before we renamed it. |
| `systems/compound-v6.py` | v6, our version after the change below: the same steps, but `decide` runs on all five games. Kept to compare against and to measure step accuracy, since it evaluates every labeled input. |
| `systems/compound-checkpoint.py` | The compound system exactly as submitted for the checkpoint (commit `ed925a4`), kept to measure against. |
| `score.py` | Our scorer. |
| `runs/` | The saved output of every run this README reports. |

## Our systems

**Single-call** (`systems/single.py`). One prompt asks the model to label each game ACCEPT, BREAK or CAN'T TELL
against the rubric and to pick an accepted game or decline.

**Compound** (`systems/compound.py`). Two model steps, then plain Python for every rubric rule that can be
checked from data:

1. `extract_requirements` (1 call): reads the request and returns the requirements: players, maximum minutes,
   the youngest player's age, mode (cooperative or competitive), complexity (light, medium or heavy) and things to
   avoid (fighting, violence, horror, timer, player elimination). Wishes are kept separately and never checked.
   Python keeps a mode or complexity only if the model's quote of the request backs it and isn't a wish; for the
   mode, the rubric's wording in a non-wish sentence of the request is also enough.
2. `decide` (1 call per game): reads one game and reports facts, not verdicts: the player range and play time
   when the card lacks them, whether the description says the rules are easy or complex, and whether each avoided
   feature is present. Each fact taken from the description must come with a quote that Python finds in the
   description.
3. Python applies the rubric: player range, play time, age and mode from the card; complexity from the weight,
   game types and the description clues, as in RUBRIC.md section 3; avoided features from the card's tags plus
   `decide`'s answer. It goes through the games in order and picks the first that passes every check, or
   declines. It calls `decide` only for a game whose card doesn't already rule it out, and stops at the first
   acceptable game.

A reply that doesn't fit its type is retried once, within the limit of 10 calls per request. A game still without
a valid reply is never picked, so every request gets an answer.

## Results

Every run below finished with 0 failed requests. Cost and time are per request.

### Public requests (150)

| System | Run | Score | Cost | Time | Calls |
|---|---|---|---|---|---|
| Single-call | `runs/public.jsonl` | 93/150 | $0.00042 | 0.33 s | 1.0 |
| Single-call | `runs/single-expert-3` | 97/150 | $0.00027 | 0.30 s | 1.0 |
| Compound, checkpoint version | `runs/cp-public-run1` | 132/150 | $0.00176 | 3.54 s | 6.0 |
| Compound, checkpoint version | `runs/cp-public-run2` | 133/150 | $0.00176 | 3.45 s | 6.0 |
| Compound, v6 (`compound-v6.py`) | `runs/v5-expert-public-run2` | 137/150 | $0.00182 | 3.37 s | 6.0 |
| Compound, v6 (`compound-v6.py`) | `runs/compound-expert-3` | 139/150 | $0.00184 | 3.26 s | 6.0 |
| Compound, fewer calls, before the mode change | `runs/c2-public-run1` | 138/150 | $0.00057 | 1.04 s | 2.1 |
| Compound, fewer calls, before the mode change | `runs/c2-public-run2` | 136/150 | $0.00054 | 1.05 s | 2.1 |
| Compound, final (`compound.py`) | `runs/final-public-run1` | 140/150 | $0.00057 | 1.05 s | 2.1 |
| Compound, final (`compound.py`) | `runs/final-public-run2` | 142/150 | $0.00054 | 1.05 s | 2.1 |

### Checkpoint requests (50)

| System | Run | Score | Cost |
|---|---|---|---|
| Single-call | official checkpoint run (course app, held-out set 2) | 34/50 (68%) | $0.0004 |
| Compound, checkpoint version | official checkpoint run (course app, held-out set 2) | 44/50 (88%) | $0.0018 |
| Single-call | `runs/checkpoint-single-2` | 34/50 | $0.00042 |
| Compound, checkpoint version | `runs/cp-checkpoint-run1` | 45/50 | $0.00180 |
| Compound, v6 (`compound-v6.py`) | `runs/checkpoint-compound-2` | 45/50 | $0.00184 |
| Compound, v6 (`compound-v6.py`) | `runs/checkpoint_requests-compound` | 46/50 | $0.00180 |
| Compound, fewer calls, before the mode change | `runs/checkpoint_requests-compound-2` | 45/50 | $0.00056 |
| Compound, final (`compound.py`) | `runs/final-checkpoint-run1` | 46/50 | $0.00051 |

The compound system does clearly better than the single-call system, at 1.3 to 2 times the cost per request
(`compound.py`), or 4 to 7 times for v6; the single-call system's cost varied between its two runs. Two runs of the same version differ by up to 2 requests out of 150,
because the model's answers vary; we treat differences that small as noise.

### Feedback requests (50, unseen)

| Submission | Version | Feedback score |
|---|---|---|
| not recorded yet | | |

## Labels and step accuracy

We labeled every input of both model steps on the 10 public practice requests and the 10 hidden labeling
requests (`labels/`). With our labels in place of both model steps, the system answers all 10 practice requests
right (Gradescope label check).

Step accuracy on the 10 hidden labeling requests:

| Step | Run | Every labeled field right | Per field |
|---|---|---|---|
| `extract_requirements` | `runs/labeling-normal-5` (normal run) | 9 of 10 | players, time, age, mode, avoid 10/10; complexity 9/10 |
| `decide` | `runs/labeling-swap-extract-5` (our extraction labels swapped in) | 43 of 50 (0.86) | players 0.98–1.0, time 1.0, age 1.0, easy rules 0.96, complex rules 0.98, avoid 0.94 |

`decide` has to be measured with our extraction labels swapped in (`--override extract_requirements=...`).
In a normal run, the model's extraction fills free-text fields (quotes, wishes) that our labels leave empty, so
`decide`'s inputs almost never match the labeled ones and the accuracy tool finds nothing to compare.

Disagreements we found while checking:

- The one extraction "miss", L03, is a wrong label: the request never asks for a complexity level, and the model
  is right to return none.
- `decide` still makes real mistakes on avoided features read from the description, in both directions: it
  called a cooperative game's "win or lose as a group" player elimination (L03), and missed "everyone
  simultaneously tries to grab" as a timer (L04).

## Where it fails

### Checkpoint version on the checkpoint requests (`runs/cp-checkpoint-run1`, 45/50)

This is the system we submitted for the checkpoint (`systems/compound-checkpoint.py`, commit `ed925a4`; the course
app confirms it ran our submission from Tue 13 Oct, 19:06). The official checkpoint run scored 44/50, but the
course app doesn't list which requests were wrong. The failures below come from our rerun of the same code, which
scored 45/50; answers vary between runs of the same code, so one official failure may be missing here.

| Request | What went wrong | Group |
|---|---|---|
| H1-016 | Call of Cthulhu: The Card Game is a right medium game, but `decide` called its rules complex from "a solid game experience, full of strategy and excitement", so Python rejected it and declined | Wrong rule-difficulty clue |
| H1-088 | Techno Bowl is a right medium game, but `decide` quoted "complex rules" from "without the need for complex rules", dropping the "without", so Python rejected it and declined | Wrong rule-difficulty clue |
| H1-082 | "play against each other": the model extracted competitive, but its quote ("we want a game…" for "My husband and I want a game…") wasn't word for word, so the mode was discarded and a cooperative game was picked | Mode dropped |
| H1-096 | "play against each other": same as H1-082, and a cooperative game was picked | Mode dropped |
| H1-030 | The Voting Game's card has no player count; `decide` reported 3–10 players from "for up to 10 players", inventing the minimum, so the game counted as fitting 6 players | Player count from the description |

| Group | Count |
|---|---|
| Mode dropped | 2 |
| Wrong rule-difficulty clue | 2 |
| Player count from the description | 1 |

We checked each diagnosis by replacing the first wrong output and rerunning only the Python part on the recorded
outputs, with no model calls. Each single correction turns the wrong answer into a right one:

| Request | First wrong output | Corrected to | Pick before → after |
|---|---|---|---|
| H1-016 | `decide` on D: complex rules true | false | decline → D (right) |
| H1-088 | `decide` on D: complex rules true | false | decline → D (right) |
| H1-082 | `extract_requirements`: mode none | competitive | A → B (right) |
| H1-096 | `extract_requirements`: mode none | competitive | D → E (right) |
| H1-030 | `decide` on A: players 3–10 | not given | A → C (right) |

Five failures are too few to rank the groups, so we grouped the same version's failures on the public requests
too (`runs/cp-public-run1`: 18 wrong, `runs/cp-public-run2`: 17 wrong):

| Group | Public run 1 | Public run 2 | Checkpoint | Requests |
|---|---|---|---|---|
| Mode dropped | 5 | 5 | 2 | P029, P039, P053, P116, P143, H1-082, H1-096 |
| Wrong rule-difficulty clue | 3 | 5 | 2 | P059, P067, P076, P108, P146, H1-016, H1-088 |
| Avoid wrong | 5 | 2 | 0 | P022, P068, P071, P125, P150 |
| Complexity clue or card missed | 3 | 3 | 0 | P074, P135, P145 |
| Other | 2 | 2 | 1 | P023, P043, H1-030 |

The two largest groups are mode dropped and wrong rule-difficulty clues. In the first, the model is right and a
Python check throws its answer away. In the second, the model takes a quote that exists in the description as
evidence about the rules, when the quote is about something else.

### v6 on the checkpoint requests (`runs/checkpoint-compound-2`, 45/50)

| Request | What went wrong | Group |
|---|---|---|
| H1-067 | "play head to head": the model extracted competitive, but its quote of the request wasn't word for word, so a Python check discarded the mode and a cooperative game was picked | Mode dropped |
| H1-082 | "play against each other": same as H1-067 | Mode dropped |
| H1-030 | The Voting Game's card has no player count; the model took one from an unrelated sentence of the description | Invented player count |
| H1-044 | Munchkin Apocalypse: the model missed a complexity clue in the description, so a right medium game was rejected | Complexity clue missed |
| H1-074 | Pass the Pigs: the model missed player elimination in the description | Avoid missed |

| Group | Count |
|---|---|
| Mode dropped | 2 |
| Invented player count | 1 |
| Complexity clue missed | 1 |
| Avoid missed | 1 |

The same groups explain the 13 misses of the current version on the public requests (`runs/v5-expert-public-run2`):
mode dropped 6 (P029, P039, P053, P116, P127, P143), invented player count 2 (P043, P100), complexity clue missed
or invented 3 (P074, P135, P145), avoid wrong 2 (P068, P125). The first group comes from Python, not the model: the
model extracts the mode correctly, and the check that requires its quote to match the request word for word
throws it away.

## What we changed

### First change: rule-difficulty clues must talk about the rules

**Group it addresses:** wrong rule-difficulty clues, the second-largest group of the checkpoint version
(2 of 5 checkpoint failures, 3 and 5 of the public failures).

**The change** touches three of `decide`'s output fields, `easy_rules`, `complex_rules` and `min_age`, and
nothing else (commit `71b6630`, with "expert" added in `ec2708e`). We found the problem with our step-accuracy
check: on the hidden labeling requests, the checkpoint version's `decide` matched our labels on only 25 of 50
`easy_rules`, 46 of 50 `complex_rules` and 28 of 50 `min_age` values (`runs/labeling-swap-extract-3`).

#### `easy_rules` and `complex_rules`: the quote must be about the rules

*Why.* In the checkpoint version, `decide` had to back each clue with a quote, and Python accepted the clue if the
quote existed anywhere in the description. Real quotes about something other than the rules got through:

| Request | Game | Clue | Quote the model gave | Why it's wrong under the rubric |
|---|---|---|---|---|
| L01 | Shy Monsters | easy | "asymmetric bluffing game" | A genre says nothing about the rules |
| L05 | Bohnanza: Das Würfelspiel | easy | "the easiest orders to complete" | One part of the game |
| L07 | Buzzword | easy | "easy to quite difficult" | About the questions, not the rules |
| L01 | Beneath the Med | complex | "extremely challenging to survive until the Armistice" | How hard it is to win |
| L03 | Exit: The Cursed Labyrinth | complex | "Difficulty level: 2 of 5" | Puzzle difficulty, not rules |
| P076 | Warangel | complex | "light, fantasy wargame" | Says the opposite |
| H1-016 | Call of Cthulhu: The Card Game | complex | "a solid game experience, full of strategy and excitement" | Strategy isn't rule complexity |

A wrong clue changes the complexity decision: a wrong "complex" makes a medium game count as heavy, so the
system rejected the right game and declined in P059, P067, P076, P108, P146 and H1-016.

*Code.* `verified_clue` now takes a wording pattern, and a quote counts only if it exists in the description
**and** matches the pattern:

- `EASY_WORDING`: "simple", "straightforward", "light", "lighter", or "easy"/"easier", but "easy to …" only when
  followed by learn, teach, play, understand, pick up, explain or get into. So "easy to learn" counts and "easy to
  escape" doesn't.
- `COMPLEX_WORDING`: "complex", "complicated", "heavy", "heavier", "experienced", "expert", "hardcore".

Four sentences in the `decide` prompt give the same rule with the examples above.

*Limit.* The check reads words, not meaning: "a simple character-building system" (one part of Dice & Dragons,
L06) still counts as easy, and "without the need for complex rules" (H1-088) would still count as complex if the
model quoted only "complex rules".

#### `min_age`: Python decides it

*Why.* The rubric checks age only when the request gives a child's age. The model returned FAIL when no age was
asked at all, for example on L01 (Shy Monsters, Beneath the Med, Go-Moku), explaining that "the minimum age of 10
is greater than the unspecified youngest player's age". The prompt already said to return PASS when no age is
given, and the model ignored it.

*Code.* A new function, `check_age`, overrides the model's value: no age in the request means PASS; a card that
lists an age is compared with the child's age directly; only when neither the request nor the card settles it
does the model's answer from the description count. The prompt also says that an unknown player age is never a
reason to FAIL.

*Effect on answers.* None by itself: `answer()` already ignored the model's age when no age was asked or the card
listed one. The fix makes the step's output right, so step accuracy and our labels measure what the step does.

We wrote no prediction before making this change: we found the problem in our step-accuracy check against our
labels, before the checkpoint requests were released. The results are:

| | Checkpoint version | After the change (v6, `compound-v6.py`) |
|---|---|---|
| Public score, 2 runs each | 132, 133 | 137, 139 |
| Checkpoint score | 45 | 45, 46 |
| The 7 requests of the group (P059, P067, P076, P108, P146, H1-016, H1-088) | wrong in at least one run: 7 | wrong in any run: 0 |
| `decide` against our labels (hidden labeling requests, recorded replies) | easy rules 25/50, complex rules 46/50, age 28/50 | easy rules 48/50, complex rules 49/50, age 50/50 |
| Feedback score | not recorded yet | not recorded yet |

We keep the change: it fixed every request of its group in every run, and the public score rose by 5 to 6, more
than the 1 to 2 that two runs of the same version differ by. It doesn't fix every wrong clue: a quote that
contains rule wording but negates it ("without the need for complex rules", H1-088) still passes the check.
H1-088 came out right in all 3 runs after the change because the model no longer reported that clue, perhaps
because of the added prompt sentences; the Python check alone wouldn't have rejected it.

### Other changes since the checkpoint

| Change | Why | Effect |
|---|---|---|
| A reply with 0 for "not given" counts as not given; a reply that doesn't fit is retried once or the game is skipped | The version before the checkpoint gave no answer on P048 (Gradescope check 7) | Already in the checkpoint submission (`ed925a4`); every run since has 0 failed requests |

### Cost: fewer model calls

**Goal.** Spend fewer tokens per request without changing any answer. v6 called the model 6 times per request:
once for `extract_requirements` and once for `decide` on each of the five games. The `decide` calls were 92% of
the prompt tokens, about 2,500 tokens each.

**Idea.** Many `decide` calls can't change the pick:

1. **Games the card already rules out.** If the card's player range, longest play time, minimum age or
   cooperative tag breaks a requirement, or the card has a tag of an avoided feature, or the weight decides
   complexity on its own, Python rejects the game whatever `decide` says. `ruled_out_by_card()` finds these games
   from the card alone, and they get no `decide` call. For complexity, it tries all four combinations of the easy
   and complex clues and rules the game out only if none of them would pass.
2. **Games after the pick.** `answer()` picks the first acceptable game in order, so the games after it never
   matter. The new `answer()` evaluates the games one at a time and stops at the first acceptable one.

The steps, prompts and rubric checks are unchanged: we moved v6's acceptance checks into `is_acceptable()` without
changing a line of their logic. So the labels and the step types are the same as v6's.

**Check that no answer changed.** Before any real run, we replayed v6's recorded step outputs through the new
`answer()`, with no model calls: the same pick on 300 of 300 public requests (two full runs), on 40 of 40 practice
and labeling requests, and on 20 of 20 requests with our labels in place of both steps.

**Measured result** (per request, averaged over the runs in the results tables):

| | v6 (`compound-v6.py`) | Fewer calls (`c2-` runs) | Change |
|---|---|---|---|
| Model calls | 6.0 | 2.1 | −65% |
| Prompt tokens | 13,528 | 3,837 | −72% |
| Output tokens | 945 | 277 | −71% |
| Cost | $0.00183 | $0.00056 | −70% |
| Time | 3.32 s | 1.05 s | −69% |
| Time for all 150 public requests | 498 s (8.3 min) | 157 s (2.6 min) | −69% |
| Public score, 2 runs each | 137, 139 | 138, 136 | within noise |
| Checkpoint score | 45, 46 | 45 | within noise |

On the checkpoint requests, time per request fell from 3.5 s to 1.0 s and cost from $0.0018 to $0.00056. The score
differences between the two versions are no larger than between two runs of the same version, which fits with
the replay: given the same model outputs, both versions pick the same game.

Compared with the single-call system ($0.00027 to $0.00042 per request), the final system costs 1.3 to 2 times as
much per request, against 4 to 7 times for v6.

### The change for the largest group: keep a correctly extracted mode

**Group it addresses:** mode dropped, the largest group of the checkpoint version: 12 failures across its three
runs (5 and 5 public, 2 checkpoint; P029, P039, P053, P116, P143, H1-082, H1-096).

**What goes wrong.** `extract_requirements` returns the mode together with a quote from the request as evidence.
A Python check, `explicit_requirement`, keeps the mode only if that quote appears in the request word for word.
The model gets the mode right but paraphrases the quote: for "My husband and I want a game for the two of us to
play against each other" (H1-082) it quoted "we want a game for the two of us to play against each other". The
check then sets the mode to none, Python stops checking cooperative against competitive, and a game with the wrong
mode can be picked: a cooperative kids' game for H1-082, which asked for play against each other.

**The change** (`systems/compound.py`, in `extract_requirements`): when the quote doesn't match word for word,
the new function `mode_in_request` looks at the request itself. It keeps the model's mode if a sentence of the
request contains the rubric's wording for that mode and isn't a wish:

- cooperative: "against the game", "as one team", "team up", "cooperative", "co-op";
- competitive: "head to head", "against each other", "against one another", "competitive", "free for all";
- a sentence with "would be nice", "bonus points", "we love" and the like is a wish and doesn't count, as before.

So "It would be nice if the game can be played either PvP or co-op" (H1-030) still gives no mode, and "play
together" alone still doesn't mean cooperative, as the rubric says. The change only keeps a mode the model
extracted; it never adds one.

**Prediction**, written before running anything:

1. **Requests it should fix:** public P029, P039, P053, P116, P127, P143; checkpoint H1-067, H1-082. In each, the
   model extracted the right mode and the quote check discarded it.
2. **Currently right answers to check again:** every request with a mode requirement, e.g. P031, P090, P101, P129,
   P134, so the fix doesn't start keeping a mode that the request only wishes for.
3. **Keep it if** the average of 2 public runs rises by at least 3, none of the rechecked requests turns wrong, and
   the feedback score doesn't drop. Otherwise we report that it didn't hold up.

**Offline check, before any new run.** The `decide` prompt doesn't use the mode, so v6's recorded outputs stay
valid when only the mode changes. We replayed v6's four saved runs through the new code, with the model's recorded
extraction replies and no model calls:

| Run replayed | Before | With the change | Fixed | Became wrong |
|---|---|---|---|---|
| `runs/v5-expert-public-run2` | 137/150 | 143/150 | P029, P039, P053, P116, P127, P143 | none |
| `runs/compound-expert-3` | 139/150 | 144/150 | P029, P039, P053, P116, P143 | none |
| `runs/checkpoint-compound-2` | 45/50 | 47/50 | H1-067, H1-082 | none |
| `runs/checkpoint_requests-compound` | 46/50 | 48/50 | H1-067, H1-096 | none |

Every request in the prediction was fixed in at least one replay, and no right answer became wrong. The change
also kept the mode on P025, P098 and H1-090, which were right before and stay right.

**Real runs** (`systems/compound.py`, compared with the same low-cost code before the change):

| | Before the change | After the change |
|---|---|---|
| Public, 2 runs | 138, 136 (`runs/c2-public-run1`, `runs/c2-public-run2`) | 140, 142 (`runs/final-public-run1`, `runs/final-public-run2`) |
| Checkpoint | 45 (`runs/checkpoint_requests-compound-2`) | 46 (`runs/final-checkpoint-run1`) |
| Feedback | not run yet | not run yet |
| Cost and time per request | $0.00056, 1.05 s | $0.00055, 1.05 s |

**Compared with the prediction, request by request:**

1. *Requests it should fix:* all six public requests of the group (P029, P039, P053, P116, P127, P143) are right
   in both runs after the change; before, P029, P039, P053, P116 and P143 were wrong in both runs. On the
   checkpoint requests, H1-067 and H1-096 turned right; H1-082 was already right in the run before.
2. *Rechecked right answers:* P031, P090, P101, P129 and P134 stay right in both runs.
3. *Answers that turned wrong:* five requests that were right in both runs before are wrong in one run after.
   We checked each trace; none comes from the change, because in four of them the request has no mode
   requirement and nothing about the mode changed:

   | Request | First wrong output | Group |
   |---|---|---|
   | P006 | `decide` said Senjutsu: Battle For Japan has horror | Avoid wrong |
   | P141 | `decide` said Warhammer 40,000 and Fief have player elimination | Avoid wrong |
   | H1-052 | `decide` said Mahé has fighting | Avoid wrong |
   | P019 | `decide` gave 1822PNW, whose card has no player count, 2 players, quoting just "2", which the quote check found inside "1822" | Player count from the description |
   | P098 | The mode was kept, rightly ("go head to head"), but the model paraphrased the complexity quote ("I want…" for "we want…"), so the same word-for-word check dropped "heavy", and a light game was picked | Quote check, complexity |

   These are the run-to-run variation we also see between two runs of unchanged code. P098 shows that the
   word-for-word quote check also drops complexity requirements now and then; the change fixed it only for mode.

**Decision: we keep the change.** The average of the two public runs rose from 137 to 141, more than the 3 we set
as the threshold; every request of the group is right in both runs; none of the rechecked answers turned wrong,
and the five new failures come from other groups. The feedback comparison is still to be run.

**What's still wrong** in the two final public runs (8 and 10 failures) and the final checkpoint run (4): avoided
features judged wrongly from the description (P006, P068, P125, P141, H1-052, H1-074), complexity clues missed or
dropped (P074, P098, P135, P145, H1-044) and invented player counts (P019, P043, P100, H1-030). The next changes we
would make: accept a player count from the description only if its quote mentions players and a number, and apply
the mode change's sentence check to complexity as well.
