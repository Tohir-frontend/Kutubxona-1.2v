# Xostingga joylash qo'llanmasi (cPanel + Python App)

## Kerakli fayllar (zip ichida)

| Fayl | Vazifasi |
|------|----------|
| `web.py` | Asosiy ilova kodi |
| `passenger_wsgi.py` | Xosting kirish nuqtasi (`application` obyekti) |
| `requirements.txt` | O'rnatiladigan kutubxonalar (Flask va boshqalar) |
| `.env` | Gmail, SECRET_KEY, admin login/parol (maxfiy — hech kimga bermang) |
| `kutubxona.json` | Kitoblar bazasi |
| `audio.json` | Audio kitoblar bazasi |
| `users.json` | Foydalanuvchilar (bo'lmasa avtomatik yaratiladi) |
| `static/` | Rasmlar (muqovalar, texnikum suratlari) |
| `.htaccess` | Maxfiy fayllarni brauzerdan bloklash qoidalari |

## Qadamlar

### 1. Papka yarating
cPanel File Manager → `/home/xonqatex` → **+ Folder** → nomi: `library`

> `public_html`ni app root qilib bo'lmaydi ("Directory public_html not allowed" xatosi beradi).

### 2. Zipni `library` ichiga chiqaring
`library` ichida quyidagilar bo'lishi kerak: `web.py`, `passenger_wsgi.py`, `requirements.txt`, `.env`, `kutubxona.json`, `audio.json`, `users.json`, `static/`.

### 3. `.env` mazmunini tekshiring
```
GMAIL=erjanovtohir1993@gmail.com
APP_PASSWORD=<Gmail ilova paroli (16 belgi)>
SECRET_KEY=<uzun tasodifiy kalit>
ADMIN_EMAIL=erjanovtohir1993@gmail.com
ADMIN_PASSWORD=<admin paroli>
FLASK_DEBUG=0
```
`FLASK_DEBUG=0` bo'lishi shart (internetga ochiq serverda debug yoqilmaydi).

### 4. Setup Python App → Create Application
| Maydon | Qiymat |
|--------|--------|
| Версия Python | 3.11 (yoki eng yangisi) |
| Корневой каталог приложения | `library` |
| URL приложения | `pedagogika-edu.uz` |
| Файл запуска приложения | `passenger_wsgi.py` |
| Файл логов Passenger | `logs/passenger.log` |

### 5. Kutubxonalarni o'rnatish
Python App sahifasidagi **Run Pip Install** maydoniga `requirements.txt` yozib yuboring
(yoki venvga kirib: `pip install -r requirements.txt`).

### 6. `passenger_wsgi.py`ni tekshirish
Agar sayt **"It works!"** ko'rsatsa — cPanel faylni almashtirgan. Faylni ochib, mazmunini shunday qiling:
```python
from web import app as application
```

### 7. Restart
Python App sahifasida **Restart** tugmasini bosing → `https://pedagogika-edu.uz` ochiladi.

### 8. Xavfsizlik (docroot)
`public_html` ichida `.htaccess` bo'lishi kerak (maxfiy fayllar bloklanadi):
```apache
<FilesMatch "^(\.env|users\.json|kutubxona\.json|audio\.json|README\.md)$">
    Require all denied
</FilesMatch>
<FilesMatch "\.(py|pyc|zip)$">
    Require all denied
</FilesMatch>
```

## Muammo bo'lsa

- **500 xatosi / ModuleNotFoundError** → pip install qilinmagan (5-qadam)
- **"It works!"** → 6-qadam (passenger_wsgi.py)
- **"Directory public_html not allowed"** → app root `library` bo'lishi kerak (1-qadam)
- Boshqa xato → `/home/xonqatex/logs/passenger.log` faylining oxirini ko'ring
