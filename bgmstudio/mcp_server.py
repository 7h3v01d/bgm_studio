"""MCP server exposing the music engine as tools.

  stdio (Claude Desktop / Claude Code / most agent frameworks):
      python -m bgmstudio.mcp_server
  HTTP (remote agents):
      python -m bgmstudio.mcp_server --http --port 8766
"""
from __future__ import annotations

import argparse
from typing import Optional

try:  # MCP Python SDK 2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP

from . import service

mcp = FastMCP("bgmstudio")


@mcp.tool()
def list_moods() -> dict:
    """List the available music moods and what each one sounds like."""
    return service.moods()


@mcp.tool()
def generate_bgm(mood: str = "calm", duration_seconds: float = 60.0, loop: bool = False,
                 seed: Optional[int] = None, key: Optional[str] = None, bpm: Optional[float] = None,
                 format: str = "wav", target_lufs: float = -20.0, output_dir: Optional[str] = None,
                 also_midi: bool = False) -> dict:
    """Generate instrumental background music of EXACTLY duration_seconds and save it to disk.

    loop=True gives a sample-seamless loop (no fade-out); loop=False ends with a cadence and fade.
    Re-use the returned seed to regenerate identical music. Returns the file path and metadata.
    """
    return service.generate_bgm(mood, duration_seconds, loop=loop, seed=seed, key=key, bpm=bpm, format=format,
                                target_lufs=target_lufs, out_dir=output_dir, midi=also_midi)


@mcp.tool()
def generate_scene_sequence(scenes: list[dict], xfade: float = 2.0, seed: Optional[int] = None,
                            key: Optional[str] = None, format: str = "wav", target_lufs: float = -20.0,
                            output_dir: Optional[str] = None) -> dict:
    """Per-scene background music in ONE file. scenes = [{"mood": "lofi", "duration": 30}, ...] in video order.
    Each scene's downbeat lands exactly on its cut, all scenes share a key, and moods crossfade after each cut.
    Total length equals the sum of durations."""
    return service.generate_sequence(scenes, xfade=xfade, seed=seed, key=key, format=format,
                                     target_lufs=target_lufs, out_dir=output_dir)


@mcp.tool()
def mix_with_narration(narration_path: str, mood: str = "calm", lead_in: float = 1.5, tail_out: float = 3.0,
                       music_lufs: float = -26.0, duck_db: float = 9.0, final_lufs: float = -16.0,
                       seed: Optional[int] = None, format: str = "wav", output_dir: Optional[str] = None,
                       scenes: Optional[list[dict]] = None, xfade: float = 2.0) -> dict:
    """Generate music that fits a narration file exactly, duck it under the speech, and write the final mix.

    Music starts lead_in seconds before the first word and fades tail_out seconds after the last.
    Optional scenes=[{"mood","duration"},...] (durations summing to the narration length) switches mood per scene.
    """
    return service.mix_with_narration(narration_path, mood, lead_in=lead_in, tail_out=tail_out,
                                      music_lufs=music_lufs, duck_db=duck_db, final_lufs=final_lufs, seed=seed,
                                      format=format, out_dir=output_dir, scenes=scenes, xfade=xfade)


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
