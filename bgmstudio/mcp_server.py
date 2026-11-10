# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""MCP server exposing the music engine as tools.

  stdio (Claude Desktop / Claude Code / most agent frameworks):
      python -m bgmstudio.mcp_server
  HTTP (remote agents):
      python -m bgmstudio.mcp_server --http --port 8766
"""
from __future__ import annotations

import argparse
from typing import Optional, Union

try:  # MCP Python SDK 2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP

from . import service
from .cues import summary as cue_summary


def _slim(r: dict) -> dict:
    """Agents get the cue sheet without the per-bar list (it can run to thousands of entries); the full sheet is
    in the file at meta_path."""
    return {**r, "cues": cue_summary(r["cues"])} if "cues" in r else r

mcp = FastMCP("bgmstudio")


@mcp.tool()
def list_moods() -> dict:
    """List the available music moods and what each one sounds like."""
    return service.moods()


@mcp.tool()
def generate_bgm(mood: str = "calm", duration_seconds: float = 60.0, loop: bool = False,
                 seed: Optional[int] = None, key: Optional[str] = None, bpm: Optional[float] = None,
                 format: str = "wav", target_lufs: float = -20.0, output_dir: Optional[str] = None,
                 also_midi: bool = False, intensity: Optional[Union[float, list[float]]] = None,
                 stems: bool = False) -> dict:
    """Generate instrumental background music of EXACTLY duration_seconds and save it to disk.

    loop=True gives a sample-seamless loop (no fade-out); loop=False ends with a cadence and fade.
    Re-use the returned seed to regenerate identical music. Returns the file path and metadata.
    intensity: 0..1 (0.5 = the mood as designed; low = sparse/quiet, high = busy/driving), or a list of 0..1
    points spread evenly across the track to follow a story's tension curve, e.g. [0.2, 0.3, 0.6, 1.0, 0.3].
    Story moods: horror, sleep, folklore, suspense (call list_moods for all).
    stems=True also writes pad/bass/keys/melody/sparkle/drums files that add up to the track.
    The result includes "cues" (sections and scene timing; per-bar downbeats are in the JSON at meta_path) and
    "provenance" (seed, engine version, SoundFont and its licence, file hashes).
    """
    return _slim(service.generate_bgm(mood, duration_seconds, loop=loop, seed=seed, key=key, bpm=bpm, format=format,
                                      target_lufs=target_lufs, out_dir=output_dir, midi=also_midi,
                                      intensity=intensity, stems=stems))


@mcp.tool()
def generate_scene_sequence(scenes: list[dict], xfade: float = 2.0, seed: Optional[int] = None,
                            key: Optional[str] = None, format: str = "wav", target_lufs: float = -20.0,
                            output_dir: Optional[str] = None, tempo_match: bool = True, max_bpm_jump: float = 6.0,
                            transitions: str = "none", fx_level_db: float = -3.0, stems: bool = False) -> dict:
    """Per-scene background music in ONE file. scenes = [{"mood": "lofi", "duration": 30}, ...] in video order.
    Each scene's downbeat lands exactly on its cut, all scenes share a key, and moods crossfade after each cut.
    Total length equals the sum of durations.
    tempo_match keeps neighbouring scenes within max_bpm_jump BPM. transitions adds a synthesized effect at each cut:
    none | riser | impact | riser_impact | downlifter | swell | auto (auto picks by energy change); a scene's own
    "transition" key overrides the cut into that scene.
    Each scene may carry "intensity" (0..1 or a curve): it shapes that scene's music, sets its level relative to the
    other scenes, and feeds transitions="auto" (a jump in tension gets a riser/impact, a drop a downlifter).
    stems=True also writes one file per instrument group plus "fx" (the transitions); they add up to the track.
    The result includes "cues" (scene, section and transition times) and "provenance"."""
    return _slim(service.generate_sequence(scenes, xfade=xfade, seed=seed, key=key, format=format,
                                           target_lufs=target_lufs, out_dir=output_dir, tempo_match=tempo_match,
                                           max_bpm_jump=max_bpm_jump, transitions=transitions,
                                           fx_level_db=fx_level_db, stems=stems))


@mcp.tool()
def mix_with_narration(narration_path: str, mood: str = "calm", lead_in: float = 1.5, tail_out: float = 3.0,
                       music_lufs: float = -26.0, duck_db: float = 9.0, final_lufs: float = -16.0,
                       seed: Optional[int] = None, format: str = "wav", output_dir: Optional[str] = None,
                       scenes: Optional[list[dict]] = None, xfade: float = 2.0, tempo_match: bool = True,
                       max_bpm_jump: float = 6.0, transitions: str = "none", fx_level_db: float = -3.0,
                       intensity: Optional[Union[float, list[float]]] = None, stems: bool = False) -> dict:
    """Generate music that fits a narration file exactly, duck it under the speech, and write the final mix.

    Music starts lead_in seconds before the first word and fades tail_out seconds after the last.
    Optional scenes=[{"mood","duration"},...] (durations summing to the narration length) switches mood per scene;
    scenes may carry "intensity". Without scenes, intensity (0..1 or a curve) shapes the single-mood bed.
    stems=True also writes voice / music / fx files (aligned and ducked) that add up to the mix.
    The result includes "cues" (in mix time, with the narration's start/end) and "provenance".
    """
    return _slim(service.mix_with_narration(narration_path, mood, lead_in=lead_in, tail_out=tail_out,
                                      music_lufs=music_lufs, duck_db=duck_db, final_lufs=final_lufs, seed=seed,
                                      format=format, out_dir=output_dir, scenes=scenes, xfade=xfade,
                                      tempo_match=tempo_match, max_bpm_jump=max_bpm_jump,
                                      transitions=transitions, fx_level_db=fx_level_db, intensity=intensity,
                                      stems=stems))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="serve streamable-HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args()
    if a.http:
        try:  # SDK 2.x takes host/port on run()
            mcp.run(transport="streamable-http", host=a.host, port=a.port)
        except TypeError:  # SDK 1.x keeps them in settings
            mcp.settings.host, mcp.settings.port = a.host, a.port
            mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
