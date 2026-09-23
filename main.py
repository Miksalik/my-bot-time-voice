import discord
from discord.ext import commands, tasks
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

# Геймерская палитра цветов по степени редкости (Hex-коды)
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

# Сетка статусных ролей с привязанными цветами редкости
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

def get_new_nickname(current_name, hours, emoji):
    """Отрезает старый суффикс часов и возвращает имя с новым суффиксом и смайликом"""
    clean_name = re.split(r'\s*\|\s*\d+ч.*$', current_name)[0]
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
    """Управляет выдачей ролей по геймерской палитре редкости и присылает логи каждые 10 часов"""
    hours_int = int(total_hours)
    guild = member.guild
    
    # 1. Находим текущую подходящую статусную роль по сетке часов
    target_milestone = None
    for milestone in sorted(HOURS_ROLES.keys()):
        if hours_int >= milestone:
            target_milestone = milestone
            
    if not target_milestone:
        return  # Меньше 1 часа — ничего не делаем

    role_info = HOURS_ROLES[target_milestone]
    target_role_name = role_info["name"]
    role_emoji = role_info["emoji"]
    final_hex = role_info["color"]  # Берем фиксированный цвет редкости вместо Steam
    
    # 2. Ищем или создаем роль с цветом редкости на сервере
    target_role = discord.utils.get(guild.roles, name=target_role_name)
    if not target_role:
        role_color = discord.Color(final_hex)
        target_role = await guild.create_role(name=target_role_name, color=role_color, reason="Система редкости рангов")
        print(f"[Успех] Создана роль редкости: {target_role_name}")
        
    # Флаг: получили ли мы абсолютно новую роль именно в эту минуту
    is_new_role_gained = target_role not in member.roles

    # 3. Выдаем новую роль
    if is_new_role_gained:
        await member.add_roles(target_role)

    # 4. Очищаем все старые часовые роли, чтобы они не копились
    for role in member.roles:
        if ("часов" in role.name or "час" in role.name or any(r["name"] == role.name for r in HOURS_ROLES.values())) and role.name != target_role_name:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                print(f"[Ошибка] Бот не может управлять ролью {role.name}. Поднимите его роль выше в списке!")

    # 5. Обновляем никнейм (Ставим часы и смайлик роли в конец)
    current_display_name = member.display_name
    new_nick = get_new_nickname(current_display_name, hours_int, role_emoji)
    
    is_nick_changed = current_display_name != new_nick
    if is_nick_changed:
        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden:
            print(f"[Ошибка] Нет прав на смену ника для {member.name} (владелец или админ).")

    # 6. ТРИГГЕР УВЕДОМЛЕНИЙ: Отправляем красивый лог каждые 10 часов ИЛИ при получении новой роли
    # (hours_int % 10 == 0 и проверка смены ника гарантируют, что бот поздравит ровно один раз на отметках 10, 20, 30...)
    if is_new_role_gained or (hours_int >= 10 and hours_int % 10 == 0 and is_nick_changed):
        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            if log_channel:
                # Склонение слова "час"
                if hours_int % 10 == 1 and hours_int % 100 != 11:
                    hours_text = "час"
                elif hours_int % 10 in [2, 3, 4] and hours_int % 100 not in [11, 12, 13, 14]:
                    hours_text = "часа"
                else:
                    hours_text = "часов"

                await log_channel.send(f"🎉 Поздравляем {member.mention} с новым достижением активности!")
                
                embed_lvl = discord.Embed(
                    title="📈 Прогресс Голосовой Активности!",
                    description=f"Вы преодолели отметку в **{hours_int}** {hours_text} в голосовых каналах сервера!",
                    color=final_hex
                )
                embed_lvl.add_field(name="Текущий ранг на сервере:", value=target_role.mention)
                embed_lvl.add_field(name="Отображение в профиле:", value=f"`{new_nick}`", inline=False)
                
                if member.avatar:
                    embed_lvl.set_thumbnail(url=member.avatar.url)
                embed_lvl.set_footer(text="Борьба за топ продолжается! 🔥")
                await log_channel.send(embed=embed_lvl)
        except Exception as e:
            print(f"[Ошибка отправки лога]: {e}")


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
            total_seconds = res[0]
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
    print("=========================================")
    print(f"Бот {bot.user} успешно запущен и готов к работе!")
    print(f"Канал для логов и команд установлен на ID: {LOG_CHANNEL_ID}")
    print("=========================================")
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

@bot.command(name="time")
async def show_voice_time(ctx, target_member: discord.Member = None):
    """Выводит личную статистику или статистику другого человека"""
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
            await ctx.send(f"⚠️ Участник {user_to_check.mention} еще не сидел в голосовых каналах.")
        return

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

    title_text = "📊 Ваша голосовая активность" if is_checking_self else f"📊 Активность: {user_to_check.display_name}"
    embed = discord.Embed(title=title_text, color=0x1c6c9a)
    embed.add_field(name="⏳ Наиграно времени:", value=f"**{hours}** ч. **{minutes}** мин.", inline=False)
    embed.add_field(name="🛡️ Текущий ранг:", value=f"**{current_role_name}**", inline=True)

    if next_milestone_hours and hours < 5000:
        remaining_seconds = (next_milestone_hours * 3600) - saved_seconds
        rem_hours = remaining_seconds // 3600
        rem_minutes = (remaining_seconds % 3600) // 60
        embed.add_field(
            name="🎯 До следующей роли:", 
            value=f"Осталось **{rem_hours}** ч. **{rem_minutes}** мин. (до **{next_role_name}** на {next_milestone_hours} ч.)", 
            inline=False
        )
    else:
        embed.add_field(name="Статус:", value="Максимальный уровень активности достигнут!", inline=False)

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
        await ctx.send("📊 Список лидеров пока пуст!")
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
        
        user_status = get_role_status_text(hours)
        leaderboard_text += f"{medals[index]} {name} — **{hours}** ч. **{minutes}** мин. ({user_status})\n"

    embed.description = leaderboard_text
    await ctx.send(embed=embed)


# === АНГЛИЙСКАЯ КОМАНДА ДЛЯ АДМИНИСТРАТОРА ===
@bot.command(name="sync")
async def sync_old_database(ctx):
    """Синхронизирует ники и роли всем игрокам на основе старой базы данных"""
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("❌ У вас нет прав для использования этой команды.")
        return

    await ctx.send("⏳ Начинаю синхронизацию старой базы данных. Это займет некоторое время...")
    
    cursor.execute("SELECT user_id, total_seconds FROM users")
    all_users = cursor.fetchall()
    
    success_count = 0
    for user_id, total_seconds in all_users:
        member = ctx.guild.get_member(user_id)
        if not member:
            try:
                member = await ctx.guild.fetch_member(user_id)
            except:
                continue
                
        if member:
            await manage_time_roles(member, total_seconds / 3600)
            success_count += 1
            time.sleep(0.5)  # Задержка для предотвращения блокировок Discord API
            
    await ctx.send(f"✅ Синхронизация успешно завершена! Обновлено профилей пользователей: {success_count}.")

# Безопасный запуск бота
token = os.getenv("BOT_TOKEN")
if token:
    bot.run(token)
else:
    print("Ошибка: Переменная BOT_TOKEN не настроена в панели хостинга!")

@bot.command(name="top_full")
async def show_full_leaderboard(ctx):
    """Выводит полный список абсолютно всех пользователей сервера из базы данных"""
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS:
        await ctx.send(f"❌ {ctx.author.mention}, эту команду можно использовать только в канале <#{LOG_CHANNEL_ID}>!", delete_after=5)
        await ctx.message.delete()
        return

    current_time = int(time.time())

    # Получаем данные из базы
    cursor.execute("SELECT user_id, total_seconds FROM users")
    db_users = cursor.fetchall()
    all_users = {user_id: total_seconds for user_id, total_seconds in db_users}

    # Добавляем тех, кто сидит в голосовых прямо сейчас
    for user_id, join_time in active_sessions.items():
        session_duration = current_time - join_time
        if user_id in all_users:
            all_users[user_id] += session_duration
        else:
            all_users[user_id] = session_duration

    if not all_users:
        await ctx.send("📊 База данных пуста, никто еще не сидел в каналах!")
        return

    # Сортируем список участников по убыванию времени
    sorted_top = sorted(all_users.items(), key=lambda item: item, reverse=True)

    # Собираем общий текст
    embed_chunks = []
    current_chunk_text = ""
    
    for index, (user_id, total_seconds) in enumerate(sorted_top):
        member = ctx.guild.get_member(user_id)
        name = member.mention if member else f"Участник [{user_id}]"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        user_status = get_role_status_text(hours)
        
        if index == 0: medal = "🥇"
        elif index == 1: medal = "🥈"
        elif index == 2: medal = "🥉"
        else: medal = f"`#{index + 1}`"

        line = f"{medal} {name} — **{hours}** ч. **{minutes}** мин. ({user_status})\n"
        
        # Если текст превышает 3500 символов, отсекаем его в новый блок, чтобы не взорвать лимиты Discord
        if len(current_chunk_text) + len(line) > 3500:
            embed_chunks.append(current_chunk_text)
            current_chunk_text = line
        else:
            current_chunk_text += line

    if current_chunk_text:
        embed_chunks.append(current_chunk_text)

    # Отправляем блоки по очереди
    for i, chunk_text in enumerate(embed_chunks):
        title = "🏆 ПОЛНЫЙ список лидеров активности" if i == 0 else "🏆 ПОЛНЫЙ список лидеров (Продолжение)"
        embed = discord.Embed(title=title, description=chunk_text, color=0xe6cc80)
        embed.set_footer(text=f"Часть {i + 1} из {len(embed_chunks)}")
        await ctx.send(embed=embed)
