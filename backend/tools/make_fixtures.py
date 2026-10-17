"""Generate synthetic STT fixtures (EN/RU/DE, ~5/10/30 s) with the backend's Piper voices.

Synthetic speech is clean and easy, so these clips are a smoke-test baseline; add real
recordings (your own voice, or CC0/CC-BY clips) next to them for honest comparisons.

Usage (the Piper voices must be loaded in the backend):
    python tools/make_fixtures.py --api http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.audio import decode_audio, encode_wav  # noqa: E402

VOICES = {
    "en": "tts.piper.en_US-lessac-medium",
    "ru": "tts.piper.ru_RU-irina-medium",
    "de": "tts.piper.de_DE-thorsten-medium",
}

TEXTS = {
    "en": {
        "short": "The quick brown fox jumps over the lazy dog near the river bank.",
        "medium": "Speech recognition turns spoken words into text. Modern models are trained on "
                  "hundreds of thousands of hours of audio and work in many languages.",
        "long": "Yesterday we tested several speech models on the same machine. The first model was fast "
                "but made a few mistakes with numbers and names. The second one was slower, yet it "
                "understood almost every word, even when the speaker talked quickly. In the afternoon "
                "we compared streaming and batch processing, and measured how long each client waited "
                "for the first words to appear on the screen.",
    },
    "ru": {
        "short": "Съешь же ещё этих мягких французских булок да выпей чаю.",
        "medium": "Распознавание речи превращает сказанные слова в текст. Современные модели обучены "
                  "на сотнях тысяч часов записей и понимают много языков.",
        "long": "Вчера мы проверили несколько моделей распознавания речи на одном компьютере. Первая модель "
                "работала быстро, но ошибалась в числах и именах. Вторая была медленнее, зато понимала почти "
                "каждое слово, даже когда диктор говорил быстро. После обеда мы сравнили потоковую и пакетную "
                "обработку и измерили, сколько времени каждый клиент ждал первых слов на экране.",
    },
    "de": {
        "short": "Franz jagt im komplett verwahrlosten Taxi quer durch Bayern.",
        "medium": "Spracherkennung verwandelt gesprochene Worte in Text. Moderne Modelle wurden mit "
                  "Hunderttausenden Stunden Audio trainiert und verstehen viele Sprachen.",
        "long": "Gestern haben wir mehrere Sprachmodelle auf demselben Rechner getestet. Das erste Modell war "
                "schnell, machte aber Fehler bei Zahlen und Namen. Das zweite war langsamer, verstand jedoch "
                "fast jedes Wort, selbst wenn der Sprecher schnell redete. Am Nachmittag haben wir Streaming "
                "und Stapelverarbeitung verglichen und gemessen, wie lange jeder Client auf die ersten Wörter "
                "warten musste.",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "fixtures" / "audio"))
    args = parser.parse_args()
    out = Path(args.out)
    with httpx.Client(base_url=args.api, timeout=120) as client:
        for lang, texts in TEXTS.items():
            (out / lang).mkdir(parents=True, exist_ok=True)
            for name, text in texts.items():
                r = client.post("/api/tts/synthesize", json={"model_id": VOICES[lang], "text": text})
                r.raise_for_status()
                audio = decode_audio(base64.b64decode(r.json()["audio_wav_b64"]), 16000)
                stem = f"synthetic_{name}"
                (out / lang / f"{stem}.wav").write_bytes(encode_wav(audio, 16000))
                (out / lang / f"{stem}.txt").write_text(text + "\n", encoding="utf-8")
                print(f"{lang}/{stem}.wav  {len(audio) / 16000:.1f}s")


if __name__ == "__main__":
    main()
