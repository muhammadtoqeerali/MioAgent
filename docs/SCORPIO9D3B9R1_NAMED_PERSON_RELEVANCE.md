# SCORPIO9D3B9R1 — Named-person live-research relevance correction

## Observed production defect (27 October 2026)

The B9 Chat research branch correctly fetched only public HTTPS pages and withheld
unsupported current-employment claims, but displayed the unrelated
`https://www.e-verify.gov/` as `[W1]` in response to a request about Muhammad
Toqeer Ali at KIOS Cyprus. The source did not mention the person and is not a
relevant employer/affiliation source. The generic topical search quality layer
could rank employment verification pages by words such as *verify* and *work*.

## Correction

For questions with extractable named people, use a focused quoted-name query,
and **require the complete person's name in the returned title/snippet** before
any page fetch or model inference. Accept exact Given–Middle–Surname or common
Surname–Given–Middle formats. If all returned records are unrelated, try at most
one person-only quoted search. If none qualify, return an explicitly inconclusive
result **with no links to irrelevant sources**. No automatically generated URL,
privilege elevation, page instructions, filesystem access, or headless browser.

Normal non-person research follows the preexisting B9 pipeline. The strict
gate may exclude some valid organization-only directory listings; this is a
known conservative trade-off until a richer disambiguation model with tests is
available. Retrieved excerpts do **not** certify real-time employment. Only
verified excerpts are passed into the source-cited local-model research prompt.

## Operator workflow

Guarded source-only release, followed (if passed) by a separately approved
API-only restart with Chat and Work SQLite backups. No production user task is
created by the release or its acceptance. Existing services stay running.
