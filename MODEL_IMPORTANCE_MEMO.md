# The Harness Can Matter More Than the Model

**Internal engineering memo — what we learned about LLM model importance from the benchmark runs**
*Scope: BU Bench V1 (100 clean-automation tasks) and Stealth Bench V1 (80 anti-bot tasks), run locally on Steel + browser-use, cross-referenced with the published BU Bench result set. Figures are from our own runs unless tagged “published.”*

---

## TL;DR

- **Model choice is a real and powerful lever — but it is not *the* lever.** Whether it matters most, a little, or almost not at all depends on what is actually capping your agent: the **model tier**, the **harness**, or an **environmental floor**.
- **When you’re already at the frontier tier, swapping harnesses beats swapping frontier models.** Same model (opus-4-7) scored **86 / 74 / 65** across bcode / ClaudeCodeHarness / browser-use on BU Bench — a **21-point spread from scaffolding alone** — larger than the gap between most frontier models on the same harness.
- **Hit an environmental floor and the model barely matters.** On Stealth Bench, Claude Opus 4.8 and GLM-5.2 scored **identically (52/80)**. Their per-task agreement (79%) was no higher than running the *same* model twice (81%). The captcha floor — not the model — sets the ceiling.
- **At the frontier, “a better model” mostly buys efficiency, not accuracy:** Opus matched GLM-5.2’s score in **~30% fewer steps**, **~30% fewer LLM calls**, and **~2.3× fewer completion tokens**.
- **Single-run rankings are noise.** Same model, same config, different runs disagreed on **15–20% of tasks** — the same magnitude as cross-frontier-model differences. Rank on multiple runs or don’t rank at all.

---

## The setup

We ran two benchmarks:

| Benchmark | What it tests | Floor |
|---|---|---|
| **BU Bench V1** (100 tasks) | Clean browser automation: navigate, search, extract, multi-step reasoning | None — the site cooperates |
| **Stealth Bench V1** (80 tasks) | Same kind of task, but behind live anti-bot protection (Cloudflare, PerimeterX, DataDome, hCaptcha, Arkose, Imperva, Kasada) | **Captcha / anti-bot walls** |

Agents were driven through the **browser-use** framework on the **Steel** stealth browser. Models spanned the frontier (Opus 4.8, GPT-5.5, Gemini 3.x Pro, GLM-5.2) down to small/cheap tiers (Haiku 4.5, GPT-5-mini/5.4-mini, Gemini 2.5 Flash, GLM-5.1).

The published BU Bench results let us also compare **agent harnesses** (browser-use vs ClaudeCodeHarness vs bcode) holding the model fixed — which is the crux of this memo.

---

## Finding 1 — On clean automation, model tier is the single biggest lever

Hold the harness fixed (browser-use) and sweep the model on BU Bench. The spread is enormous:

| Tier | Model | BU Bench score |
|---|---|---|
| Frontier | gpt-5.5 | **68** |
| Frontier | claude-opus-4-7 | 65 |
| Frontier | gemini-3.1-pro-preview | 59–62 |
| Frontier | gemini-3-flash-preview | 58–66 |
| Frontier | claude-sonnet-4-6 | 57–63 |
| Mid | gpt-5 | 46–56 |
| Mid | qwen3.6-plus | 53–56 |
| Mid | kimi-k2.5 | 41–45 |
| Mid | deepseek-v4-pro | 45 |
| Mid | grok-4.20 | 35–43 |
| Weak | gemini-2.5-flash | 30–38 |
| Weak | gpt-5-mini | 35–39 |
| Weak | glm-5.1 | **16–34** |
| Weak | gpt-4.1 | 24–28 |
| Weak | minimax-m2.7 | 23–31 |
| Weak | claude-haiku-4-5 | 15–24 |
| Weak | gpt-5.4-mini | 19–23 |

That is roughly a **50-point spread (≈16% → ≈68%)** driven by model alone. **Crossing a capability tier is the highest-leverage model decision you can make.** If your agent is on a weak tier, nothing else you do matters as much as getting off it.

---

## Finding 2 — But at the frontier tier, the harness can beat the model swap

Here is the headline finding. Hold the model fixed at **opus-4-7** and sweep the *harness* on BU Bench:

| Harness | opus-4-7 score |
|---|---|
| bcode | **86** |
| ClaudeCodeHarness | 74 |
| browser-use | 65 |

**Same model. 21-point spread.** And the direction is consistent across model families — ClaudeCodeHarness with sonnet-4-6 (~65) also out-scored browser-use with sonnet-4-6 (~59).

Now compare that to **swapping frontier models on a fixed harness**:

- browser-use: opus-4-7 **65** vs gpt-5.5 **68** vs gemini-3-flash ~62 vs sonnet-4-6 ~59 → **frontier-vs-frontier gap ≈ 5–9 points.**

So at the frontier, **the harness you run on can move the score 2–4× more than which frontier model you pick.** The practical implication: if your team is spending its energy picking between Opus, GPT-5.5, and Gemini-Pro, you may be optimizing the smaller dial. The scaffolding — how the loop is structured, what tools/state the model sees, how errors and recovery are handled — is often the bigger lever once the model is competent.

> *Caveat: each harness cell above is largely a single run, and per-run variance is real (see Finding 5). Treat 65→86 as directional, not statistical. But it’s consistent across two model families and is large enough to take seriously.*

---

## Finding 3 — Hit an environmental floor and the model barely matters at all

Now move to Stealth Bench, where the *sites* fight back. Same harness, same browser, same 80 tasks — just swap the model:

| Model | Score | Steps | LLM calls | Completion tokens | Wall-clock |
|---|---|---|---|---|---|
| **Claude Opus 4.8** | **52 / 80 (65.0%)** | 918 | 857 | 471K | 23,066s |
| **GLM-5.2** (solver-off) | **51 / 80 (63.7%)** | 1,178 | 1,115 | 1.08M | 32,819s |
| **GLM-5.2** (solver-on) | **52 / 80 (65.0%)** | 1,327 | 1,259 | 1.21M | 34,007s |

**The model swap moved the score by one task.** It’s within noise.

Why? Because the failures aren’t model failures. **~90% of the failures on Stealth Bench are captcha / anti-bot walls** — PerimeterX “Press & Hold”, DataDome, hCaptcha, Arkose, Cloudflare Turnstile. Opus 4.8: 25 of 28 failures were explicit captcha blocks. GLM-5.2: 23–25 of its failures were the same. No matter how clever the model is, it cannot solve a PerimeterX press-and-hold challenge that lives inside a cross-origin iframe with a closed shadow DOM — which is exactly where these challenges live.

The cleanest proof that the **environment**, not the **model**, sets the ceiling: look at which tasks each model passed.

- Opus passes **but GLM fails**: tasks `2, 15, 33, 42, 47, 51, 62, 64, 73` (9 tasks)
- GLM passes **but Opus fails**: tasks `9, 20, 29, 31, 59, 63, 70, 72` (8 tasks)

That’s a **symmetric, near-random reshuffle** — 17 disagreements split 9/8. Both models solved roughly the same *kind* of task; which specific captcha instance fired on a given run is stochastic. (We verified separately that 7 of 11 PerimeterX-protected targets **weren’t even challenged** on a bare fresh stealth session — the challenges are triggered by agent behavior, not inherent to the destination.)

**The lesson: before you attribute a score gap to the model, identify the floor. If everything is dying on the same wall, the model isn’t your problem — the environment is.** On Stealth Bench, the levers that actually move the score are retry-on-challenge with a fresh session/proxy/fingerprint, and humanizing the agent’s action cadence so it doesn’t trip the detector in the first place — *not* the model. (We measured this directly: the Steel built-in captcha solver was a **no-op** here — solver-on 52 vs solver-off 51, captcha fails identical-to-worse.)

---

## Finding 4 — At the frontier, “better model” means efficiency, not accuracy

When two frontier models converge on the same pass-rate, don’t conclude the model doesn’t matter. It matters in a different dimension:

| Metric | Opus 4.8 | GLM-5.2 (solver-off) | Ratio |
|---|---|---|---|
| Mean steps per **passed** task | 11.8 | 16.8 | Opus **~30% fewer** |
| Median steps per passed task | 10 | 14 | — |
| Total LLM calls | 857 | 1,115 | Opus ~23% fewer |
| Completion tokens | 471K | 1.08M | Opus **~2.3× fewer** |
| Prompt-cache hit rate | **66%** (11.9M of 18.0M cached) | none exposed | — |
| Wall-clock (80 tasks) | 23,066s | 32,819s | Opus ~30% faster |

Same score, but Opus is **more decisive**: fewer steps, terser output, and heavy use of prompt caching that a long agentic loop is uniquely positioned to exploit. In an agent that loops 800–1,300 times, completion-token verbosity and cache-hit ratio dominate cost and latency. **A model that emits half the tokens and finishes in 30% fewer steps is a different product economics**, even at identical accuracy.

So the model does matter at the frontier — but measure it on **tokens, steps, latency, and cost**, not just pass-rate, because pass-rate has already converged.

---

## Finding 5 — Variance is large; single-run rankings are a trap

This is the methodological warning underpinning all of the above. Run the **same model, same config** twice and look at task-level disagreement:

- **GLM-5.2 solver-on vs solver-off** (same model, two full runs): **81% task agreement** — 15 tasks flipped.
- **Opus 4.8 vs GLM-5.2** (different models): **79% task agreement** — 17 tasks flipped.

**Cross-model disagreement was no larger than same-model run noise.** On a floored benchmark like this, that is the honest read: you cannot rank these two frontier models apart at n=1.

The published BU Bench runs show the same effect on a clean benchmark — wide per-run scatter for a fixed model:

- gpt-4.1: 24, 25, 28, 28, 24
- glm-5.1: 16, 25, 34 *(an 18-point range on the same model)*
- ChatBrowserUse-1: 37 → 58 across 13 runs
- claude-sonnet-4-5: 54–60

**Implication: any model comparison based on a single run per model is unreliable below a ~10-point gap, and meaningless below ~5.** Rank models on the mean of multiple runs, and report variance alongside the mean. The cleanest comparisons we have are the ones where one variable is held truly fixed — which is exactly why the harness comparison (Finding 2) and the Stealth head-to-head (Finding 3) carry weight despite single runs: they isolate one factor.

---

## A mental model: floor, ceiling, and three dials

Stop treating “the model” as a single knob. An agent’s score is bounded by three things, and your job is to know which one is binding:

```
   ┌────────────────────────── CEILING ───────────────────────────┐
   │  set by the HARNESS (scaffolding, tools, recovery, context)   │
   │                                                              │
   │    … the agent operates in here …                            │
   │                                                              │
   │  set by the MODEL (reasoning, tool-use, decisiveness)        │
   │                                                              │
   │    … up against …                                            │
   │                                                              │
   │  set by the ENVIRONMENT FLOOR (captcha, logins, WAFs, rate   │
   │  limits, site availability)                                  │
   └────────────────────────────────── FLOOR ─────────────────────┘
```

- **The model tier is the biggest lever only when nothing else is binding** — i.e., on clean tasks (BU Bench), where crossing weak→frontier is worth ~50 points.
- **The harness becomes the biggest lever once the model is frontier-tier**, because model-vs-model gaps compress to single digits while harness gaps stay in the teens-to-twenties.
- **The environment floor trumps everything**: when tasks die on captcha, both model and harness are irrelevant until you fix the floor. We saw the browser’s stealth flag alone move GLM-5.2 from **41/80 → 51/80** on Stealth Bench — a +10-point / +25%-relative lift with *zero* model change.

The diagnostic question to ask before optimizing: **on the failing tasks, what actually killed them?** Tally the failure reasons. If it’s “blocked by captcha / login / WAF,” fix the floor. If it’s “looped forever / took a wrong action / misread the page,” the harness or model is binding. We wasted real effort tuning a captcha solver that was a no-op because we hadn’t checked that the failures were environment-floored.

---

## Practical recommendations

1. **Rank models on multiple runs, report variance.** Below a ~10-point mean gap, don’t claim a winner at n=1. Our cross-model “gap” on Stealth Bench (52 vs 51) is indistinguishable from run noise (79% vs 81% agreement).
2. **Before swapping models, profile the failure reasons.** If failures cluster on an environmental wall (captcha/login/WAF/timeout), the model isn’t your lever — fix the floor (retry with fresh session/proxy/fingerprint; humanize action cadence). We measured the Steel captcha solver as a no-op on this benchmark; don’t repeat that detour.
3. **Once you’re on a frontier model, invest in the harness next.** opus-4-7 went 65 → 86 by changing scaffolding, not the model. The harness is the higher-leverage dial at the frontier tier.
4. **Measure frontier-model differences on efficiency, not just accuracy.** Track steps/task, LLM calls, completion tokens, cache-hit rate, wall-clock, and $/task. Opus matched GLM-5.2’s score at ~2.3× fewer tokens and ~30% fewer steps — that’s the real “model advantage” once pass-rate has converged.
5. **Hold one variable fixed when you compare.** The only comparisons that survived scrutiny here were same-harness/model-sweep (Finding 1), same-model/harness-sweep (Finding 2), and same-harness+browser/model-sweep on a floored benchmark (Finding 3). Multi-variable changes are uninterpretable.
6. **Cross tiers aggressively, swap tiers rarely.** The 50-point model spread on BU Bench is almost entirely *between* tiers (weak→frontier), not *within* the frontier. Pick a frontier model, then stop fiddling with model identity and start fiddling with everything else.

---

## Appendix — the runs behind this memo

**Stealth Bench V1, browser-use + Steel (our runs):**

| Run | Model | Config | Score | Steps |
|---|---|---|---|---|
| 20260619_183920 | claude-opus-4-8 | framework, solver-off | 52/80 | 918 |
| 20260620_071023 | GLM-5.2 | framework, solver-off | 51/80 | 1,178 |
| 20260619_213449 | GLM-5.2 | framework, solver-on | 52/80 | 1,327 |
| 20260617_213610 | GLM-5.2 | raw browser, stealth-on | 51/79 | 1,175 |
| 20260618_134156 | GLM-5.2 | raw browser, stealth-off | 41/80 | 1,170 |

Per-task agreement: Opus-vs-GLM(solver-off) = 79% (17 disagreements, 9/8 symmetric split); GLM solver-on-vs-off (same model, repeatability) = 81% (15 disagreements). Stealth failures ~90% captcha/anti-bot for both models.

**BU Bench V1, published results (browser-use harness unless noted):**

- Harness sweep, fixed model opus-4-7: bcode **86**, ClaudeCodeHarness 74, browser-use 65.
- Model sweep, fixed harness (selected): gpt-5.5 68, opus-4-7 65, gemini-3.1-pro ~60, sonnet-4-6 ~59, gpt-5 ~52, kimi-k2.5 ~43, glm-5.1 ~25, gpt-4.1 ~26, haiku-4-5 ~20, gpt-5.4-mini ~21, minimax-m2.7 ~27, gemini-2.5-flash ~35.

Artifacts: `results/` (summaries), `run_data/` (per-task traces, gitignored), archived full runs in the `bu-bench-results` repo.
