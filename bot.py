import asyncio
import os
import re
from pathlib import Path

import yt_dlp
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

WEBHOOK_PATH = "/webhook"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

if not RENDER_EXTERNAL_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL не найден")


DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

COOKIES_FILE = Path("/tmp/youtube_cookies.txt")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def is_youtube_url(text: str) -> bool:
    return bool(
        re.match(
            r"^https?://(www\.)?(youtube\.com|youtu\.be)/.+",
            text.strip(),
        )
    )


def check_cookies():
    if not COOKIES_FILE.exists():
        raise RuntimeError(
            "Файл YouTube cookies не найден: "
            f"{COOKIES_FILE}"
        )

    if COOKIES_FILE.stat().st_size == 0:
        raise RuntimeError("Файл YouTube cookies пустой")


def download_video(url: str) -> Path:
    check_cookies()

    output = str(
        DOWNLOAD_DIR / "%(id)s.%(ext)s"
    )

    options = {
        # ВАЖНО:
        # Берём готовый mp4-файл, чтобы не требовался ffmpeg.
        "format": (
            "best[ext=mp4][height<=720]/"
            "best[height<=720]/"
            "best"
        ),

        "outtmpl": output,

        "noplaylist": True,

        # YouTube
        "extractor_args": {
            "youtube": {
                "player_client": ["mweb"],
            },
            "youtubepot-bgutilhttp": {
                "base_url": "http://127.0.0.1:4416",
            },
        },

        # Cookies отдельного YouTube-аккаунта
        "cookiefile": str(COOKIES_FILE),

        # Не скачивать огромные файлы
        "max_filesize": 49 * 1024 * 1024,

        # Сетевые настройки
        "retries": 3,
        "fragment_retries": 3,

        # Логи
        "quiet": False,
        "no_warnings": False,
    }

    print("=== YT-DLP START ===")
    print("URL:", url)
    print("Cookies:", COOKIES_FILE)
    print("=== YT-DLP OPTIONS ===")

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            url,
            download=True,
        )

        video_id = info["id"]

    files = list(
        DOWNLOAD_DIR.glob(f"{video_id}.*")
    )

    if not files:
        raise FileNotFoundError(
            "После скачивания файл не найден"
        )

    return files[0]


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "🎬 Кидай ссылку на YouTube."
    )


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

        if file_size > 49 * 1024 * 1024:
            await status.edit_text(
                "❌ Видео получилось больше 49 МБ."
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

        print(
            "DOWNLOAD ERROR:",
            repr(error),
        )

        await status.edit_text(
            "❌ Не получилось скачать видео."
        )

    finally:

        if video_path and video_path.exists():
            try:
                video_path.unlink()
            except Exception:
                pass


async def health(request):
    return web.Response(text="OK")


async def main():

    app = web.Application()

    app.router.add_get(
        "/",
        health,
    )

    webhook_url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + WEBHOOK_PATH
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

    print("================================")
    print("🤖 BOT STARTED")
    print("PORT:", PORT)
    print("WEBHOOK:", webhook_url)
    print("COOKIES:", COOKIES_FILE)
    print("================================")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
