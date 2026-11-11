# 21 — THE CI: THE ARCHITECTURE MAP

<docsys kind="arch-map" role="instance"/>

TRIGGER:[a change to `../../DESIGN.md` that adds, removes or re-wires a trigger, a workflow, a tier or a repo policy
(⇒ redraw here, same turn)]

Arrows point from what fires to what it runs. Everything under REVIEWER REPO runs on the public `sancovp/cicd-reviewer`.

```mermaid
flowchart TB
  classDef session fill:#ede7f6,stroke:#4527a0;
  classDef trig fill:#e3f2fd,stroke:#1565c0;
  classDef ai fill:#fce4ec,stroke:#ad1457;
  classDef det fill:#e8f5e9,stroke:#2e7d32;
  classDef dep fill:#fff8e1,stroke:#ff8f00,stroke-dasharray:4 3;

  SESSION["a session — works on a branch, opens its PR READY when done (a DRAFT = parked), fixes BLOCKING, resolves conflicts; merges only as the queue by hand"]:::session
  BYHAND["the QUEUE BY HAND (§5) — only while GitHub Actions starts no job: the session reads each ready PR, posts its verdict on the tip, merges a clean, fresh one as a squash labelled review-owed, comments a BLOCKING or CONFLICT one, parks or sends to its source what §8 never merges"]:::session
  subgraph HOME["THE CANONICAL HOME (private, billed)"]
    TRIG["cicd-review-on-pr.yml — a ready PR opened / marked ready / pushed; never a draft, never om-is-the-base · the SkillTree gate, then a dispatch"]:::trig
  end
  subgraph REV["REVIEWER REPO (public, free minutes)"]
    REVIEW["review.yml → the REVIEWER (MODE=review) — one PR, its verdict on the exact tip; run checked on GitHub, retried once · first outage.py asks whether the model answers: down ⇒ VERDICT: UNREVIEWED, no model · a merged review-owed PR ⇒ its late review (MODE=review-merged), a BLOCKING one opening a Fix owed issue"]:::ai
    QUEUE["merge-queue.yml → merge_queue.py — one run per repo at a time: ready (CLEAN, or UNREVIEWED with its checks passed; never from the standing or the Pages source branch) · fresh · grouped by shared files · squash at the reviewed tip · an UNREVIEWED merge labelled review-owed"]:::det
    COORD["the COORDINATOR (MODE=coordinate) — overlapping ready PRs: their order, any holds"]:::ai
    SWEEP["sweep.yml → sweep.py — daily, every source repo, every branch but the default, the standing and the Pages source: delete merged branches · park drafts · open missing PRs · dispatch reviews · hand CLEAN PRs to the queue"]:::det
    ISSUE["UNMERGED WORK — STUCK · PARKED · REVIEW OWED (an issue on the canonical home; every sweep keeps the oldest open one and closes any other as its duplicate)"]:::det
  end
  GH["GitHub · SEAM: PRs, reviews, merges, the GraphQL comparison"]:::dep
  MODEL["MiniMax · SEAM: the model behind both AI tiers"]:::dep

  SESSION -->|"opens a ready PR"| TRIG
  TRIG -->|"dispatch review-pr"| REVIEW
  REVIEW -->|"hand off"| QUEUE
  QUEUE -->|"only when ready PRs overlap"| COORD
  QUEUE -->|"not fresh / after a merge: review again"| REVIEW
  SWEEP -->|"dispatch review-pr, spaced — and the late review of every merged review-owed PR"| REVIEW
  SWEEP -->|"merge-queue"| QUEUE
  SWEEP --> ISSUE
  ISSUE -->|"read first by the next session in that repo"| SESSION
  REVIEW --> GH
  QUEUE --> GH
  SWEEP --> GH
  REVIEW --> MODEL
  COORD --> MODEL
  SESSION -->|"Actions starts no job"| BYHAND
  BYHAND -->|"verdicts, merges, labels, comments"| GH
  BYHAND -.->|"its review-owed merges, read once jobs start again"| REVIEW
```
