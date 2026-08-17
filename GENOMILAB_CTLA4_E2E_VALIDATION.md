# GenomiLab CTLA4 demo end-to-end validation

Date: 2026-08-15 (America/Los_Angeles)

## Verdict

**Working recorded demo.** The final v5 run completed the synthetic CTLA4
investigation in the GenomiLab portal and produced a validated H.264 MP4. Minor
viewport-framing imperfections are accepted for this demo take; the essential
question, genome finding, evidence, iterative rounds, clinician questions, and
handoff controls are visible.

## Final run

- Run directory: `demo_artifacts/GenomiLab-CTLA4-recorded-demo-2026-08-15-final-v5`
- Investigation: `investigation-ca212abd45fd4a3c99ae1f141ddf26ed`
- Synthetic user: `user-caa8c842015c8784`
- Active AGI: `vcf-sha256-18474cd4c6f2179a7db4a19fe1208014a0e850ee649f90dced411a1c56e40e85`
- AGI snapshot: `agi-snapshot-sha256-0c5fdbc52518528f7256586000f155c1fdd48c76ba2f856d4ef8de08ff85eeef`
- Fixture scope: isolated one-variant synthetic recording twin; not a whole
  genome and not the user's private genome profile.

## Investigation completeness

- 1 patient question and 4 initial hypotheses.
- 3 persistent specialists.
- 3 completed rounds with 3 reports each, for 9 specialist reports.
- 5 final hypothesis states represented: candidate, open, rejected, supported,
  and weakened.
- Symptom-led candidate-gene searching surfaced heterozygous CTLA4 Q76H:
  `rs2469719303`, GRCh38 `2:203870704 G>C`, genotype `0/1`.
- 3 research artifacts: Genomi sequence-substitution verification, an
  illustrative precomputed ESM result, and an illustrative precomputed Proto
  result.
- Brief version 1 contains 8 chronology entries and 4 case-specific clinician
  questions.
- **Print / Save PDF** and **Download doctor brief (.html)** are present.
- Q76H remains classified as a variant of uncertain significance.

## Recording validation

- Video: `genomilab-ctla4-demo.mp4`
- Recording manifest: `recording-manifest.json`
- Capture method: 132 periodic in-app-browser viewport screenshots encoded as
  a screenshot timelapse; this is not a continuous screen recording.
- Frames: JPEG, 1280 × 720 presentation, 2 fps.
- Duration: 66.0 seconds, independently verified with `ffprobe`.
- Video: H.264, no audio, 3,859,885 bytes.
- MP4 SHA-256:
  `0610a4319f3c76f4200ea573ad67be433b50c4a93651bf5b6f79571b9887ad18`
- Recording-manifest SHA-256:
  `12aa4f78f6fe89241c510d80701a1e5c23bd67272b66cff3e7064ba7440f5988`
- Ordered-frame-set SHA-256:
  `96c39710b1d3635eacb76d47d5e1739deee283ba9b44bf65427aa6041d23744c`
- Capture-provenance SHA-256:
  `5b14796deb78c78fd90e490fbd7425435023c1bce46b94b0f492e4a46cf23e84`
- Actual browser capture span: 691.925 seconds; the MP4 presents each frame at
  a fixed 500 ms interval.
- Encoder: ffmpeg 8.1 with libx264/yuv420p and fast-start metadata.

The capture validator observed all 20 timeline events, classified the first 3
as pre-viewer setup, and verified one in-app-browser navigation for each of the
17 post-viewer stages. The final frame coverage extends well beyond the
required five-second post-completion hold.

## Visual and privacy review

The following final-take frames were inspected:

- `frame-000001.jpg`: opening patient workspace.
- `frame-000019.jpg`: bounded Active Genome Index Q76H finding.
- `frame-000024.jpg`: Paperclip literature evidence beside personal-genome
  evidence.
- `frame-000122.jpg`: brief with print and HTML download controls.
- `frame-000132.jpg`: case-specific clinician questions and linked patient
  records.

The completed portal text contains no approval, acknowledgement, unavailable,
or plan-acceptance scene. Artifact scans found no launch token, private VCF
filename, or private whole-genome path in the capture provenance, recording
manifest, or final report.

## Evidence fidelity

- Specialist orchestration is a scripted fixture walkthrough with three
  persistent roles.
- Paperclip is a curated replay from the checked evidence ledger.
- Genomi performs the local sequence-substitution verification.
- ESM and Proto are clearly scoped illustrative precomputed demo results.
- The ESM and Proto illustrations are nonclinical and do not determine the
  hypothesis board or clinician handoff.

The demo is research support, not diagnosis or treatment, and ends by asking
the patient to take the evidence-linked brief to an immunologist or clinical
geneticist.
