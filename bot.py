import os
import asyncio
import logging
import re
import json
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
import yt_dlp
from ytmusicapi import YTMusic
from pyrogram import Client

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8823053211:AAFeZyJbfXQ4beh5W6XheH62gGKdGb48NkI")
API_ID = int(os.getenv("API_ID", "32523825"))
API_HASH = os.getenv("API_HASH", "77f5ee6cdc3f9b9cd8884b01c7f2268d")
SESSION_STRING = os.getenv("SESSION_STRING", "")
SESSION_FILE = Path(".session_string")

YT_REGEX = re.compile(r"(youtube\.com|youtu\.be|music\.youtube\.com)")
SPOTIFY_REGEX = re.compile(r"spotify\.com/(track|album|playlist)/")


class MusicBot:
    def __init__(self):
        self.app = Application.builder().token(BOT_TOKEN).build()
        self.call_client = None
        self.current_streams = {}
        self.queue = {}
        self.ytmusic = YTMusic()
        self.userbot = None

        yt_dlp.utils.bug_reports_message = lambda **kwargs: ""

        self.ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
            "noplaylist": True,
        }

    async def _ensure_session_string(self):
        """Get session string from env or file, validate and fail if not set"""
        import base64

        def is_valid_session_string(s: str) -> bool:
            try:
                base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
                return True
            except Exception:
                return False

        if SESSION_STRING:
            if is_valid_session_string(SESSION_STRING):
                return SESSION_STRING
            else:
                logger.error("SESSION_STRING is invalid (not valid base64)")
                raise RuntimeError(
                    "SESSION_STRING is invalid. Generate a new one:\n"
                    "python -c \"import asyncio; from pyrogram import Client; "
                    "async def gen(): "
                    "app=Client('userbot', api_id=32523825, api_hash='77f5ee6cdc3f9b9cd8884b01c7f2268d'); "
                    "await app.start(); print(await app.export_session_string()); await app.stop() "
                    "asyncio.run(gen())\"\n"
                    "Run this in Railway Shell, then add output as SESSION_STRING in Variables."
                )

        if SESSION_FILE.exists():
            session = SESSION_FILE.read_text().strip()
            if is_valid_session_string(session):
                return session

        # On Railway/headless, fail with clear message
        raise RuntimeError(
            "SESSION_STRING not set. Generate in Railway Shell:\n"
            "python -c \"import asyncio; from pyrogram import Client; "
            "async def gen(): "
            "app=Client('userbot', api_id=32523825, api_hash='77f5ee6cdc3f9b9cd8884b01c7f2268d'); "
            "await app.start(); print(await app.export_session_string()); await app.stop() "
            "asyncio.run(gen())\"\n"
            "Copy output → Railway Variables → SESSION_STRING → Redeploy."
        )

    async def initialize(self):
        session = await self._ensure_session_string()

        self.userbot = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=session)
        await self.userbot.start()
        self.call_client = PyTgCalls(self.userbot)
        await self.call_client.start()

        if hasattr(self.call_client, 'on_kicked'):
            self.call_client.on_kicked(self.on_kicked)
        if hasattr(self.call_client, 'on_closed_voice_chat'):
            self.call_client.on_closed_voice_chat(self.on_voice_chat_closed)
        if hasattr(self.call_client, 'on_stream_end'):
            self.call_client.on_stream_end(self.on_stream_end)

    async def on_kicked(self, _, chat_id: int):
        logger.info(f"Bot kicked from voice chat {chat_id}")
        self.current_streams.pop(chat_id, None)
        self.queue.pop(chat_id, None)

    async def on_voice_chat_closed(self, _, chat_id: int):
        logger.info(f"Voice chat closed in {chat_id}")
        self.current_streams.pop(chat_id, None)
        self.queue.pop(chat_id, None)

    async def on_stream_end(self, _, chat_id: int):
        logger.info(f"Stream ended in {chat_id}")
        await self.play_next(chat_id)

    async def play_next(self, chat_id: int):
        if chat_id in self.queue and self.queue[chat_id]:
            next_track = self.queue[chat_id].pop(0)
            await self.play_audio(chat_id, next_track["url"], next_track["title"], next_track["duration"])
        else:
            self.current_streams.pop(chat_id, None)
            await self.call_client.leave(chat_id)

    def _detect_source(self, query: str) -> str:
        if YT_REGEX.search(query):
            if "music.youtube.com" in query:
                return "ytmusic"
            return "youtube"
        if SPOTIFY_REGEX.search(query):
            return "spotify"
        return "search"

    def search_youtube(self, query: str, max_results: int = 5):
        search_opts = {**self.ydl_opts, "default_search": "ytsearch", "max_entries": max_results}
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            try:
                result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
                return result.get("entries", []) if result else []
            except Exception as e:
                logger.error(f"YouTube search error: {e}")
                return []

    def search_ytmusic(self, query: str, max_results: int = 5):
        try:
            results = self.ytmusic.search(query, filter="songs", limit=max_results)
            return [
                {
                    "id": r.get("videoId"),
                    "title": r.get("title"),
                    "artist": ", ".join([a["name"] for a in r.get("artists", [])]) if r.get("artists") else "Unknown",
                    "duration": r.get("duration_seconds", 0),
                    "webpage_url": f"https://youtube.com/watch?v={r.get('videoId')}",
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"YTMusic search error: {e}")
            return []

    def get_spotify_track_info(self, url: str):
        """Extract track info from Spotify URL using spotdl's metadata (no API key needed)"""
        try:
            import spotdl
            from spotdl.utils.spotify import SpotifyClient
            # Try to init without credentials (public metadata only)
            try:
                SpotifyClient.init()
            except:
                pass
            song = spotdl.Song.from_url(url)
            return {
                "title": song.name,
                "artist": song.artists[0] if song.artists else "",
                "duration": song.duration,
                "search_query": f"{song.name} {song.artists[0]}" if song.artists else song.name,
            }
        except Exception as e:
            logger.error(f"Spotify info error: {e}")
            return None

    def get_spotify_album_playlist_tracks(self, url: str):
        """Get all tracks from Spotify album/playlist"""
        try:
            import spotdl
            from spotdl.utils.spotify import SpotifyClient
            try:
                SpotifyClient.init()
            except:
                pass
            if "playlist" in url:
                songs = spotdl.Song.from_playlist(url)
            elif "album" in url:
                songs = spotdl.Song.from_album(url)
            else:
                return []
            return [
                {
                    "title": s.name,
                    "artist": s.artists[0] if s.artists else "",
                    "duration": s.duration,
                    "search_query": f"{s.name} {s.artists[0]}" if s.artists else s.name,
                }
                for s in songs
            ]
        except Exception as e:
            logger.error(f"Spotify playlist error: {e}")
            return []

    def get_stream_url(self, video_url: str):
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=False)
                formats = info.get("formats", [])
                audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
                if audio_formats:
                    best_audio = max(audio_formats, key=lambda x: x.get("abr", 0))
                    return best_audio["url"], info.get("title"), info.get("duration", 0)
                return info.get("url"), info.get("title"), info.get("duration", 0)
            except Exception as e:
                logger.error(f"Stream URL error for {video_url}: {e}")
                return None, None, 0

    async def play_audio(self, chat_id: int, stream_url: str, title: str, duration: int):
        try:
            await self.call_client.play(chat_id, MediaStream(stream_url))
            self.current_streams[chat_id] = {"title": title, "duration": duration}
            return True
        except Exception as e:
            logger.error(f"Play error: {e}")
            return False

    async def resolve_and_play(self, chat_id: int, query: str, msg):
        source = self._detect_source(query)

        # Spotify playlist/album - queue all tracks
        if source == "spotify" and ("playlist" in query or "album" in query):
            tracks = self.get_spotify_album_playlist_tracks(query)
            if not tracks:
                await msg.edit_text("❌ No tracks found")
                return

            await msg.edit_text(f"🎵 Found {len(tracks)} tracks. Searching YouTube...")

            added = 0
            for i, track in enumerate(tracks):
                results = self.search_youtube(track["search_query"], 1)
                if results:
                    stream_url, title, duration = self.get_stream_url(results[0]["webpage_url"])
                    if stream_url:
                        if i == 0 and chat_id not in self.current_streams:
                            success = await self.play_audio(chat_id, stream_url, title, duration)
                            if success:
                                await msg.edit_text(f"🎵 Now playing: {title}")
                        else:
                            self.queue.setdefault(chat_id, []).append({"url": stream_url, "title": title, "duration": duration})
                        added += 1
                if i < 5:
                    await asyncio.sleep(0.3)

            if added > 0 and chat_id in self.current_streams:
                await msg.edit_text(f"🎵 Now playing: {tracks[0]['title']}\n➕ Queued {added-1} more tracks")
            return

        # Single track
        if source == "spotify":
            info = self.get_spotify_track_info(query)
            if info:
                results = self.search_youtube(info["search_query"], 1)
                if results:
                    stream_url, title, duration = self.get_stream_url(results[0]["webpage_url"])
                else:
                    await msg.edit_text("❌ Not found on YouTube")
                    return
            else:
                await msg.edit_text("❌ Failed to get Spotify track info")
                return
        elif source == "ytmusic":
            stream_url, title, duration = self.get_stream_url(query)
        else:
            results = self.search_youtube(query, 1)
            if not results:
                results = self.search_ytmusic(query, 1)
            if not results:
                await msg.edit_text("❌ No results found")
                return
            track = results[0]
            url = track.get("webpage_url") or f"https://youtube.com/watch?v={track.get('id')}"
            stream_url, title, duration = self.get_stream_url(url)

        if not stream_url:
            await msg.edit_text("❌ Failed to get stream")
            return

        if chat_id not in self.current_streams:
            success = await self.play_audio(chat_id, stream_url, title, duration)
            if success:
                await msg.edit_text(f"🎵 Now playing: {title}")
            else:
                await msg.edit_text("❌ Failed to join voice chat. Start a voice chat first!")
        else:
            self.queue.setdefault(chat_id, []).append({"url": stream_url, "title": title, "duration": duration})
            await msg.edit_text(f"➕ Added to queue: {title}")

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_type = update.effective_chat.type
        if chat_type == "private":
            await update.message.reply_text(
                "👋 Hello! I'm your Music Bot! 🎵\n\n"
                "I can play music in voice chats from YouTube, YouTube Music, and Spotify!\n\n"
                "**What I can do:**\n"
                "🎵 Play songs from YouTube, YouTube Music, and Spotify\n"
                "🔍 Search for music and let you pick from results\n"
                "⏭️ Skip tracks, view queue, control playback\n"
                "🔊 Adjust volume between 1-100%\n\n"
                "**To get started:**\n"
                "1. Add me to your Telegram group\n"
                "2. Promote me to admin with 'Voice Chat' permissions\n"
                "3. Start a voice chat in your group\n"
                "4. Use `/play <song name or URL>` to start playing!\n\n"
                "Use /help to see all available commands!"
            )
        else:
            await update.message.reply_text(
                "🎵 Music Bot is ready! Use /play <song name or URL> to start playing music in this voice chat.\n"
                "Use /help to see all available commands."
            )

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_type = update.effective_chat.type
        if chat_type == "private":
            await update.message.reply_text(
                "🎵 **Music Bot Help**\n\n"
                "I can play music in voice chats from YouTube, YouTube Music, and Spotify!\n\n"
                "**Available Commands:**\n"
                "/start - Start the bot and see welcome message\n"
                "/help - Show this help message\n"
                "/play <song name or URL> - Play music in voice chat\n"
                "/search <query> - Search for songs and select from results\n"
                "/skip - Skip the current track\n"
                "/queue - Show the current song queue\n"
                "/stop - Stop playback and leave voice chat\n"
                "/pause - Pause the current playback\n"
                "/resume - Resume paused playback\n"
                "/volume <1-100> - Set volume level\n\n"
                "**Supported Sources:**\n"
                "• YouTube: youtube.com/watch?v=..., youtu.be/...\n"
                "• YouTube Music: music.youtube.com/watch?v=...\n"
                "• Spotify: spotify.com/track/..., spotify.com/album/..., spotify.com/playlist/...\n"
                "• Search: Just type song name or artist\n\n"
                "**How to Use:**\n"
                "1. Add me to your group\n"
                "2. Start a voice chat in the group\n"
                "3. Use /play <song name or URL> to start playing\n"
                "4. Use other commands to control playback\n\n"
                "Note: The bot requires a user account with voice chat permissions to join and play in voice chats."
            )
        else:
            await update.message.reply_text(
                "🎵 Music Bot Commands:\n"
                "/play <song> - Play music\n"
                "/search <query> - Search songs\n"
                "/skip - Skip track\n"
                "/queue - Show queue\n"
                "/stop - Stop and leave\n"
                "/pause - Pause playback\n"
                "/resume - Resume playback\n"
                "/volume <1-100> - Set volume"
            )

    async def play_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /play <song name or URL>")
            return

        chat_id = update.effective_chat.id
        query = " ".join(context.args)
        msg = await update.message.reply_text(f"🔍 Searching: {query}...")
        await self.resolve_and_play(chat_id, query, msg)

    async def search_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /search <query>")
            return

        query = " ".join(context.args)
        results = self.search_youtube(query, 5)
        if not results:
            results = self.search_ytmusic(query, 5)

        if not results:
            await update.message.reply_text("❌ No results found")
            return

        keyboard = []
        for i, track in enumerate(results[:5]):
            title = track.get("title", "Unknown")
            artist = track.get("artist", track.get("uploader", ""))
            duration = track.get("duration", 0)
            dur_str = f"{duration//60}:{duration%60:02d}" if duration else "?"
            display = f"{i+1}. {title}"
            if artist:
                display += f" - {artist}"
            display += f" ({dur_str})"
            video_id = track.get("id") or track.get("videoId", "")
            keyboard.append([InlineKeyboardButton(display, callback_data=f"play_{video_id}")])

        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        await update.message.reply_text(
            f"🔍 Results for: {query}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        data = query.data
        if data == "cancel":
            await query.edit_message_text("Cancelled")
            return

        if data.startswith("play_"):
            video_id = data[5:]
            chat_id = update.effective_chat.id

            await query.edit_message_text("🔄 Getting stream...")

            stream_url, title, duration = self.get_stream_url(f"https://youtube.com/watch?v={video_id}")

            if not stream_url:
                await query.edit_message_text("❌ Failed to get stream")
                return

            if chat_id not in self.current_streams:
                success = await self.play_audio(chat_id, stream_url, title, duration)
                if success:
                    await query.edit_message_text(f"🎵 Now playing: {title}")
                else:
                    await query.edit_message_text("❌ Failed to join voice chat. Start a voice chat first!")
            else:
                self.queue.setdefault(chat_id, []).append({"url": stream_url, "title": title, "duration": duration})
                await query.edit_message_text(f"➕ Added to queue: {title}")

    async def skip_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if chat_id in self.current_streams:
            if chat_id in self.queue and self.queue[chat_id]:
                next_track = self.queue[chat_id].pop(0)
                await self.play_audio(chat_id, next_track["url"], next_track["title"], next_track["duration"])
            else:
                self.current_streams.pop(chat_id, None)
                await self.call_client.leave(chat_id)
            await update.message.reply_text("⏭ Skipped")
        else:
            await update.message.reply_text("Nothing playing")

    async def queue_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        text = "📋 Queue:\n"

        if chat_id in self.current_streams:
            track = self.current_streams[chat_id]
            text += f"🎵 Now: {track['title']}\n"

        if chat_id in self.queue and self.queue[chat_id]:
            for i, track in enumerate(self.queue[chat_id], 1):
                text += f"{i}. {track['title']}\n"
        else:
            text += "Queue empty"

        await update.message.reply_text(text)

    async def stop_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        self.current_streams.pop(chat_id, None)
        self.queue.pop(chat_id, None)
        await self.call_client.leave(chat_id)
        await update.message.reply_text("⏹ Stopped and left voice chat")

    async def pause_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if chat_id in self.current_streams:
            await self.call_client.pause(chat_id)
            await update.message.reply_text("⏸ Paused")
        else:
            await update.message.reply_text("Nothing playing")

    async def resume_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if chat_id in self.current_streams:
            await self.call_client.resume(chat_id)
            await update.message.reply_text("▶️ Resumed")
        else:
            await update.message.reply_text("Nothing playing")

    async def volume_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or not context.args[0].isdigit():
            await update.message.reply_text("Usage: /volume <1-100>")
            return

        vol = int(context.args[0])
        vol = max(1, min(100, vol))

        chat_id = update.effective_chat.id
        if chat_id in self.current_streams:
            await self.call_client.set_volume(chat_id, vol)
            await update.message.reply_text(f"🔊 Volume set to {vol}%")
        else:
            await update.message.reply_text("Nothing playing")

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_cmd))
        self.app.add_handler(CommandHandler("help", self.help_cmd))
        self.app.add_handler(CommandHandler("play", self.play_cmd))
        self.app.add_handler(CommandHandler("search", self.search_cmd))
        self.app.add_handler(CommandHandler("skip", self.skip_cmd))
        self.app.add_handler(CommandHandler("queue", self.queue_cmd))
        self.app.add_handler(CommandHandler("stop", self.stop_cmd))
        self.app.add_handler(CommandHandler("pause", self.pause_cmd))
        self.app.add_handler(CommandHandler("resume", self.resume_cmd))
        self.app.add_handler(CommandHandler("volume", self.volume_cmd))
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))

    async def run(self):
        await self.initialize()
        self.setup_handlers()
        # Set bot commands menu
        await self.app.bot.set_my_commands([
            BotCommand("start", "Start the bot and see welcome message"),
            BotCommand("help", "Get help and list of available commands"),
            BotCommand("play", "Play a song from YouTube, Spotify, or YouTube Music"),
            BotCommand("search", "Search for songs and select from results"),
            BotCommand("skip", "Skip the current track"),
            BotCommand("queue", "View the current song queue"),
            BotCommand("stop", "Stop playback and leave voice chat"),
            BotCommand("pause", "Pause the current playback"),
            BotCommand("resume", "Resume paused playback"),
            BotCommand("volume", "Set volume level (1-100)")
        ])
        logger.info("Bot started with command menu set!")
        try:
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            # yahan pyrogram/pytgcalls ka initialize bhi already ho chuka hoga
            # ab bot ko zinda rakhne ke liye:
            await asyncio.Event().wait()  # ya jo bhi existing idle mechanism hai (pyrogram ka idle() bhi chalega agar already import hai)
        finally:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()


async def main():
    bot = MusicBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())

