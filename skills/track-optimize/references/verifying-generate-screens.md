# Verifying `generate` screens — what the synthetic panel cannot see

The focus-group panel scores a **transcript of design intent**. It reads copy. It cannot see that a
grounding join returned nothing, that a wage figure is invented, that a rating never saved, or that a
widget ignored its option array. That whole class of defect is invisible to it.

Evidence from the Welcome v8 rebuild (2026-07-28): the panel scored the track **12/16** and did not
notice that the career screen was **showing fabricated wages to every member**. One mechanical pass
against the grounding snapshot found it immediately.

A second reason not to lean on the score alone: it **anti-correlates with completion**. The live
Welcome version scored 7/16 and completes at ~79%. A 16/16 version has never shipped.

Panel first for copy, tone and pacing. Then this, before anything is called ready.

---

## 1. The proxy call, exactly

`generate` substeps are served by **`POST https://studio.nsls.org/api/generate`**. This is not the MCP
endpoint and not `Authorization: Bearer`.

```
Header:  X-Proxy-Token: $STUDIO_MCP_TOKEN
Body:    {"type":"generate","template":<aiPromptConfig.template>,
          "profile":<slug → answer map>,"grounding":<substep's grounding spec>}
Returns: plain text, streamed. NOT JSON.
```

Reference implementation is `streamFromProxy` in `skills/track-prototype/prototype/player.js`. Expect
HTTP 429 after roughly 15 rapid calls; back off ~20s and space calls ~6s.

## 2. Confirm figures are actually arriving

Send a probe template before trusting any prose output:

```
List EXACTLY the labor-market figures supplied to you, verbatim, one per line.
If none were supplied, output the single word NONE. Output nothing else.
```

If this returns `NONE`, the screen is ungrounded and every number in the real output is invented.

**`grounding.from` join rules**, established by probe (same profile, same spec, only the answer shape
changed):

| `from.major` points at | Result |
|---|---|
| a `multi-select-list` answer (an **array**) | **no figures** |
| a plain string answer | resolves |
| `"education"` (the whole structured answer) | **no figures** |
| **`"education.major"`** (subfield path) | **resolves** |

Subfield addressing works and is undocumented. The array case fails **silently**: an empty payload,
no error, so the track looks authored-correctly and the model fills the gap by inventing.

## 3. Diff every printed number against the snapshot, in code

Never by eye. Load `skills/value-moment/data/grounding-snapshot.json`. Then, for each printed
figure, **resolve the occupation the prose attributes it to** and assert the figure matches
*that* entry — `majors[cip].careers[<that occupation>].medianWageAnnual`, or
`stateWages[<that occupation's soc>][ST]` for a state figure. Assert each named occupation
appears in that major's career list too; models add plausible neighbours that were never supplied.

**Pair the number to the name — don't just check set membership.** "Does this figure appear
somewhere in `careers[*]`?" plus "does this occupation appear somewhere in `careers[*]`?" both
pass when the sentence names career A and prints career B's wage. That is a misattribution, and
it is indistinguishable from grounded output to a check that only asks whether each value exists
in the aggregate. A figure that resolves against the wrong occupation must **fail**.

Note this is a *different* failure from the fabricated `$146,910` placeholder in *Authoring
rules* below — there the
number existed nowhere in the snapshot, so a membership check catches it. Misattribution uses only
real values, so membership checks pass it through. You need both assertions.

## 4. Test the empty case

A field that grounds to nothing must print **no numbers at all**. Models fill silence by inventing.
Confirm this explicitly with an unmatchable field value.

Free-text majors resolve for only about **7 of 13** realistic member typings. `"Communication,
General"` resolves; **`"Communications"` does not**. When a match does occur it is semantically
correct, so the failure mode is silent-and-safe rather than wrong.

## 5. Run N≥6 per branch and count

These prompts are non-deterministic. Single runs mislead. The same template rendered real figures
4/6, then 7/8 after one instruction change. Report rates, not anecdotes.

## 6. Check the real answer data before trusting a persona

PostHog `substep_save_result` carries `track_slug`, `substep_slug` and `answer`. Two findings from
Welcome that no persona exercise would have produced:

- **~13% of rating answers save as `0`** — the wheel not registering. Any threshold logic must branch
  on *missing* before it branches on *low*, or it tells members they are unsure of their direction
  when they never said so.
- **The population skewed the opposite way from the personas.** 66% rated career direction 6+ and 63%
  rated job confidence 6+, so the modal member was the confident one, not the uncertain one every
  persona set centers.

Also check the merged-field trap: on a `dropdown-with-checkboxes` substep, nearly every row saved as
`{"dropdown":0}`. The checkboxes were filled and the rating was silently dropped.

---

## Authoring rules learned by measured failure

Each of these was proven by a re-run, not reasoned about.

**Give the model member-facing meaning, never authoring shorthand.** A segment documented as
"Seeker. Less pressure to decide; exploration made doable" is a note to ourselves. The model named
the label, had nothing sayable, and produced `"strength-based evidence"`. Write out what each segment
means *for the member*.

**Worked examples beat rules.** A 2x2 stated as prose bullets misclassified 2 of 2 test members. One
worked example per quadrant, plus a named check on the observed confusion, fixed it on the next run.

**Prohibitions get routed around by paraphrase.** Banning "some work history behind you" produced
"some work experience behind you." Ban the shape, list variants, and restate as a positive format
requirement with a self-check.

**Pushing hard for a specific fact induces fabrication.** Demanding a member's real job title
produced invented ones. Add an exact-copy rule plus a safe fallback, and accept the fallback.

**Never put a realistic placeholder number in a format example.** `$146,910` was written as an
illustration and emitted verbatim as a state median across two separate runs.

**Emphatic anti-invention framing suppresses real data too.** "An invented number is the worst thing
this screen can do" caused real supplied figures to be dropped on 2 of 6 runs. Prefer a positive
default: *if the figures block contains a median wage you MUST use it; only if it is literally empty
take the other path.*

**Unconditional phrasing overrides a later conditional.** "include the relevant sources for every
response" beat an "if pay isn't included, don't include" clause two lines down.

**A supplied payload can carry competing text.** The BLS block ships its own attribution string and
the model preferred it over the authored source line. Name it and forbid substituting it.

**Cap words and require a stand-alone first line.** A screen grew to 174 words as requirements
accumulated. A hard cap, plus "the FIRST sentence must stand alone as the whole point" and "never
write two sentences that make the same point," brought it to 95 words with every function intact.

**Give each screen a distinct remit.** A closing screen re-said what an earlier screen had already
said about the same inputs. Assign it different material.

---

## Record the run so calibration becomes measurable

Log every panel result with the `record_score_run` MCP tool, passing the `content_hash` of the exact
content scored. That is what pairs panel scores against live telemetry. Without it, "the rubric does
not predict completion" stays an anecdote instead of a curve.

Register the bet with `record_hypothesis`: weak step, the one change, predicted outcome, baseline.
