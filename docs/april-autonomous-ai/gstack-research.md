# GStack Research

By Garry Tan (YC CEO). MIT license. ~20K GitHub stars.
Repo: github.com/garrytan/gstack

## What It Is
Transforms Claude Code into a virtual engineering team via 21 specialized slash commands ("skills").
Each skill assigns a distinct persona: CEO, Designer, Engineering Manager, Release Manager, Doc Engineer, QA.

Already installed in our Claude Code setup — all 21 skills available.

## Key Skills for Our Use Case

### Planning Phase
| Skill | Role | Use For |
|-------|------|---------|
| `/office-hours` | YC Partner | Brainstorm ideas before coding. 3 alternative approaches. |
| `/plan-ceo-review` | CEO | 10x thinking. 4 modes: Expansion, Selective, Hold, Reduction. |
| `/plan-eng-review` | Staff Engineer | Lock architecture. ASCII diagrams. Edge cases. Test plan. |

### Build + Review
| Skill | Role | Use For |
|-------|------|---------|
| `/review` | Paranoid Staff Eng | Pre-landing PR review. N+1 queries, race conditions, security. |
| `/investigate` | Debugger | Root cause analysis. No fixes without investigation first. |

### Testing
| Skill | Role | Use For |
|-------|------|---------|
| `/qa` | QA Lead | Browser-based testing with real Chromium. Finds + fixes bugs. |
| `/qa-only` | QA Reporter | Same but report-only, no code changes. |

### Ship + Reflect
| Skill | Role | Use For |
|-------|------|---------|
| `/ship` | Release Manager | Sync main, run tests, push, open PR. |
| `/document-release` | Doc Engineer | Update README/docs to match shipped code. |
| `/retro` | Eng Manager | Weekly metrics, shipping streaks, test health trends. |

## CEO Review (`/plan-ceo-review`) Deep Dive
The flagship skill. Sequence:
1. Pre-review audit: git history, TODO/FIXME/HACK, CLAUDE.md, architecture
2. Nuclear scope challenge: "Is this the real problem or a symptom?"
3. 4 modes: Expansion (dream big), Selective (cherry-pick), Hold (bulletproof), Reduction (MVP)
4. 10-section review: architecture, security, data flow, performance, deployment, etc.

## Integration with Paperclip
- gstack = skills (what each agent knows how to do)
- Paperclip = orchestrator (who does what, when)
- When Paperclip spawns a `claude_local` agent in the project dir, it gets gstack skills automatically
- Also exists: gstack-auto (community) — spawns 3 parallel implementations, scores, picks winner

## Conductor Pattern
GStack supports 10-15 parallel Claude Code sessions. Each in its own workspace.
Manage like a CEO — check in on critical decisions, rest runs autonomously.
