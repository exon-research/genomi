# Genomi Output Rules

Output standards for all Genomi skills.

## Directness

Start with the answer. Mention Active Genome Index use only when it materially
affects the result, a limitation, a blocker, or a required next action. Put
command names, local paths, and provenance mechanics after the meaning.

## Response Depth

Follow the user's current-chat response-depth preference when one is known.
Use the host response profiles in
`src/genomi/runtime/host_response_profiles.json` when available. If none is
known, use the default profile without asking a standalone style question.

Style never overrides evidence limits, answer-confidence judgments, privacy
boundaries, or clinical-confirmation language.

## Tool Disclosure

- Genomi tools return one presented shape for normal CLI or MCP calls.
- Use `--debug-raw` only for local CLI debugging when inspecting uncompacted
  result dictionaries. That path is not exposed through MCP.
- Do not paste local artifact paths into user-facing answers unless the user is
  rebuilding, validating, or debugging local artifacts.

## Answer Quality

- Use supported medical conclusions only.
- Keep prose concise and specific.
- Use real dates from sources or omit dates.
- Use personal risk percentages only when a cited source supports them.
- Use absence language with callability or callset limits.
- Keep broad source rows and raw candidate dumps out of chat.

## User-facing terms

Translate internal vocabulary:

- “your genome source file” before `VCF`.
- “a public database of lab-submitted variant reports” before `ClinVar`.
- “one copy has this change” before heterozygous or `0/1`.
- “both copies have this change” before homozygous or `1/1`.
- “uncertain meaning” before VUS.
- “read support and genotype quality from the lab file” before DP/GQ.

## Evidence format

Each answer should include:

- Evidence classes used: sample observation, callability, ClinVar/static,
  population frequency, GWAS, reviewed source, or limitation.
- Evidence implications: answer support, parse/digitize, genotype support,
  callability, source review, clinical confirmation, or report rendering.
- Active Genome Index status only when it materially affects those evidence
  classes or implications. Do not include a routine statement that no Active
  Genome Index was used.

## Privacy

After `genomi.parse_source`, refer to the Active Genome Index.
Surface the original intake path for rebuild or validation work. External
search receives selected public targets only unless the user explicitly chooses
to share broader private context.
