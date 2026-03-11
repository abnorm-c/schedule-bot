import sqlite3
import datetime
from datetime import datetime
import os

DB_PATH = '/data/rep_bot.db'  

def init_db():
    """Создает таблицы в базе данных при первом запуске"""  
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Таблица пользователей
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        balance INTEGER DEFAULT 0,
        registered_date TEXT
    )
    ''')
    
    # Таблица транзакций (история пополнений)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        status TEXT DEFAULT 'pending',
        date TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    conn.commit()
    conn.close()

def init_schedule_db():
    """Создает таблицы для расписания"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Таблица для активного расписания
    cur.execute('''
    CREATE TABLE IF NOT EXISTS schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        price_1 INTEGER NOT NULL,
        price_2 INTEGER NOT NULL,
        booked_by INTEGER DEFAULT NULL,
        booked_duration INTEGER DEFAULT NULL,
        booked_format TEXT DEFAULT NULL,
        created_date TEXT,
        booked_date TEXT DEFAULT NULL,
        FOREIGN KEY (booked_by) REFERENCES users (user_id)
    )
    ''')
    
    # Таблица для шаблона расписания
    cur.execute('''
    CREATE TABLE IF NOT EXISTS schedule_template (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL,
        time TEXT NOT NULL,
        price_1 INTEGER NOT NULL,
        price_2 INTEGER NOT NULL,
        created_date TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Проверяем, есть ли колонка date
    try:
        cur.execute("SELECT date FROM schedule LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE schedule ADD COLUMN date TEXT DEFAULT '2024-01-01'")
        print("✅ Колонка date добавлена в существующую таблицу")
    
    # Проверяем, есть ли колонка booked_format
    try:
        cur.execute("SELECT booked_format FROM schedule LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE schedule ADD COLUMN booked_format TEXT DEFAULT NULL")
        print("✅ Колонка booked_format добавлена в существующую таблицу")
    
    conn.commit()
    conn.close()

def init_profile_db():
    """Создает таблицу профилей пользователей"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute('''
    CREATE TABLE IF NOT EXISTS profiles (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        grade TEXT,
        subjects TEXT,
        default_format TEXT DEFAULT 'online',
        phone TEXT,
        parent_phone TEXT,
        notes TEXT,
        registered_date TEXT,
        last_visit TEXT,
        total_lessons INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    conn.commit()
    conn.close()

def add_user(user_id, username, full_name):
    """Добавляет нового пользователя или возвращает существующего"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    
    if not user:
        cur.execute('''
        INSERT INTO users (user_id, username, full_name, registered_date)
        VALUES (?, ?, ?, ?)
        ''', (user_id, username, full_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        is_new = True
    else:
        is_new = False
    
    conn.close()
    return is_new

def get_balance(user_id):
    """Возвращает баланс пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0

def add_transaction(user_id, amount):
    """Создает запрос на пополнение (статус pending)"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    INSERT INTO transactions (user_id, amount, status, date)
    VALUES (?, ?, ?, ?)
    ''', (user_id, amount, 'pending', datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    transaction_id = cur.lastrowid
    conn.close()
    return transaction_id

def confirm_transaction(transaction_id):
    """Подтверждает оплату и начисляет деньги на баланс"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT user_id, amount FROM transactions WHERE id = ? AND status = 'pending'", (transaction_id,))
    trans = cur.fetchone()
    
    if trans:
        user_id, amount = trans
        
        cur.execute("UPDATE transactions SET status = 'confirmed' WHERE id = ?", (transaction_id,))
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        
        conn.commit()
        conn.close()
        return user_id, amount
    else:
        conn.close()
        return None, None

def get_pending_transactions():
    """Получить все неподтвержденные транзакции"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    SELECT t.id, u.username, u.full_name, t.amount, t.date 
    FROM transactions t
    JOIN users u ON t.user_id = u.user_id
    WHERE t.status = 'pending'
    ORDER BY t.date DESC
    ''')
    result = cur.fetchall()
    conn.close()
    return result

def cancel_transaction(transaction_id):
    """Отменяет заявку на пополнение"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT user_id, amount FROM transactions WHERE id = ? AND status = 'pending'", (transaction_id,))
    trans = cur.fetchone()
    
    if trans:
        cur.execute("UPDATE transactions SET status = 'cancelled' WHERE id = ?", (transaction_id,))
        conn.commit()
        conn.close()
        return trans[0]
    else:
        conn.close()
        return None

def update_balance(user_id, amount, operation="add"):
    """
    Ручная корректировка баланса
    operation: "add" - добавить, "set" - установить конкретное значение
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        if operation == "add":
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            new_balance = cur.fetchone()[0]
            
        elif operation == "set":
            cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id))
            new_balance = amount
            
        else:
            if conn:
                conn.close()
            return None, None
            
        conn.commit()
        
        cur.execute("SELECT username, full_name FROM users WHERE user_id = ?", (user_id,))
        user_info = cur.fetchone()
        
        conn.close()
        return user_info, new_balance
        
    except Exception as e:
        print(f"Ошибка в update_balance: {e}")
        if conn:
            conn.close()
        return None, None

# ========== ПРОФИЛИ ==========

def get_profile(user_id):
    """Получает профиль пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
    profile = cur.fetchone()
    conn.close()
    return profile

def create_profile(user_id, name, grade, subjects, phone, default_format='online'):
    """Создает новый профиль"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    INSERT INTO profiles 
    (user_id, name, grade, subjects, phone, default_format, registered_date, last_visit)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, name, grade, subjects, phone, default_format, 
          datetime.now().strftime("%Y-%m-%d %H:%M"),
          datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def update_profile(user_id, **kwargs):
    """Обновляет поля профиля"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for key, value in kwargs.items():
        cur.execute(f"UPDATE profiles SET {key} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def update_last_visit(user_id):
    """Обновляет дату последнего визита"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE profiles SET last_visit = ? WHERE user_id = ?", 
                (datetime.now().strftime("%Y-%m-%d %H:%M"), user_id))
    conn.commit()
    conn.close()

def increment_lessons_count(user_id):
    """Увеличивает счетчик уроков пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE profiles SET total_lessons = total_lessons + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ========== РАСПИСАНИЕ ==========

def get_week_dates():
    """Возвращает даты текущей недели (Пн-Вс)"""
    from datetime import datetime, timedelta
    
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    
    week_dates = {}
    days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    
    for i, day in enumerate(days):
        date = monday + timedelta(days=i)
        week_dates[day] = date.strftime("%Y-%m-%d")
    
    return week_dates

def get_template_slots():
    """Возвращает шаблон расписания из базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    SELECT day, time, price_1, price_2 FROM schedule_template
    ORDER BY 
        CASE day
            WHEN 'Пн' THEN 1 WHEN 'Вт' THEN 2 WHEN 'Ср' THEN 3
            WHEN 'Чт' THEN 4 WHEN 'Пт' THEN 5 WHEN 'Сб' THEN 6 WHEN 'Вс' THEN 7
        END, time
    ''')
    slots = cur.fetchall()
    conn.close()
    
    if not slots:
        # Если шаблон пуст, возвращаем тестовый
        return [
            {"day": "Пн", "time": "12:00", "price_1": 500, "price_2": 900},
            {"day": "Пн", "time": "13:00", "price_1": 500, "price_2": 900},
            {"day": "Пн", "time": "14:00", "price_1": 500, "price_2": 900},
            {"day": "Пн", "time": "15:00", "price_1": 600, "price_2": 1100},
            {"day": "Пн", "time": "16:00", "price_1": 600, "price_2": 1100},
            {"day": "Вт", "time": "12:00", "price_1": 500, "price_2": 900},
            {"day": "Вт", "time": "13:00", "price_1": 500, "price_2": 900},
            {"day": "Вт", "time": "14:00", "price_1": 500, "price_2": 900},
            {"day": "Вт", "time": "15:00", "price_1": 600, "price_2": 1100},
            {"day": "Вт", "time": "16:00", "price_1": 600, "price_2": 1100},
            {"day": "Ср", "time": "12:00", "price_1": 500, "price_2": 900},
            {"day": "Ср", "time": "13:00", "price_1": 500, "price_2": 900},
            {"day": "Ср", "time": "14:00", "price_1": 500, "price_2": 900},
            {"day": "Ср", "time": "15:00", "price_1": 600, "price_2": 1100},
            {"day": "Ср", "time": "16:00", "price_1": 600, "price_2": 1100},
        ]
    
    return [{"day": s[0], "time": s[1], "price_1": s[2], "price_2": s[3]} for s in slots]

def create_weekly_schedule():
    """Создаёт расписание на текущую неделю на основе шаблона"""
    week_dates = get_week_dates()
    template = get_template_slots()
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    created_count = 0
    for slot in template:
        day = slot['day']
        if day in week_dates:
            cur.execute('''
            SELECT id FROM schedule 
            WHERE date = ? AND time = ? AND day = ?
            ''', (week_dates[day], slot['time'], day))
            
            if not cur.fetchone():
                cur.execute('''
                INSERT INTO schedule (day, date, time, price_1, price_2, created_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    day, 
                    week_dates[day], 
                    slot['time'], 
                    slot['price_1'], 
                    slot['price_2'],
                    datetime.now().strftime("%Y-%m-%d %H:%M")
                ))
                created_count += 1
    
    conn.commit()
    conn.close()
    return created_count

def cleanup_old_slots():
    """Удаляет прошедшие окошки"""
    from datetime import datetime, timedelta
    
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M")
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute('''
    DELETE FROM schedule 
    WHERE (date < ?) OR (date = ? AND time < ?)
    ''', (today, today, current_time))
    
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted

def refresh_weekly_schedule():
    """Обновляет расписание"""
    deleted = cleanup_old_slots()
    created = create_weekly_schedule()
    return deleted, created

def get_available_slots():
    """Получает только свободные окошки (только будущие даты)"""
    from datetime import datetime, timedelta
    
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    
    # Берем окошки на неделю вперед
    week_later = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Получаем все окошки, которые:
    # 1. Не заняты (booked_by IS NULL)
    # 2. Даты в пределах недели
    # 3. Исключаем прошедшие:
    #    - дата больше сегодня
    #    - ИЛИ дата равна сегодня, но время больше текущего
    cur.execute('''
    SELECT * FROM schedule 
    WHERE booked_by IS NULL
    AND date BETWEEN ? AND ?
    AND (date > ? OR (date = ? AND time > ?))
    ORDER BY date, time
    ''', (today, week_later, today, today, current_time))
    
    slots = cur.fetchall()
    conn.close()
    return slots

def get_slots_by_day():
    """Группирует окошки по дням"""
    slots = get_available_slots()
    
    days_order = {'Пн': 1, 'Вт': 2, 'Ср': 3, 'Чт': 4, 'Пт': 5, 'Сб': 6, 'Вс': 7}
    grouped = {}
    
    for slot in slots:
        day = slot[1]
        if day not in grouped:
            grouped[day] = []
        grouped[day].append({
            'id': slot[0],
            'date': slot[2],
            'time': slot[3],
            'price_1': slot[4],
            'price_2': slot[5]
        })
    
    for day in grouped:
        grouped[day].sort(key=lambda x: x['time'])
    
    return grouped

def book_slot(slot_id, user_id, duration, lesson_format):
    """
    Записывает пользователя на окошко
    duration: 1 или 2 (количество уроков)
    lesson_format: 'online' или 'offline'
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Получаем информацию о выбранном слоте
    cur.execute('''
    SELECT day, date, time, price_1, price_2, booked_by FROM schedule 
    WHERE id = ? AND booked_by IS NULL
    ''', (slot_id,))
    slot = cur.fetchone()
    
    if not slot:
        conn.close()
        return None, None
    
    day, date, start_time, price_1, price_2, _ = slot
    
    # Если duration = 2, нужно заблокировать следующий слот
    if duration == 2:
        # Вычисляем время следующего урока (прибавляем 1 час)
        from datetime import datetime, timedelta
        time_obj = datetime.strptime(start_time, "%H:%M")
        next_time_obj = time_obj + timedelta(hours=1)
        next_time = next_time_obj.strftime("%H:%M")
        
        # Проверяем, существует ли следующий слот и свободен ли он
        cur.execute('''
        SELECT id FROM schedule 
        WHERE day = ? AND date = ? AND time = ? AND booked_by IS NULL
        ''', (day, date, next_time))
        
        next_slot = cur.fetchone()
        
        if not next_slot:
            conn.close()
            return None, None  # Нет следующего слота для сдвоенного занятия
        
        next_slot_id = next_slot[0]
    
    # Определяем цену
    price = price_2 if duration == 2 else price_1
    
    # Проверяем баланс
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    
    if not user or user[0] < price:
        conn.close()
        return None, price
    
    # Списываем деньги
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, user_id))
    
    # Бронируем основной слот
    cur.execute('''
    UPDATE schedule 
    SET booked_by = ?, booked_duration = ?, booked_format = ?, booked_date = ? 
    WHERE id = ?
    ''', (user_id, duration, lesson_format, datetime.now().strftime("%Y-%m-%d %H:%M"), slot_id))
    
    # Если сдвоенное - бронируем следующий слот как занятый (но без списания денег)
    if duration == 2:
        cur.execute('''
        UPDATE schedule 
        SET booked_by = ?, booked_duration = ?, booked_format = ?, booked_date = ? 
        WHERE id = ?
        ''', (user_id, duration, lesson_format, datetime.now().strftime("%Y-%m-%d %H:%M"), next_slot_id))
    
    # Получаем новый баланс
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = cur.fetchone()[0]
    
    conn.commit()
    conn.close()
    
    increment_lessons_count(user_id)
    
    return new_balance, price
def get_user_bookings(user_id):
    """Получает все записи пользователя с ID записей"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    SELECT day, date, time, booked_duration, booked_format, price_1, price_2, booked_date, id 
    FROM schedule 
    WHERE booked_by = ?
    ORDER BY date, time
    ''', (user_id,))
    bookings = cur.fetchall()
    conn.close()
    return bookings

def cancel_booking(booking_id, user_id):
    """
    Отменяет запись на урок
    """
    from datetime import datetime, timedelta
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Получаем информацию о записи
    cur.execute('''
    SELECT booked_by, booked_duration, price_1, price_2, day, date, time, booked_format, id 
    FROM schedule 
    WHERE id = ? AND booked_by = ?
    ''', (booking_id, user_id))
    
    booking = cur.fetchone()
    
    if not booking:
        conn.close()
        return None, None, None, None, "Запись не найдена"
    
    (booked_by, duration, price_1, price_2, day, 
     lesson_date, lesson_time, lesson_format, slot_id) = booking
    
    # Определяем цену
    price = price_1 if duration == 1 else price_2
    
    # Если сдвоенное - нужно найти и отменить следующий слот
    if duration == 2:
        time_obj = datetime.strptime(lesson_time, "%H:%M")
        next_time_obj = time_obj + timedelta(hours=1)
        next_time = next_time_obj.strftime("%H:%M")
        
        # Ищем следующий слот, который тоже занят этим пользователем
        cur.execute('''
        SELECT id FROM schedule 
        WHERE day = ? AND date = ? AND time = ? AND booked_by = ?
        ''', (day, lesson_date, next_time, user_id))
        
        next_slot = cur.fetchone()
        if next_slot:
            # Очищаем следующий слот
            cur.execute('''
            UPDATE schedule 
            SET booked_by = NULL, booked_duration = NULL, booked_format = NULL, booked_date = NULL 
            WHERE id = ?
            ''', (next_slot[0],))
    
    # Проверяем время до урока
    now = datetime.now()
    lesson_datetime = datetime.strptime(f"{lesson_date} {lesson_time}", "%Y-%m-%d %H:%M")
    hours_before = (lesson_datetime - now).total_seconds() / 3600
    
    penalty = 0
    refund = price
    
    # Правила отмены
    if hours_before < 2:
        penalty = int(price * 0.25)
        refund = price - penalty
    
    # Возвращаем деньги
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (refund, user_id))
    
    # Очищаем основной слот
    cur.execute('''
    UPDATE schedule 
    SET booked_by = NULL, booked_duration = NULL, booked_format = NULL, booked_date = NULL 
    WHERE id = ?
    ''', (booking_id,))
    
    conn.commit()
    
    # Получаем новый баланс
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = cur.fetchone()[0]
    
    conn.close()
    
    booking_info = f"{day} {lesson_date} {lesson_time}"
    return new_balance, refund, penalty, booking_info, lesson_format
	
def add_template_slot(day, time, price_1, price_2):
    """Добавляет время в шаблон расписания"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    INSERT INTO schedule_template (day, time, price_1, price_2)
    VALUES (?, ?, ?, ?)
    ''', (day, time, price_1, price_2))
    conn.commit()
    template_id = cur.lastrowid
    conn.close()
    return template_id

def delete_template_slot(template_id):
    """Удаляет время из шаблона расписания"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM schedule_template WHERE id = ?", (template_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted

def get_all_template_slots():
    """Получает все времена из шаблона"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    SELECT * FROM schedule_template 
    ORDER BY 
        CASE day
            WHEN 'Пн' THEN 1 WHEN 'Вт' THEN 2 WHEN 'Ср' THEN 3
            WHEN 'Чт' THEN 4 WHEN 'Пт' THEN 5 WHEN 'Сб' THEN 6 WHEN 'Вс' THEN 7
        END, time
    ''')
    slots = cur.fetchall()
    conn.close()
    return slots