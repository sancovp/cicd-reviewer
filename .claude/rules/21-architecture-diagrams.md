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

  SESSION["a session — works on a branch, opens its PR READY when done (a DRAFT = parked), fixes BLOCKING, resolves conflicts, never merges"]:::session
  subgraph HOME["THE CANONICAL HOME (private, billed)"]
    TRIG["cicd-review-on-pr.yml — a ready PR opened / marked ready / pushed; never a draft, never om-is-the-base · the SkillTree gate, then a dispatch"]:::trig
  end
  subgraph REV["REVIEWER REPO (public, free minutes)"]
    REVIEW["review.yml → the REVIEWER (MODE=review) — one PR, its verdict on the exact tip; run checked on GitHub, retried once"]:::ai
    QUEUE["merge-queue.yml → merge_queue.py — one run per repo at a time: ready · fresh · grouped by shared files · squash at the reviewed tip"]:::det
    COORD["the COORDINATOR (MODE=coordinate) — overlapping ready PRs: their order, any holds"]:::ai
    SWEEP["sweep.yml → sweep.py — daily, every source repo: delete merged branches · park drafts · open missing PRs · dispatch reviews · hand CLEAN PRs to the queue"]:::det
    ISSUE["UNMERGED WORK — STUCK · PARKED (an issue on the canonical home)"]:::det
  end
  GH["GitHub · SEAM: PRs, reviews, merges, the GraphQL comparison"]:::dep
  MODEL["MiniMax · SEAM: the model behind both AI tiers"]:::dep

  SESSION -->|"opens a ready PR"| TRIG
  TRIG -->|"dispatch review-pr"| REVIEW
  REVIEW -->|"hand off"| QUEUE
  QUEUE -->|"only when ready PRs overlap"| COORD
  QUEUE -->|"not fresh / after a merge: review again"| REVIEW
  SWEEP -->|"dispatch review-pr, spaced"| REVIEW
  SWEEP -->|"merge-queue"| QUEUE
  SWEEP --> ISSUE
  ISSUE -->|"read first by the next session in that repo"| SESSION
  REVIEW --> GH
  QUEUE --> GH
  SWEEP --> GH
  REVIEW --> MODEL
  COORD --> MODEL
```
