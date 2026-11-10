# SPDX-License-Identifier: Apache-2.0
"""Release regression: loudness analysis must not write temporary PCM WAVs."""
import subprocess
import numpy as np
import pytest
from bgmstudio import audio as audio_mod


def test_loudness_uses_raw_pcm_stdin_without_scratch_wav(monkeypatch):
    def no_disk_write(*args, **kwargs):
        raise AssertionError('loudness unexpectedly wrote temporary WAV')

    monkeypatch.setattr(audio_mod.sf, 'write', no_disk_write)
    observed = {}

    def fake_run(cmd, *, input, capture_output, timeout):
        observed['command'] = cmd
        observed['pcm'] = input
        observed['timeout'] = timeout
        return subprocess.CompletedProcess(cmd, 0, b'', b'I: -20.7 LUFS\n')

    monkeypatch.setattr(audio_mod.subprocess, 'run', fake_run)
    pcm = np.full((100, 2), 0.25, dtype=np.float32)
    assert audio_mod.measure_lufs(pcm) == -20.7
    assert observed['pcm'] == pcm.tobytes()
    assert 'pipe:0' in observed['command']
    assert observed['timeout'] == audio_mod.FFMPEG_TIMEOUT


def test_loudness_process_failure_is_not_silently_treated_as_silence(monkeypatch):
    def fake_run(cmd, *, input, capture_output, timeout):
        return subprocess.CompletedProcess(cmd, 1, b'', b'ffmpeg failed')

    monkeypatch.setattr(audio_mod.subprocess, 'run', fake_run)
    with pytest.raises(RuntimeError, match='loudness measurement failed'):
        audio_mod.measure_lufs(np.zeros((100, 2), dtype=np.float32))


def test_loudness_empty_input_does_not_start_ffmpeg(monkeypatch):
    def no_run(*args, **kwargs):
        raise AssertionError('FFmpeg must not launch for empty arrays')

    monkeypatch.setattr(audio_mod.subprocess, 'run', no_run)
    assert audio_mod.measure_lufs(np.zeros((0, 2), dtype=np.float32)) is None


def test_loudness_rejects_malformed_audio_shape():
    with pytest.raises(ValueError, match='mono or stereo'):
        audio_mod.measure_lufs(np.zeros((100, 3), dtype=np.float32))
