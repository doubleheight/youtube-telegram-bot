import asyncio
import os
import re
from pathlib import Path
import yt_dlp
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from dotenv import load_dotenv
# =========================
# НАСТРОЙКИ
# =========================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_PATH = "/webhook"
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Environment Variables")
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
# =========================
# TELEGRAM
# =========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
# =========================
# ПРОВЕРКА YOUTUBE ССЫЛКИ
# =========================
def is_youtube_url(text: str) -> bool:
    return bool(
        re.match(
            r"^https?://(www\.)?(youtube\.com|youtu\.be)/.+",
            text.strip(),
        )
    )
# =========================
# СКАЧИВАНИЕ YOUTUBE
# =========================
def download_video(url: str) -> Path:
    output = str(
        DOWNLOAD_DIR / "%(id)s.%(ext)s"
    )
    options = {
        # До 720p, чтобы не раздувать размер файла
        "format": (
            "bestvideo[height<=720]+bestaudio/"
            "best[height<=720]/"
            "best"
        ),
        "outtmpl": output,
        "noplaylist": True,
        # Не показываем прогресс в обычном виде,
        # но ошибки оставляем в логах Render.
        "quiet": False,
        "no_warnings": False,
        # Используем mweb — актуальный рекомендуемый
        # вариант для работы с PO Token provider.
        "extractor_args": {
            "youtube": {
                "player_client": ["mweb"],
            }
        },
        # Если видео скачивается отдельными video/audio
        # потоками — yt-dlp сможет объединить их.
        "merge_output_format": "mp4",
        # Не сохранять лишние файлы.
        "writethumbnail": False,
        "writeinfojson": False,
        "writesubtitles": False,
        # Повторить запрос при временных ошибках.
        "retries": 3,
        "fragment_retries": 3,
        # Нормальный User-Agent.
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            )
        },
    }
    print("========================================")
    print("YouTube download started")
    print("URL:", url)
    print("yt-dlp version:", yt_dlp.version.__version__)
    print("========================================")
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                url,
                download=True,
            )
            video_id = info["id"]
            print("Downloaded video ID:", video_id)
    except Exception as error:
        print("========================================")
        print("yt-dlp ERROR:")
        print(repr(error))
        print("========================================")
        raise
    files = list(
        DOWNLOAD_DIR.glob(f"{video_id}.*")
    )
    # Убираем возможные временные/служебные файлы.
    files = [
        file
        for file in files
        if file.suffix.lower()
        in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not files:
        raise FileNotFoundError(
            "После скачивания видеофайл не найден"
        )
    # Если файлов несколько — берём самый большой.
    video_path = max(
        files,
        key=lambda file: file.stat().st_size,
    )
    print("Video file:", video_path)
    print(
        "Video size:",
        video_path.stat().st_size,
        "bytes",
    )
    return video_path
# =========================
# /start
# =========================
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "🎬 Привет!\n\n"
        "Кидай ссылку на YouTube — "
        "я попробую скачать видео."
    )
# =========================
# ОБРАБОТКА СООБЩЕНИЙ
# =========================
@dp.message()
async def handle_message(message: types.Message):
    if not message.text:
        return
    url = message.text.strip()
    if not is_youtube_url(url):
        await message.answer(
            "❌ Пришли ссылку на YouTube."
        )
        return
    status = await message.answer(
        "⏳ Скачиваю видео..."
    )
    video_path = None
    try:
        video_path = await asyncio.to_thread(
            download_video,
            url,
        )
        file_size = video_path.stat().st_size
        # Telegram Bot API обычно ограничивает отправку
        # файлов ботом примерно 50 МБ.
        if file_size > 49 * 1024 * 1024:
            await status.edit_text(
                "❌ Видео получилось больше 49 МБ.\n"
                "Попробуй более короткое видео."
            )
            return
        await status.edit_text(
            "📤 Видео готово. Отправляю..."
        )
        await message.answer_video(
            video=types.FSInputFile(
                video_path
            ),
            supports_streaming=True,
        )
        await status.delete()
    except Exception as error:
        print("========================================")
        print("DOWNLOAD ERROR:")
        print(repr(error))
        print("========================================")
        try:
            await status.edit_text(
                "❌ Не получилось скачать это видео."
            )
        except Exception:
            pass
    finally:
        # Удаляем видео после отправки.
        if video_path and video_path.exists():
            try:
                video_path.unlink()
            except Exception as error:
                print(
                    "Не удалось удалить файл:",
                    repr(error),
                )
# =========================
# RENDER HEALTH CHECK
# =========================
async def health(request):
    return web.Response(
        text="OK"
    )
# =========================
# MAIN
# =========================
async def main():
    app = web.Application()
    app.router.add_get(
        "/",
        health,
    )
    webhook_url = os.getenv(
        "RENDER_EXTERNAL_URL"
    )
    if not webhook_url:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL не найден"
        )
    webhook_url = (
        webhook_url.rstrip("/")
        + WEBHOOK_PATH
    )
    print(
        "Webhook URL:",
        webhook_url,
    )
    await bot.set_webhook(
        webhook_url,
        drop_pending_updates=True,
    )
    async def webhook_handler(request):
        data = await request.json()
        update = types.Update.model_validate(
            data
        )
        await dp.feed_update(
            bot,
            update,
        )
        return web.Response(
            text="OK"
        )
    app.router.add_post(
        WEBHOOK_PATH,
        webhook_handler,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )
    await site.start()
    print("========================================")
    print("🤖 Бот запущен!")
    print("🌐 Port:", PORT)
    print("========================================")
    while True:
        await asyncio.sleep(3600)
# =========================
# START
# =========================
if __name__ == "__main__":
    asyncio.run(main())
