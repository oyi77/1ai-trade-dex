# PolyEdge Research Paper

## Overview

This directory contains the source files for the research paper:
**"PolyEdge: Autonomous Prediction Market Trading with Bounded AGI Safety, Evolutionary Strategy Composition, and Adversarial Decision Validation"**

## Files

| File | Description |
|------|-------------|
| `paper.tex` | Main LaTeX source file (assembles all sections) |
| `paper.bib` | BibTeX bibliography (15 verified references) |
| `paper.pdf` | Compiled PDF (33 pages) |
| `sections/sec3_architecture.tex` | System Architecture (Section 3) |
| `sections/sec4_autonomy.tex` | AGI Autonomy with Hard Safety Boundaries (Section 4) |
| `sections/sec5_evolution.tex` | Evolutionary Strategy Composition (Section 5) |
| `sections/sec6_debate.tex` | Dual-Debate Decision Validation (Section 6) |
| `sections/sec7_results.tex` | Experiments & Results (Section 7) |
| `sections/sec8_discussion.tex` | Discussion & Future Work (Section 8) |
| `sections/sec9_manifesto.tex` | Manifesto (Appendix) |
| `figures/architecture.pdf` | System architecture diagram |
| `figures/autonomy_pipeline.pdf` | ADR-006 experiment lifecycle pipeline |
| `figures/genome.pdf` | StrategyGenome chromosome structure |
| `figures/debate_flow.pdf` | MiroFish dual-debate flow |
| `figures/performance.pdf` | Performance chart (real data from metrics.csv) |
| `figures/experiments.pdf` | Experiment lifecycle heatmap (real data) |
| `figures/strategy_distribution.pdf` | Strategy distribution chart (real data) |
| `data/metrics.csv` | Extracted dashboard metrics |
| `data/experiments.json` | Experiment summary from SQLite DB |
| `data/system_stats.json` | Codebase scale metrics |
| `manifesto.md` | Standalone manifesto document |
| `supplementary_video.mp4` | 50-second abstract video (1920x1080, H.264) |
| `supplementary/supplementary.tex` | Supplementary material LaTeX source |
| `supplementary/supplementary.pdf` | Supplementary material PDF (8 pages) |
| `scripts/generate_charts.py` | Chart regeneration script (matplotlib) |
| `scripts/generate_abstract_video.py` | Abstract video generation script |
| `scripts/video_script.md` | Video narration script |

## Compiling

```bash
cd docs/paper
pdflatex paper.tex
bibtex paper
pdflatex paper.tex
pdflatex paper.tex
```

Or with `latexmk`:
```bash
latexmk -pdf paper.tex
```

For the supplementary material:
```bash
cd supplementary
pdflatex supplementary.tex
bibtex supplementary
pdflatex supplementary.tex
pdflatex supplementary.tex
```

## Dependencies

- `pdflatex` (TeX Live or MiKTeX)
- Standard packages: `amsmath`, `amsthm`, `graphicx`, `hyperref`, `natbib`, `booktabs`, `tikz`
- For chart regeneration: `matplotlib`, `numpy`, `pandas`, `seaborn`
- For video regeneration: `matplotlib`, `ffmpeg`, `numpy`, `Pillow`

## Abstract Video

The `supplementary_video.mp4` is a 50-second visual abstract of the paper. It can be regenerated:

```bash
cd docs/paper
source ../../venv/bin/activate
python scripts/generate_abstract_video.py
```

The video covers:
1. Title card with author
2. Problem statement with honest performance data
3. Three safety pillars (Bounded Autonomy, Evolution, Debate)
4. Live deployment results
5. Open source call to action

## arXiv Submission

Categories: `cs.AI`, `q-fin.TR`, `cs.LG`

Upload `arxiv-submission.tar.gz` which contains:
- `paper.tex`, `paper.bib`, `paper.pdf`
- All section `.tex` files
- All figure `.pdf` files
- Data files

## Zenodo Artifact

`supplementary.zip` contains the complete artifact including:
- All LaTeX source files (main paper + supplementary)
- Compiled PDFs (main + supplementary)
- All figures
- Data files
- Abstract video
- Chart and video generation scripts
- Narration script

## Data Provenance

All metrics and experiment data were extracted from the live PolyEdge deployment at `polyedge.aitradepulse.com` and the SQLite database `data/polyedge.db`. No data was fabricated.

## License

MIT - same as the PolyEdge project.