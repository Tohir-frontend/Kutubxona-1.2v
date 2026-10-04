# Xostingga joylash qo'llanmasi (cPanel + Python App)

Domen: **kutubxonalar.uz**

## Kerakli fayllar

`deploy/` papkasidagi `kutubxonalar.zip` fayli tayyor — uni cPanel File Manager
orqali serverga yuklash uchun mo'ljallangan.

| Fayl | Vazifasi |
|------|----------|
| `web.py` | Asosiy ilova kodi |
| `passenger_wsgi.py` | Xosting kirish nuqtasi (`application` obyekti) |
| `requirements.txt` | O'rnatiladigan kutubxonalar (Flask, Flask-WTF, python-dotenv, Werkzeug) |
| `.env` | Gmail, SECRET_KEY, admin login/parol (**maxfiy — hech kimga bermang**) |
| `kutubxona.json` | Kitoblar bazasi |
| `fanlar.json` | Sinflar va umumiy fanlar ro'yxati |
| `users.json` | Foydalanuvchilar (yo'q bo'lsa avtomatik yaratiladi) |
| `static/covers/` | Kitob muqovalari |
| `static/files/` | Yuklangan PDF fayllar (bo'sh bo'lsa ham papka bo'lishi shart) |

> `static/` ichidagi bo'sh papkalar (`covers`, `files`) zipga kiritilgan bo'lishi
> kerak — ilova ularga yozadi.

## Qadamlar

### 1. Zipni yuklab oling
`deploy/kutubxonalar.zip` faylini kompyuteringizga saqlang.

> **Ogohlantirish:** zip ichida `.env` fayli bor (parollar bilan). Zipni hech kimga
> yubormang va GitHub'ga yuklamang.

### 2. Serverda papka yarating
cPanel File Manager → `/home/USER` → **+ Folder** → nomi: `library`

> `public_html`ni app root qilib bo'lmaydi ("Directory public_html not allowed" xatosi beradi).

### 3. Zipni `library` ichiga chiqaring
File Manager → `library` ichiga kiring → **Upload** → zipni yuklang →
zipni **Extract** qiling.

Natijada `library` ichida bo'lishi kerak:
`web.py`, `passenger_wsgi.py`, `requirements.txt`, `.env`, `kutubxona.json`,
`fanlar.json`, `users.json`, `static/` (ichida `covers/`, `files/`, `texnikum/`).

> Agar zip ichida `kutubxonalar/` papkasi paydo bo'lsa, uning ichidagi fayllarni
> `library` ga ko'chiring — ilova ularni bir daraja yuqorida izlaydi.

### 4. `.env` mazmunini tekshiring
```
GMAIL=...@gmail.com
APP_PASSWORD=<Gmail ilova paroli (16 belgi)>
SECRET_KEY=<uzun tasodifiy kalit>
ADMIN_EMAIL=...@gmail.com
ADMIN_PASSWORD=<admin paroli>
FLASK_DEBUG=0
```
`FLASK_DEBUG=0` bo'lishi **shart** (internetga ochiq serverda debug yoqilmaydi).

### 5. Setup Python App → Create Application
| Maydon | Qiymat |
|--------|--------|
| Python versiyasi | 3.11+ |
| Application root | `library` |
| Application URL | `kutubxonalar.uz` |
| Application startup file | `passenger_wsgi.py` |
| Passenger log file | `logs/passenger.log` |

### 6. Kutubxonalarni o'rnatish
Python App sahifasidagi **Run Pip Install** maydoniga `requirements.txt` yozib yuboring.

### 7. `passenger_wsgi.py`ni tekshiring
Agar sayt **"It works!"** ko'rsatsa — cPanel faylni standart shablon bilan
almashtirgan. Faylni ochib, ichiga faqat shuni yozing:
```python
from web import app as application
```

### 8. Yozish huquqlarini tekshiring
Ilova `kutubxona.json`, `fanlar.json`, `users.json` fayllarini **o'zgartiradi** va
`static/covers`, `static/files` papkalariga **rasm/PDF yozadi**.

File Manager → `library` ni tanlang → **Change Permissions** →
`755` (yoki `775`) → **Change Permissions**. `static` va uning ichidagi
`covers`, `files` papkalariga ham xuddi shunday.

### 9. `public_html` ga `.htaccess` qo'ying
Ilova `public_html` dan tashqarida turgani uchun maxfiy fayllarni yashirish uchun
`public_html` ichida **alohida** `.htaccess` fayli bo'lishi kerak.

File Manager → `public_html` → **+ File** → nomi `.htaccess` → quyidagicha yozing:
```apache
<FilesMatch "^(\.env|users\.json|kutubxona\.json|fanlar\.json)$">
    Require all denied
</FilesMatch>
<FilesMatch "\.(py|pyc|zip)$">
    Require all denied
</FilesMatch>
```

> cPanel ko'pincha `.htaccess` faylini yaratishga to'sqinlik qiladi. Bu holda
> **Settings → Hidden Files** yoqilganini tekshirib, faylni FileZilla orqali
> yuklash yoki xosting yordamiga murojaat qilish kerak.

### 10. Restart
Python App sahifasida **Restart** tugmasini bosing →
`https://kutubxonalar.uz` ochiladi.

## Muammo bo'lsa

| Belgi | Sabab va yechim |
|-------|-----------------|
| "It works!" | `passenger_wsgi.py` cPanel shabloni bilan almashgan (7-qadam) |
| 500 / ModuleNotFoundError | pip install qilinmagan (6-qadam) |
| "Directory public_html not allowed" | Application root `library` bo'lishi kerak (2-qadam) |
| 500, logda "papkasini yaratib bo'lmadi" | Yozish huquqi yo'q (8-qadam) |
| Sayt ishlaydi, kitob qo'shilmaydi | `kutubxona.json` yozilmayapti — 8-qadamni takrorlang |
| `.env` kkalari bo'sh | `.env` yuklanmagan yoki `FLASK_DEBUG=1` qolgan |
| Eski ma'lumotlar ko'rinadi | Brauzer keshi — `Ctrl+F5` |

Boshqa xoto bo'lsa `/home/USER/logs/passenger.log` faylining oxirini ko'ring.
