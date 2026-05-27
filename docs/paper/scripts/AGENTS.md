<!-- Parent: ../AGENTS.md -->
<!-- Updated: 2026-05-27 -->

# scripts

## Purpose
Chart generation and video production scripts for the research paper.

## Key Files

| File | Description |
|------|-------------|
| `generate_abstract_video.py` | Generates 50-second 1080p H.264 abstract overview video |
| `generate_charts.py` | Generates all paper figures from experiment data |
| `video_script.md` | Script for the abstract video narration |

## For AI Agents

### Working In This Directory
- Read `../data/` for input, write to `../figures/` for output
- Run with `python generate_charts.py` from this directory
- Video generation requires ffmpeg