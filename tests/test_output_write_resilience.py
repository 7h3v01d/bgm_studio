# SPDX-License-Identifier: Apache-2.0
"""Output-write regressions: atomicity, retry and actionable failure reporting."""
from pathlib import Path
import logging
import numpy as np
import pytest
import soundfile as sf
from bgmstudio import audio


def test_lossless_write_retries_transient_system_error_without_leaking_partial(tmp_path, monkeypatch):
    dest = tmp_path / 'music.wav'
    samples = np.zeros((100, 2), dtype=np.float32)
    original = audio.sf.write
    calls = []
    monkeypatch.setattr(audio.time, 'sleep', lambda _: None)

    def flaky(path, *args, **kwargs):
        calls.append(path)
        if len(calls) == 1:
            Path(path).write_bytes(b'partial')
            raise sf.LibsndfileError(2)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(audio.sf, 'write', flaky)
    assert audio.write_audio(str(dest), samples) == str(dest)
    assert len(calls) == 2 and calls[0] != calls[1]
    assert len(list(tmp_path.iterdir())) == 1
    assert sf.info(str(dest)).frames == 100


def test_persistent_failure_does_not_replace_existing_audio(tmp_path, monkeypatch, caplog):
    dest = tmp_path / 'music.wav'
    original = b'previous known good output'
    dest.write_bytes(original)
    monkeypatch.setattr(audio.time, 'sleep', lambda _: None)
    calls = []

    def broken(path, *args, **kwargs):
        calls.append(path)
        Path(path).write_bytes(b'broken partial')
        raise sf.LibsndfileError(2)

    monkeypatch.setattr(audio.sf, 'write', broken)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match='audio output could not be written'):
            audio.write_audio(str(dest), np.zeros((100, 2), dtype=np.float32))
    assert len(calls) == 2
    assert dest.read_bytes() == original
    assert list(tmp_path.iterdir()) == [dest]
    assert 'free=' in caplog.text and 'pcm_bytes=' in caplog.text


def test_lossless_success_identical_to_original_soundfile_encoding(tmp_path):
    samples = np.linspace(-0.8, 0.8, 480, dtype=np.float32)[:, None]
    expected = tmp_path / 'expected.wav'
    actual = tmp_path / 'actual.wav'
    sf.write(expected, samples, 44100, format='WAV', subtype='PCM_24')
    audio.write_audio(str(actual), samples, 44100)
    assert actual.read_bytes() == expected.read_bytes()
