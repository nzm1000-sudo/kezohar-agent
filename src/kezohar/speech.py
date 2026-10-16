"""Read an answer aloud in a natural male Hebrew voice (Gemini TTS, the owner's free key; owner decision 2026-10-16).

Returns WAV bytes. Each text is generated once and kept in data/store/tts, so a repeated answer plays at once.
"""
import base64
import hashlib
import json
import struct
import urllib.request
from pathlib import Path
from . import config

VOICE = 'Charon'
MODELS = ('gemini-3.8-flash-tts', 'gemini-3.1-flash-tts-preview', 'gemini-2.5-flash-preview-tts')


def _wav(pcm, rate=24000):
    return b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16) \
        + b'data' + struct.pack('<I', len(pcm)) + pcm


def speak(text, voice=None):
    text = ' '.join(str(text or '').split())[:1200]
    key = config.get('GEMINI_API_KEY', '')
    if not text or not key:
        return None
    voice = voice or config.get('TTS_VOICE', VOICE)
    cache = Path(config.get('TTS_CACHE', 'data/store/tts'))
    path = cache / (hashlib.sha256((voice + '\n' + text).encode()).hexdigest()[:32] + '.wav')
    if path.exists():
        return path.read_bytes()
    # Plain text only: a style prompt is read aloud too (measured 12 s for a 4 s sentence) and the TTS models reject a
    # system instruction. The voice itself (Charon: a calm, deep male voice) carries the tone.
    body = {'contents': [{'parts': [{'text': text}]}],
            'generationConfig': {'responseModalities': ['AUDIO'],
                                 'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}}}}
    for model in MODELS:
        req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                                     json.dumps(body).encode(), {'Content-Type': 'application/json', 'x-goog-api-key': key,
                                                                 'User-Agent': 'kezohar-agent/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                part = json.load(r)['candidates'][0]['content']['parts'][0]['inlineData']
        except Exception:
            continue  # quota or a busy model: the next one
        audio = base64.b64decode(part['data'])
        # Some models return a WAV already, some raw 24 kHz PCM.
        audio = audio if audio[:4] == b'RIFF' else _wav(audio)
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return audio
    return None
