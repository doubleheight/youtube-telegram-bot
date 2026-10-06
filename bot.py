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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def is_youtube_url(text: str) -> bool:
    return bool(
        re.match(
            r"^https?://(www\.)?(youtube\.com|youtu\.be)/.+",
            text.strip(),
        )
    )


def download_video(url: str) -> Path:

    output = str(
        DOWNLOAD_DIR / "%(id)s.%(ext)s"
    )

    options = {
        # Берём готовый файл, чтобы не требовался ffmpeg
        "format": (
            "best[ext=mp4][height<=720]/"
            "best[height<=720]/"
            "best"
        ),

        "outtmpl": output,

        "noplaylist": True,

        # YouTube + bgutil PO Token
        "extractor_args": {
            "youtube": {
                "player_client": ["mweb"],
            },
            "youtubepot-bgutilhttp": {
                "base_url": "http://127.0.0.1:4416",
            },
        },

        # Логи нужны нам для нормальной диагностики
        "quiet": False,
        "no_warnings": False,

        "retries": 3,
        "fragment_retries": 3,
    }

    print("================================")
    print("YT-DLP DOWNLOAD")
    print("URL:", url)
    print("================================")

    with yt_dlp.YoutubeDL(options) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        video_id = info["id"]

    files = list(
        DOWNLOAD_DIR.glob(
            f"{video_id}.*"
        )
    )

    if not files:
        raise FileNotFoundError(
            "Видео скачалось, но файл не найден"
        )

    return files[0]


@dp.message(CommandStart())
async def start(message: types.Message):

    await message.answer(
        "🎬 Привет!\n\n"
        "Кидай ссылку на YouTube."
    )


@dp.message()
async def handle_message(
    message: types.Message
):

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

        # Telegram Bot API: держим запас ниже лимита
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
            "================================"
        )

        print(
            "DOWNLOAD ERROR:",
            repr(error),
        )

        print(
            "================================"
        )

        try:

            await status.edit_text(
                "❌ Не получилось скачать видео."
            )

        except Exception:
            pass

    finally:

        if (
            video_path
            and video_path.exists()
        ):

            try:
                video_path.unlink()

            except Exception as error:

                print(
                    "FILE DELETE ERROR:",
                    repr(error),
                )


async def health(
    request
):

    return web.Response(
        text="OK"
    )


async def main():

    app = web.Application()

    # Render health check
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

    async def webhook_handler(
        request
    ):

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
    print("BGUTIL: http://127.0.0.1:4416")
    print("================================")

    while True:

        await asyncio.sleep(
            3600
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )
