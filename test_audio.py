#!/usr/bin/env python3
"""Test microphone input and speech detection."""
import numpy as np
import sounddevice as sd

def test_microphone():
    """Test if microphone picks up sound."""
    print("🎤 Testing microphone for 3 seconds...")
    print("   (Speak loudly)\n")

    sr = 16000
    duration = 3
    audio = sd.rec(int(sr * duration), samplerate=sr, channels=1, dtype='float32')
    sd.wait()

    audio = audio.flatten()
    rms_values = []

    # Calculate RMS in 100ms chunks
    chunk_size = sr // 10
    for i in range(0, len(audio), chunk_size):
        chunk = audio[i:i+chunk_size]
        rms = float(np.sqrt(np.mean(chunk**2)))
        rms_values.append(rms)
        print(f"  RMS level: {rms:.4f}")

    max_rms = max(rms_values)
    print(f"\n✓ Max RMS detected: {max_rms:.4f}")
    print(f"  If this is < 0.01, your mic is too quiet")
    print(f"  If this is > 0.05, you have good signal")

if __name__ == "__main__":
    test_microphone()
