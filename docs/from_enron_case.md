# Lessons carried from the Enron case

The sibling repository `enron-case` was a header-only analysis of the public
Enron corpus. It is a different project, but three of its decisions carry over
directly to this framework.

1. **Use the smallest data that can answer the question.** There we read only
   envelope headers and never the body or Subject. Here playbooks declare
   `aggregate` or `metadata` by default; `identifier` and `content` are the
   exception and require purpose plus approval.

2. **Record the decision, not just the result.** There the dedup choice was
   documented with evidence, cost and the role of AI brainstorming. Here a
   playbook is the decision artefact: it is reviewable before execution, and
   `audit.explain` records what actually ran.

3. **Test the risk you claim to have mitigated.** There we published a linkage
   attack against our own pseudonyms. Here the `content_lookup` example exists
   specifically to show the engine denying content use without approval. A
   privacy control that has never failed a test is not evidence.

What does **not** carry over: pseudonym analysis, graph metrics and the 2001
finding. This repository is a general framework, not an Enron analysis.
