<div align="center">

# 🛡️ Aegis — ربات دیسکورد همه‌کاره

**نسخه فارسی** 🇮🇷 • [English](#english-version) 🇬🇧

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?style=for-the-badge&logo=discord&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-19%20passed-3DDC84?style=for-the-badge&logo=pytest&logoColor=white)

</div>

---

## ✨ معرفی

ایجیس یک بات دیسکورد **ماژولار و حرفه‌ای** با ۱۴ ماژول کامل است — از مدیریت سرور و تیکت پشتیبانی تا اقتصاد، لِوِلینگ، موزیک و بازی‌های تعاملی. همه‌چیز با دکمه و منوی تعاملی کار می‌کند.

## 🧩 ماژول‌ها

### ⚖️ مدیریت (Moderation)
- 🔨 بن، کیک، میوت و اخطار با شناسه کیس
- 📋 تاریخچه کامل موارد + پاکسازی پیام

### 🤖 خودکار (AutoMod)
- 🚫 فیلتر کلمات و لینک‌ها
- 🛡️ ضد اسپم خودکار

### 🎫 تیکت پشتیبانی
- 🎫 پنل زیبا با منوی موضوع + دکمه‌های باز کردن سریع
- 🔴 سیستم اولویت (سبز تا قرمز)
- 🤝 دکمه‌های Claim / Lock / Unlock
- 📄 ترنسکریپت خودکار در لاگ مدیریتی
- ⭐ امتیازدهی ستاره‌ای پس از بستن تیکت
- 📊 آمار کامل با `/ticket stats`

### 🎉 قرعه‌کشی
- 🎁 ورود و خروج با یک دکمه
- 💾 بعد از ری‌استارت هم ادامه پیدا می‌کند
- 👑 محدودیت نقش برای شرکت

### 📈 لِوِلینگ
- ⭐ XP خودکار هوشمند
- 🏆 جدول برترین‌ها صفحه‌بندی‌شده
- 🎭 نقش جایزه برای هر سطح
- 🔮 پیش‌نمایش نقش بعدی در `/rank`

### 💰 اقتصاد
- 🪙 جایزه روزانه و هفتگی + کار
- 🎰 اسلات، بلک‌جک، شیر یا خط
- 🛒 فروشگاه با خرید نقش

### 🎮 سرگرمی
- ✊ سنگ کاغذ قیچی تک‌نفره و دوئل دو نفره
- 🪙 استریک‌فلیپ • 🔢 حدس عدد
- 🎯 ترویا • 🎱 ۸بال • 😂 میم و جوک
- 🏷️ تگ سفارشی • 🔢 بازی شمارش گروهی

### 🎵 موزیک | 🎙️ صدا | 📊 لاگ | 🛡️ ضد نابودی | 👋 تعامل | 🛠️ ابزار | ⚙️ تنظیمات
- 🎶 پخش موزیک با FFmpeg
- 🔊 Join-to-Create + پنل دکمه‌ای (قفل، مخفی، محدودیت، Claim) + کیک صوتی
- 📜 لاگ کامل رویدادها
- 💣 ضد Nuke و ضد Raid
- 🕐 AFK، یادآور، LFG، کنفشن ناشناس
- ⚙️ پنل مدیریت ماژول‌ها با یک دستور

## 🚀 راه‌اندازی سریع

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# فایل .env را ویرایش کنید: DISCORD_TOKEN و OWNER_IDS
python main.py
```

### 🐳 داکر

```bash
docker build -t aegis-discord-bot .
docker run --env-file .env -v aegis-data:/app/data aegis-discord-bot
```

> 💡 برای توسعه `SYNC_GUILD_ID` را تنظیم کنید تا کامندها فوراً ظاهر شوند.
> ربات را با اسکوپ‌های `bot` و `applications.commands` اینوایت کنید.

---

<a name="english-version"></a>

<div align="center">

# 🛡️ Aegis — Full-Featured Discord Bot

**[نسخه فارسی](#readme)** 🇮🇷 • English Version 🇬🇧

</div>

---

## ✨ Overview

Aegis is a **modular, production-grade** Discord bot built on `discord.py 2.x`
with 14 complete modules — from moderation and support tickets to economy,
leveling, music, and interactive games. Everything works through buttons and
interactive menus.

Slash commands are grouped so the tree stays under Discord's 100-command cap.
An optional per-guild prefix still works for `ping` / `help`.

## 🧩 Modules

### ⚖️ Moderation
- 🔨 Ban, kick, mute and warnings with case IDs
- 📋 Full case history + message purging

### 🤖 AutoMod
- 🚫 Word and link filtering
- 🛡️ Automatic anti-spam

### 🎫 Support Tickets
- 🎫 Beautiful panel with topic menu + quick-open buttons
- 🔴 Priority system (low to urgent)
- 🤝 Claim / Lock / Unlock buttons
- 📄 Automatic transcript to the moderation log
- ⭐ Star rating after ticket closure
- 📊 Full statistics via `/ticket stats`

### 🎉 Giveaways
- 🎁 One-button entry and leave
- 💾 Survives restarts
- 👑 Required-role gating

### 📈 Leveling
- ⭐ Smart automatic XP
- 🏆 Paginated leaderboards
- 🎭 Role rewards per level
- 🔮 Next reward preview in `/rank`

### 💰 Economy
- 🪙 Daily, weekly rewards + work
- 🎰 Slots, blackjack, coin flip
- 🛒 Shop with role purchases

### 🎮 Fun & Games
- ✊ Rock-paper-scissors solo and duels
- 🪙 Streak flip • 🔢 Number guessing
- 🎯 Trivia • 🎱 8-ball • 😂 Memes and jokes
- 🏷️ Custom tags • 🔢 Community counting

### 🎵 Music | 🎙️ Voice | 📊 Logging | 🛡️ Protection | 👋 Engagement | 🛠️ Utility | ⚙️ Configuration
- 🎶 Music playback with FFmpeg
- 🔊 Join-to-Create + button panel (lock, hide, limit, claim) + voice kick
- 📜 Complete event logging
- 💣 Anti-nuke and anti-raid
- 🕐 AFK, reminders, LFG, anonymous confessions
- ⚙️ Module control panel with one command

## 🚀 Quick Start

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# edit .env and set DISCORD_TOKEN and OWNER_IDS
# optional: edit config/config.yml and config/messages.yml
python main.py
```

### 🐳 Docker

```bash
docker build -t aegis-discord-bot .
docker run --env-file .env -v aegis-data:/app/data aegis-discord-bot
```

> 💡 Set `SYNC_GUILD_ID` for development so commands appear instantly.
> Invite the application with the `bot` and `applications.commands` scopes.

---

<div align="center">

**MIT License** • Made with ❤️ by [mohammad1390555](https://github.com/mohammad1390555)

</div>
