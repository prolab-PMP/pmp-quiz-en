---
title: "PMP Formulas Cheat Sheet: Earned Value, Communication Channels, and Estimation"
summary: "The handful of PMP formulas worth memorizing, what each one means, and how they appear in scenario questions."
date: "2026-06-12"
read_time: "7 min read"
keywords: "PMP formulas, earned value, EVM, communication channels, three point estimate, PMP math"
---

# PMP Formulas Cheat Sheet

You do not need to be a mathematician to pass the PMP exam, but a small set of formulas shows up often enough that memorizing them is worth the effort. More importantly, the exam usually tests whether you understand what a number *means*, not just whether you can plug values into a formula. This guide covers the formulas that earn the most points and how to read them.

## Earned value management (EVM)

Earned value is the most tested formula family. Three base values feed everything else:

- **Planned Value (PV):** the budgeted cost of work scheduled to be done by now.
- **Earned Value (EV):** the budgeted cost of work actually completed.
- **Actual Cost (AC):** the real money spent to complete that work.

From those three, you derive variances and indexes:

| Formula | Meaning | How to read it |
| --- | --- | --- |
| CV = EV − AC | Cost Variance | Negative = over budget |
| SV = EV − PV | Schedule Variance | Negative = behind schedule |
| CPI = EV ÷ AC | Cost Performance Index | Below 1.0 = over budget |
| SPI = EV ÷ PV | Schedule Performance Index | Below 1.0 = behind schedule |

A quick way to remember direction: for variances, **negative is bad**; for indexes, **below 1.0 is bad**. If a question says CPI is 0.85, the project is spending 85 cents of value for every dollar spent, so it is over budget.

## Forecasting (EAC and friends)

When a question asks "how much will this project cost in total now," it is testing forecasting:

| Formula | When to use |
| --- | --- |
| EAC = BAC ÷ CPI | Current cost performance will continue |
| EAC = AC + (BAC − EV) | The remaining work will go as originally planned |
| ETC = EAC − AC | Estimate left to finish |
| VAC = BAC − EAC | Variance at completion |

BAC is the Budget at Completion, the original total budget. The trick is reading the scenario to decide which EAC assumption applies.

## Communication channels

A favorite quick question: how many communication channels exist in a team of *n* people?

> Channels = n × (n − 1) ÷ 2

For 6 people that is 6 × 5 ÷ 2 = 15. The exam often asks how many channels are *added* when the team grows, so calculate both sizes and subtract. Adding one person to a team of 6 (15 channels) to make 7 (21 channels) adds 6 channels.

## Three-point estimation (PERT)

When a task has uncertainty, PMP uses three estimates: optimistic (O), most likely (M), and pessimistic (P).

| Formula | Name |
| --- | --- |
| (O + 4M + P) ÷ 6 | Beta / PERT estimate |
| (O + M + P) ÷ 3 | Triangular estimate |
| (P − O) ÷ 6 | Standard deviation |

The beta formula weights the most likely value heavily, which is why it is the default in most questions.

## Procurement and value

A few smaller formulas appear in cost and procurement questions. Point of Total Assumption (PTA) shows up in fixed-price incentive contracts, and present value or benefit-cost ratio appears in project selection. For most candidates these are lower priority than EVM and communication channels.

## How to study formulas

Do not memorize formulas in isolation. Practice them inside scenario questions so you learn to recognize *which* formula a question is really asking for. A question that mentions "we have spent more than planned for the work done" is a CV or CPI question even if it never uses the word variance. On PMP Quiz you can filter practice toward calculation-style questions and review each one until the meaning, not just the math, is automatic.
