# Decisions — polyedge-32-fixes

## 2026-05-08 Session
- Wave execution order: W1 → W2 → W3 → W4 → W5 → Final
- T2 depends on T1 (needs clamp_probability)
- All other Wave 1 tasks are independent and can run in parallel
