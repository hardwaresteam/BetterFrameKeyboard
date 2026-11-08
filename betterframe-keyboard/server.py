#!/usr/bin/env python3
"""BetterFrame Keyboard helper.

Runs on the Steam Frame. Serves the keyboard page on http://localhost:8643
(localhost counts as secure, so WebXR and the microphone are allowed), and
does the speech work on the headset itself:

  POST /api/stt   audio in  -> text out   (faster-whisper, if installed)
  POST /api/tts   text in   -> WAV out    (Piper, if installed)
  GET  /api/status          -> what is available

Nothing leaves the headset. Only the Python standard library is required;
voice features turn on when setup.sh has installed them.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
VOICES = os.path.join(HERE, "voices")
# base.en is fast enough on the Frame to show words while you are still talking.
# small.en is more accurate but slower; pick it with BF_STT_MODEL=small.en
STT_MODEL = os.environ.get("BF_STT_MODEL", "base.en")
# other languages: the multilingual model, downloaded and loaded only the first time you dictate in one
STT_MULTI = os.environ.get("BF_STT_MULTI", "base")
MAX_UPLOAD = 25 * 1024 * 1024

STREAM_DIR = os.path.join(HERE, "models", "sherpa-onnx-streaming-zipformer-en-2023-06-26")
STREAM_TAG = "epoch-99-avg-1-chunk-16-left-128.int8.onnx"

_model = None
_model_lock = threading.Lock()

# ---- real-time recognizer (sherpa-onnx): words while you talk -------------
_rec = None
_rec_lock = threading.Lock()
_streams = {}  # sid -> [stream, last_used]


def have_stream():
    return (importlib.util.find_spec("sherpa_onnx") is not None
            and os.path.exists(os.path.join(STREAM_DIR, "tokens.txt")))


def get_rec():
    global _rec
    if _rec is None:
        import sherpa_onnx
        d = STREAM_DIR + "/"
        _rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=d + "tokens.txt",
            encoder=d + "encoder-" + STREAM_TAG,
            decoder=d + "decoder-" + STREAM_TAG,
            joiner=d + "joiner-" + STREAM_TAG,
            num_threads=2, sample_rate=16000, feature_dim=80,
            decoding_method="greedy_search", enable_endpoint_detection=False,
        )
        print("[live] real-time recognizer ready", flush=True)
    return _rec


def stream_feed(sid, pcm):
    import time
    import numpy as np
    a = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    with _rec_lock:
        rec = get_rec()
        entry = _streams.get(sid)
        if entry is None:
            entry = [rec.create_stream(), 0]
            _streams[sid] = entry
        entry[1] = time.time()
        st = entry[0]
        if len(a):
            st.accept_waveform(16000, a)
        while rec.is_ready(st):
            rec.decode_stream(st)
        text = rec.get_result(st)
        if len(_streams) > 8:  # forget old sentences
            for k, _v in sorted(_streams.items(), key=lambda kv: kv[1][1])[: len(_streams) - 8]:
                _streams.pop(k, None)
    return text if isinstance(text, str) else getattr(text, "text", str(text))
_run_lock = threading.Lock()  # one transcription at a time keeps each one fast


def have_whisper():
    return importlib.util.find_spec("faster_whisper") is not None


def piper_cmd():
    """Return (command list, voice path) for Piper, or (None, None)."""
    voice = None
    if os.path.isdir(VOICES):
        for name in sorted(os.listdir(VOICES)):
            if name.endswith(".onnx") and os.path.exists(os.path.join(VOICES, name + ".json")):
                voice = os.path.join(VOICES, name)
                break
    if not voice:
        return None, None
    exe = os.path.join(os.path.dirname(sys.executable), "piper")
    if os.path.exists(exe):
        return [exe], voice
    exe = shutil.which("piper")
    if exe:
        return [exe], voice
    if importlib.util.find_spec("piper") is not None:
        return [sys.executable, "-m", "piper"], voice
    return None, None


_multi = None


def get_multi():
    global _multi
    with _model_lock:
        if _multi is None:
            from faster_whisper import WhisperModel
            threads = int(os.environ.get("BF_THREADS", "2"))
            print(f"[stt] loading {STT_MULTI} for other languages...", flush=True)
            _multi = WhisperModel(STT_MULTI, device="cpu", compute_type="int8", cpu_threads=threads)
        return _multi


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            # Only a couple of cores: using all of them starves SteamVR and makes the headset stutter.
            threads = int(os.environ.get("BF_THREADS", "2"))
            print(f"[stt] loading {STT_MODEL} on CPU ({threads} threads)...", flush=True)
            # (setup downloads it straight into models/; an older install has it in the usual download cache)
            local = os.path.join(HERE, "models", "faster-whisper-" + STT_MODEL)
            where = local if os.path.isfile(os.path.join(local, "model.bin")) else STT_MODEL
            _model = WhisperModel(where, device="cpu", compute_type="int8", cpu_threads=threads)
            print("[stt] ready", flush=True)
        return _model


def wav_to_array(data):
    """16-bit PCM WAV bytes -> float32 mono numpy array at the file's rate (the page sends 16 kHz)."""
    import io
    import wave
    import numpy as np
    with wave.open(io.BytesIO(data), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("expected 16-bit audio")
    a = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if rate != 16000:  # simple resample, the page normally sends 16 kHz already
        n = int(len(a) * 16000 / rate)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a


def decode_file(path):
    """A recorded clip (ogg / webm) -> float32 mono numpy array at 16 kHz. Done here rather than by the speech
    library, whose own way stopped working with newer versions of the audio library (needed on newer Python)."""
    import av
    import numpy as np
    out = []
    with av.open(path) as c:
        rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in c.decode(audio=0):
            for f in rs.resample(frame) or []:
                out.append(f.to_ndarray().reshape(-1))
        for f in rs.resample(None) or []:
            out.append(f.to_ndarray().reshape(-1))
    a = np.concatenate(out) if out else np.zeros(0, dtype=np.int16)
    return a.astype(np.float32) / 32768.0


def transcribe(audio, draft=False, context=None, lang=None):
    """audio: a numpy array (from WAV) or a file path.
    draft=True is the quick pass shown while you talk; the final pass after a pause is more careful.
    lang: the keyboard's language (two letters); anything but English uses the multilingual model."""
    english_only = STT_MODEL.endswith(".en")
    other = bool(lang) and lang != "en" and english_only
    model = get_multi() if other else get_model()
    with _run_lock:
        segments, _info = model.transcribe(
            audio,
            language=lang if lang else ("en" if english_only else None),
            beam_size=1 if draft else 3,
            best_of=1,
            temperature=0.0,
            vad_filter=not draft,
            vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=False,
            without_timestamps=True,
            initial_prompt=context or None,
        )
        return " ".join(s.text.strip() for s in segments).strip()


_voice = None
_voice_lock = threading.Lock()


def get_voice():
    """Keep the Piper voice loaded so speaking starts right away."""
    global _voice
    with _voice_lock:
        if _voice is None:
            _cmd, path = piper_cmd()
            if not path or importlib.util.find_spec("piper") is None:
                return None
            from piper import PiperVoice
            _voice = PiperVoice.load(path)
            print("[tts] voice ready", flush=True)
        return _voice


def synthesize(text, rate):
    rate = min(1.8, max(0.5, float(rate or 1)))
    try:
        voice_obj = get_voice()
    except Exception as e:  # fall back to the command-line Piper below
        sys.stderr.write(f"[tts] in-process voice failed: {e}\n")
        voice_obj = None
    if voice_obj is not None:
        import io
        import wave
        buf = io.BytesIO()
        cfg = None
        try:
            from piper import SynthesisConfig
            cfg = SynthesisConfig(length_scale=1 / rate)
        except Exception:
            pass
        with wave.open(buf, "wb") as w:
            if cfg is not None:
                voice_obj.synthesize_wav(text, w, syn_config=cfg)
            else:
                voice_obj.synthesize_wav(text, w)
        return buf.getvalue()
    cmd, voice = piper_cmd()
    if not cmd:
        raise RuntimeError("Piper is not installed")
    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        args = cmd + ["--model", voice, "--output_file", out, "--length_scale", f"{1 / rate:.2f}"]
        p = subprocess.run(args, input=text.encode("utf-8"), capture_output=True, timeout=60)
        if p.returncode != 0 or not os.path.getsize(out):
            raise RuntimeError(p.stderr.decode("utf-8", "replace")[-400:] or "Piper failed")
        with open(out, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json",
        ".wasm": "application/wasm",
    }

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("[http] " + (fmt % args) + "\n")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_UPLOAD:
            raise ValueError("empty or too large")
        return self.rfile.read(n)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            cmd, voice = piper_cmd()
            return self.send_json(200, {
                "stt": have_whisper(),
                "model": STT_MODEL,
                "loaded": _model is not None,
                "live": have_stream(),
                "tts": bool(cmd),
                "voice": os.path.basename(voice) if voice else None,
            })
        if self.path.startswith("/api/"):
            return self.send_json(404, {"error": "unknown"})
        # never serve the venv, models or scripts' secrets
        if any(part in self.path for part in ("/venv", "/models", "/..")):
            return self.send_json(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        try:
            if self.path.startswith("/api/stream"):
                if not have_stream():
                    return self.send_json(501, {"error": "Real-time voice typing isn't installed. Run setup.sh."})
                from urllib.parse import urlparse, parse_qs
                sid = parse_qs(urlparse(self.path).query).get("sid", ["0"])[0][:40]
                n = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(n) if 0 < n <= MAX_UPLOAD else b""
                return self.send_json(200, {"text": stream_feed(sid, data)})
            if self.path.startswith("/api/stt"):
                if not have_whisper():
                    return self.send_json(501, {"error": "Voice typing isn't installed. Run setup.sh."})
                data = self.read_body()
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "wav" in ctype:
                    from urllib.parse import urlparse, parse_qs
                    qs = parse_qs(urlparse(self.path).query)
                    draft = qs.get("mode", ["final"])[0] == "draft"
                    context = (qs.get("context", [""])[0] or "")[-200:]
                    lang = (qs.get("lang", [""])[0] or "")[:3].lower() or None
                    return self.send_json(200, {"text": transcribe(wav_to_array(data), draft=draft, context=context, lang=lang)})
                ext = ".ogg" if "ogg" in ctype else ".webm"
                fd, path = tempfile.mkstemp(suffix=ext)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                try:
                    text = transcribe(decode_file(path))
                finally:
                    os.remove(path)
                return self.send_json(200, {"text": text})
            if self.path.startswith("/api/tts"):
                req = json.loads(self.read_body() or b"{}")
                text = str(req.get("text", ""))[:1000].strip()
                if not text:
                    return self.send_json(400, {"error": "no text"})
                wav = synthesize(text, req.get("rate", 1))
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav)))
                self.end_headers()
                self.wfile.write(wav)
                return
            return self.send_json(404, {"error": "unknown"})
        except Exception as e:  # report, keep serving
            sys.stderr.write(f"[error] {e}\n")
            return self.send_json(500, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser(description="BetterFrame Keyboard helper")
    ap.add_argument("--port", type=int, default=8643)
    ap.add_argument("--preload", action="store_true", help="load the speech model at start")
    args = ap.parse_args()
    cmd, voice = piper_cmd()
    print("BetterFrame Keyboard helper")
    print(f"  page:          http://localhost:{args.port}")
    print(f"  voice typing:  {'on (' + STT_MODEL + ')' if have_whisper() else 'off (run setup.sh)'}")
    print(f"  speak on Enter: {'Piper, ' + os.path.basename(voice) if cmd else 'browser voice only'}")
    if args.preload and have_whisper():
        threading.Thread(target=get_model, daemon=True).start()
    if args.preload and have_stream():
        def warm_live():
            try:
                with _rec_lock:
                    get_rec()
            except Exception as e:
                sys.stderr.write(f"[live] couldn't load the real-time recognizer: {e}\n")
        threading.Thread(target=warm_live, daemon=True).start()
    print(f"  live words:    {'on' if have_stream() else 'off (run setup.sh)'}")
    if args.preload and os.environ.get("BF_PRELOAD_VOICE") == "1":  # the system keyboard never reads aloud; load on first use
        def warm_voice():
            try:
                get_voice()
            except Exception as e:
                sys.stderr.write(f"[tts] couldn't preload the voice: {e}\n")
        threading.Thread(target=warm_voice, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
