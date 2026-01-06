from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpeakerInfo:
    id: str
    name: str
    channels: int


@dataclass(frozen=True, slots=True)
class MicrophoneInfo:
    id: str
    name: str
    channels: int


def list_speakers() -> list[SpeakerInfo]:
    import soundcard as sc

    speakers: list[SpeakerInfo] = []
    for speaker in sc.all_speakers():
        speakers.append(
            SpeakerInfo(
                id=speaker.id,
                name=speaker.name,
                channels=speaker.channels,
            )
        )
    return speakers


def default_speaker_id() -> str:
    import soundcard as sc

    return sc.default_speaker().id


def list_microphones() -> list[MicrophoneInfo]:
    import soundcard as sc

    microphones: list[MicrophoneInfo] = []
    for mic in sc.all_microphones():
        microphones.append(
            MicrophoneInfo(
                id=mic.id,
                name=mic.name,
                channels=mic.channels,
            )
        )
    return microphones


def default_microphone_id() -> str:
    import soundcard as sc

    return sc.default_microphone().id
