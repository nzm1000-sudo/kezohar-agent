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


WHISPER_MODEL = '/Users/nitz/.lmstudio/models/mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx'
WHISPER_SITE = '/Users/nitz/Library/Python/3.9/lib/python/site-packages'
_ALIGN = """
import sys, json
sys.path.insert(0, sys.argv[3])
import mlx_whisper
r = mlx_whisper.transcribe(sys.argv[1], path_or_hf_repo=sys.argv[2], language='he', word_timestamps=True)
print(json.dumps([[w['word'].strip(), float(w['start']), float(w['end'])] for s in r['segments'] for w in s.get('words', [])]))
"""


def _norm(word):
    import re
    from .hebrew import normalize
    return re.sub(r'[^א-תa-z0-9]', '', normalize(word or ''))


def align(text, voice=None):
    """Each word of `text` with its start and end in the reading (the owner's Whisper, ivrit-ai, run once and kept
    beside the audio). The voice is not touched: Whisper only listens. None when there is no reading yet."""
    import difflib
    import subprocess
    import sys
    text = ' '.join(str(text or '').split())[:1200]
    voice = voice or config.get('TTS_VOICE', VOICE)
    cache = Path(config.get('TTS_CACHE', 'data/store/tts'))
    stem = hashlib.sha256((voice + '\n' + text).encode()).hexdigest()[:32]
    wav, timing = cache / (stem + '.wav'), cache / (stem + '.words.json')
    if timing.exists():
        return json.loads(timing.read_text())
    if not wav.exists():
        return None
    # A separate process: the model's memory is released when it ends; one alignment at a time.
    from .model_gate import local_slot
    try:
        with local_slot(60, path=cache / 'align.lock'):
            heard = json.loads(subprocess.run([sys.executable, '-c', _ALIGN, str(wav), WHISPER_MODEL, WHISPER_SITE],
                                              capture_output=True, text=True, timeout=60, check=True).stdout)
    except Exception:
        return None
    words = text.split()
    a, b = [_norm(w) for w in words], [_norm(w) for w, _, _ in heard]
    times = [None] * len(words)
    for block in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            times[block.a + k] = heard[block.b + k][1:]
    # Words Whisper heard differently (abbreviations, numbers, spelling) take a share of the time between neighbours.
    i = 0
    while i < len(words):
        if times[i] is None:
            j = i
            while j < len(words) and times[j] is None:
                j += 1
            start = times[i - 1][1] if i else 0.0
            end = times[j][0] if j < len(words) else (heard[-1][2] if heard else start + 0.4 * (j - i))
            step = max(0.05, (end - start) / (j - i))
            for k in range(i, j):
                times[k] = [round(start + step * (k - i), 3), round(start + step * (k - i + 1), 3)]
            i = j
        else:
            i += 1
    result = [[w, round(t[0], 3), round(t[1], 3)] for w, t in zip(words, times)]
    timing.write_text(json.dumps(result, ensure_ascii=False))
    return result
