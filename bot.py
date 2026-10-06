import asyncio
import os
import re
from pathlib import Path

import yt_dlp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def is_youtube_url(text: str) -> bool:
    return bool(
        re.match(
            r"^https?://(www\.)?(youtube\.com|youtu\.be)/.+",
            text.strip()
        )
    )


def download_video(url: str) -> Path:
    output = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")

    options = {
        "format": "best[ext=mp4][height<=720]/best[height<=720]",
        "outtmpl": output,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info["id"]

    files = list(DOWNLOAD_DIR.glob(f"{video_id}.*"))

    if not files:
        raise FileNotFoundError("Видео не найдено после скачивания")

    return files[0]


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "🎬 Привет!\n\n"
        "Кидай мне ссылку на YouTube — "
        "я попробую скачать видео и отправить его сюда."
    )


@dp.message()
async def handle_message(message: types.Message):

    if not message.text:
        return

    url = message.text.strip()

    if not is_youtube_url(url):
        await message.answer(
            "❌ Нужна ссылка на YouTube."
        )
        return

    status = await message.answer(
        "⏳ Скачиваю видео..."
    )

    video_path = None

    try:
        video_path = await asyncio.to_thread(
            download_video,
            url
        )

        file_size = video_path.stat().st_size

        # Telegram Bot API имеет ограничение на отправку файлов.
        # Оставляем запас ниже лимита.
        if file_size > 49 * 1024 * 1024:
            await status.edit_text(
                "❌ Видео получилось слишком большим для отправки."
            )
            return

        await status.edit_text(
            "📤 Готово. Отправляю видео..."
        )

        await message.answer_video(
            video=types.FSInputFile(video_path),
            supports_streaming=True
        )

        await status.delete()

    except Exception as error:

        print("ERROR:", repr(error))

        await status.edit_text(
            "❌ Не получилось скачать это видео.\n\n"
            "Попробуй другую ссылку."
        )

    finally:

        if video_path and video_path.exists():
            try:
                video_path.unlink()
            except Exception:
                pass


async def main():
    print("🤖 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
