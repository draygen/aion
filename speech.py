"""Speech-to-text module using Whisper on GPU."""

import numpy as np
import sounddevice as sd
import logging
import sys
import time

from config import CONFIG

logger = logging.getLogger("jarvis.speech")

# Lazy load the model to avoid slow startup
_model = None


def get_model():
    """Load Whisper model lazily with GPU support."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        model_size = CONFIG.get("whisper_model", "base")
        logger.info(f"Loading Whisper model '{model_size}' on GPU...")
        print(f"Loading Whisper model '{model_size}'... (first time may download ~150MB)")

        # Use CUDA if available, otherwise CPU
        try:
            _model = WhisperModel(
                model_size,
                device="cuda",
                compute_type="float16"  # Use float16 for GPU efficiency
            )
            logger.info("Whisper model loaded successfully on GPU")
        except Exception as e:
            logger.warning(f"GPU not available, falling back to CPU: {e}")
            print("GPU not available, using CPU (slower)...")
            _model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8"
            )
            logger.info("Whisper model loaded on CPU")
        print("Whisper ready.")
    return _model


def record_audio(
    sample_rate: int = 16000,
    silence_threshold: float = 0.01,
    silence_duration: float = 1.5,
    max_duration: float = 30.0,
    min_duration: float = 0.5
) -> np.ndarray | None:
    """
    Record audio from microphone until silence is detected.

    Args:
        sample_rate: Audio sample rate (Whisper expects 16kHz)
        silence_threshold: RMS threshold below which audio is considered silence
        silence_duration: Seconds of silence before stopping
        max_duration: Maximum recording duration
        min_duration: Minimum recording duration before silence detection kicks in

    Returns:
        numpy array of audio data, or None if cancelled
    """
    print("Listening... (speak now, silence to finish)")

    chunks = []
    silent_chunks = 0
    chunk_duration = 0.1  # 100ms chunks
    chunk_samples = int(sample_rate * chunk_duration)
    silence_chunks_needed = int(silence_duration / chunk_duration)
    max_chunks = int(max_duration / chunk_duration)
    min_chunks = int(min_duration / chunk_duration)

    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype='float32') as stream:
            for i in range(max_chunks):
                audio_chunk, _ = stream.read(chunk_samples)
                chunks.append(audio_chunk.copy())

                # Calculate RMS for silence detection
                rms = np.sqrt(np.mean(audio_chunk ** 2))

                if rms < silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0

                # Stop if enough silence after minimum duration
                if i >= min_chunks and silent_chunks >= silence_chunks_needed:
                    break

    except KeyboardInterrupt:
        print("\nRecording cancelled.")
        return None
    except Exception as e:
        logger.error(f"Error recording audio: {e}")
        print(f"Error recording: {e}")
        return None

    if not chunks:
        return None

    # Concatenate all chunks
    audio = np.concatenate(chunks, axis=0).flatten()
    duration = len(audio) / sample_rate
    logger.debug(f"Recorded {duration:.1f}s of audio")

    # Check if we got meaningful audio
    if np.max(np.abs(audio)) < silence_threshold:
        print("No speech detected.")
        return None

    return audio


def transcribe(audio: np.ndarray, sample_rate: int = 16000) -> str:
    """
    Transcribe audio using Whisper.

    Args:
        audio: numpy array of audio samples
        sample_rate: sample rate of the audio

    Returns:
        Transcribed text
    """
    model = get_model()

    # faster-whisper expects float32 audio
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)

    logger.debug("Transcribing audio...")
    start_time = time.time()

    segments, info = model.transcribe(
        audio,
        beam_size=5,
        language="en",
        vad_filter=True,  # Filter out non-speech
        vad_parameters=dict(min_silence_duration_ms=500)
    )

    # Collect all segment texts
    text = " ".join(segment.text.strip() for segment in segments)

    elapsed = time.time() - start_time
    logger.debug(f"Transcription took {elapsed:.2f}s: {text}")

    return text.strip()


def listen() -> str | None:
    """
    Record audio and transcribe it.

    Returns:
        Transcribed text, or None if no speech detected/cancelled
    """
    audio = record_audio()
    if audio is None:
        return None

    text = transcribe(audio)
    if not text:
        print("Could not understand audio.")
        return None

    return text


def check_microphone() -> bool:
    """Check if a microphone is available."""
    try:
        devices = sd.query_devices()
        input_devices = [d for d in devices if d['max_input_channels'] > 0]
        if not input_devices:
            print("No microphone found.")
            return False
        default = sd.query_devices(kind='input')
        logger.info(f"Using microphone: {default['name']}")
        return True
    except Exception as e:
        logger.error(f"Error checking microphone: {e}")
        print(f"Microphone error: {e}")
        return False


if __name__ == "__main__":
    # Test the speech module
    logging.basicConfig(level=logging.DEBUG)
    print("Speech module test")
    print("=" * 40)

    if not check_microphone():
        sys.exit(1)

    print("\nSay something...")
    text = listen()
    if text:
        print(f"\nYou said: {text}")
    else:
        print("\nNo speech detected.")
