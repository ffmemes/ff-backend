---
id: ocr_length_preference_v1
status: inconclusive
hypothesis: OCR text length predicts like preference (prospective observational confirmation; protocol not committed)
primary_metric: positive-group effect (pp)
guardrails: late OCR <=5% (validity gate)
unit: user
variants: none (observational)
started: 2026-09-06
check_on: 2026-10-05
decided: 2026-10-05
result: +5.78 pp (95% CI +3.80 to +7.88), support 25/36, but late OCR 23.1% > 5% gate: invalid
learning: OCR coverage lag can invalidate text-feature readouts; check OCR freshness before reading them
code: 
readout: 
---

# OCR length preference v1

Concluded October 5, 2026: **quality_failed**. Recorded positive-group effect +5.78 pp (95% CI +3.80 to +7.88), support 25/36, but late OCR 23.14% positive / 22.84% overall exceeds the 5% validity gate. No confirmation, extension or ranking rollout. One-shot automation paused. The protocol and final-readout JSON (`docs/analyst/research/2026-09-06-ocr-length/`) were never committed to this repo; this note is the surviving record.

Prospective observational confirmation, with no recommendation treatment.

Observation: September 6 00:30 — October 4 00:30, 2026, Moscow. Final readout: October 5 10:00 Moscow. No interim outcome-based decisions. Keep all frozen users in reach denominators; do not extend or deploy ranking changes automatically.
