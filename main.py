import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import calendar
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- СТРОКА ПОДКЛЮЧЕНИЯ БЕРЁТСЯ ИЗ НАСТРОЕК RENDER ---
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# --- ФУНКЦИЯ РАСЧЁТА ДАТЫ ОКОНЧАНИЯ ---
def calculate_end_date(payment_date_str, sub_type, days_week_str, sessions_total):
    try:
        pay_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date()
    except:
        return ""

    if sub_type == "Абонемент":
        year = pay_date.year
        month = pay_date.month + 1
        day = pay_date.day
        if month > 12:
            month = 1
            year += 1
        last_day_of_month = calendar.monthrange(year, month)[1]
        if day > last_day_of_month:
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
        return datetime(year, month, day).strftime("%Y-%m-%d")

    elif sub_type == "Персональные тренировки":
        if not days_week_str or sessions_total <= 0:
            return ""
        day_map = {"Пн": 0, "Вт": 1, "Ср": 2, "Чт": 3, "Пт": 4, "Сб": 5, "Вс": 6}
        selected_days = []
        for d in days_week_str.split(","):
            d = d.strip()
            if d in day_map:
                selected_days.append(day_map[d])
        if not selected_days:
            return ""
        current_date = pay_date + timedelta(days=1)
        count = 0
        last_date = None
        while count < sessions_total:
            if current_date.weekday() in selected_days:
                count += 1
                last_date = current_date
            current_date += timedelta(days=1)
        return last_date.strftime("%Y-%m-%d") if last_date else ""
    return ""

# --- СОЗДАНИЕ ТАБЛИЦЫ (ПРИ ПЕРВОМ ЗАПУСКЕ) ---
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS clients') 
    cursor.execute('''
        CREATE TABLE clients (
            id SERIAL PRIMARY KEY,
            last_name TEXT NOT NULL,
            first_name TEXT NOT NULL,
            payment_date TEXT,
            first_training_date TEXT,
            subscription_end_date TEXT,
            amount REAL,
            phone TEXT,
            birthday TEXT,
            notes TEXT,
            subscription_type TEXT,
            trainer TEXT,
            sessions_total INTEGER,
            sessions_left INTEGER,
            training_days TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# --- ГЛАВНАЯ СТРАНИЦА ---
@app.get("/", response_class=HTMLResponse)
async def read_clients(request: Request):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute("SELECT * FROM clients ORDER BY last_name, first_name")
    clients_data = cursor.fetchall()
    cursor.close()
    conn.close()
    
    today = datetime.now().date()
    clients = []
    warnings = []
    
    for client in clients_data:
        days_left = None
        end_date_str = client['subscription_end_date']
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                days_left = (end_date - today).days
            except:
                pass
        client_dict = dict(client)
        client_dict['days_left'] = days_left
        clients.append(client_dict)
        
        if client['subscription_type'] == "Персональные тренировки" and days_left is not None:
            if 0 <= days_left <= 5:
                warnings.append(f"У {client['last_name']} {client['first_name']} заканчивается абонемент через {days_left} дней!")
            elif days_left < 0:
                warnings.append(f"У {client['last_name']} {client['first_name']} абонемент ПРОСРОЧЕН на {abs(days_left)} дней!")
    
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"clients": clients, "count": len(clients), "warnings": warnings}
    )

# --- ДОБАВЛЕНИЕ КЛИЕНТА ---
@app.post("/add")
async def add_client(
    last_name: str = Form(...),
    first_name: str = Form(...),
    payment_date: str = Form(...),
    first_training_date: str = Form(""),
    amount: str = Form("0"), 
    phone: str = Form(""),
    birthday: str = Form(""),
    notes: str = Form(""),
    subscription_type: str = Form("Абонемент"),
    trainer: str = Form(""),
    sessions_total: str = Form("0"),
    training_days: str = Form("")
):
    sessions_total_int = int(sessions_total) if sessions_total else 0
    amount_float = float(amount) if amount else 0.0

    end_date = calculate_end_date(payment_date, subscription_type, training_days, sessions_total_int)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO clients (
            last_name, first_name, payment_date, first_training_date, 
            subscription_end_date, amount, phone, birthday, notes, 
            subscription_type, trainer, sessions_total, sessions_left, training_days
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        last_name, first_name, payment_date, first_training_date,
        end_date, amount_float, phone, birthday, notes,
        subscription_type, trainer, sessions_total_int, sessions_total_int, training_days
    ))
    conn.commit()
    cursor.close()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

# --- РЕДАКТИРОВАНИЕ ---
@app.get("/edit/{client_id}", response_class=HTMLResponse)
async def edit_client_form(request: Request, client_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
    client = cursor.fetchone()
    cursor.close()
    conn.close()
    if not client:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="edit.html", context={"client": client})

@app.post("/update/{client_id}")
async def update_client(
    client_id: int,
    last_name: str = Form(...),
    first_name: str = Form(...),
    payment_date: str = Form(...),
    first_training_date: str = Form(""),
    subscription_end_date: str = Form(...),
    amount: str = Form("0"),
    phone: str = Form(""),
    birthday: str = Form(""),
    notes: str = Form(""),
    subscription_type: str = Form("Абонемент"),
    trainer: str = Form(""),
    sessions_total: str = Form("0"),
    training_days: str = Form("")
):
    sessions_total_int = int(sessions_total) if sessions_total else 0
    amount_float = float(amount) if amount else 0.0

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE clients SET 
            last_name=%s, first_name=%s, payment_date=%s, first_training_date=%s, 
            subscription_end_date=%s, amount=%s, phone=%s, birthday=%s, notes=%s, 
            subscription_type=%s, trainer=%s, sessions_total=%s, training_days=%s
        WHERE id = %s
    ''', (
        last_name, first_name, payment_date, first_training_date,
        subscription_end_date, amount_float, phone, birthday, notes,
        subscription_type, trainer, sessions_total_int, training_days, client_id
    ))
    conn.commit()
    cursor.close()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)