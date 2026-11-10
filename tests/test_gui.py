"""Headless GUI input-contract tests (do not require a display)."""
import pytest
from bgm_gui import export_path, validate_track


def test_valid_track():
    obj = validate_track('ambient', '120.5', '123', .6, 'wav')
    assert obj['duration'] == 120.5 and obj['seed'] == 123 and obj['intensity'] == .6


def test_blank_seed_is_random():
    assert validate_track('calm', '60', '', .5, 'flac')['seed'] is None


@pytest.mark.parametrize('duration', ['NaN', 'inf', '-1', '3.9', '7201', 'hello'])
def test_invalid_durations(duration):
    with pytest.raises(ValueError):
        validate_track('calm', duration, '', .5, 'wav')


@pytest.mark.parametrize('seed', ['1.3', 'banana', '2e3'])
def test_invalid_seeds(seed):
    with pytest.raises(ValueError):
        validate_track('calm', '60', seed, .5, 'wav')


@pytest.mark.parametrize('name', ['../escape', 'CON', 'folder\\file', 'bad:name', '..', '  '])
def test_invalid_export_names(tmp_path, name):
    with pytest.raises(ValueError):
        export_path(str(tmp_path), name, 'wav')


def test_export_path(tmp_path):
    assert export_path(str(tmp_path), 'track', 'wav') == tmp_path / 'track.wav'
