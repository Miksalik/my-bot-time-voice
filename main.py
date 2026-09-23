import discord
from discord.ext import commands
import sqlite3
import time
import os
import re

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
    595594811239694374, 864117995932090389, 316985657371262988  # ID админов
]
LOG_CHANNEL_ID = 1534155761608032336  # ID текстового канала для статистики и оповещений
# ================================

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

# Геймерская палитра цветов по степени редкости
RARITY_COLORS = {
    "COMMON": 0x9d9d9d,       # Обычный (Серый)
    "UNCOMMON": 0x1eff00,     # Необычный (Зеленый)
    "RARE": 0x0070dd,         # Редкий (Синий)
    "EPIC": 0xa335ee,         # Эпический (Фиолетовый)
    "LEGENDARY": 0xff8000,    # Легендарный (Оранжевый)
    "MYTHIC": 0xff4040,       # Мифический (Ярко-красный)
    "ANCIENT": 0xe6cc80,      # Древний / Золотой (Янтарный)
    "IMMORTAL": 0xe5c158      # Бессмертный (Переливчатый золотой)
}

# Сетка статусных ролей
HOURS_ROLES = {
    1:    {"name": "🧭 Прохожий", "emoji": "🧭", "color": RARITY_COLORS["COMMON"]},
    5:    {"name": "⛺ Турист", "emoji": "⛺", "color": RARITY_COLORS["COMMON"]},
    10:   {"name": "🎒 Постоялец", "emoji": "🎒", "color": RARITY_COLORS["UNCOMMON"]},
    50:   {"name": "🛡️ Местный", "emoji": "🛡️", "color": RARITY_COLORS["UNCOMMON"]},
    100:  {"name": "⚔️ Завсегдатай", "emoji": "⚔️", "color": RARITY_COLORS["RARE"]},
    150:  {"name": "🏰 Горожанин", "emoji": "🏰", "color": RARITY_COLORS["RARE"]},
    200:  {"name": "🏅 Олдфаг", "emoji": "🏅", "color": RARITY_COLORS["RARE"]},
    300:  {"name": "🔮 Знаток", "emoji": "🔮", "color": RARITY_COLORS["EPIC"]},
    400:  {"name": "📜 Хранитель", "emoji": "📜", "color": RARITY_COLORS["EPIC"]},
    500:  {"name": "🌟 Активист", "emoji": "🌟", "color": RARITY_COLORS["EPIC"]},
    750:  {"name": "💎 Ветеран", "emoji": "💎", "color": RARITY_COLORS["LEGENDARY"]},
    1000: {"name": "👑 Элита сервера", "emoji": "👑", "color": RARITY_COLORS["LEGENDARY"]},
    1250: {"name": "🔱 Магистр чата", "emoji": "🔱", "color": RARITY_COLORS["LEGENDARY"]},
    1500: {"name": "🌌 Небожитель", "emoji": "🌌", "color": RARITY_COLORS["MYTHIC"]},
    1750: {"name": "🌋 Творец истории", "emoji": "🌋", "color": RARITY_COLORS["MYTHIC"]},
    2000: {"name": "🪐 Легенда", "emoji": "🪐", "color": RARITY_COLORS["MYTHIC"]},
    2500: {"name": "⚡ Титан голосовых", "emoji": "⚡", "color": RARITY_COLORS["ANCIENT"]},
    3000: {"name": "🌀 Хранитель Времени", "emoji": "🌀", "color": RARITY_COLORS["ANCIENT"]},
    3500: {"name": "☄️ Вечный", "emoji": "☄️", "color": RARITY_COLORS["ANCIENT"]},
    4000: {"name": "🔮 Абсолют", "emoji": "🔮", "color": RARITY_COLORS["IMMORTAL"]},
    4500: {"name": "⛩️ Патриарх сервера", "emoji": "⛩️", "color": RARITY_COLORS["IMMORTAL"]},
    5000: {"name": "🪐 Повелитель Эфира", "emoji": "🪐", "color": RARITY_COLORS["IMMORTAL"]}
}
last_promoted_hours = {}

def get_new_nickname(current_name, hours, emoji):
    """Начисто стирает любые старые хвосты и возвращает ник со строгим отображением ЧАСОВ"""
    clean_name = re.sub(r'\s*\|\s*\d+ч.*$', '', current_name).strip()
    suffix = f" | {hours}ч{emoji}"
    if len(clean_name) + len(suffix) > 32:
        clean_name = clean_name[:32 - len(suffix)]
    return f"{clean_name}{suffix}"

def get_role_status_text(hours_int):
    """Возвращает название роли по часам"""
    current_role_name = "🧭 Прохожий"
    for milestone in sorted(HOURS_ROLES.keys()):
        if hours_int >= milestone:
            current_role_name = HOURS_ROLES[milestone]["name"]
    return current_role_name

async def manage_time_roles(member, total_hours):
    """Управляет выдачей ролей по редкости и присылает логи строго один раз в 10 часов"""
    hours_int = int(total_hours)
    guild = member.guild
    
    target_milestone = None
    for milestone in sorted(HOURS_ROLES.keys()):
        if hours_int >= milestone:
            target_milestone = milestone
            
    if not target_milestone:
        return

    role_info = HOURS_ROLES[target_milestone]
    target_role_name = role_info["name"]
    role_emoji = role_info["emoji"]
    final_hex = role_info["color"]
    
    target_role = discord.utils.get(guild.roles, name=target_role_name)
    if not target_role:
        target_role = await guild.create_role(name=target_role_name, color=discord.Color(final_hex), reason="Ранги")
        
    is_new_role_gained = target_role not in member.roles
    if is_new_role_gained:
        await member.add_roles(target_role)

    for role in member.roles:
        if ("часов" in role.name or "час" in role.name or any(r["name"] == role.name for r in HOURS_ROLES.values())) and role.name != target_role_name:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                pass

    current_display_name = member.display_name
    new_nick = get_new_nickname(current_display_name, hours_int, role_emoji)
    
    is_nick_changed = current_display_name != new_nick
    if is_nick_changed:
        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden:
            pass

    already_notified = last_promoted_hours.get(member.id) == hours_int
    if not already_notified and (is_new_role_gained or (hours_int >= 10 and hours_int % 10 == 0)):
        last_promoted_hours[member.id] = hours_int
        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            if log_channel:
                if hours_int % 10 == 1 and hours_int % 100 != 11: hours_text = "час"
                elif (hours_int % 10 == 2 or hours_int % 10 == 3 or hours_int % 10 == 4) and not (hours_int % 100 == 12 or hours_int % 100 == 13 or hours_int % 100 == 14): hours_text = "часа"
                else: hours_text = "часов"

                embed_lvl = discord.Embed(title="📈 Прогресс активности!", description=f"Преодолена отметка в **{hours_int}** {hours_text}!", color=final_hex)
                embed_lvl.add_field(name="Ранг:", value=target_role.mention)
                if member.avatar: embed_lvl.set_thumbnail(url=member.avatar.url)
                await log_channel.send(f"🎉 Поздравляем {member.mention}!", embed=embed_lvl)
        except:
            pass

def update_user_voice_time(user_id):
    """Вспомогательная функция для мгновенного сохранения накопленного в сессии времени в БД"""
    current_time = int(time.time())
    if user_id in active_sessions:
        duration = current_time - active_sessions[user_id]
        if duration > 0:
            cursor.execute("INSERT OR IGNORE INTO users (user_id, total_seconds) VALUES (?, 0)", (user_id,))
            cursor.execute("UPDATE users SET total_seconds = total_seconds + ? WHERE user_id = ?", (duration, user_id))
            conn.commit()
            active_sessions[user_id] = current_time

@bot.event
async def on_ready():
    print("=========================================")
    print(f"Бот {bot.user} успешно переведен на событийную модель!")
    print("=========================================")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    user_id = member.id
    current_time = int(time.time())
    
    # Смена канала или выход — мгновенно сохраняем время
    if before.channel is not None:
        update_user_voice_time(user_id)
        if after.channel is None:
            active_sessions.pop(user_id, None)
            
    # Вход в канал
    if after.channel is not None and before.channel is None:
        active_sessions[user_id] = current_time
@bot.command(name="time")
async def show_voice_time(ctx, target_member: discord.Member = None):
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS:
        await ctx.send("❌ Не тот канал!", delete_after=5)
        return

    user_to_check = target_member if (target_member and ctx.author.id in ADMIN_IDS) else ctx.author
    
    # Принудительно сохраняем текущие набежавшие секунды перед чтением
    update_user_voice_time(user_to_check.id)

    cursor.execute("SELECT total_seconds FROM users WHERE user_id = ?", (user_to_check.id,))
    res = cursor.fetchone()
    saved_seconds = res[0] if res else 0

    hours = saved_seconds // 3600
    minutes = (saved_seconds % 3600) // 60

    next_milestone_hours = None
    current_role_name = get_role_status_text(hours)
    next_role_name = "Повелитель Эфира (Максимум)"
    
    milestones = sorted(HOURS_ROLES.keys())
    for i, milestone in enumerate(milestones):
        if hours >= milestone:
            if i + 1 < len(milestones):
                next_milestone_hours = milestones[i + 1]
                next_role_name = HOURS_ROLES[next_milestone_hours]["name"]
        else:
            if next_milestone_hours is None:
                next_milestone_hours = milestones
                next_role_name = HOURS_ROLES[next_milestone_hours]["name"]
            break

    embed = discord.Embed(title=f"📊 Активность: {user_to_check.display_name}", color=0x0070dd)
    embed.add_field(name="⏳ Наиграно времени:", value=f"**{hours}** ч. **{minutes}** мин.", inline=False)
    embed.add_field(name="🛡️ Текущий ранг:", value=f"**{current_role_name}**", inline=True)

    if next_milestone_hours and hours < 5000:
        remaining_seconds = (next_milestone_hours * 3600) - saved_seconds
        embed.add_field(name="🎯 До следующей роли:", value=f"Осталось **{remaining_seconds // 3600}** ч. **{(remaining_seconds % 3600) // 60}** мин. (до {next_role_name})", inline=False)

    await ctx.send(embed=embed)
    if isinstance(user_to_check, discord.Member):
        await manage_time_roles(user_to_check, saved_seconds / 3600.0)

@bot.command(name="top")
async def show_top_users(ctx):
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS: return
    
    # Перед выводом топа принудительно сохраняем время всех, кто сидит онлайн прямо сейчас
    for uid in list(active_sessions.keys()):
        update_user_voice_time(uid)

    cursor.execute("SELECT user_id, total_seconds FROM users")
    all_users = {uid: sec for uid, sec in cursor.fetchall() if sec > 0}
    if not all_users:
        await ctx.send("📊 Топ пуст!")
        return

    sorted_top = sorted(all_users.items(), key=lambda item: item[1], reverse=True)[:10]
    embed = discord.Embed(title="🏆 ТОП-10 Активных", color=0xb6960d)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    text = ""

    for idx, (uid, sec) in enumerate(sorted_top):
        member = ctx.guild.get_member(uid) or (await ctx.guild.fetch_member(uid) if ctx.guild else None)
        name = member.mention if member else f"Участник [{uid}]"
        text += f"{medals[idx]} {name} — **{sec // 3600}** ч. **{(sec % 3600) // 60}** мин. ({get_role_status_text(sec // 3600)})\n"

    embed.description = text
    await ctx.send(embed=embed)

@bot.command(name="top_full")
async def show_full_leaderboard(ctx):
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS: return
    
    for uid in list(active_sessions.keys()):
        update_user_voice_time(uid)

    cursor.execute("SELECT user_id, total_seconds FROM users")
    all_users = {uid: sec for uid, sec in cursor.fetchall() if sec > 0}
    if not all_users: return

    sorted_top = sorted(all_users.items(), key=lambda item: item[1], reverse=True)
    pages, current_text, per_page = [], "", 20

    for idx, (uid, sec) in enumerate(sorted_top):
        member = ctx.guild.get_member(uid) or (await ctx.guild.fetch_member(uid) if ctx.guild else None)
        name = member.mention if member else f"Участник [{uid}]"
        medal = "🥇" if idx==0 else ("🥈" if idx==1 else ("🥉" if idx==2 else f"`#{idx+1}`"))
        current_text += f"{medal} {name} — **{sec // 3600}** ч. **{(sec % 3600) // 60}** мин. ({get_role_status_text(sec // 3600)})\n"

        if (idx + 1) % per_page == 0 or (idx + 1) == len(sorted_top):
            pages.append(current_text)
            current_text = ""

    for i, t in enumerate(pages):
        embed = discord.Embed(title="🏆 ПОЛНЫЙ список лидеров", description=t, color=0xe6cc80)
        embed.set_footer(text=f"Страница {i+1} из {len(pages)}")
        await ctx.send(embed=embed)

@bot.command(name="sync")
async def sync_old_database(ctx):
    if ctx.author.id not in ADMIN_IDS: return
    await ctx.send("⏳ Синхронизация...")
    cursor.execute("SELECT user_id, total_seconds FROM users")
    success = 0
    for uid, sec in cursor.fetchall():
        member = ctx.guild.get_member(uid) or (await ctx.guild.fetch_member(uid) if ctx.guild else None)
        if member:
            await manage_time_roles(member, sec / 3600.0)
            success += 1
            time.sleep(0.3)
    await ctx.send(f"✅ Обновлено: {success}.")

token = os.getenv("BOT_TOKEN")
if token: bot.run(token)
else: print("Ошибка: BOT_TOKEN нет!")
