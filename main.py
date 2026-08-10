import discord
from discord.ext import commands, tasks
import sqlite3
import time
import colorsys
import os

# Настройка намерений
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)
active_sessions = {}

# === ВАЖНЫЕ НАСТРОЙКИ СЕРВЕРА ===
ADMIN_IDS = [
    595594811239694374, 864117995932090389, 316985657371262988  # Впишите сюда ваш ID и ID других админов через запятую
]
LOG_CHANNEL_ID = 1534155761608032336  # ЗАМЕНИТЕ НА ID ТЕКСТОВОГО КАНАЛА ДЛЯ СТАТИСТИКИ И ОПОВЕЩЕНИЙ
# ===============================

# Подключение базы данных SQLite
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
db_path = os.path.join(DATA_DIR, 'voice_time.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    total_seconds INTEGER DEFAULT 0
)
""")
conn.commit()

# Базовые 10 цветов уровней Steam (для десятков часов: 0, 10, 20... 90)
BASE_STEAM_COLORS = [
    0x9b9b9b, 0x931c22, 0xe35914, 0xb6960d, 0x2d7831, 
    0x1c6c9a, 0x4c327d, 0xbf429c, 0x5e3a31, 0xa28564
]

def adjust_brightness(hex_color, hours):
    """Автоматически меняет яркость базового цвета под каждую сотню часов"""
    r = (hex_color >> 16) & 0xFF
    g = (hex_color >> 8) & 0xFF
    b = hex_color & 0xFF

    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    hundreds = int(hours) // 100

    if hundreds == 0:
        modifier = 0.0
    elif hundreds == 1:
        modifier = -0.15
    elif hundreds == 2:
        modifier = -0.30
    elif hundreds == 3:
        modifier = 0.15
    elif hundreds == 4:
        modifier = 0.30
    else:
        modifier = (hundreds % 3 - 1) * 0.12

    l = max(0.10, min(0.90, l + modifier))
    new_r, new_g, new_b = colorsys.hls_to_rgb(h, l, s)
    return (int(new_r * 255) << 16) + (int(new_g * 255) << 8) + int(new_b * 255)

async def manage_time_roles(member, total_hours):
    """Управляет созданием, покраской и выдачей ролей на сервере"""
    hours_int = int(total_hours)
    
    # 1. Определяем, какую роль нужно выдать
    if hours_int >= 10:
        current_milestone = (hours_int // 10) * 10
        target_role_name = f"{current_milestone} часов"
        digit = (current_milestone // 10) % 10
        base_color = BASE_STEAM_COLORS[digit]
        final_hex = adjust_brightness(base_color, current_milestone)
    elif hours_int >= 5:
        current_milestone = 5
        target_role_name = "5 часов"
        final_hex = 0x757575  # Глубокий серый
    elif hours_int >= 1:
        current_milestone = 1
        target_role_name = "1 час"
        final_hex = 0xffffff  # Чистый белый цвет на старте
    else:
        return  # Если меньше 1 часа, ничего не делаем

    guild = member.guild

    # 2. Ищем или создаем роль
    target_role = discord.utils.get(guild.roles, name=target_role_name)
    if not target_role:
        role_color = discord.Color(final_hex)
        target_role = await guild.create_role(name=target_role_name, color=role_color, reason="Часовая система")
        print(f"[Успех] Создана роль: {target_role_name}")

    # 3. Выдаем роль, если её еще нет
    if target_role not in member.roles:
        await member.add_roles(target_role)
        
        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            if log_channel:
                hours_text = "час" if current_milestone == 1 else ("часа" if current_milestone == 5 else "часов")
                await log_channel.send(f"🎉 Поздравляем {member.mention} с повышением уровня активности!")
                
                embed_lvl = discord.Embed(
                    title="📈 Новый Уровень Голосовой Активности!",
                    description=f"Вы провели уже целых **{current_milestone}** {hours_text} в голосовых каналах сервера!",
                    color=final_hex
                )
                embed_lvl.add_field(name="Новая полученная роль:", value=target_role.mention)
                embed_lvl.set_thumbnail(url=member.avatar.url if member.avatar else None)
                embed_lvl.set_footer(text="Статус персонажа: Активен 🎮")
                await log_channel.send(embed=embed_lvl)
        except Exception as e:
            print(f"[Ошибка отправки лога] Не удалось отправить сообщение в канал {LOG_CHANNEL_ID}: {e}")

    # 4. Очищаем все остальные часовые роли (включая роли 1 час и 5 часов)
    for role in member.roles:
        if ("часов" in role.name or "час" in role.name) and role.name != target_role_name:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                print(f"[Ошибка] Бот не может управлять ролью {role.name}. Поднимите его роль выше!")

# Исправленная фоновая проверка в реальном времени
@tasks.loop(seconds=60)
async def check_live_voice_users():
    current_time = int(time.time())
    for user_id, join_time in list(active_sessions.items()):
        duration = current_time - join_time
        if duration <= 0:
            continue
            
        active_sessions[user_id] = current_time
        
        cursor.execute("INSERT OR IGNORE INTO users (user_id, total_seconds) VALUES (?, 0)", (user_id,))
        cursor.execute("UPDATE users SET total_seconds = total_seconds + ? WHERE user_id = ?", (duration, user_id))
        conn.commit()
        
        cursor.execute("SELECT total_seconds FROM users WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        if res:
            total_seconds = res[0]  # Исправлено: извлекаем число из кортежа базы данных
            for guild in bot.guilds:
                member = guild.get_member(user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(user_id)
                    except:
                        continue
                if member:
                    await manage_time_roles(member, total_seconds / 3600)

@bot.event
async def on_ready():
    print(f"==========================================")
    print(f"Бот {bot.user} успешно запущен и готов к работе!")
    print(f"Канал для логов и команд установлен на ID: {LOG_CHANNEL_ID}")
    print(f"==========================================")
    if not check_live_voice_users.is_running():
        check_live_voice_users.start()

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    user_id = member.id
    current_time = int(time.time())

    # Вход в голосовой канал
    if before.channel is None and after.channel is not None:
        active_sessions[user_id] = current_time

    # Выход из голосового канала
    elif before.channel is not None and after.channel is None:
        if user_id in active_sessions:
            join_time = active_sessions.pop(user_id)
            duration = current_time - join_time

            cursor.execute("INSERT OR IGNORE INTO users (user_id, total_seconds) VALUES (?, 0)", (user_id,))
            cursor.execute("UPDATE users SET total_seconds = total_seconds + ? WHERE user_id = ?", (duration, user_id))
            conn.commit()

            cursor.execute("SELECT total_seconds FROM users WHERE user_id = ?", (user_id,))
            total_seconds = cursor.fetchone()
            if total_seconds:
                await manage_time_roles(member, total_seconds[0] / 3600)

@bot.command(name="time")
async def show_voice_time(ctx, target_member: discord.Member = None):
    """Выводит личную статистику ИЛИ статистику другого человека"""
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS:
        await ctx.send(f"❌ {ctx.author.mention}, эту команду можно использовать только в канале <#{LOG_CHANNEL_ID}>!", delete_after=5)
        await ctx.message.delete()
        return

    current_time = int(time.time())
    
    if target_member is not None:
        if ctx.author.id not in ADMIN_IDS:
            await ctx.send(f"❌ {ctx.author.mention}, у вас нет прав просматривать чужую статистику!")
            return
        user_to_check = target_member
        is_checking_self = False
    else:
        user_to_check = ctx.author
        is_checking_self = True

    cursor.execute("SELECT total_seconds FROM users WHERE user_id = ?", (user_to_check.id,))
    result = cursor.fetchone()
    saved_seconds = result[0] if result else 0

    if user_to_check.id in active_sessions:
        saved_seconds += (current_time - active_sessions[user_to_check.id])

    if saved_seconds == 0:
        if is_checking_self:
            await ctx.send(f"❌ {ctx.author.mention}, вы еще не сидели в голосовых каналах.")
        else:
            await ctx.send(f"📋 Участник {user_to_check.mention} еще не сидел в голосовых каналах.")
        return

    hours = saved_seconds // 3600
    minutes = (saved_seconds % 3600) // 60

    if hours < 1:
        next_milestone_hours = 1
    elif hours < 5:
        next_milestone_hours = 5
    elif hours < 10:
        next_milestone_hours = 10
    else:
        next_milestone_hours = ((hours // 10) + 1) * 10

    remaining_seconds = (next_milestone_hours * 3600) - saved_seconds
    rem_hours = remaining_seconds // 3600
    rem_minutes = (remaining_seconds % 3600) // 60

    title_text = "📊 Ваша голосовая активность" if is_checking_self else f"📊 Активность: {user_to_check.display_name}"
    embed = discord.Embed(title=title_text, color=0x1c6c9a)
    embed.add_field(name="⏱️ Наиграно времени:", value=f"**{hours}** ч. **{minutes}** мин.", inline=False)
    
    if hours < 2000:
        hours_text = "час" if next_milestone_hours == 1 else ("часа" if next_milestone_hours == 5 else "ч.")
        embed.add_field(name="🎯 До следующей роли:", value=f"Осталось **{rem_hours}** ч. **{rem_minutes}** мин. (до {next_milestone_hours} {hours_text})", inline=False)
    else:
        embed.add_field(name="👑 Статус:", value="Максимальный уровень активности достигнут!", inline=False)
        
    embed.set_footer(text=f"Запросил: {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)

@bot.command(name="top")
async def show_top_users(ctx):
    """Выводит топ-10 активных пользователей сервера"""
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS:
        await ctx.send(f"❌ {ctx.author.mention}, эту команду можно использовать только в канале <#{LOG_CHANNEL_ID}>!", delete_after=5)
        await ctx.message.delete()
        return

    current_time = int(time.time())
    
    cursor.execute("SELECT user_id, total_seconds FROM users")
    db_users = cursor.fetchall()
    all_users = {user_id: total_seconds for user_id, total_seconds in db_users}
    
    for user_id, join_time in active_sessions.items():
        session_duration = current_time - join_time
        if user_id in all_users:
            all_users[user_id] += session_duration
        else:
            all_users[user_id] = session_duration

    if not all_users:
        await ctx.send("📋 Список лидеров пока пуст!")
        return

    sorted_top = sorted(all_users.items(), key=lambda item: item[1], reverse=True)[:10]

    embed = discord.Embed(title="🏆 ТОП-10 Активных в Голосовых Каналах", color=0xb6960d)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    leaderboard_text = ""
    
    for index, (user_id, total_seconds) in enumerate(sorted_top):
        member = ctx.guild.get_member(user_id)
        name = member.mention if member else f"Участник [{user_id}]"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        leaderboard_text += f"{medals[index]} {name} — **{hours}** ч. **{minutes}** мин.\n"

    embed.description = leaderboard_text
    await ctx.send(embed=embed)

# Безопасный запуск через переменную среды хостинга
token = os.getenv("BOT_TOKEN")
if token:
    bot.run(token)
else:
    print("Ошибка: Переменная BOT_TOKEN не настроена в панели хостинга!")
