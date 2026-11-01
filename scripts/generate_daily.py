#!/usr/bin/env python3
"""Generate one day of conversation content (en + es-AR) and native-speaker audio.

Usage:
  python scripts/generate_daily.py                 # today's date (KST), all languages
  python scripts/generate_daily.py --date 2026-11-08 --lang es
  python scripts/generate_daily.py --backfill-audio   # add audio to days that lack it

Env (one AI key is required unless --backfill-audio):
  ANTHROPIC_API_KEY | GEMINI_API_KEY | NVIDIA_API_KEY   sentence generation (first one set is used)
  AI_PROVIDER = anthropic | gemini | nvidia             optional override
  AI_MODEL                                              optional model override
  AZURE_SPEECH_KEY, AZURE_SPEECH_REGION  neural TTS (optional - without it the app uses the device voice)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
AUDIO = ROOT / "audio"
KST = dt.timezone(dt.timedelta(hours=9))

SENTENCES_PER_DAY = 5
HISTORY_LIMIT = 300  # previous sentences shown to the model to avoid repeats

# Same theme for both languages each day; rotates through the list.
THEMES = [
    "인사와 안부", "카페·식당", "길 묻기·교통", "쇼핑", "감정·리액션", "약속 잡기", "여행·숙소",
    "날씨·계절", "직장·업무", "취미·여가", "건강·병원", "집·일상생활", "전화·메시지", "칭찬·감사",
    "부탁·도움 요청", "사과·변명", "음식·요리", "주말 계획", "친구 사귀기", "돈·계산",
    "불만·문제 해결", "축하·기념일", "가족 이야기", "공항·비행기", "의견 말하기",
]
THEME_EPOCH = dt.date(2026, 11, 1)  # "인사와 안부" day

LANGS = {
    "en": {
        "name": "American English",
        "guide": (
            "- Use natural, everyday American English as people actually speak it (contractions, common idioms, phrasal verbs).\n"
            "- IPA: General American, e.g. 'going' → ˈɡoʊɪŋ.\n"
            "- In `note`, mention British alternatives when they differ (e.g. check ↔ bill)."
        ),
        "voices": ["en-US-JennyNeural", "en-US-GuyNeural"],
        "ssml_lang": "en-US",
    },
    "es": {
        "name": "Rioplatense Spanish (Argentina, Buenos Aires)",
        "guide": (
            "- Write as a porteño would actually speak. ALWAYS use voseo instead of tú: vos tenés, querés, podés, sos, andás; "
            "imperatives mirá, vení, decime, disculpá. Use ustedes (never vosotros).\n"
            "- Prefer Argentine vocabulary where natural: acá, colectivo, subte, laburo, che, dale, re, bárbaro, finde, "
            "plata, auto, celular, pileta, frutilla, palta, talle, valija, maní, nomás.\n"
            "- IPA: Buenos Aires pronunciation — ll/y as [ʃ] (llevar → ʃeˈβaɾ, yo → ʃo), seseo (c/z → s), "
            "intervocalic b/d/g as [β ð ɣ].\n"
            "- For voseo verbs, `note` must name the form and compare with tú (e.g. 'vos 현재형 (tú tienes → vos tenés)').\n"
            "- When a word differs from Spain Spanish, say so in `note` (e.g. '스페인: autobús')."
        ),
        "voices": ["es-AR-ElenaNeural", "es-AR-TomasNeural"],
        "ssml_lang": "es-AR",
    },
}

SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The sentence in the target language"},
                    "translation": {"type": "string", "description": "Natural Korean translation"},
                    "situation": {"type": "string", "description": "When to use it, in Korean, short (e.g. '카페에서 주문할 때')"},
                    "tip": {"type": "string", "description": "One-line Korean tip on nuance/grammar/culture, or empty string"},
                    "words": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "word": {"type": "string", "description": "Exact surface form as it appears in text (word or short phrase)"},
                                "lemma": {"type": "string", "description": "Dictionary form, or empty string if same as word"},
                                "pos": {"type": "string", "description": "Part of speech in Korean, e.g. 동사, 명사(여성), 구동사"},
                                "meaning": {"type": "string", "description": "Korean meaning as used in this sentence"},
                                "ipa": {"type": "string", "description": "IPA without slashes"},
                                "note": {"type": "string", "description": "Short Korean note (conjugation, usage, regional difference) or empty string"},
                            },
                            "required": ["word", "lemma", "pos", "meaning", "ipa", "note"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["text", "translation", "situation", "tip", "words"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- helpers
def kst_target_date(now: dt.datetime | None = None) -> str:
    """The workflow runs ~05:00 KST; anything before 05:00 KST still targets the previous day."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.astimezone(KST) - dt.timedelta(hours=5)).date().isoformat()


def theme_for(date: str) -> str:
    return THEMES[(dt.date.fromisoformat(date) - THEME_EPOCH).days % len(THEMES)]


def load_index() -> dict:
    p = CONTENT / "index.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_index(index: dict) -> None:
    index = {k: sorted(set(v)) for k, v in sorted(index.items())}
    (CONTENT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")


def day_path(lang: str, date: str) -> Path:
    return CONTENT / lang / f"{date}.json"


def previous_sentences(lang: str) -> list[str]:
    files = sorted((CONTENT / lang).glob("*.json"), reverse=True)
    out: list[str] = []
    for f in files:
        out += [s["text"] for s in json.loads(f.read_text())["sentences"]]
        if len(out) >= HISTORY_LIMIT:
            break
    return out[:HISTORY_LIMIT]


def word_in_text(word: str, text: str) -> bool:
    # Same rule as markWords() in app.js: case-insensitive, not inside another word.
    pat = r"(?<![\w'’])" + re.escape(word) + r"(?![\w'’])"
    return re.search(pat, text, flags=re.IGNORECASE) is not None


# ---------------------------------------------------------------- Claude
SYSTEM_PROMPT = (
    "You write daily conversation lessons for Korean adults learning a foreign language. "
    "Output is shown in a mobile app: each sentence has a Korean translation, a situation label, "
    "a short tip, and glosses for the key words. All explanations are in natural Korean (해요체)."
)

JSON_EXAMPLE = """{"sentences": [{"text": "...", "translation": "...", "situation": "...", "tip": "...",
  "words": [{"word": "...", "lemma": "...", "pos": "...", "meaning": "...", "ipa": "...", "note": "..."}]}]}"""


def build_prompt(lang: str, date: str, theme: str) -> str:
    cfg = LANGS[lang]
    history = previous_sentences(lang)
    return f"""Create today's lesson.

Language: {cfg['name']}
Date: {date}
Theme: {theme}
Level: beginner to intermediate (A2–B1)

Requirements:
- Exactly {SENTENCES_PER_DAY} sentences that native speakers really say in daily life within this theme. Short to medium length (3–12 words).
- Cover different moments of the theme (e.g. asking, answering, reacting) so the set feels like a mini scenario.
- For each sentence gloss 1–4 key words or short phrases a learner would not know. `word` must be copied exactly as it appears in `text` (same spelling and accents). Skip trivial words (a, the, el, la, y).
- `translation`, `situation`, `tip`, `pos`, `meaning`, `note` are written in Korean.
- `situation`: under 20 Korean characters. `tip`: one sentence, or "" if nothing useful.
- `lemma`: dictionary form, or "" if same as word. `ipa`: IPA without slashes. `note`: short, or "".
{cfg['guide']}

Do NOT reuse any of these previously taught sentences (or trivial variations of them):
{json.dumps(history, ensure_ascii=False)}"""


def json_instructions() -> str:
    return (
        "\n\nReturn ONLY a JSON object (no markdown, no commentary) with exactly this shape; "
        f"every field is required and is a string unless it is a list:\n{JSON_EXAMPLE}"
    )


def check_shape(data: dict) -> list[dict]:
    """Validate model output against SCHEMA (needed for providers without strict schema enforcement)."""
    sents = data.get("sentences") if isinstance(data, dict) else None
    if not isinstance(sents, list) or len(sents) < SENTENCES_PER_DAY:
        raise ValueError(f"need {SENTENCES_PER_DAY} sentences")
    for s in sents:
        for k in ("text", "translation", "situation"):
            if not isinstance(s.get(k), str) or not s[k].strip():
                raise ValueError(f"sentence missing {k}")
        s["tip"] = s.get("tip") or ""
        if not isinstance(s.get("words"), list):
            raise ValueError("words must be a list")
        for w in s["words"]:
            for k in ("word", "pos", "meaning", "ipa"):
                if not isinstance(w.get(k), str) or not w[k].strip():
                    raise ValueError(f"word missing {k}")
            w["lemma"] = w.get("lemma") or ""
            w["note"] = w.get("note") or ""
    return sents


def parse_json_text(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def http_json(url: str, body: dict, headers: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read()[:500].decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                wait = 15 * (attempt + 1)
                print(f"HTTP {e.code}, retrying in {wait}s: {detail[:120]}", file=sys.stderr)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {detail}") from e
    raise RuntimeError("unreachable")


def call_anthropic(model: str, prompt: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=model,
        max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"model declined: {msg.stop_details}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("output truncated (max_tokens)")
    print(f"  usage: in={msg.usage.input_tokens} out={msg.usage.output_tokens}", file=sys.stderr)
    return json.loads(next(b.text for b in msg.content if b.type == "text"))


def call_gemini(model: str, prompt: str) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt + json_instructions()}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9, "maxOutputTokens": 16000},
    }
    res = http_json(url, body, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    cand = (res.get("candidates") or [{}])[0]
    if cand.get("finishReason") not in (None, "STOP"):
        raise ValueError(f"finishReason={cand.get('finishReason')}")
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
    u = res.get("usageMetadata", {})
    print(f"  usage: in={u.get('promptTokenCount')} out={u.get('candidatesTokenCount')}", file=sys.stderr)
    return parse_json_text(text)


def call_nvidia(model: str, prompt: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt + json_instructions()}],
        "temperature": 0.7,
        "max_tokens": 8000,
    }
    res = http_json("https://integrate.api.nvidia.com/v1/chat/completions", body,
                    {"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}", "Accept": "application/json"})
    choice = res["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("output truncated (length)")
    u = res.get("usage", {})
    print(f"  usage: in={u.get('prompt_tokens')} out={u.get('completion_tokens')}", file=sys.stderr)
    content = choice["message"]["content"] or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S)  # reasoning models
    return parse_json_text(content)


PROVIDERS = {
    # name: (env var holding the key, default model, call function)
    "anthropic": ("ANTHROPIC_API_KEY", "claude-opus-5-5", call_anthropic),
    "gemini": ("GEMINI_API_KEY", "gemini-flash-latest", call_gemini),
    "nvidia": ("NVIDIA_API_KEY", "meta/llama-3.3-70b-instruct", call_nvidia),
}


def pick_provider() -> tuple[str, str]:
    """AI_PROVIDER env wins; otherwise the first provider whose key is set (anthropic > gemini > nvidia)."""
    name = (os.environ.get("AI_PROVIDER") or "").strip().lower()
    if not name:
        name = next((n for n, (env, _, _) in PROVIDERS.items() if os.environ.get(env)), "")
    if name not in PROVIDERS:
        raise SystemExit("No AI provider configured: set ANTHROPIC_API_KEY, GEMINI_API_KEY or NVIDIA_API_KEY")
    env, default_model, _ = PROVIDERS[name]
    if not os.environ.get(env):
        raise SystemExit(f"AI_PROVIDER={name} but {env} is not set")
    return name, (os.environ.get("AI_MODEL") or "").strip() or default_model


def generate_sentences(lang: str, date: str, theme: str) -> list[dict]:
    provider, model = pick_provider()
    call = PROVIDERS[provider][2]
    prompt = build_prompt(lang, date, theme)
    last_err: Exception | None = None
    for attempt in range(3):
        print(f"[{lang}] {provider}/{model} (attempt {attempt + 1})", file=sys.stderr)
        try:
            return check_shape(call(model, prompt))
        except (ValueError, KeyError, IndexError) as e:  # malformed output -> ask again
            last_err = e
            print(f"[{lang}] bad output: {e}", file=sys.stderr)
    raise RuntimeError(f"[{lang}] {provider} failed to return valid JSON: {last_err}")


def build_day(lang: str, date: str, theme: str, raw: list[dict]) -> dict:
    if len(raw) < SENTENCES_PER_DAY:
        raise RuntimeError(f"[{lang}] expected {SENTENCES_PER_DAY} sentences, got {len(raw)}")
    sentences = []
    for i, s in enumerate(raw[:SENTENCES_PER_DAY], 1):
        words = []
        for w in s["words"]:
            if not word_in_text(w["word"], s["text"]):
                print(f"[{lang}] dropping gloss not found in sentence: {w['word']!r} / {s['text']!r}", file=sys.stderr)
                continue
            entry = {"word": w["word"], "pos": w["pos"], "meaning": w["meaning"], "ipa": w["ipa"].strip("/[] ")}
            if w["lemma"] and w["lemma"].lower() != w["word"].lower():
                entry["lemma"] = w["lemma"]
            if w["note"]:
                entry["note"] = w["note"]
            words.append(entry)
        item = {
            "id": f"{lang}-{date.replace('-', '')}-{i}",
            "text": s["text"].strip(),
            "translation": s["translation"].strip(),
            "situation": s["situation"].strip(),
            "words": words,
        }
        if s["tip"].strip():
            item["tip"] = s["tip"].strip()
        sentences.append(item)
    return {"date": date, "language": lang, "theme": theme, "level": "초급~중급", "sentences": sentences}


# ---------------------------------------------------------------- Azure TTS
def azure_tts(text: str, lang: str, voice: str, rate: str, out: Path) -> None:
    key, region = os.environ["AZURE_SPEECH_KEY"], os.environ["AZURE_SPEECH_REGION"]
    ssml = (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{LANGS[lang]['ssml_lang']}'>"
        f"<voice name='{voice}'><prosody rate='{rate}'>{xml_escape(text)}</prosody></voice></speak>"
    )
    req = urllib.request.Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "daily-conversation",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(r.read())
                return
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Azure TTS {e.code}: {e.read()[:200]!r}") from e


def add_audio(day: dict) -> bool:
    """Synthesize sentence (normal + slow) and word audio. Returns True if anything changed."""
    lang, date = day["language"], day["date"]
    voices = LANGS[lang]["voices"]
    base = AUDIO / lang / date
    changed = False
    for i, s in enumerate(day["sentences"], 1):
        voice = voices[(i - 1) % len(voices)]  # alternate female/male
        if not s.get("audio"):
            azure_tts(s["text"], lang, voice, "0%", base / f"{i}.mp3")
            azure_tts(s["text"], lang, voice, "-35%", base / f"{i}-slow.mp3")
            s["audio"] = {"normal": f"audio/{lang}/{date}/{i}.mp3", "slow": f"audio/{lang}/{date}/{i}-slow.mp3"}
            changed = True
        for k, w in enumerate(s["words"], 1):
            if not w.get("audio"):
                azure_tts(w["word"], lang, voices[0], "-15%", base / f"w{i}-{k}.mp3")
                w["audio"] = f"audio/{lang}/{date}/w{i}-{k}.mp3"
                changed = True
    return changed


def tts_enabled() -> bool:
    return bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION"))


def write_day(day: dict) -> None:
    p = day_path(day["language"], day["date"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(day, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today in KST)")
    ap.add_argument("--lang", choices=list(LANGS), action="append", help="repeatable; default all")
    ap.add_argument("--force", action="store_true", help="regenerate even if the day exists")
    ap.add_argument("--backfill-audio", action="store_true", help="only add audio to existing days missing it")
    args = ap.parse_args()
    langs = args.lang or list(LANGS)

    if args.backfill_audio:
        if not tts_enabled():
            print("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION not set", file=sys.stderr)
            return 1
        index = load_index()
        for lang in langs:
            for date in index.get(lang, []):
                day = json.loads(day_path(lang, date).read_text())
                if add_audio(day):
                    write_day(day)
                    print(f"[{lang}] {date}: audio added")
        return 0

    date = args.date or kst_target_date()
    dt.date.fromisoformat(date)  # validate
    theme = theme_for(date)
    index = load_index()
    if not tts_enabled():
        print("::warning::Azure TTS not configured - content will use the device voice", file=sys.stderr)

    for lang in langs:
        if day_path(lang, date).exists() and not args.force:
            print(f"[{lang}] {date} already exists - skipping (use --force to regenerate)")
            continue
        day = build_day(lang, date, theme, generate_sentences(lang, date, theme))
        if tts_enabled():
            add_audio(day)
        write_day(day)
        index.setdefault(lang, []).append(date)
        save_index(index)
        print(f"[{lang}] {date} ({theme}): {len(day['sentences'])} sentences written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
