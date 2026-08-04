import discord
from discord.ext import commands
import sqlite3
import time
import colorsys
import os

# Настройка намерений — для отслеживания войса нужен intents.voice_states
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
active_sessions = {}

# === НАСТРОЙКИ АДМИНИСТРАТОРОВ ===
# Впишите сюда ID через запятую (например:)
ADMIN_IDS = [1534155761608032336]  
# ==============================

# Подключение базы данных SQLite
conn = sqlite3.connect("voice_time.db")
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
    current_milestone = (int(total_hours) // 10) * 10
    if current_milestone == 0:
        return

    target_role_name = f"{current_milestone} часов"
    guild = member.guild

    digit = (current_milestone // 10) % 10
    base_color = BASE_STEAM_COLORS[digit]
    final_hex = adjust_brightness(base_color, current_milestone)

    target_role = discord.utils.get(guild.roles, name=target_role_name)
    if not target_role:
        role_color = discord.Color(final_hex)
        target_role = await guild.create_role(name=target_role_name, color=role_color, reason="Часовая система")
        print(f"[Успех] Создана роль: {target_role_name}")

    if target_role not in member.roles:
        await member.add_roles(target_role)

    for role in member.roles:
        if "часов" in role.name and role.name != target_role_name:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                print(f"[Ошибка] Бот не может управлять ролью {role.name}. Поднимите его роль выше!")

@bot.event
async def on_ready():
    print(f"==========================================")
    print(f"Бот {bot.user} запущен через os.getenv!")
    print(f"Доступные команды: !time , !top")
    print(f"==========================================")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    user_id = member.id
    current_time = int(time.time())

    if before.channel is None and after.channel is not None:
        active_sessions[user_id] = current_time

    elif before.channel is not None and after.channel is None:
        if user_id in active_sessions:
            join_time = active_sessions.pop(user_id)
            duration = current_time - join_time

            cursor.execute("INSERT OR IGNORE INTO users (user_id, total_seconds) VALUES (?, 0)", (user_id,))
            cursor.execute("UPDATE users SET total_seconds = total_seconds + ? WHERE user_id = ?", (duration, user_id))
            conn.commit()

            cursor.execute("SELECT total_seconds FROM users WHERE user_id = ?", (user_id,))
            total_seconds = cursor.fetchone()
            
            # ДЛЯ ТЕСТА: удалите '/ 3600', чтобы считать секунды как часы
            await manage_time_roles(member, total_seconds[0] / 3600)

@bot.command(name="time")
async def show_voice_time(ctx, target_member: discord.Member = None):
    """Выводит личную статистику ИЛИ статистику другого человека для админов"""
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

    next_milestone_hours = ((hours // 10) + 1) * 10
    remaining_seconds = (next_milestone_hours * 3600) - saved_seconds
    rem_hours = remaining_seconds // 3600
    rem_minutes = (remaining_seconds % 3600) // 60

    title_text = "📊 Ваша голосовая активность" if is_checking_self else f"📊 Активность: {user_to_check.display_name}"
    embed = discord.Embed(title=title_text, color=0x1c6c9a)
    embed.add_field(name="⏱️ Наиграно времени:", value=f"**{hours}** ч. **{minutes}** мин.", inline=False)
    
    if hours < 2000:
        embed.add_field(name="🎯 До следующей роли:", value=f"Осталось **{rem_hours}** ч. **{rem_minutes}** мин. (до {next_milestone_hours} ч.)", inline=False)
    else:
        embed.add_field(name="👑 Статус:", value="Максимальный уровень активности достигнут!", inline=False)
        
    embed.set_footer(text=f"Запросил: {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)

@bot.command(name="top")
async def show_top_users(ctx):
    """Выводит топ-10 активных пользователей сервера"""
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
