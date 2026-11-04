#!/usr/bin/env python3
"""Debug audio input and microphone detection."""
import numpy as np
import sounddevice as sd

def list_devices():
    """List all audio devices."""
    print("🎵 Available Audio Devices:\n")
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        print(f"  [{i}] {device['name']}")
        print(f"      Channels: {device['max_input_channels']} in, {device['max_output_channels']} out")

    default_in = sd.default.device[0]
    default_out = sd.default.device[1]
    print(f"\n  Default input device: [{default_in}]")
    print(f"  Default output device: [{default_out}]\n")

def test_recording(device=None, duration=3):
    """Record and show audio levels."""
    print(f"🎤 Recording for {duration} seconds...")
    print("   (Speak loudly and clearly)\n")

    sr = 16000
    audio = sd.rec(int(sr * duration), samplerate=sr, channels=1, dtype='float32', device=device)
    sd.wait()

    audio = audio.flatten()
    rms_values = []
    chunk_size = sr // 10  # 100ms chunks

    print("RMS Levels (100ms chunks):")
    for i in range(0, len(audio), chunk_size):
        chunk = audio[i:i+chunk_size]
        if len(chunk) > 0:
            rms = float(np.sqrt(np.mean(chunk**2)))
            rms_values.append(rms)
            bar = "█" * int(rms * 200)  # Visual bar
            print(f"  {rms:.5f} {bar}")

    if rms_values:
        max_rms = max(rms_values)
        avg_rms = np.mean(rms_values)
        print(f"\n📊 Statistics:")
        print(f"  Max RMS: {max_rms:.5f}")
        print(f"  Avg RMS: {avg_rms:.5f}")
        print(f"\n⚠️  Diagnosis:")
        if max_rms < 0.01:
            print(f"  ❌ Microphone signal is TOO WEAK")
            print(f"     → Check if mic is muted or disconnected")
            print(f"     → Check System Preferences > Sound > Input")
            print(f"     → Try a different microphone")
        elif max_rms < 0.03:
            print(f"  ⚠️  Signal is weak but might work")
            print(f"     → Speak LOUDER and CLOSER to mic")
            print(f"     → Increase SILENCE_THRESHOLD in .env")
        else:
            print(f"  ✓ Signal looks good!")
    else:
        print("  ❌ No audio recorded at all!")

if __name__ == "__main__":
    list_devices()

    device_id = input("\nEnter device ID to test (press Enter for default): ").strip()
    device_id = int(device_id) if device_id else None

    test_recording(device=device_id)
