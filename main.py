import asyncio
import logging
import sqlite3
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile, InputMediaPhoto
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

TOKEN = "6520086943:AAErH79sglJmnp3Jns6fEzGbmNsDJwfwcNY"
CHANNEL_ID = "@djddnd103"

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()


# FSM States
class PostState(StatesGroup):
    waiting_for_photos = State()
    waiting_for_caption = State()
    waiting_for_time = State()


# Database connection
def init_db():
    conn = sqlite3.connect("posts.db")
    cursor = conn.cursor()

    # Jadvalni yaratish
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_path TEXT NOT NULL,
            caption TEXT NOT NULL,
            post_time TEXT NOT NULL,
            group_id TEXT NOT NULL
        )
    """)

    # Agar jadval allaqachon mavjud bo'lsa, `group_id` ustunini qo'shish
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN group_id TEXT")
    except sqlite3.OperationalError:
        # Agar ustun allaqachon mavjud bo'lsa, xatolikni e'tiborsiz qoldirish
        pass

    conn.commit()
    conn.close()


@dp.message(Command("add_post"))
async def add_post_command(message: types.Message, state: FSMContext):
    await message.reply("Iltimos, 9 tagacha rasm yuboring. Yuborib bo‘lgach, 'Yuborish' deb yozing.")
    await state.update_data(images=[])
    await state.set_state(PostState.waiting_for_photos)


@dp.message(PostState.waiting_for_photos, F.photo)
async def save_photos(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    images = user_data.get("images", [])

    if len(images) >= 9:
        await message.reply("Siz faqat 9 ta rasm yuborishingiz mumkin. 'Yuborish' deb yozing.")
        return

    image_path = f"photo_{message.from_user.id}_{len(images)}.jpg"
    await message.bot.download(message.photo[-1], image_path)
    images.append(image_path)
    await state.update_data(images=images)
    await message.reply(f"{len(images)}/9 rasm qabul qilindi. Davom eting yoki 'Yuborish' deb yozing.")


@dp.message(PostState.waiting_for_photos, F.text.lower() == "yuborish")
async def finish_photos(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    images = user_data.get("images", [])

    if not images:
        await message.reply("Iltimos, kamida bitta rasm yuboring!")
        return

    await state.set_state(PostState.waiting_for_caption)
    await message.reply("Endi, post uchun matn yuboring.")


@dp.message(PostState.waiting_for_caption, F.text)
async def save_caption(message: types.Message, state: FSMContext):
    await state.update_data(caption=message.text)
    await message.reply("Endi, vaqtni HH:MM formatda kiriting.")
    await state.set_state(PostState.waiting_for_time)


@dp.message(PostState.waiting_for_time, F.text)
async def save_time(message: types.Message, state: FSMContext):
    post_time = message.text.strip()
    try:
        datetime.strptime(post_time, "%H:%M")  # Formatni tekshiramiz
    except ValueError:
        await message.reply("Iltimos, vaqtni to'g'ri formatda kiriting (masalan, 15:30)")
        return

    user_data = await state.get_data()
    images = user_data.get("images")
    caption = user_data.get("caption")
    group_id = f"{message.from_user.id}_{post_time.replace(':', '')}"

    conn = sqlite3.connect("posts.db")
    cursor = conn.cursor()
    for image_path in images:
        cursor.execute("INSERT INTO posts (image_path, caption, post_time, group_id) VALUES (?, ?, ?, ?)",
                       (image_path, caption, post_time, group_id))
    conn.commit()
    conn.close()

    await message.reply(f"Post muvaffaqiyatli saqlandi! {post_time} da kanalga joylanadi.")
    await state.clear()


async def post_to_channel():
    now = datetime.now().strftime("%H:%M")
    conn = sqlite3.connect("posts.db")
    cursor = conn.cursor()
    cursor.execute("SELECT image_path, caption, group_id FROM posts WHERE post_time = ?", (now,))
    posts = cursor.fetchall()
    conn.close()

    post_groups = {}
    for image_path, caption, group_id in posts:
        if group_id not in post_groups:
            post_groups[group_id] = {"caption": caption, "images": []}
        post_groups[group_id]["images"].append(image_path)

    for group_id, data in post_groups.items():
        media = [
            InputMediaPhoto(media=FSInputFile(img), caption=data["caption"] if i == 0 else "")
            for i, img in enumerate(data["images"])
        ]
        try:
            await bot.send_media_group(CHANNEL_ID, media)
            # After successfully sending the media, delete the entries from the database
            conn = sqlite3.connect("posts.db")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM posts WHERE group_id = ?", (group_id,))
            conn.commit()
            conn.close()

            # Optionally delete the image files if no longer needed
            for img in data["images"]:
                try:
                    os.remove(img)
                except FileNotFoundError:
                    logging.warning(f"Image file not found: {img}")
                except Exception as e:
                    logging.error(f"Failed to delete image {img}: {e}")
        except Exception as e:
            logging.error(f"Failed to send media group for group {group_id}: {e}")


async def scheduler_task():
    scheduler.add_job(post_to_channel, "interval", minutes=1)
    scheduler.start()


async def main():
    init_db()
    dp.startup.register(scheduler_task)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())