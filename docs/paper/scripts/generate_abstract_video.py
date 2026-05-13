#!/usr/bin/env python3
"""
Generate a 50-second abstract video for the PolyEdge research paper.

Requirements: matplotlib, numpy, Pillow, ffmpeg
Output: docs/paper/supplementary_video.mp4 (1920x1080, 30fps, H.264)
"""

from pathlib import Path

# Use Agg backend (no GUI)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.animation import FuncAnimation, FFMpegWriter

# --- Constants ---
W, H = 1920, 1080
FPS = 30
DPI = 100
FIG_W, FIG_H = W / DPI, H / DPI

# Colors (dark theme)
BG_COLOR = "#0a0a0a"
ACCENT = "#00b4d8"
ACCENT2 = "#48cae4"
ACCENT3 = "#90e0ef"
WHITE = "#ffffff"
GRAY = "#aaaaaa"
RED = "#ff6b6b"
GREEN = "#51cf66"
YELLOW = "#ffd43b"

# Data from live deployment
DATA = {
    "title": "PolyEdge",
    "subtitle": "Autonomous Prediction Market Trading",
    "author": "Muchammad Fikri Izzuddin",
    "experiments": 25,
    "trades": 162,
    "markets": 132,
    "win_rate": "35.7%",
    "total_pnl": "-$622.04",
    "strategies": 9,
    "pillars": [
        ("Bounded\nAutonomy", "Hard safety gates\nRisk profiles, promotion\npipeline, budget caps"),
        ("Evolutionary\nComposition", "StrategyGenome\nChromosomal mutation\n& crossover"),
        ("Adversarial\nValidation", "Dual-debate system\nBull vs Bear agents\nJudge verdict"),
    ],
    "conclusion": "Open source. Open data.\nOpen critique.",
}

# Scene timing (in seconds)
SCENES = [
    (0, 6, "title"),        # Title card
    (6, 15, "problem"),     # Problem statement
    (15, 30, "pillars"),    # Three pillars
    (30, 42, "results"),    # Results
    (42, 50, "call"),       # Call to action
]


def ease_in_out(t):
    """Smooth easing function."""
    return t * t * (3 - 2 * t)


def draw_text_centered(ax, text, y, fontsize=40, color=WHITE, weight="bold", alpha=1.0):
    ax.text(0.5, y, text, transform=ax.transAxes, fontsize=fontsize,
            color=color, weight=weight, ha="center", va="center", alpha=alpha,
            fontfamily="sans-serif")


def draw_scene_title(fig, ax, progress):
    """Scene 1: Title fade-in with geometric lines."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_facecolor(BG_COLOR)
    
    alpha = min(1.0, progress * 2) if progress < 0.5 else 1.0
    
    # Title
    draw_text_centered(ax, DATA["title"], 0.62, fontsize=80, color=ACCENT, weight="bold", alpha=alpha)
    draw_text_centered(ax, DATA["subtitle"], 0.50, fontsize=32, color=WHITE, weight="normal", alpha=alpha * 0.9)
    draw_text_centered(ax, DATA["author"], 0.38, fontsize=24, color=GRAY, weight="normal", alpha=alpha * 0.8)
    
    # Geometric accent lines
    line_alpha = alpha * 0.4
    for i in range(5):
        y = 0.25 + i * 0.12
        ax.plot([0.1, 0.9], [y, y], color=ACCENT, alpha=line_alpha * (1 - abs(i - 2) * 0.2),
                linewidth=0.5, transform=ax.transAxes)


def draw_scene_problem(fig, ax, progress):
    """Scene 2: Problem statement with data."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_facecolor(BG_COLOR)
    
    alpha = ease_in_out(min(1.0, progress * 1.5))
    
    draw_text_centered(ax, "Autonomous AI trading needs", 0.78, fontsize=36, color=WHITE, weight="normal", alpha=alpha)
    draw_text_centered(ax, "hard safety boundaries", 0.68, fontsize=48, color=RED, weight="bold", alpha=alpha)
    
    # Data boxes
    if progress > 0.3:
        data_alpha = ease_in_out(min(1.0, (progress - 0.3) * 2))
        metrics = [
            (f"{DATA['trades']} trades", ACCENT),
            (f"{DATA['win_rate']} win rate", YELLOW),
            (f"PnL: {DATA['total_pnl']}", RED),
        ]
        for i, (label, color) in enumerate(metrics):
            x_pos = 0.2 + i * 0.3
            ax.text(x_pos, 0.48, label, transform=ax.transAxes, fontsize=30,
                    color=color, weight="bold", ha="center", va="center", alpha=data_alpha)
    
    # Honest disclosure
    if progress > 0.6:
        disc_alpha = ease_in_out(min(1.0, (progress - 0.6) * 2.5))
        draw_text_centered(ax, "Early research. honest results.", 0.30, fontsize=22, color=GRAY, weight="normal", alpha=disc_alpha)


def draw_scene_pillars(fig, ax, progress):
    """Scene 3: Three pillars with icons."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_facecolor(BG_COLOR)
    
    draw_text_centered(ax, "Three Safety Mechanisms", 0.90, fontsize=32, color=WHITE, weight="bold", alpha=0.9)
    
    pillar_colors = [ACCENT, GREEN, YELLOW]
    icon_labels = ["[LOCK]", "[DNA]", "[VS]"]
    
    for i, (title, desc) in enumerate(DATA["pillars"]):
        # Staggered reveal
        pillar_progress = (progress * 3 - i) if progress > i / 3 else 0
        alpha = ease_in_out(max(0, min(1.0, pillar_progress)))
        
        x_center = 0.17 + i * 0.33
        
        # Pillar box
        rect = mpatches.FancyBboxPatch(
            (x_center - 0.14, 0.25), 0.28, 0.50,
            boxstyle="round,pad=0.02", facecolor=BG_COLOR,
            edgecolor=pillar_colors[i], linewidth=2, alpha=alpha * 0.8,
            transform=ax.transAxes
        )
        ax.add_patch(rect)
        
        # Icon
        ax.text(x_center, 0.68, icon_labels[i], transform=ax.transAxes,
                fontsize=36, ha="center", va="center", alpha=alpha)
        
        # Title
        ax.text(x_center, 0.55, title, transform=ax.transAxes,
                fontsize=20, color=pillar_colors[i], weight="bold",
                ha="center", va="center", alpha=alpha,
                linespacing=1.4)
        
        # Description
        ax.text(x_center, 0.40, desc, transform=ax.transAxes,
                fontsize=14, color=GRAY, ha="center", va="center", alpha=alpha * 0.9,
                linespacing=1.3)


def draw_scene_results(fig, ax, progress):
    """Scene 4: Architecture and results."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_facecolor(BG_COLOR)
    
    alpha = ease_in_out(min(1.0, progress * 1.5))
    
    draw_text_centered(ax, "Live Deployment Results", 0.90, fontsize=36, color=WHITE, weight="bold", alpha=alpha)
    
    # Stats grid
    stats = [
        ("Experiments", str(DATA["experiments"]), ACCENT),
        ("Trades", str(DATA["trades"]), ACCENT2),
        ("Markets", str(DATA["markets"]), ACCENT3),
        ("Strategies", str(DATA["strategies"]), GREEN),
    ]
    
    for i, (label, value, color) in enumerate(stats):
        row = i // 2
        col = i % 2
        x = 0.30 + col * 0.40
        y = 0.65 - row * 0.22
        
        val_alpha = ease_in_out(max(0, min(1.0, (progress - 0.1 - i * 0.1) * 3)))
        ax.text(x, y, value, transform=ax.transAxes, fontsize=48,
                color=color, weight="bold", ha="center", va="center", alpha=val_alpha)
        ax.text(x, y - 0.07, label, transform=ax.transAxes, fontsize=18,
                color=GRAY, ha="center", va="center", alpha=val_alpha * 0.8)
    
    # Pipeline flow
    if progress > 0.5:
        flow_alpha = ease_in_out(min(1.0, (progress - 0.5) * 2))
        stages = ["DRAFT", "SHADOW", "PAPER", "LIVE"]
        stage_colors = [GRAY, YELLOW, ACCENT, GREEN]
        for i, (stage, scolor) in enumerate(zip(stages, stage_colors)):
            x = 0.15 + i * 0.22
            ax.text(x, 0.22, stage, transform=ax.transAxes, fontsize=18,
                    color=scolor, weight="bold", ha="center", va="center", alpha=flow_alpha)
            if i < 3:
                ax.annotate("", xy=(0.15 + (i + 1) * 0.22 - 0.05, 0.22),
                           xytext=(0.15 + i * 0.22 + 0.05, 0.22),
                           transform=ax.transAxes,
                           arrowprops=dict(arrowstyle="->", color=ACCENT, lw=1.5, alpha=flow_alpha))


def draw_scene_call(fig, ax, progress):
    """Scene 5: Call to action."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_facecolor(BG_COLOR)
    
    alpha = ease_in_out(min(1.0, progress * 2))
    
    draw_text_centered(ax, DATA["conclusion"], 0.60, fontsize=40, color=ACCENT, weight="bold", alpha=alpha)
    draw_text_centered(ax, "github.com/berkah-karya/polyedge", 0.48, fontsize=24, color=WHITE, weight="normal", alpha=alpha * 0.8)
    
    # License badge
    draw_text_centered(ax, "MIT License  •  Open Source", 0.38, fontsize=18, color=GRAY, weight="normal", alpha=alpha * 0.7)
    
    # Final credit
    if progress > 0.5:
        end_alpha = ease_in_out(min(1.0, (progress - 0.5) * 2))
        draw_text_centered(ax, "PolyEdge Research Paper", 0.24, fontsize=16, color=GRAY, weight="normal", alpha=end_alpha * 0.6)
        draw_text_centered(ax, "Muchammad Fikri Izzuddin", 0.18, fontsize=14, color=GRAY, weight="normal", alpha=end_alpha * 0.5)


def ease_in_tree(t):
    """Minor helper for trailing fades."""
    return t * t


SCENE_FUNCS = {
    "title": draw_scene_title,
    "problem": draw_scene_problem,
    "pillars": draw_scene_pillars,
    "results": draw_scene_results,
    "call": draw_scene_call,
}


def get_scene(frame):
    """Get scene name and local progress for a given frame."""
    t = frame / FPS  # Current time in seconds
    for start, end, name in SCENES:
        if start <= t < end:
            local_progress = (t - start) / (end - start)
            return name, local_progress
    # Fallback: last scene
    return SCENES[-1][2], 1.0


def render_frame(frame):
    """Render a single frame."""
    ax.clear()
    scene_name, progress = get_scene(frame)
    SCENE_FUNCS[scene_name](fig, ax, progress)
    return []


# --- Main ---
total_seconds = SCENES[-1][1]  # End time of last scene
total_frames = int(total_seconds * FPS)

fig, ax = plt.subplots(figsize=(FIG_W, FIG_H), dpi=DPI)
fig.patch.set_facecolor(BG_COLOR)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.set_facecolor(BG_COLOR)
ax.axis("off")
fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

output_path = Path(__file__).parent.parent / "supplementary_video.mp4"

anim = FuncAnimation(fig, render_frame, frames=total_frames, blit=False, interval=1000 / FPS)

writer = FFMpegWriter(fps=FPS, metadata={
    "artist": "Muchammad Fikri Izzuddin",
    "title": "PolyEdge: Abstract Video",
    "comment": "Research paper abstract video",
}, codec="h264", extra_args=["-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "23"])

print(f"Rendering {total_frames} frames ({total_seconds}s) at {FPS}fps...")
print(f"Output: {output_path}")

anim.save(str(output_path), writer=writer, dpi=DPI)

print(f"Done! Video saved to {output_path}")
print(f"Duration: {total_seconds}s, Resolution: {W}x{H}")