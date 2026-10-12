# Design notes

Why this document exists: the interesting part of this project is not the feature
list, it is the sequence of wrong answers that had to be discarded. Each section
below is a defect that shipped into a working pipeline, was caught by data rather
than by review, and left a permanent trace in the code as a comment or a test.

---

## Part 1 — What the data said

The project started with an assumption: **sort GitHub's "recently created"
repositories by stars and you get the best new projects.**

That assumption is wrong, and the way it is wrong is measurable.

### Symptom

The daily top 100 was useless. Rank 1 had 614 stars, zero forks, zero watchers,
zero issues, no license, no programming language, and — on inspection — exactly one
file:

```
=== KindStatesman/KMS-Pico
  stars=614 forks=0 watchers=0 issues=0 lang=None license=None
  created=2026-10-09T13:53:07  pushed=2026-10-09T13:53:14  size=2KB
  owner: created=2026-06-09  public_repos=2  followers=0
  root files(1): ['README.md']
```

`created` and `pushed` are seven seconds apart. The description is AI-generated
prose about "optimizing your professional desktop environment", and the topics are
pure search-engine bait: `ms-project-crack`, `photoshop-file-not-found`,
`windows-activaton` (sic). Four of these repos, from four different accounts, had
owners all created on the **same day**, each with two repositories and no
followers.

### Why it dominates short windows

The ranking is `created:>N days`, sorted by stars. In a 24-hour window a genuine
project has had no time to accumulate stars (`robot-heads`, a good launch, had 119
after a day) while buying 300–600 stars is cheap. The ordering metric is exactly
the one a farm can manufacture. By 30 days, real projects have tens of thousands of
stars and the farms cannot compete:

| Window | Share that is spam |
|---|---:|
| 24 hours | 91 % |
| 7 days | 23 % |
| 30 days | 1 % |

### The evidence-based filter

"It looks AI-written" is not evidence, so the filter does not rely on it. The
primary criterion is a **physical** fact: a repository containing only a README is
2–4 KB, and the size distribution over 300 ranking entries is bimodal with a nearly
empty middle:

| Size bucket | Count |
|---|---:|
| ≤ 8 KB | 115 |
| 9–50 KB | 3 |
| 51–200 KB | 8 |
| 201 KB–1 MB | 16 |
| ≥ 1 MB | 158 |

Because the middle is empty, the threshold is not a tuning parameter — anything
between 9 KB and 1 MB would give the same classification.

### Cross-validation instead of self-assessment

Two independent criteria were then run against each other:

| | count |
|---|---:|
| flagged by both | 108 |
| flagged by prose only (**possible false positive**) | **0** |
| flagged by evidence only (prose missed them) | 7 |
| passed by both | 185 |

The result worth keeping is the zero: the prose-based filter never flagged anything
the physical filter disagreed with. The union of the two is what ships. The seven
entries only the evidence filter caught are why the evidence filter is the primary
one.

---

## Part 2 — Sixteen defects

### 1. Referencing a constant from the wrong module

**Symptom.** All 54 slot queries failed with `AttributeError`.

**Cause.** `FIELDS` was defined in the ranking script, but the enrichment script
read it as `build_report.FIELDS`. Two modules, one constant, no shared definition.

**Aggravating factor.** The exception handler was `except Exception as e: ...
FAIL {type(e).__name__}` — it printed the exception *type* and swallowed the
message. `AttributeError` alone does not say which attribute.

**Fix.** Define the constant locally, and print the message. One round of debugging
was spent on information the handler already had.

**Lesson.** An exception handler that discards the message is a bug multiplier.

### 2. Block-buffered output hides progress

**Symptom.** A 54-request job produced no output for 20 minutes.

**Cause.** Python block-buffers stdout when it is a pipe. The job was progressing
fine; the progress lines were sitting in a 4 KB buffer.

**Fix.** Run with `python -u`, and `flush=True` on progress prints.

### 3. Work that cannot survive an interruption

**Symptom.** A machine freeze destroyed 20 minutes of API work, because results
were only written once at the end of the run.

**Fix.** Persist after every unit of work, and add `--resume` that loads the
existing output and skips completed units.

```python
out[slot] = kept
save(out, failed, token)      # after every slot, not at the end
```

**Lesson.** For any job longer than a couple of minutes, incremental persistence is
not an optimisation, it is the difference between a retry costing seconds and
costing the whole run.

### 4. The obvious sort key dilutes relevance

**Symptom.** Querying for agent orchestration frameworks returned
`microsoft/markitdown` — a file-to-Markdown converter — as the top candidate.

**Cause.** `sort=stars` is a pure numeric ordering. `markitdown` has `langchain`
somewhere in its topics, and 189,000 stars beats everything that is actually an
agent framework.

**Rejected fix.** GitHub's own "best match" ordering is worse: it surfaced a
471-star repo above `langchain` itself.

**Fix.** Compute relevance directly from **where the keyword hit**, on the
observation that position predicts purpose:

| Hit location | Meaning |
|---|---|
| repo name | the project *is* this thing (`langchain-ai/langchain`) |
| topics | the project does this thing among others |
| description | it is mentioned in passing |

**Lesson.** A ranking signal you do not control cannot be trusted as a relevance
signal, no matter how objective it looks.

### 5. Substring matching is not keyword matching

**Symptom.** The agent-memory slot contained `zephyrproject-rtos/zephyr` (an RTOS)
and `apache/zeppelin` (a notebook).

**Cause.** The query term was `zep`. `"zep" in "zephyr"` is `True`. The same bug
would let `dify` match `modify` and `codify`.

**Fix.** Word-boundary matching for Latin terms; substring only for multi-word
phrases:

```python
re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text)
```

**Lesson.** "The keyword appears in the text" and "the keyword is the word" are
different predicates. The cheap version of the first one is almost always wrong.

### 6. A scoring formula that saturates silently

**Symptom.** `bas3line/ascii` (697 stars, 40 forks) scored **86**, and was ranked
above `d3/d3` (113,725 stars, 22,639 forks) at **84**.

**Cause.** Both adoption terms used a log scale with a divisor small enough to hit
the cap early:

```python
s += 25 * min(1.0, math.log10(1 + forks) / 2.0)    # 100 forks = full marks
s += 25 * min(1.0, math.log10(1 + stars) / 4.5)    # ~32k stars = full marks
```

So 40 forks scored 20.2 out of 25, and 22,639 forks scored 25. Five points was the
entire spread between a hobby project and one of the most-used libraries in the
world. The remaining components — license, size, freshness — then decided the
ordering.

**Fix.** Widen the divisors so the useful range is not compressed:

```python
s += 30 * min(1.0, math.log10(1 + stars) / 5.5)
s += 25 * min(1.0, math.log10(1 + forks) / 4.6)
```

**Lesson.** `min(1.0, log(x)/k)` silently discards all information above
`x = 10^k`. When a cap is used, the cap must be checked against the real
distribution, not against intuition.

**Note.** The freshness penalty that made `d3` score lower than a same-day repo is
*correct* — `Tampermonkey/tampermonkey` had not been pushed to in 558 days. The bug
was the compression, not the penalty.

### 7. Hard tiers create a cliff

**Symptom.** After fixing relevance, `Bilibili-Evolved` (30,731 stars, topics-only
hit) ranked *below* `mozilla/webextension-polyfill` (3,068 stars, name hit).

**Cause.** Sorting by `(relevance_tier, quality)` makes the tier a hard gate. Any
name match outranks any topics match, regardless of a ten-fold quality difference.

**Rejected fix.** Sorting purely by `quality + bonus` is worse in the other
direction: `freeCodeCamp` (456,813 stars) has `d3` in its topics because it
*teaches* D3, and it would outrank `d3/d3` itself.

**Fix.** Keep the additive form but size the bonus so it expresses the intended
requirement: **a topics hit must be 20 quality points better to beat a name hit.**

```python
REL_BONUS = {"manual": 100, "name": 20, "ranking": 20, "topics": 0, "description": -15}
```

**Lesson.** A hard tier is an implicit assertion that the tier difference is
infinitely large. It almost never is.

### 8. A query term that collides with another well-known project

**Symptom.** The "disk and file management" slot was led by `apache/ranger` — a
Hadoop authorisation service.

**Cause.** The query contained the bare term `ranger`, which is also the name of
the terminal file manager. Name-based relevance scoring then did exactly what it
was designed to do, on the wrong project.

**Fix.** Replace the term, and add an explicit calibration layer so a human can
override the algorithm *and record why*:

```python
SLOT_EXCLUDE = {
    "磁盘与文件管理": {
        "apache/ranger": "Hadoop authorisation service; collides with the ranger file manager",
    },
}
```

The exclusion is rendered into the slot note, so the next person to look at that
slot can see the decision instead of wondering why the obvious candidate is
missing.

**Lesson.** Name-based relevance is strong evidence and therefore also a strong
source of confident errors. It needs a documented escape hatch.

### 9. The same logic implemented twice, and it broke twice

**Symptom.** The retrieval tool crashed with `TypeError: cannot unpack non-iterable
int object`.

**Cause.** `build_vault.py` stored relevance as a tuple `(level, reason)`;
`query_skill.py` had re-implemented the same loading and stored it as a bare
integer. The duplication had already caused one earlier mismatch.

**Fix.** Delete the duplicate. `build_vault` now exports the final ranking as
machine-readable data, and the retrieval tool reads it:

```python
# build_vault.py, the single source of truth for ordering
(build_dir / "slot_index.json").write_text(
    json.dumps({slot: [r.full_name for r in recs] for slot, recs in by_slot.items()})
)
```

**Lesson.** Two implementations of one rule is not a shortcut, it is a scheduled
bug. The first occurrence was a coding error; the second was a design error, and
only the second one prompted the structural fix.

### 10. Found by a test rather than by a user

Writing a round-trip test (`Repo → to_dict → from_dict → Repo`) surfaced a real
defect: `to_dict()` serialised the license as a plain string, while
`from_search_item()` assumed GitHub's `{"spdx_id": ...}` object. Reading back a
cached run would have raised `AttributeError`.

No amount of manual use would have found this, because the write path and the read
path were never exercised in the same session.

### 11. A record created before it was validated

**Symptom.** The candidate pool held 4,805 entries, but hundreds of them belonged to
no slot at all.

**Cause.** The relevance check ran *after* the code that creates the record:

```python
candidate = ensure(repo)                     # creates the record
level, why = relevance(candidate.repo, slot.query)
if level == 0:
    continue                                 # skips the slot, keeps the record
```

Anything a search query returned became a candidate, even when it matched none of
the query terms.

**Impact.** No visible output changed — a candidate with no slot gets no note — but
every count was inflated, and "4,805 candidates" was not a meaningful number.

**Fix.** Validate first, then create:

```python
level, why = relevance(repo, slot.query)
if level == 0:
    continue
candidate = ensure(repo)
```

The pool dropped from 4,805 to 4,270. The 535 removed entries were pure dead weight.

**Lesson.** "Validate then persist" is not stylistic. When the creation of a record
is separated from the reason it exists, the count of records stops meaning anything.

### 12. A colon in a filename produced no file at all

**Symptom.** The vault contained **zero** search-log notes. No exception was raised
that anyone noticed.

**Cause.** The log filename was built from a full timestamp:

```python
stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
(log_dir / f"{stamp}-{window}.md").write_text(...)   # 2026-01-01 00:00-week.md
```

`:` is illegal in Windows filenames. The write failed, and because the log was a
secondary artefact nobody was asserting on, it went unnoticed.

**Fix.** Filenames take the date portion; the timestamp stays in the note body.

**Lesson.** This one was caught by a test asserting on **file counts**, not file
contents. A test suite that only checks "the important file has the right text"
would never have found it.

### 13. Code that contradicted its own documentation

**Symptom.** The offline demo reported the spam repository's exclusion reason as
`模板话术` ("template prose") — while Part 1 of this document argues at length that
the **physical** criterion (a repository containing only a README) is the primary
evidence, precisely because it is the one a reviewer can check by opening the page.

**Cause.** The filter is a chain of checks returning the first match:

```python
if JUNK_RE.search(repo.description):   # linguistic   <- ran first
    return "模板话术"
...
if repo.size_kb <= README_ONLY_KB:     # physical
    return f"仅README({repo.size_kb}KB)"
```

Filtering behaviour was unaffected — the predicate is an OR, and the repository was
excluded either way. But the *stated reason* was the weaker, less checkable one, and
it was the reason being shown to the user.

**Fix.** Order the checks by evidence strength, so the reason reported is always the
most checkable one: size → engagement → prose.

```python
if repo.size_kb <= README_ONLY_KB:      # a fact you can verify in one click
    return f"仅README({repo.size_kb}KB)"
...
if JUNK_RE.search(repo.description):    # a judgement
    return "模板话术"
```

A regression test now pins the precedence with three inputs that each match several
criteria at once.

**Lesson.** When a function returns *the reason*, its check order **is**
documentation. If the order and the prose disagree, the code is what users see —
and in this case the code was telling a weaker story than the design could support.

### 14. A new kind of event silently reported as an existing one

**Symptom.** When a capability slot went from empty to populated, `diff` announced it
as an upgrade:

```
🔼 出现更好的首选（1 个）—— 这是值得替换的信号
  [笔记与编辑器]  +108 分
      换下  —
      换上  logseq/logseq
```

"换下 —" says it plainly: there was nothing to replace. The same slot then appeared
again under `✅ 新填上的空缺`, so one event was reported twice, in two different
vocabularies, one of which was wrong.

**Cause.** The direction classifier had no case for "was empty, now isn't", so the
fall-through branch absorbed it:

```python
if self.old_top is None:
    return "upgrade"        # <- default, not a decision
```

**Impact.** Three genuinely different events were being collapsed:

| What happened | What it means to the user |
|---|---|
| top pick replaced by a stronger candidate | *your choice is now suboptimal — consider swapping* |
| an empty slot got its first candidate | *a capability you had no option for now has one* |
| the top pick got weaker | *something disappeared — check why* |

Only the first is a replacement. Mixing the other two into it dilutes the one signal
the whole `diff` command exists to produce.

**Fix.** Make the enum explicit and give each event its own section:

```python
if self.old_top is None:
    return "filled"
if self.new_top is None:
    return "emptied"
...
```

`is_actionable` still returns true for both `upgrade` and `filled`, because both are
worth attention — but they are no longer reported as the same thing.

**Lesson.** An `else`-shaped default in a classifier is a claim that the remaining
cases are alike. Here they were not. When the enum drives what a human reads, the
fall-through case deserves the same scrutiny as the explicit ones — and the
giveaway was visible in the output all along: *"换下 —"* is a phrase that should not
be possible.

---

## Part 3 — How the rewrite was verified

Extracting the logic from working scripts into a package is only a win if the new
code produces the same answers. Two checks were run, both against the data that
generated the numbers in the README.

**Behavioural parity, unit level.** The new modules were diffed against the old
scripts over all 300 ranking entries:

| Check | Identical | Different |
|---|---:|---:|
| Quality filter | 300 | **0** |
| Slot assignment | 185 | **0** |
| Quality score | 300 | **0** |

**End-to-end parity, artefact level.** Both pipelines were run on the same raw data
and the rendered vaults compared:

| Check | Result |
|---|---|
| Capability slots | 54 / 54 |
| **Slot top-picks identical** | **54 / 54** |
| Junk repositories | 92 / 92 |
| Repository notes | 621 vs 629 |

The eight-note difference is understood and benign, and is documented rather than
papered over: adding `full_name` as a final sort tiebreaker (to make ordering
deterministic) reshuffled candidates that were exactly tied at the per-slot display
cut-off. The newly deterministic ordering excludes eight repositories that the old,
tie-order-dependent sort happened to include. No top-pick changed.

The one difference that was *not* benign — a junk count of 115 where the old code
reported 92 — turned out to be a real semantic error: junk was being counted per
ranking *entry* rather than per unique repository, so repositories appearing in both
the daily and weekly lists were counted twice.

**Making the conclusion reproducible.** A claim in a README that a reader cannot
check is a claim taken on faith, and this one originally was: the reference
implementation and the 6 MB crawl were not published. So the crawl is now committed,
trimmed to 1.1 MB, under `tests/fixtures/real_crawl/`:

* the day/week/month rankings are kept **complete** — 240 KB, and they are what the
  junk percentages are computed from;
* the per-slot search results are cut to **the top 25 candidates per slot**, which
  necessarily includes each slot's top pick and therefore preserves every conclusion.

`tests/test_real_data.py` rebuilds the index from that fixture and asserts the same
54 top picks **with the same rank scores**. The numbers in the README are no longer
assertions about the past; they are a test that runs on every push. It also turned
out to be the sharpest regression test in the suite — it fails on real data if
scoring or relevance ordering drifts, where the synthetic sample might not notice.

---

## Part 2b — Two defects found only after publishing

Both were caught by the first CI run on GitHub, not by any of the 152 tests that
passed locally. That is the point of the two that follow.

### 15. The metadata advertised a Python version the code could not run on

**Symptom.** CI was red on Python 3.10 for all three operating systems while 3.12
passed everywhere. Every test passed locally, because the local interpreter is 3.12.

**Cause.** One f-string contained a backslash inside its replacement field:

```python
f"  - domain/{re.sub(r'[\s/]+', '-', domain_name).lower()}"
```

Backslashes inside f-string expressions were only allowed in **Python 3.12** (PEP
701). On 3.10 and 3.11 this is a `SyntaxError` at import time — the whole package
fails to load:

```
SyntaxError: f-string expression part cannot include a backslash
```

`pyproject.toml` declared `requires-python = ">=3.10"`. The metadata was untrue, and
nothing in the test suite could have caught it.

**Aggravating factor.** Two attempts at static detection both missed it:

* `ast.parse(source, feature_version=(3, 10))` accepts the file. The
  `feature_version` argument narrows the grammar but does not enforce this
  particular restriction.
* A grep for APIs added after 3.10 (`tomllib`, `typing.Self`, `datetime.UTC`, …)
  found nothing, because this is syntax, not an API.

**What actually found it.** Downloading a Python 3.10 interpreter and running the
suite under it. 8.2 MB and two minutes, versus guessing from a 403 on the log
download.

**Fix.** Hoist the expression out of the f-string, with a comment explaining why.

**Lesson.** A version floor in package metadata is a **testable claim**, and the only
test for it is running on that version. Declaring `>=3.10` while testing on 3.12 is
not a smaller version of the same test — it is a different claim.

**Follow-on.** The CI matrix ran 3.10 and 3.12 and therefore tested two of the
three affected versions. It now runs 3.10, 3.11 and 3.12 — the middle one existed
precisely because a matrix built from "oldest and newest" leaves a gap.

### 16. Chinese output crashed on Windows whenever stdout was a pipe

**Symptom.** The same CI run failed the *offline demo* step on Windows/py3.12:

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 0-73
```

**Cause.** Python on Windows writes `stdout` using the locale's code page — cp1252
on an English install. This project prints Chinese. When GitHub Actions captures
output, `stdout` is a pipe, so the console's UTF-8 handling never applies and the
encoding is cp1252, which cannot represent any of it. The first `print` of a
box-drawing line killed the process.

This was not a CI-only problem: running `python examples/demo.py` in a default
English-Windows terminal would have failed the same way for a real user.

**Fix.** Two parts, because there are two audiences:

* the code calls `ensure_safe_output()`, which sets `errors="replace"` on
  `stdout`/`stderr` — **keeping the existing encoding**. Unencodable characters
  become `?` instead of an exception. Replacing the encoding with UTF-8 would have
  broken the *working* case: a Chinese Windows console (cp936) renders Chinese
  correctly today, and would show mojibake if the encoding were forced.
* the workflow sets `PYTHONIOENCODING=utf-8`, so CI logs keep the full characters
  rather than a row of question marks.

**Lesson.** "It works on my machine" is partly a statement about the **encoding of
stdout**, which differs between a terminal, a pipe, and a CI runner. The interesting
part is that the safe fix is not "force UTF-8 everywhere" — it is "stop crashing,
without taking away the case that already worked".

---

## Part 4 — Two structural lessons

**Cross-validate independent criteria; report the disagreements.** The zero in
Part 1 is the most valuable number in this project, and it only exists because two
filters were built on different kinds of evidence (linguistic vs physical) and then
compared. A single filter, however well tuned, cannot report its own false-positive
rate.

**Prefer facts that can be re-checked by hand.** Every component of the score —
stars, forks, license, size, last push — is visible on the repository page. A
reviewer can disagree with the weights, but cannot dispute the inputs. That is the
property that makes the ranking arguable rather than merely asserted, and it is why
"the description sounded AI-generated" is only ever a supporting signal here.
