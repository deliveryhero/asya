---
title: "Research: Qodo free tier for open source — feasibility & adoption"
status: open
priority: 4 # backlog
---

## Summary

Qodo offers **genuine free automated PR reviews for open source** via GitHub App, backed by Google Cloud (Gemini partnership June 2025). Free tier includes multi-agent code review (style, testing, security, performance), severity-based prioritization, `/improve` command for code suggestions, and 250 LLM credits/month.

## Key Findings

### ✅ Verified Claims (High Confidence)
- **Multi-agent reviews**: Evaluates code style, testing, security, performance across all PRs
- **Features**: Priority-based feedback, `/improve` command for inline suggestions, 250 LLM credits/month
- **Setup**: 3-step GitHub App install → select repos → enable reviews
- **Phased adoption**: Start with PR automation (Merge), add IDE assistance (Gen), batch tasks (Command) later

### ⚠️ Critical Constraint
**30 PRs/month per organization** — exhausts quickly for active teams:
- 5-person team at 2 PRs/person/day → ~3 working days to hit limit
- Free tier viable only for POC/pilot, not sustained CI/CD

### 🤔 Unanswered
1. Eligibility criteria (min GitHub stars, public repo requirement)
2. Current product state (Merge/Gen/Command still separate or unified?)
3. Which exhausts first: 30 PR cap or 250 credit limit
4. Calendar month vs. rolling allocation

## Research Details

- **Deep research**: 5 search angles, 17 sources fetched, 81 claims → 10 confirmed, 15 killed after 3-vote adversarial verify
- **Sources**: Qodo official (pricing, solutions, docs), GitHub Marketplace, secondary (Milestone, AISO Tools, DEV)
- **Confidence**: High on core free tier existence; medium on adoption sequence (secondary analysis, not Qodo docs)

## Recommendations

1. **Test eligibility** on Asya repo — install app, verify free tier activates
2. **Measure usage** over 1-2 weeks (you'll hit 30 PR limit fast; data informs ROI)
3. **Contact Qodo** with actual PR velocity — explore sponsorship or reduced licensing
4. **Evaluate alternatives** (CodeRabbit, GitHub Copilot, etc.) given constraint

## References
- [Qodo Open Source](https://www.qodo.ai/solutions/open-source/)
- [GitHub App](https://github.com/apps/qodo-free-for-open-source-projects)
- [Pricing](https://www.qodo.ai/pricing/)
