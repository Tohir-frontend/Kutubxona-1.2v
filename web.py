"""
Xorazm pedagogika texnikumi elektron kutubxonasi
Foydalanuvchi tizimi bilan (ro'yxatdan o'tish, kirish, email tasdiqlash)
"""
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify
from flask_wtf import CSRFProtect
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import json
import os
import random
import re
import string
import uuid
from urllib.parse import urlparse

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SITE_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "site_settings.json")
DEFAULT_SITE_TITLE = "Urganch shahar 25-son maktab — Kutubxona"

app = Flask(__name__)

_maxfiy_kalit = os.getenv("SECRET_KEY")
if not _maxfiy_kalit:
    print("OGOHLANTIRISH: SECRET_KEY .env faylida topilmadi. Vaqtinchalik tasodifiy kalit ishlatiladi "
          "(server qayta ishga tushirilganda barcha sessiyalar bekor bo'ladi). "
          "Iltimos .env fayliga SECRET_KEY qo'shing.")
    _maxfiy_kalit = os.urandom(32).hex()
app.secret_key = _maxfiy_kalit

app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "static", "files")
app.config["COVER_FOLDER"] = os.path.join(os.path.dirname(__file__), "static", "covers")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
MAX_RASM_HAJM = int(0.3 * 1024 * 1024)

DATA_FILE = os.path.join(os.path.dirname(__file__), "kutubxona.json")
USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")
FANLAR_FILE = os.path.join(os.path.dirname(__file__), "fanlar.json")

csrf = CSRFProtect(app)


@app.after_request
def kesh_taqiqlash(response):
    """Brauzer keshi eski sahifani ko'rsatmasligi uchun."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

BO_LIMLAR = [
    "Umumta'lim fanlar",
    "Badiiy adabiyotlar",
]

def _papka_tayyorla(yol):
    """Papkani yaratadi. Xostingda yozish huquqi yo'q bo'lsa ham ilova
    import qilinib qolishi kerak — aks holda butun sayt 500 beradi."""
    try:
        os.makedirs(yol, exist_ok=True)
    except OSError as e:
        print(f"OGOHLANTIRISH: '{yol}' papkasini yaratib bo'lmadi ({e}). "
              "Fayl yuklash funksiyalari ishlamaydi. Papkani qo'lda yarating va "
              "unga yozish huquqini bering (chmod 755/775).")


_papka_tayyorla(app.config["UPLOAD_FOLDER"])
_papka_tayyorla(app.config["COVER_FOLDER"])


def foydalanuvchilar_yuklash():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            malumot = json.load(f)
            malumot.setdefault("sevimlilar", {})
            return malumot
    return {"tasdiqlanmaganlar": {}, "faollar": {}, "sevimlilar": {}}


def foydalanuvchilar_saqlash(f):
    with open(USERS_FILE, "w", encoding="utf-8") as fp:
        json.dump(f, fp, ensure_ascii=False, indent=2)


def fanlar_yuklash():
    """Sinflar va umumiy fanlar ro'yxatini qaytaradi.

    Natija: {"sinflar": [...], "fanlar": [...]}. Fanlar ro'yxati barcha
    sinflar uchun umumiy. Eski formatdagi fayl ({sinf: [fanlar]}) avtomatik
    ravishda bitta umumiy ro'yxatga birlashtirilib o'qiladi; keyingi
    `fanlar_saqlash` chaqirilganda yangi formatda saqlanadi."""
    malumot = {}
    if os.path.exists(FANLAR_FILE):
        with open(FANLAR_FILE, "r", encoding="utf-8") as f:
            malumot = json.load(f)
    if isinstance(malumot.get("sinflar"), list) and isinstance(malumot.get("fanlar"), list):
        return {"sinflar": malumot["sinflar"], "fanlar": malumot["fanlar"]}
    sinflar, umumiy_fanlar = [], []
    for sinf, fan_royxati in malumot.items():
        if not isinstance(fan_royxati, list):
            continue
        sinflar.append(sinf)
        for fan in fan_royxati:
            if fan and fan not in umumiy_fanlar:
                umumiy_fanlar.append(fan)
    return {"sinflar": sinflar, "fanlar": umumiy_fanlar}


def fanlar_saqlash(malumot):
    with open(FANLAR_FILE, "w", encoding="utf-8") as fp:
        json.dump({"sinflar": malumot["sinflar"], "fanlar": malumot["fanlar"]},
                  fp, ensure_ascii=False, indent=2)


_SINF_QAT = re.compile(r"(\d+)\s*-\s*sinf", re.IGNORECASE)
_QISM_SARFI = re.compile(r"\s*\d+\s*-\s*qism\s*$", re.IGNORECASE)


def kitob_sinf_fani(kitob):
    """Kitobning sinf va fanini qaytaradi.

    Avval kitobdagi `sinf`/`fan` maydonlaridan oladi. Eski kitoblarda bu
    maydonlar yo'q, ular uchun nomi matnidan ("10-sinf Fizika 2-qism")
    sinf va fan ajratib olinadi."""
    sinf = (kitob.get("sinf") or "").strip()
    fan = (kitob.get("fan") or "").strip()
    if sinf or fan:
        return {"sinf": sinf, "fan": fan}
    nomi = kitob.get("nomi") or ""
    topilma = _SINF_QAT.search(nomi)
    if not topilma:
        return {"sinf": "", "fan": ""}
    fan = _QISM_SARFI.sub("", nomi[:topilma.start()] + " " + nomi[topilma.end():]).strip(" -—")
    return {"sinf": f"{topilma.group(1)}-sinf", "fan": fan}


def sinf_tartibi(sinf):
    """Sinf nomini tabiiy tartib kalitiga aylantiradi.

    "1-sinf", "2-sinf", ..., "10-sinf" tartibi raqam bo'yicha; raqam
    bilan boshlanmagan nomlar oxirida, alifbo bo'yicha turadi."""
    topilma = re.match(r"\s*(\d+)", sinf or "")
    if topilma:
        return (0, int(topilma.group(1)), (sinf or "").lower())
    return (1, 0, (sinf or "").lower())


def fan_tartibi(fan):
    """Fan nomini alifbo tartibi kalitiga aylantiradi."""
    return (fan or "").lower()


def kitob_tartibi(kitob):
    """Kitobni sinf, so'ng fan va nom bo'yicha saralash kaliti."""
    sf = kitob_sinf_fani(kitob)
    return (sinf_tartibi(sf["sinf"]), fan_tartibi(sf["fan"]), (kitob.get("nomi") or "").lower())


def kitoblarni_tartiblash(m):
    """Har bir bo'limdagi kitoblarni sinf va fan tartibida saralaydi.

    Har bir element {"kitob": ..., "idx": ...} ko'rinishida bo'ladi: `idx`
    fayldagi haqiqiy indeks bo'lgani uchun tahrirlash/o'chirish havolalari
    saralashdan qat'i nazar to'g'ri kitobga boradi."""
    natija = {}
    for bolim, kitoblar in m.items():
        natija[bolim] = sorted(
            ({"kitob": kitob, "idx": idx} for idx, kitob in enumerate(kitoblar)),
            key=lambda qator: kitob_tartibi(qator["kitob"]),
        )
    return natija


def fanlar_tartiblash(fanlar):
    """Fanlar ro'yxatini alifbo tartibida (katta-kichik harfga qarab emas) qaytaradi."""
    return sorted(fanlar or [], key=fan_tartibi)


def sinflar_tartiblash(sinflar):
    """Sinflar ro'yxatini raqamli tabiiy tartibda qaytaradi."""
    return sorted(sinflar or [], key=sinf_tartibi)


app.jinja_env.globals["sinf_tartibi"] = sinf_tartibi
app.jinja_env.globals["fan_tartibi"] = fan_tartibi
app.jinja_env.globals["sinflar_tartiblash"] = sinflar_tartiblash
app.jinja_env.globals["fanlar_tartiblash"] = fanlar_tartiblash


def filtr_royxatlari(m):
    """Kitoblar ichida mavjud sinf va fanlar ro'yxatini (saralangan) qaytaradi."""
    sinflar, fanlar = set(), set()
    for kitoblar in m.values():
        for kitob in kitoblar:
            sf = kitob_sinf_fani(kitob)
            if sf["sinf"]:
                sinflar.add(sf["sinf"])
            if sf["fan"]:
                fanlar.add(sf["fan"])
    return sorted(sinflar, key=sinf_tartibi), sorted(fanlar, key=fan_tartibi)


app.jinja_env.globals["filtr_royxatlari"] = filtr_royxatlari
app.jinja_env.globals["kitob_sinf_fani"] = kitob_sinf_fani


def kitoblar_yuklash():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
    else:
        m = {b: [] for b in BO_LIMLAR}
    o_zgardi = False
    for kitoblar in m.values():
        for kitob in kitoblar:
            if "id" not in kitob:
                kitob["id"] = uuid.uuid4().hex
                o_zgardi = True
    if o_zgardi:
        kitoblar_saqlash(m)
    return m


def foydalanuvchi_sevimlilari(email):
    """Foydalanuvchining sevimli kitob id'lari to'plamini qaytaradi."""
    if not email:
        return set()
    f = foydalanuvchilar_yuklash()
    return set(f.get("sevimlilar", {}).get(email, []))


def kitoblar_saqlash(m):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def fayl_hajmi(fayl_nomi):
  if not fayl_nomi:
    return "0.00 MB"
  yol = os.path.join(app.config["UPLOAD_FOLDER"], fayl_nomi)
  try:
    return f"{os.path.getsize(yol) / (1024 * 1024):.2f} MB"
  except OSError:
    return "Noma'lum"


app.jinja_env.globals["fayl_hajmi"] = fayl_hajmi


def _get_texnikum_dir():
    papka = os.path.join(os.path.dirname(__file__), "static", "texnikum")
    os.makedirs(papka, exist_ok=True)
    return papka


def site_settings_yuklash():
    try:
        with open(SITE_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Site settings must be a JSON object")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        data = {"title": DEFAULT_SITE_TITLE}
        site_settings_saqlash(data)
    data.setdefault("title", DEFAULT_SITE_TITLE)
    return data


def site_settings_saqlash(data):
    with open(SITE_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def site_title():
    return (site_settings_yuklash().get("title") or DEFAULT_SITE_TITLE).strip() or DEFAULT_SITE_TITLE


app.jinja_env.globals["site_title"] = site_title


def texnikum_rasmlari():
    papka = _get_texnikum_dir()
    rasm_turlari = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    tartib = {"texnikum1": 0, "kitob": 1, "texnikum2": 2}
    rasmlar = [f for f in os.listdir(papka) if os.path.splitext(f)[1].lower() in rasm_turlari]
    return sorted(
        rasmlar,
        key=lambda fayl: tartib.get(os.path.splitext(fayl)[0].lower(), len(tartib)),
    )


def kod_yaratish():
    return "".join(random.choices(string.digits, k=6))


def tel_norm(matn):
    """Telefon raqamni +998 (xx) xxx-xx-xx formatiga keltiradi.
    Noto'g'ri bo'lsa None qaytaradi. Masalan: +998901234567, 998 90 123 45 67, 901234567."""
    raqamlar = "".join(c for c in (matn or "") if c.isdigit())
    if len(raqamlar) == 9:
        raqamlar = "998" + raqamlar
    if len(raqamlar) == 12 and raqamlar.startswith("998"):
        return f"+998 ({raqamlar[3:5]}) {raqamlar[5:8]}-{raqamlar[8:10]}-{raqamlar[10:12]}"
    return None


def email_sozlangan():
    """Gmail SMTP sozlangan bo'lsa True qaytaradi."""
    gmail = os.getenv("GMAIL")
    parol = os.getenv("APP_PASSWORD")
    return bool(gmail and parol and "your_" not in gmail)


def email_yuborish(manzil, kod):
    """Gmail SMTP orqali tasdiqlash kodini yuboradi"""
    import smtplib
    from email.mime.text import MIMEText

    gmail = os.getenv("GMAIL")
    parol = os.getenv("APP_PASSWORD")

    if not email_sozlangan():
        print(f"[DEMO] {manzil} -> tasdiqlash kodi: {kod}", flush=True)
        return False

    msg = MIMEText(
        f"Urganch shahar 25-son maktab kutubxonasi\n\n"
        f"Sizning tasdiqlash kodingiz: {kod}\n\n"
        f"Agar bu siz bo'lsangiz, kodni kiriting. Aks holda e'tibor bermang."
    )
    msg["Subject"] = "Kutubxona - Tasdiqlash kodi"
    msg["From"] = gmail
    msg["To"] = manzil

    try:
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
                server.login(gmail, parol)
                server.send_message(msg)
            return True
        except Exception:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
                server.starttls()
                server.login(gmail, parol)
                server.send_message(msg)
            return True
    except Exception as e:
        print(f"Email yuborishda xato: {e}")
        print(f"[DEMO REJIM] {manzil} -> tasdiqlash kodi: {kod}")
        return False


def admin_ga_royxat_xabari(ism, familiya, email, kod, yuborildi):
    """Har bir ro'yxatdan o'tish urinishida adminga (GMAIL manziliga)
    foydalanuvchi ma'lumotlari va tasdiqlash kodini yuboradi."""
    import smtplib
    from email.mime.text import MIMEText

    gmail = os.getenv("GMAIL")
    parol = os.getenv("APP_PASSWORD")
    if not gmail or not parol or "your_" in gmail:
        return

    holat = "yuborildi" if yuborildi else "YUBORILMADI (email manzili noto'g'ri bo'lishi mumkin)"
    matn = (
        f"Kutubxona saytida yangi ro'yxatdan o'tish urinishi:\n\n"
        f"Ism: {ism}\n"
        f"Familiya: {familiya}\n"
        f"Kiritilgan email: {email}\n"
        f"Tasdiqlash kodi: {kod}\n"
        f"Kodli xat foydalanuvchiga: {holat}\n"
    )
    msg = MIMEText(matn)
    msg["Subject"] = f"Kutubxona - Yangi royxatdan otish ({email})"
    msg["From"] = gmail
    msg["To"] = gmail

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail, parol)
            server.send_message(msg)
    except Exception as e:
        print(f"Admin xabarini yuborishda xato: {e}")


def joriy_foydalanuvchi():
    return session.get("foydalanuvchi")


ADMIN_LOGIN = os.getenv("ADMIN_EMAIL", "").lower().strip()
ADMIN_PAROL = os.getenv("ADMIN_PASSWORD", "")
if not ADMIN_LOGIN or not ADMIN_PAROL:
    print("OGOHLANTIRISH: ADMIN_EMAIL / ADMIN_PASSWORD .env faylida topilmadi. "
          "Admin sifatida kirish ishlamaydi, iltimos .env faylini to'ldiring.")


def admin_mi():
    f = joriy_foydalanuvchi()
    return bool(f and ADMIN_LOGIN and f.get("email") == ADMIN_LOGIN)


def foydalanuvchi_ismi(email):
    if not email:
        return "Tizim"
    if ADMIN_LOGIN and email == ADMIN_LOGIN:
        return "Admin"
    f = foydalanuvchilar_yuklash()
    user = f["faollar"].get(email) or f["tasdiqlanmaganlar"].get(email)
    if user:
        ism = user.get("ism", "")
        familiya = user.get("familiya", "")
        toliq = f"{ism} {familiya}".strip()
        return toliq or "Noma'lum foydalanuvchi"
    return "Noma'lum foydalanuvchi"


app.jinja_env.globals["foydalanuvchi_ismi"] = foydalanuvchi_ismi


def kitobni_topish(m, bolim, idx):
    """Bolim va idx to'g'ri bo'lsa kitobni qaytaradi, aks holda None."""
    if bolim not in m or idx < 0 or idx >= len(m[bolim]):
        return None
    return m[bolim][idx]


def kitobni_id_bilan_topish(m, kitob_id):
  """Kitobni bo'limdagi o'zgaruvchan indeks o'rniga barqaror ID orqali topadi."""
  for bolim, kitoblar in m.items():
    for idx, kitob in enumerate(kitoblar):
      if str(kitob.get("id", "")) == str(kitob_id):
        return bolim, idx, kitob
  return None


def fayllarni_tozalash(ochirilgan_kitob, qolgan_m):
    """O'chirilgan kitobning fayl/muqovasini, agar boshqa hech qaysi kitob
    ishlatmasa, diskdan ham o'chiradi (bo'sh joyni tejash uchun)."""
    ishlatilayotgan = set()
    for kitoblar in qolgan_m.values():
        for k in kitoblar:
            if k.get("fayl"):
                ishlatilayotgan.add(k["fayl"])
            if k.get("muqova"):
                ishlatilayotgan.add(k["muqova"])
    fayl = ochirilgan_kitob.get("fayl")
    if fayl and fayl not in ishlatilayotgan:
        yol = os.path.join(app.config["UPLOAD_FOLDER"], fayl)
        if os.path.exists(yol):
            os.remove(yol)
    muqova = ochirilgan_kitob.get("muqova")
    if muqova and muqova not in ishlatilayotgan:
        yol = os.path.join(app.config["COVER_FOLDER"], muqova)
        if os.path.exists(yol):
            os.remove(yol)


def yetim_fayllarni_tozalash(m):
    """Kitoblar bilan bog'lanmagan (yetim) muqova va fayllarni diskdan o'chiradi."""
    ishlatilgan_muqova = set()
    ishlatilgan_fayl = set()
    for kitoblar in m.values():
        for k in kitoblar:
            if k.get("muqova"):
                ishlatilgan_muqova.add(k["muqova"])
            if k.get("fayl"):
                ishlatilgan_fayl.add(k["fayl"])
    for papka_yol, ishlatilgan in (
        (app.config["COVER_FOLDER"], ishlatilgan_muqova),
        (app.config["UPLOAD_FOLDER"], ishlatilgan_fayl),
    ):
        if not os.path.isdir(papka_yol):
            continue
        for fayl in os.listdir(papka_yol):
            yol = os.path.join(papka_yol, fayl)
            if os.path.isfile(yol) and fayl not in ishlatilgan:
                try:
                    os.remove(yol)
                except OSError:
                    pass


def bolim_slug(bolim):
    """Bo'lim nomini HTML id sifatida ishlatish uchun xavfsiz qatorga aylantiradi."""
    if not bolim:
        return "bolim"
    xarita = str.maketrans({"'": "", "\u2018": "", "\u2019": ""})
    return "bolim-" + bolim.translate(xarita).lower().replace(" ", "-")


app.jinja_env.globals["bolim_slug"] = bolim_slug


def telegram_havolasi_mi(havola):
  """Faqat Telegram kanal yoki postining xavfsiz HTTPS havolasini qabul qiladi."""
  try:
    parsed = urlparse((havola or "").strip())
  except ValueError:
    return False
  return parsed.scheme == "https" and parsed.netloc.lower().removeprefix("www.") in {
    "t.me",
    "telegram.me",
  } and bool(parsed.path.strip("/"))


def google_drive_id_ajratish(havola):
  """Google Drive havolasidan fayl ID sini ajratib oladi.
  Qo'llab-quvvatlanadigan formatlar:
    - https://drive.google.com/file/d/FILE_ID/view...
    - https://docs.google.com/file/d/FILE_ID/...
    - https://drive.google.com/open?id=FILE_ID
    - https://drive.google.com/uc?id=FILE_ID
  """
  try:
    parsed = urlparse((havola or "").strip())
  except ValueError:
    return None
  host = parsed.netloc.lower().removeprefix("www.")
  if host not in {"drive.google.com", "docs.google.com"}:
    return None
  path_parts = parsed.path.strip("/").split("/")
  if len(path_parts) >= 3 and path_parts[0] == "file" and path_parts[1] == "d":
    return path_parts[2]
  if "id=" in parsed.query:
    from urllib.parse import parse_qs
    ids = parse_qs(parsed.query).get("id", [])
    if ids:
      return ids[0]
  return None


def google_drive_havolasi_mi(havola):
  """Google Drive havolasini tekshiradi. True/False qaytaradi."""
  return google_drive_id_ajratish(havola) is not None


def google_drive_preview_url(havola):
  """Google Drive havolasidan embed preview URL yaratadi."""
  kid = google_drive_id_ajratish(havola)
  if kid:
    return f"https://drive.google.com/file/d/{kid}/preview"
  return havola or ""


def google_drive_yuklab_url(havola):
  """Google Drive havolasidan to'g'ridan-yuklab olish URL yaratadi."""
  kid = google_drive_id_ajratish(havola)
  if kid:
    return f"https://drive.google.com/uc?export=download&id={kid}"
  return havola or ""


app.jinja_env.globals["google_drive_preview_url"] = google_drive_preview_url
app.jinja_env.globals["google_drive_yuklab_url"] = google_drive_yuklab_url


def kitob_oqish_havolasi(kitob, bolim, idx):
  """Kitob uchun o'qish havolasini qaytaradi, o'qish bo'lmasa None."""
  if kitob.get("telegram_havola"):
    return kitob["telegram_havola"]
  if kitob.get("google_drive_havola") or kitob.get("fayl"):
    return url_for("ochish", bolim=bolim, idx=idx)
  return None


app.jinja_env.globals["kitob_oqish_havolasi"] = kitob_oqish_havolasi


HTML = """
<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5">
<meta name="csrf-token" content="{{ csrf_token() }}">
<title>Urganch shahar 25-son maktab — Kutubxona</title>
<style>
  * { box-sizing: border-box; }
  html { scrollbar-width: auto; scrollbar-color: #8da8c7 #dce5ef; }
  ::-webkit-scrollbar { width: 96px; height: 32px; }
  ::-webkit-scrollbar-track { background: #dce5ef; border-radius: 10px; }
  ::-webkit-scrollbar-thumb { background: #8da8c7; border: 4px solid #dce5ef; border-radius: 10px; min-height: 48px; }
  ::-webkit-scrollbar-thumb:hover { background: #1a3a6e; }
  body { font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #1a3a6e, #2c5aa0); margin: 0; min-height: 100vh; }
  .header { background: rgba(0,0,0,0.3); color: white; }
  .header-inner { max-width: 1200px; margin: 0 auto; padding: 15px 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
  .header h1 { margin: 0; font-size: 22px; }
  .header-right { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 15px; }
  .header-right a { color: white; text-decoration: none; }
  .btn-chiqish { display: inline-flex; align-items: center; gap: 6px; background: linear-gradient(135deg, #e63950, #b8283d); color: #fff !important; padding: 8px 16px; border-radius: 20px; font-weight: bold; font-size: 14px; box-shadow: 0 3px 8px rgba(184, 40, 61, 0.5); transition: transform 0.15s, box-shadow 0.15s, background 0.15s; }
  .btn-chiqish:hover { background: linear-gradient(135deg, #ff4d64, #d32f45); transform: translateY(-2px) scale(1.05); box-shadow: 0 5px 14px rgba(184, 40, 61, 0.7); }
  .btn-chiqish:active { transform: translateY(0) scale(0.96); box-shadow: 0 2px 6px rgba(184, 40, 61, 0.5); }
  .btn-kirish, .btn-royxat { display: inline-flex; align-items: center; justify-content: center; padding: 8px 20px; border-radius: 22px; font-weight: bold; font-size: 14px; text-decoration: none; color: #fff !important; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s, background 0.2s, border-color 0.2s, color 0.2s; }
  .btn-kirish { background: rgba(255,255,255,0.12); border: 2px solid rgba(255,255,255,0.85); box-shadow: 0 3px 8px rgba(0,0,0,0.25); }
  .btn-kirish:hover { background: #fff; color: #1a3a6e !important; border-color: #fff; transform: translateY(-2px); box-shadow: 0 6px 16px rgba(255,255,255,0.45); }
  .btn-kirish:active { transform: translateY(1px) scale(0.97); box-shadow: 0 2px 5px rgba(0,0,0,0.35); }
  .btn-royxat { background: linear-gradient(135deg, #28a745, #1e7e34); border: 2px solid #1e7e34; box-shadow: 0 3px 10px rgba(40,167,69,0.5); }
  .btn-royxat:hover { background: linear-gradient(135deg, #32d15b, #28a745); border-color: #32d15b; transform: translateY(-2px); box-shadow: 0 7px 18px rgba(40,167,69,0.7); }
  .btn-royxat:active { transform: translateY(1px) scale(0.97); box-shadow: 0 2px 6px rgba(40,167,69,0.5); }
  .btn-kirish:focus-visible, .btn-royxat:focus-visible { outline: 3px solid #ffd400; outline-offset: 2px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  .nav { background: #fff; padding: 15px; border-radius: 10px; margin-bottom: 20px; text-align: center; position: sticky; top: 10px; z-index: 500; box-shadow: 0 4px 12px rgba(0,0,0,0.25); }
  .nav a { color: #1a3a6e; margin: 0 12px; text-decoration: none; font-weight: bold; }
  .flash { padding: 12px; border-radius: 6px; margin: 10px auto; max-width: 600px; text-align: center; }
  .flash-muvaffaqiyat { background: #d4edda; color: #155724; }
  .flash-xato { background: #f8d7da; color: #721c24; }
  .flash-malumot { background: #fff3cd; color: #856404; }
  .auth-form { background: #fff; padding: 30px; border-radius: 10px; max-width: 450px; margin: 30px auto; }
  .auth-form h2 { text-align: center; color: #1a3a6e; margin-top: 0; }
  .auth-form input, .auth-form select { width: 100%; padding: 10px; margin: 8px 0; border: 1px solid #ddd; border-radius: 6px; }
  .auth-form button { width: 100%; background: linear-gradient(135deg, #1a3a6e, #2c5aa0); color: white; padding: 12px; border: 2px solid #14294d; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; transition: transform 0.15s, box-shadow 0.2s, background 0.2s, border-color 0.2s; box-shadow: 0 3px 10px rgba(26,58,110,0.35); }
  .auth-form button:hover { background: linear-gradient(135deg, #24508f, #3b74c9); border-color: #24508f; transform: translateY(-2px); box-shadow: 0 7px 18px rgba(26,58,110,0.55); }
  .auth-form button:active { transform: translateY(1px) scale(0.98); box-shadow: 0 2px 6px rgba(26,58,110,0.45); }
  .auth-form button:focus-visible { outline: 3px solid #ffd400; outline-offset: 2px; }
  .auth-link { text-align: center; margin-top: 15px; }
  .auth-link a { color: #1a3a6e; }
  .bolim-sarlavha { color: white; background: rgba(0,0,0,0.3); padding: 12px; border-radius: 10px; margin: 20px 0 10px; scroll-margin-top: 80px; }
  .kitoblar { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 20px; align-items: stretch; }
  .karta { background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.15); display: flex; flex-direction: column; height: 100%; }
  .muqora { position: relative; width: 100%; height: 196px; background: linear-gradient(135deg, #1a3a6e, #2c5aa0); display: flex; align-items: center; justify-content: center; color: white; overflow: hidden }
  .kitob-ikon { font-size: 84px; line-height: 1; transition: transform 0.2s, opacity 0.2s; }
  .muqora img { width: 100%; height: 100%; object-fit: contain }
  .muqora-link { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; text-decoration: none; }
  .muqora-link:hover .kitob-ikon { opacity: 0.85; transform: scale(1.08); }
  .muqora-link:hover img { opacity: 0.85 }
  .yulduzcha { position: absolute; top: 8px; right: 8px; width: 34px; height: 34px; border-radius: 50%; background: rgba(0,0,0,0.45); display: flex; align-items: center; justify-content: center; font-size: 20px; text-decoration: none; color: #fff; line-height: 1; transition: transform 0.15s, background 0.15s; }
  .yulduzcha:hover { transform: scale(1.15); background: rgba(0,0,0,0.65); }
  .yulduzcha.faol { color: #ffc107; }
  .karta-tana { padding: 15px; display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .karta-tana h3 { margin: 0 0 8px; color: #1a3a6e; font-size: 16px; }
  .karta-tana p { margin: 4px 0; color: #666; font-size: 14px; }
  .karta-tana .qator { display: flex; justify-content: space-between; gap: 8px; }
  .karta-tana .yuklagan { font-size: 12px; color: #999; font-style: italic; }
  .tugmalar { margin-top: auto; padding-top: 10px; }
  .tugma-qator { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; margin-top: 5px; }
  .tugma-qator:first-child { margin-top: 0; }
  .btn { display: flex; align-items: center; justify-content: center; width: 100%; min-height: 34px; padding: 7px; border: none; border-radius: 6px; cursor: pointer; text-decoration: none; text-align: center; font-size: 12px; font-family: inherit; color: white; line-height: 1.2; }
  .tugma-qator form { display: flex; margin: 0; min-width: 0; padding: 0; background: none; border-radius: 0; }
  .tugma-qator form .btn { width: 100%; }
  .btn-ochish { background: #1a3a6e; }
  .btn-yuklash { background: #28a745; }
  .btn-tahrirlash { background: #ffc107; }
  .btn-ochirish { background: #dc3545; }
  form { background: #fff; padding: 20px; border-radius: 10px; margin: 20px 0; }
  form input, form select { width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 6px; }
  form button { background: linear-gradient(135deg, #1a3a6e, #2c5aa0); color: white; padding: 10px 20px; border: 2px solid #14294d; border-radius: 8px; cursor: pointer; font-weight: bold; transition: transform 0.15s, box-shadow 0.2s, background 0.2s, border-color 0.2s; }
  form button:not(.btn):hover { background: linear-gradient(135deg, #24508f, #3b74c9); border-color: #24508f; transform: translateY(-2px); box-shadow: 0 6px 16px rgba(26,58,110,0.5); }
  form button:not(.btn):active { transform: translateY(1px) scale(0.98); box-shadow: 0 2px 6px rgba(26,58,110,0.45); }
  form button:focus-visible { outline: 3px solid #ffd400; outline-offset: 2px; }
  /* Sinf va fan nomi kartada katta harfli va qalin */
  .sinf-fan-nomi { font-weight:700; text-transform:uppercase; letter-spacing:.4px; }
  p.sinf-fan-nomi { margin:0 0 6px; color:#1a3a6e; font-size:13px; }
  /* Sinflar va fanlar ro'yxati (admin) */
  .sinf-qator { color:#1a3a6e; margin:14px 0 6px; display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
  .sinf-nomi { font-size:17px; }
  .fanlar-royxati { list-style:none; padding:0; margin:0; }
  .fan-qator { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid #eee; flex-wrap:wrap; }
  .fan-nomi { font-size:15px; }
  .qator-amallar { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
  .qator-amallar form { display:flex; align-items:center; gap:6px; margin:0; padding:0; background:none; border-radius:0; }
  .qator-amallar input[type="text"] { width:150px; margin:0; padding:6px 8px; font-size:13px; }
  .qator-amallar .btn { width:auto; min-height:28px; padding:5px 12px; font-size:12px; }
  @media (max-width: 700px) {
    .qator-amallar { width:100%; }
    .qator-amallar form { flex:1 1 100%; }
    .qator-amallar input[type="text"] { flex:1; width:auto; }
  }
  .qidiruv-form { display: flex; gap: 10px; }
  .qidiruv-form input { flex: 1; }
  .reader { background: #fff; padding: 20px; border-radius: 10px; text-align: center; }
  .reader iframe { width: 100%; height: 600px; border: none; border-radius: 8px; }

  .btn-qaytish { display: inline-flex; align-items: center; gap: 10px; background: linear-gradient(135deg, #ff7a45, #ff4d4d); color: #fff; border: none; padding: 12px 22px; border-radius: 30px; font-size: 15px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 14px rgba(255, 77, 77, 0.45); transition: transform 0.15s, box-shadow 0.15s; }
  .btn-qaytish:hover { transform: translateY(-2px) scale(1.03); box-shadow: 0 6px 18px rgba(255, 77, 77, 0.6); }
  .btn-qaytish:active { transform: translateY(0) scale(0.98); }
  .btn-qaytish .btn-qaytish-ok { font-size: 18px; }
  .btn-qaytish .btn-qaytish-esc { background: rgba(255,255,255,0.25); border: 1px solid rgba(255,255,255,0.6); border-radius: 6px; padding: 2px 8px; font-size: 12px; letter-spacing: 0.5px; }

  .btn-chiqish-pastki, .btn-yuklab-ochish {
    display: inline-flex; align-items: center; gap: 8px;
    border: none; border-radius: 12px;
    font-size: 14px; font-weight: bold;
    padding: 10px 20px;
    cursor: pointer;
    text-decoration: none;
    color: #fff;
    transition: background 0.2s, transform 0.1s, box-shadow 0.2s;
  }
  .btn-chiqish-pastki { background: linear-gradient(135deg, #e63950, #b8283d); box-shadow: 0 3px 10px rgba(184,40,61,0.5); }
  .btn-chiqish-pastki:hover { background: linear-gradient(135deg, #ff4d64, #d32f45); transform: translateY(-2px) scale(1.05); box-shadow: 0 5px 16px rgba(184,40,61,0.7); }
  .btn-chiqish-pastki:active { transform: translateY(0) scale(0.96); box-shadow: 0 2px 6px rgba(184,40,61,0.5); }
  .btn-yuklab-ochish { background: linear-gradient(135deg, #28a745, #1e7e34); box-shadow: 0 3px 10px rgba(40,167,69,0.5); }
  .btn-yuklab-ochish:hover { background: linear-gradient(135deg, #32ff7e, #28a745); transform: translateY(-2px) scale(1.05); box-shadow: 0 5px 16px rgba(40,167,69,0.7); }
  .btn-yuklab-ochish:active { transform: translateY(0) scale(0.96); box-shadow: 0 2px 6px rgba(40,167,69,0.5); }

  .karusel { background: rgba(255,255,255,0.05); border-radius: 12px; overflow: hidden; margin-bottom: 25px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
  .karusel-track { display: flex; transition: transform 2s ease-in-out; }
  .karusel-slide { min-width: 100%; display: flex; align-items: center; justify-content: center; background: #000 }
  .karusel-slide img { width: 100%; height: 400px; object-fit: contain; display: block }

  @media (max-width: 1200px) {
    .kitoblar { grid-template-columns: repeat(4, 1fr); gap: 16px; }
  }

  @media (max-width: 950px) {
    .kitoblar { grid-template-columns: repeat(3, 1fr); gap: 14px; }
  }

  @media (max-width: 700px) {
    .header-inner { flex-direction: column; align-items: center; gap: 8px; text-align: center; padding: 12px; }
    .header h1 { font-size: 18px; }
    .header-right { justify-content: center; }
    .container { padding: 10px; }
    .nav { padding: 10px; margin-bottom: 14px; }
    .nav a { margin: 0 6px; font-size: 14px; display: inline-block; }
    .bolim-sarlavha { padding: 10px; margin: 14px 0 8px; }
    .bolim-sarlavha h2 { font-size: 17px; }
    .muqora { height: 126px; }
    .kitob-ikon { font-size: 56px; }
    .yulduzcha { width: 28px; height: 28px; font-size: 16px; }
    .karta-tana { padding: 10px; }
    .karta-tana h3 { font-size: 14px; }
    .karta-tana p { font-size: 12px; }
    .btn { font-size: 11px; padding: 6px; min-height: 30px; }
    .auth-form { padding: 18px; margin: 16px auto; max-width: 92%; }
    .qidiruv-form { flex-direction: column; }
    .karusel-slide img { height: 220px; }
    .reader { padding: 10px; }
    .reader h2 { font-size: 18px; }
    .btn-qaytish { font-size: 13px; padding: 10px 16px; }
    #pdf-controls { position: static !important; box-shadow: none !important; border-radius: 8px !important; justify-content: center !important; }
    #pdf-canvas-wrap { margin-bottom: 20px !important; }
    #search-text { width: 100% !important; }
  }

  @media (max-width: 620px) {
    .kitoblar { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  }

  @media (max-width: 480px) {
    .kitoblar { grid-template-columns: repeat(2, 1fr); gap: 10px; }
    .container { padding: 8px; }
    .muqora { height: 150px; }
    .kitob-ikon { font-size: 54px; }
    .yulduzcha { width: 26px; height: 26px; font-size: 14px; }
    .karta-tana { padding: 8px; }
    .karta-tana h3 { font-size: 13px; }
    .karta-tana p { font-size: 11px; }
    .btn { font-size: 10px; padding: 5px 3px; min-height: 28px; }
    #search-status { display: none; }
  }

  @media (min-width: 1600px) {
    .container, .header-inner { max-width: 1500px; }
    .karusel-slide img { height: 500px; }
  }

  /* ===== Aksessbiliti: ko'zi ojiz va zaif ko'ruvchilar uchun ===== */
  :focus-visible { outline: 3px solid #ffd400 !important; outline-offset: 2px; }
  body.fokus-kuchli :focus { outline: 4px solid #ffd400 !important; outline-offset: 2px; background-color: rgba(255,212,0,0.18) !important; }
  .ekran-oquvchi { position: absolute !important; left: -9999px !important; width: 1px !important; height: 1px !important; overflow: hidden !important; }
  #aky-btn { position: fixed; right: 16px; bottom: 90px; z-index: 3000; width: 58px; height: 58px; border-radius: 50%; border: 3px solid #fff; background: #ffd400; color: #111; font-size: 28px; line-height: 1; cursor: pointer; box-shadow: 0 5px 18px rgba(0,0,0,0.45); }
  #aky-btn:hover { transform: scale(1.06); }
  #aky-panel { position: fixed; right: 16px; bottom: 158px; z-index: 3000; width: 280px; max-width: 92vw; background: #fff; color: #16181d; border-radius: 14px; box-shadow: 0 10px 34px rgba(0,0,0,0.5); padding: 14px; display: none; }
  #aky-panel.ochiq { display: block; }
  #aky-panel h3 { margin: 0 0 10px; font-size: 16px; color: #1a3a6e; }
  #aky-panel button { display: block; width: 100%; margin: 5px 0; padding: 11px 12px; border: 1px solid #ccd4e0; border-radius: 9px; background: #f3f6fb; color: #16181d; font-size: 14px; font-weight: 600; cursor: pointer; text-align: left; }
  #aky-panel button:hover { background: #e6ecf6; }
  #aky-panel button.faol { background: #1a3a6e; color: #fff; border-color: #1a3a6e; }
  #diktor-holat { position: fixed; left: 16px; bottom: 90px; z-index: 3000; background: rgba(0,0,0,0.85); color: #fff; padding: 9px 16px; border-radius: 22px; font-size: 13px; font-weight: bold; display: none; }
  #diktor-holat.ochiq { display: block; }
  #aky-yordam { margin: 8px 0 0; font-size: 11px; color: #5b6472; line-height: 1.4; }

  /* Tungi rejim */
  body.tungi { background: linear-gradient(135deg, #060b16, #0d1626); }
  body.tungi .header { background: rgba(0,0,0,0.5); }
  body.tungi .container { color: #e7edf7; }
  body.tungi .nav { background: #14203a; }
  body.tungi .nav a { color: #a8c6ff; }
  body.tungi .bolim-sarlavha { background: rgba(255,255,255,0.09); color: #e7edf7; }
  body.tungi .karta, body.tungi .reader, body.tungi .auth-form, body.tungi form { background: #14203a; color: #e7edf7; }
  body.tungi .karta-tana h3 { color: #a8c6ff; }
  body.tungi .karta-tana p, body.tungi .karta-tana small { color: #b9c6d8; }
  body.tungi .reader h2, body.tungi .auth-form h2, body.tungi form h2 { color: #a8c6ff; }
  body.tungi form input, body.tungi form select { background: #0c1730; color: #e7edf7; border-color: #2c3d63; }
  body.tungi .auth-form { border: 1px solid #24344f; }
  body.tungi .btn-tahrirlash { color: #16181d; }
  body.tungi .qidiruv-form input { background: #0c1730; color: #e7edf7; }
  body.tungi #aky-panel { background: #14203a; color: #e7edf7; }
  body.tungi #aky-panel button { background: #0c1730; color: #e7edf7; border-color: #2c3d63; }
  body.tungi #aky-panel button.faol { background: #2c5aa0; color: #fff; }
  body.tungi #aky-panel h3 { color: #a8c6ff; }
  body.tungi #aky-yordam { color: #9aa7bb; }
  .saralash { background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); border-radius: 10px; padding: 12px 16px; margin-bottom: 18px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .saralash label { color: #fff; font-weight: bold; font-size: 14px; }
  .saralash select { padding: 8px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.4); background: #fff; color: #1a3a6e; font-size: 14px; min-width: 140px; cursor: pointer; }
  .saralash .filter-group { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; flex-shrink: 1; min-width: 0; }
  .saralash .filter-group select { min-width: 110px; flex: 1 1 auto; }
  .saralash button { padding: 8px 14px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.4); background: rgba(255,255,255,0.2); color: #fff; cursor: pointer; font-size: 13px; font-weight: bold; transition: background 0.2s; }
  .saralash button:hover { background: rgba(255,255,255,0.35); }
  body.tungi .saralash { background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.15); }
  body.tungi .saralash select { background: #0c1730; color: #e7edf7; border-color: #2c3d63; }
  body.tungi .saralash button { background: rgba(255,255,255,0.12); border-color: #2c3d63; }
  body.tungi .saralash button:hover { background: rgba(255,255,255,0.22); }
</style>
</head>
<body data-sahifa="{{ sahifa }}">
<a class="ekran-oquvchi" href="#asosiy-mazmun">Asosiy mazmunga o'tish</a>
<button id="aky-btn" type="button" onclick="akyPanelAlmashtir()" aria-label="Qulaylik sozlamalarini ochish" aria-expanded="false" title="Qulaylik sozlamalari">&#9855;</button>
<div id="aky-panel" role="dialog" aria-modal="false" aria-label="Qulaylik sozlamalari">
  <h3>Qulaylik sozlamalari</h3>
  <button type="button" id="aky-tun" onclick="tunAlmashtir()" aria-pressed="false">Tungi rejim</button>
  <button type="button" onclick="akyShrift(1)" aria-label="Shriftni kattalashtirish">A+ Shriftni kattalashtirish</button>
  <button type="button" onclick="akyShrift(-1)" aria-label="Shriftni kichiklashtirish">A- Shriftni kichiklashtirish</button>
  <button type="button" id="aky-diktor" onclick="diktorAlmashtir()" aria-pressed="false">Diktor (ovozli yo'naltirish)</button>
  <button type="button" onclick="akySahifaAyt()" aria-label="Joriy sahifani ovozda aytish">Sahifani ovozda aytish</button>
  <button type="button" id="aky-fokus" onclick="akyFokus()" aria-pressed="false">Kuchli fokus (kontrast)</button>
  <button type="button" onclick="akyTiklash()" aria-label="Boshlang'ich holatga qaytarish">Boshlang'ich holatga qaytarish</button>
  <p id="aky-yordam">Diktor yoqilganda sahifadagi tugma va maydonlar ovozda aytib turiladi. PDF sahifasida "Ovozli o'qish" tugmasi kitobni o'qib beradi.</p>
</div>
<div id="diktor-holat" role="status" aria-live="polite">Diktor yoqilgan</div>
<div id="aky-announce" class="ekran-oquvchi" role="status" aria-live="assertive"></div>
<div class="header">
  <div class="header-inner">
    <h1>{{ site_title() }}</h1>
    <div class="header-right">
      {% if foydalanuvchi %}
        <span>Salom, <b>{{ foydalanuvchi.ism }}</b>!</span>
        <a class="btn-chiqish" href="{{ url_for('chiqish') }}">⏻ Chiqish</a>
      {% else %}
        <a class="btn-kirish" href="{{ url_for('kirish') }}">Kirish</a>
        <a class="btn-royxat" href="{{ url_for('royxat') }}">Ro'yxatdan o'tish</a>
      {% endif %}
    </div>
  </div>
</div>
<div class="container" id="asosiy-mazmun" tabindex="-1">

  {% with xabarlar = get_flashed_messages(with_categories=true) %}
    {% for tur, xabar in xabarlar %}
      <div class="flash flash-{{ tur }}">{{ xabar }}</div>
    {% endfor %}
  {% endwith %}

  {% if sahifa == 'bosh' %}
    <div class="nav">
      <a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a>
      <a href="{{ url_for('qidirish') }}">Qidirish</a>
      {% if foydalanuvchi %}
        <a href="{{ url_for('qoshish') }}">Kitob qo'shish</a>
        <a href="{{ url_for('sevimlilar_sahifa') }}">★ Sevimlilarim</a>
        {% if foydalanuvchi.rol == 'admin' %}
          <a href="{{ url_for('admin_boshqaruv') }}">🛠️ Boshqaruv paneli</a>
          <a href="{{ url_for('fanlar_sahifa') }}">📚 Fanlar va sinflar</a>
          <a href="{{ url_for('foydalanuvchilar_sahifa') }}">👥 Foydalanuvchilar</a>
        {% endif %}
      {% endif %}
    </div>

    {% if texnikum_rasmlari %}
    <div class="karusel">
      <div class="karusel-track">
        {% for rasm in texnikum_rasmlari %}
        <div class="karusel-slide">
          <img src="{{ url_for('static', filename='texnikum/' + rasm) }}" alt="Texnikum">
        </div>
        {% endfor %}
      </div>
    </div>
    {% else %}
    <div style="background:rgba(255,255,255,0.1); color:white; padding:30px; text-align:center; border-radius:10px; margin-bottom:20px">
      Texnikum rasmlari yuklanmagan. <code>Kutubxona/static/texnikum/</code> papkasiga rasmlarni qo'ying.
    </div>
    {% endif %}

    {% set filt_sinf, filt_fan = filtr %}
    <div class="saralash" id="saralash-panel">
      <span class="filter-group">
        <label for="sinf-filter">Sinf:</label>
        <select id="sinf-filter" aria-label="Sinf bo'yicha saralash">
          <option value="">Barcha sinflar</option>
          {% for sinf in filt_sinf %}
          <option value="{{ sinf }}">{{ sinf }}</option>
          {% endfor %}
        </select>
      </span>
      <span class="filter-group">
        <label for="fan-filter">Fan:</label>
        <select id="fan-filter" aria-label="Fan bo'yicha saralash">
          <option value="">Barcha fanlar</option>
          {% for fan in filt_fan %}
          <option value="{{ fan }}">{{ fan }}</option>
          {% endfor %}
        </select>
      </span>
      <button type="button" onclick="saralashTiklash()">Tozalash</button>
    </div>

    {% for bolim in bolimlar %}
      <div class="bolim-sarlavha" id="{{ bolim_slug(bolim) }}">
        <h2 style="margin:0">{{ bolim }} <small>({{ malumot[bolim]|length }} ta)</small></h2>
      </div>
      {% if malumot[bolim] %}
      <div class="kitoblar">
        {% for qator in malumot[bolim] %}
         {% set kitob = qator.kitob %}
         {% set sf = kitob_sinf_fani(kitob) %}
         <div class="karta" data-sinf="{{ sf.sinf }}" data-fan="{{ sf.fan }}">
           <div class="muqora">
             {% set oqish_url = kitob_oqish_havolasi(kitob, bolim, qator.idx) %}
             {% set tg_bosiq = kitob.telegram_havola %}
             {% if oqish_url %}<a href="{{ oqish_url }}"{% if tg_bosiq %} target="_blank" rel="noopener"{% endif %} class="muqora-link">{% endif %}
             {% if kitob.muqova %}
             <img src="{{ url_for('static', filename='covers/' + kitob.muqova) }}" alt="{{ kitob.nomi }}" style="cursor:{{ 'pointer' if oqish_url else 'default' }}">
             {% else %}
             <span class="kitob-ikon" style="cursor:{{ 'pointer' if oqish_url else 'default' }}">&#128214;</span>
             {% endif %}
             {% if oqish_url %}</a>{% endif %}
             {% if foydalanuvchi %}
               <a class="yulduzcha {{ 'faol' if kitob.id in sevimlilar else '' }}" href="#"
                  data-url="{{ url_for('sevimli_belgilash_id', kitob_id=kitob.id) }}"
                  onclick="return sevimliBosildi(this, event)"
                  title="Sevimlilarga qo'shish/olib tashlash">{{ '★' if kitob.id in sevimlilar else '☆' }}</a>
             {% endif %}
           </div>
           <div class="karta-tana">
             <h3>{{ kitob.nomi }}</h3>
{% if sf.sinf or sf.fan %}
              <p class="sinf-fan-nomi">
                {% if sf.sinf %}{{ sf.sinf }}{% endif %}
                {% if sf.fan %} — {{ sf.fan }}{% endif %}
              </p>
              {% endif %}
             <p class="qator"><span>{{ kitob.muallif }}</span><span>{{ kitob.yili }}</span></p>
            <div class="tugmalar">
              <div class="tugma-qator">
              {% if kitob.telegram_havola %}
                <a class="btn btn-ochish" href="{{ kitob.telegram_havola }}" target="_blank" rel="noopener">O'qish</a>
                <a class="btn btn-yuklash" href="{{ kitob.telegram_havola }}" target="_blank" rel="noopener">Telegramdan yuklash</a>
              {% elif kitob.google_drive_havola %}
                <a class="btn btn-ochish" href="{{ google_drive_preview_url(kitob.google_drive_havola) }}" target="_blank" rel="noopener">Ko'rish</a>
                <a class="btn btn-yuklash" href="{{ google_drive_yuklab_url(kitob.google_drive_havola) }}" target="_blank" rel="noopener">Yuklab olish</a>
              {% elif kitob.fayl %}
                <a class="btn btn-ochish" href="{{ url_for('ochish', bolim=bolim, idx=qator.idx) }}">O'qish</a>
                <a class="btn btn-yuklash" href="{{ url_for('static', filename='files/' + kitob.fayl) }}" download>Yuklab</a>
              {% endif %}
              </div>
              {% if foydalanuvchi and (kitob.tomonidan == foydalanuvchi.email or foydalanuvchi.rol == 'admin') %}
                <div class="tugma-qator">
                <a class="btn btn-tahrirlash" href="{{ url_for('tahrirlash', bolim=bolim, idx=qator.idx) }}">Tahrir</a>
                <form method="post" action="{{ url_for('ochirish_id', kitob_id=kitob.id) }}" onsubmit="return confirm(&quot;O'chirilsinmi?&quot;)">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <button type="submit" class="btn btn-ochirish">O'chirish</button>
                </form>
                </div>
              {% endif %}
            </div>
          </div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    {% endfor %}

  {% elif sahifa == 'qidirish' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
    <form class="qidiruv-form" method="get" id="qidiruv-form">
      <input type="search" name="so_rov" id="qidiruv-maydon" placeholder="Kitob yoki muallif izlash..." value="{{ so_rov or '' }}" aria-label="Kitob yoki muallif izlash" autocomplete="off">
    </form>
    {% if natija %}
    <div class="kitoblar" style="margin-top:20px">
      {% for item in natija %}
      {% set sf = kitob_sinf_fani(item.kitob) %}
      <div class="karta" data-sinf="{{ sf.sinf }}" data-fan="{{ sf.fan }}">
        <div class="muqora">
          {% set oqish_url = kitob_oqish_havolasi(item.kitob, item.bolim, item.idx) %}
          {% set tg_bosiq = item.kitob.telegram_havola %}
          {% if oqish_url %}<a href="{{ oqish_url }}"{% if tg_bosiq %} target="_blank" rel="noopener"{% endif %} class="muqora-link">{% endif %}
          {% if item.kitob.muqova %}
          <img src="{{ url_for('static', filename='covers/' + item.kitob.muqova) }}" alt="{{ item.kitob.nomi }}" style="cursor:{{ 'pointer' if oqish_url else 'default' }}">
          {% else %}
          <span class="kitob-ikon" style="cursor:{{ 'pointer' if oqish_url else 'default' }}">&#128214;</span>
          {% endif %}
          {% if oqish_url %}</a>{% endif %}
          {% if foydalanuvchi %}
            <a class="yulduzcha {{ 'faol' if item.kitob.id in sevimlilar else '' }}" href="#"
               data-url="{{ url_for('sevimli_belgilash_id', kitob_id=item.kitob.id) }}"
               onclick="return sevimliBosildi(this, event)"
               title="Sevimlilarga qo'shish/olib tashlash">{{ '★' if item.kitob.id in sevimlilar else '☆' }}</a>
          {% endif %}
        </div>
        <div class="karta-tana">
          <small style="color:#1a3a6e">{{ item.bolim }}{% if sf.sinf or sf.fan %} — <span class="sinf-fan-nomi">{{ sf.sinf }}{% if sf.fan %} / {{ sf.fan }}{% endif %}</span>{% endif %}</small>
          <h3>{{ item.kitob.nomi }}</h3>
           <p>{{ item.kitob.muallif }} ({{ item.kitob.yili }})</p>
           <div class="tugmalar">
             <div class="tugma-qator">
             {% if item.kitob.telegram_havola %}
               <a class="btn btn-ochish" href="{{ item.kitob.telegram_havola }}" target="_blank" rel="noopener">O'qish</a>
               <a class="btn btn-yuklash" href="{{ item.kitob.telegram_havola }}" target="_blank" rel="noopener">Telegramdan yuklash</a>
             {% elif item.kitob.google_drive_havola %}
               <a class="btn btn-ochish" href="{{ google_drive_preview_url(item.kitob.google_drive_havola) }}" target="_blank" rel="noopener">Ko'rish</a>
               <a class="btn btn-yuklash" href="{{ google_drive_yuklab_url(item.kitob.google_drive_havola) }}" target="_blank" rel="noopener">Yuklab olish</a>
             {% elif item.kitob.fayl %}
               <a class="btn btn-ochish" href="{{ url_for('ochish', bolim=item.bolim, idx=item.idx) }}">O'qish</a>
               <a class="btn btn-yuklash" href="{{ url_for('static', filename='files/' + item.kitob.fayl) }}" download>Yuklab</a>
             {% endif %}
             </div>
           </div>
         </div>
       </div>
       {% endfor %}
     </div>
    {% elif so_rov %}
    <p style="color:white; text-align:center; margin-top:20px">Hech narsa topilmadi.</p>
    {% else %}
    <p style="color:white; text-align:center; margin-top:20px">Qidirish uchun yuqoridagi maydonga kitob yoki muallif nomini yozing.</p>
    {% endif %}

  {% elif sahifa == 'sevimlilar' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
    <h2 style="color:white">★ Mening sevimlilarim</h2>
    {% if natija %}
    <div class="kitoblar" style="margin-top:20px">
      {% for item in natija %}
      {% set sf = kitob_sinf_fani(item.kitob) %}
      <div class="karta" data-olib-tashlansin="1" data-sinf="{{ sf.sinf }}" data-fan="{{ sf.fan }}">
        <div class="muqora">
          {% set oqish_url = kitob_oqish_havolasi(item.kitob, item.bolim, item.idx) %}
          {% set tg_bosiq = item.kitob.telegram_havola %}
          {% if oqish_url %}<a href="{{ oqish_url }}"{% if tg_bosiq %} target="_blank" rel="noopener"{% endif %} class="muqora-link">{% endif %}
          {% if item.kitob.muqova %}
          <img src="{{ url_for('static', filename='covers/' + item.kitob.muqova) }}" alt="{{ item.kitob.nomi }}" style="cursor:{{ 'pointer' if oqish_url else 'default' }}">
          {% else %}
          <span class="kitob-ikon" style="cursor:{{ 'pointer' if oqish_url else 'default' }}">&#128214;</span>
          {% endif %}
          {% if oqish_url %}</a>{% endif %}
          <a class="yulduzcha faol" href="#"
             data-url="{{ url_for('sevimli_belgilash_id', kitob_id=item.kitob.id) }}"
             onclick="return sevimliBosildi(this, event)"
             title="Sevimlilardan olib tashlash">★</a>
        </div>
        <div class="karta-tana">
          <small style="color:#1a3a6e">{{ item.bolim }}{% if sf.sinf or sf.fan %} — <span class="sinf-fan-nomi">{{ sf.sinf }}{% if sf.fan %} / {{ sf.fan }}{% endif %}</span>{% endif %}</small>
          <h3>{{ item.kitob.nomi }}</h3>
          <p class="qator"><span>{{ item.kitob.muallif }}</span><span>{{ item.kitob.yili }}</span></p>
          <div class="tugmalar">
            <div class="tugma-qator">
            {% if item.kitob.telegram_havola %}
              <a class="btn btn-ochish" href="{{ item.kitob.telegram_havola }}" target="_blank" rel="noopener">O'qish</a>
              <a class="btn btn-yuklash" href="{{ item.kitob.telegram_havola }}" target="_blank" rel="noopener">Telegramdan yuklash</a>
            {% elif item.kitob.google_drive_havola %}
              <a class="btn btn-ochish" href="{{ google_drive_preview_url(item.kitob.google_drive_havola) }}" target="_blank" rel="noopener">Ko'rish</a>
              <a class="btn btn-yuklash" href="{{ google_drive_yuklab_url(item.kitob.google_drive_havola) }}" target="_blank" rel="noopener">Yuklab olish</a>
            {% elif item.kitob.fayl %}
              <a class="btn btn-ochish" href="{{ url_for('ochish', bolim=item.bolim, idx=item.idx) }}">O'qish</a>
              <a class="btn btn-yuklash" href="{{ url_for('static', filename='files/' + item.kitob.fayl) }}" download>Yuklab</a>
            {% endif %}
            </div>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <p style="color:white; text-align:center; margin-top:20px">Sevimlilar ro'yxati bo'sh. Kitoblar ustidagi ☆ belgisini bosib qo'shing.</p>
    {% endif %}

  {% elif sahifa == 'qoshish' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
      <form method="post" enctype="multipart/form-data">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <h2>Yangi kitob qo'shish</h2>
      <label>Bo'lim:</label>
      <select name="bolim" required>
        {% for bolim in bolimlar %}
        <option value="{{ bolim }}">{{ bolim }}</option>
        {% endfor %}
      </select>
      <label>Sinf:</label>
      <select name="sinf" required>
        <option value="">Sinfni tanlang</option>
        {% for sinf in sinflar_tartiblash(sinflar) %}
        <option value="{{ sinf }}">{{ sinf }}</option>
        {% endfor %}
      </select>
      <label>Fan:</label>
      <select name="fan" required>
        <option value="">Fanni tanlang</option>
        {% for fan in fanlar_tartiblash(fanlar) %}
        <option value="{{ fan }}">{{ fan }}</option>
        {% endfor %}
      </select>
      {% if not fanlar %}
      <small style="color:#721c24">Hali fan qo'shilmagan. Fan va sinf ro'yxatini admin boshqaradi.</small>
      {% endif %}
      <label>Kitob nomi (ixtiyoriy):</label>
      <input type="text" name="nomi">
      <label>Muallif (ixtiyoriy):</label>
      <input type="text" name="muallif">
          <label>Nashr yili (ixtiyoriy):</label>
          <input type="text" name="yili">
          <label>Muqova rasmi (ixtiyoriy, max 0.3 MB):</label>
          <input type="file" name="muqova" accept="image/*" onchange="if(this.files[0] && this.files[0].size > 0.3*1024*1024){ alert('Rasm hajmi 0.3 MB dan katta! Kichikroq rasm tanlang.'); this.value=''; }">
          <label>Telegram kanalidagi kitob havolasi (ixtiyoriy):</label>
          <input type="url" name="telegram_havola" placeholder="https://t.me/kanal/123">
          <label>Google Drive'dagi kitob havolasini kiriting.</label>
          <input type="url" name="google_drive_havola" placeholder="https://drive.google.com/file/d/ID/view" required>
          <button type="submit">Saqlash</button>
    </form>

  {% elif sahifa == 'tahrirlash' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
    <form method="post" enctype="multipart/form-data">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Kitobni tahrirlash</h2>
      <label>Nomi (ixtiyoriy):</label>
      <input type="text" name="nomi" value="{{ kitob.nomi or '' }}">
      <label>Sinf:</label>
      <select name="sinf">
        <option value="">Sinfni tanlang</option>
        {% for sinf in sinflar_tartiblash(sinflar) %}
        <option value="{{ sinf }}" {{ 'selected' if kitob.get('sinf') == sinf else '' }}>{{ sinf }}</option>
        {% endfor %}
      </select>
      <label>Fan:</label>
      <select name="fan">
        <option value="">Fanni tanlang</option>
        {% for fan in fanlar_tartiblash(fanlar) %}
        <option value="{{ fan }}" {{ 'selected' if kitob.get('fan') == fan else '' }}>{{ fan }}</option>
        {% endfor %}
      </select>
      <label>Muallif (ixtiyoriy):</label>
      <input type="text" name="muallif" value="{{ kitob.muallif or '' }}">
        <label>Nashr yili (ixtiyoriy):</label>
        <input type="text" name="yili" value="{{ kitob.yili or '' }}">
        <label>Muqova rasmi (ixtiyoriy, max 0.3 MB):</label>
        <input type="file" name="muqova" accept="image/*" onchange="if(this.files[0] && this.files[0].size > 0.3*1024*1024){ alert('Rasm hajmi 0.3 MB dan katta! Kichikroq rasm tanlang.'); this.value=''; }">
        {% if kitob.muqova %}<small>Hozirgi rasm: {{ kitob.muqova }} — yangi rasm tanlasangiz almashtiriladi.</small>{% endif %}
        <label>Telegram kanalidagi kitob havolasi (ixtiyoriy):</label>
        <input type="url" name="telegram_havola" value="{{ kitob.telegram_havola or '' }}" placeholder="https://t.me/kanal/123">
        <label>Google Drive'dagi kitob havolasini kiriting.</label>
        <input type="url" name="google_drive_havola" value="{{ kitob.google_drive_havola or '' }}" placeholder="https://drive.google.com/file/d/ID/view" required>
        <button type="submit">Saqlash</button>
    </form>

  {% elif sahifa == 'admin_boshqaruv' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
    <div class="auth-form">
      <h2>Bosh sahifa matni va rasmlarini boshqarish</h2>
      <form method="post">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <label>Sahifa sarlavhasi:</label>
        <input type="text" name="title" value="{{ site_title() }}" required>
        <button type="submit">Saqlash</button>
      </form>
    </div>

    <div class="auth-form">
      <h2>Yangi rasm yuklash</h2>
      <form method="post" enctype="multipart/form-data">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <label>Rasm fayli (max 5 MB):</label>
        <input type="file" name="homepage_image" accept="image/*" required>
        <button type="submit">Yuklash</button>
      </form>
    </div>

    <div class="auth-form">
      <h2>Hozirgi rasmlar ({{ texnikum_rasmlari|length }} ta)</h2>
      {% for rasm in texnikum_rasmlari %}
        <div style="display:flex; align-items:center; gap:12px; padding:12px 0; border-bottom:1px solid #eee; flex-wrap:wrap">
          <img src="{{ url_for('static', filename='texnikum/' + rasm) }}" alt="{{ rasm }}" style="width:120px; height:80px; object-fit:cover; border-radius:8px; border:1px solid #ddd">
          <span style="font-weight:bold; word-break:break-all">{{ rasm }}</span>
          <form method="post" action="{{ url_for('admin_rasm_ochirish') }}" onsubmit="return confirm('Rasm o\'chirilsinmi?');">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="filename" value="{{ rasm }}">
            <button type="submit" class="btn btn-ochirish">O'chirish</button>
          </form>
          <form method="post" enctype="multipart/form-data">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="replace_filename" value="{{ rasm }}">
            <input type="file" name="homepage_image" accept="image/*" required>
            <button type="submit" class="btn btn-tahrirlash">Almashtirish</button>
          </form>
        </div>
      {% else %}
        <p style="color:#666; text-align:center">Hozircha rasm yuklanmagan.</p>
      {% endfor %}
    </div>
  {% elif sahifa == 'fanlar' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
    <h2 style="color:white">Sinflar va fanlar ro'yxati</h2>
    <div class="auth-form">
      <h2>Yangi sinf qo'shish</h2>
      <form id="sinf-qoshish-form" method="post" action="{{ url_for('sinf_qoshish') }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <label>Sinf nomi:</label>
        <input type="text" name="sinf" required placeholder="Masalan: 9-sinf">
        <button type="submit">Qo'shish</button>
      </form>
      <div id="sinf-xabar" style="margin-top:10px;color:#155724"></div>
    </div>
    <div class="auth-form">
      <h2>Yangi fan qo'shish</h2>
      <p style="margin:0 0 10px;color:#555;font-size:14px">Fanlar ro'yxati <b>barcha sinflar uchun umumiy</b> — bir marta qo'shsangiz, barcha sinflarda tanlanadi.</p>
      <form id="fan-qoshish-form" method="post" action="{{ url_for('fan_qoshish') }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <label>Fan nomi:</label>
        <input type="text" name="fan" required placeholder="Masalan: Matematika">
        <button type="submit">Qo'shish</button>
      </form>
      <div id="fan-xabar" style="margin-top:10px;color:#155724"></div>
    </div>
    <div class="auth-form">
      <h2>Sinflar ({{ sinflar | length }}) — raqam tartibida</h2>
      <ul class="fanlar-royxati">
        {% for sinf in sinflar_tartiblash(sinflar) %}
        <li class="fan-qator">
          <span class="fan-nomi">{{ sinf }}</span>
          <span class="qator-amallar">
            <form method="post" action="{{ url_for('sinf_tahrirlash') }}" onsubmit="return sinfTahrirlash(this)" class="tahrirlash-formasi">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <input type="hidden" name="eski_sinf" value="{{ sinf }}">
              <input type="text" name="yangi_sinf" value="{{ sinf }}" aria-label="{{ sinf }} sinfining yangi nomi">
              <button type="submit" class="btn btn-tahrirlash">Saqlash</button>
            </form>
            <form method="post" action="{{ url_for('sinf_ochirish') }}" onsubmit="return sinfOchirish(this)">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <input type="hidden" name="sinf" value="{{ sinf }}">
              <button type="submit" class="btn btn-ochirish">O'chirish</button>
            </form>
          </span>
        </li>
        {% else %}
        <li style="padding:6px 0;color:#666">Hali sinf qo'shilmagan.</li>
        {% endfor %}
      </ul>
    </div>
    <div class="auth-form">
      <h2>Fanlar ({{ fanlar | length }}) — barcha sinflar uchun, alifbo tartibida</h2>
      <ul class="fanlar-royxati">
        {% for fan in fanlar_tartiblash(fanlar) %}
        <li class="fan-qator">
          <span class="fan-nomi">{{ fan }}</span>
          <span class="qator-amallar">
            <form method="post" action="{{ url_for('fan_tahrirlash') }}" onsubmit="return fanTahrirlash(this)" class="tahrirlash-formasi">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <input type="hidden" name="eski_fan" value="{{ fan }}">
              <input type="text" name="yangi_fan" value="{{ fan }}" aria-label="{{ fan }} fanining yangi nomi">
              <button type="submit" class="btn btn-tahrirlash">Saqlash</button>
            </form>
            <form method="post" action="{{ url_for('fan_ochirish') }}" onsubmit="return fanOchirish(this, '{{ fan }}')">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
              <input type="hidden" name="fan" value="{{ fan }}">
              <button type="submit" class="btn btn-ochirish">O'chirish</button>
            </form>
          </span>
        </li>
        {% else %}
        <li style="padding:6px 0;color:#666">Hali fan qo'shilmagan.</li>
        {% endfor %}
      </ul>
    </div>

  {% elif sahifa == 'ochish' %}
    <div class="nav" style="text-align:left; background:transparent; padding:0; box-shadow:none; position:static">
      <button type="button" class="btn-qaytish" onclick="qaytish()">
        <span class="btn-qaytish-ok">←</span> Oldingi joyga qaytish
        <span class="btn-qaytish-esc">Esc</span>
      </button>
    </div>
    <div class="reader">
      <h2>{% if kitob.nomi %}{{ kitob.nomi }}{% if kitob.muallif %} — {% endif %}{% endif %}{{ kitob.muallif or '' }}</h2>
      <p style="color:#666">PDF hajmi: {{ fayl_hajmi(kitob.fayl) }}</p>

      <div id="pdf-controls" style="background:#1a3a6e; padding:12px; border-radius:8px; margin:10px 0; display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:space-between; position:fixed; bottom:0; left:0; right:0; z-index:1000; box-shadow:0 -4px 12px rgba(0,0,0,0.2); color:white">
        <button onclick="qaytish()" class="btn-chiqish-pastki">⬅ Chiqish</button>
        <span style="display:flex; align-items:center; gap:5px">
          <input type="number" id="page-num" min="1" value="1" style="width:60px; padding:6px; text-align:center; border:1px solid #ddd; border-radius:4px">
          <span>/ <span id="page-count">0</span></span>
        </span>
        <button onclick="prevPage()" class="pdf-btn">◄ Oldingi</button>
        <button onclick="nextPage()" class="pdf-btn">Keyingi ►</button>
        <button onclick="zoomOut()" class="pdf-btn">−</button>
        <input type="range" id="zoom-slider" min="50" max="200" value="100" step="10" style="width:120px" oninput="setZoom(this.value)">
        <button onclick="zoomIn()" class="pdf-btn">+</button>
        <span id="zoom-val" style="min-width:45px">100%</span>
        <input type="text" id="search-text" placeholder="Matn izlash..." style="padding:6px; border:1px solid #ddd; border-radius:4px; width:160px" aria-label="PDF ichidan matn izlash">
        <button onclick="searchPDF()" class="pdf-btn">🔍 Izlash</button>
        <button onclick="pdfOqi()" class="pdf-btn" id="pdf-oqi-btn" aria-label="PDF kitobni ovozli o'qish">🔊 Ovozli o'qish</button>
        <span id="search-status" style="font-size:12px; color:#666"></span>
        <a class="pdf-btn btn-yuklab" href="{{ url_for('static', filename='files/' + kitob.fayl) }}" download style="background:#28a745; text-decoration:none">⬇ Yuklab</a>
      </div>

      <div id="pdf-canvas-wrap" style="position:relative; background:#555; padding:10px; border-radius:8px; margin-bottom:80px">
        <div id="pdf-viewer" style="display:flex; justify-content:center; min-height:600px">
          <canvas id="pdf-canvas" style="background:white; box-shadow:0 4px 12px rgba(0,0,0,0.3); max-width:100%"></canvas>
        </div>
      </div>

      <div id="pdf-loading" style="text-align:center; padding:20px; color:#1a3a6e">Yuklanmoqda...</div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
    <script>
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

    let pdfDoc = null, pageNum = 1, pageRendering = false, pageNumPending = null;
    let scale = 1.0, searchMatches = [], currentMatch = 0;

    const url = "{{ url_for('static', filename='files/' + kitob.fayl) }}";

    function qaytish() {
      if (window.history.length > 1) window.history.back();
      else window.location.href = "{{ url_for('bosh_sahifa') }}";
    }

    function renderPage(num) {
      pageRendering = true;
      pdfDoc.getPage(num).then(page => {
        const viewport = page.getViewport({scale: scale});
        const canvas = document.getElementById('pdf-canvas');
        const ctx = canvas.getContext('2d');
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        page.render({canvasContext: ctx, viewport: viewport}).promise.then(() => {
          pageRendering = false;
          if (pageNumPending !== null) {
            renderPage(pageNumPending);
            pageNumPending = null;
          }
        });
      });
      document.getElementById('page-num').value = num;
    }

    function queueRenderPage(num) {
      if (pageRendering) pageNumPending = num;
      else renderPage(num);
    }

    function prevPage() {
      if (pageNum <= 1) return;
      pageNum--;
      queueRenderPage(pageNum);
    }

    function nextPage() {
      if (pageNum >= pdfDoc.numPages) return;
      pageNum++;
      queueRenderPage(pageNum);
    }

    document.getElementById('page-num').addEventListener('change', function() {
      let n = parseInt(this.value);
      if (n >= 1 && n <= pdfDoc.numPages) { pageNum = n; queueRenderPage(pageNum); }
    });

    function setZoom(val) {
      scale = val / 100;
      document.getElementById('zoom-val').textContent = val + '%';
      queueRenderPage(pageNum);
    }

    function zoomIn() {
      let v = Math.min(200, parseInt(document.getElementById('zoom-slider').value) + 10);
      document.getElementById('zoom-slider').value = v;
      setZoom(v);
    }

    function zoomOut() {
      let v = Math.max(50, parseInt(document.getElementById('zoom-slider').value) - 10);
      document.getElementById('zoom-slider').value = v;
      setZoom(v);
    }

    function searchPDF() {
      const q = document.getElementById('search-text').value.trim();
      if (!q) return;
      document.getElementById('search-status').textContent = 'Izlanmoqda...';
      searchMatches = [];
      let promises = [];
      for (let i = 1; i <= pdfDoc.numPages; i++) {
        promises.push(pdfDoc.getPage(i).then(p => p.getTextContent().then(tc => {
          const text = tc.items.map(it => it.str).join(' ').toLowerCase();
          if (text.includes(q.toLowerCase())) searchMatches.push(i);
        })));
      }
      Promise.all(promises).then(() => {
        if (searchMatches.length === 0) {
          document.getElementById('search-status').textContent = 'Topilmadi';
        } else {
          currentMatch = 0;
          pageNum = searchMatches[0];
          queueRenderPage(pageNum);
          document.getElementById('search-status').textContent = '1/' + searchMatches.length + ' (sahifa ' + searchMatches[0] + ')';
          document.getElementById('search-text').onkeydown = function(e) {
            if (e.key === 'Enter' && searchMatches.length) {
              currentMatch = (currentMatch + 1) % searchMatches.length;
              pageNum = searchMatches[currentMatch];
              queueRenderPage(pageNum);
              document.getElementById('search-status').textContent = (currentMatch+1) + '/' + searchMatches.length + ' (sahifa ' + searchMatches[currentMatch] + ')';
            }
          };
        }
      });
    }

    pdfjsLib.getDocument(url).promise.then(pdf => {
      pdfDoc = pdf;
      document.getElementById('page-count').textContent = pdf.numPages;
      document.getElementById('pdf-loading').style.display = 'none';
      renderPage(1);
    }).catch(err => {
      document.getElementById('pdf-loading').textContent = 'Xato: ' + err.message;
    });

    let pdfOqilmoqda = false, pdfOvoz = null;

    function pdfTugmaYangila() {
      const b = document.getElementById('pdf-oqi-btn');
      if (b) b.textContent = pdfOqilmoqda ? '⏹ O\\'qishni to\\'xtatish' : '🔊 Ovozli o\\'qish';
    }

    function pdfOvozTanla() {
      if (!('speechSynthesis' in window)) return;
      const ovozlar = speechSynthesis.getVoices();
      pdfOvoz = ovozlar.find(v => (v.lang || '').toLowerCase().startsWith('uz')) ||
                ovozlar.find(v => (v.lang || '').toLowerCase().startsWith('tr')) ||
                ovozlar.find(v => (v.lang || '').toLowerCase().startsWith('ru')) ||
                ovozlar[0] || null;
    }
    if ('speechSynthesis' in window) {
      pdfOvozTanla();
      speechSynthesis.onvoiceschanged = pdfOvozTanla;
    }

    function pdfOqi() {
      if (!('speechSynthesis' in window)) {
        alert('Bu brauzerda ovozli o\\'qish qo\\'llab-quvvatlanmaydi.');
        return;
      }
      if (pdfOqilmoqda) {
        pdfOqilmoqda = false;
        speechSynthesis.cancel();
        pdfTugmaYangila();
        return;
      }
      if (!pdfDoc) return;
      pdfOqilmoqda = true;
      pdfTugmaYangila();
      pdfOqiSahifa(pageNum);
    }

    function pdfOqiSahifa(n) {
      if (!pdfOqilmoqda) return;
      if (n > pdfDoc.numPages) {
        pdfOqilmoqda = false;
        pdfTugmaYangila();
        return;
      }
      if (n !== pageNum) { pageNum = n; queueRenderPage(pageNum); }
      pdfDoc.getPage(n).then(p => p.getTextContent()).then(tc => {
        const matn = tc.items.map(it => it.str).join(' ').replace(/\\s+/g, ' ').trim();
        if (!matn) { pdfOqiSahifa(n + 1); return; }
        const u = new SpeechSynthesisUtterance(matn);
        u.lang = 'uz-UZ';
        if (pdfOvoz) u.voice = pdfOvoz;
        u.rate = 0.95;
        u.onend = () => { if (pdfOqilmoqda) pdfOqiSahifa(n + 1); };
        speechSynthesis.speak(u);
      }).catch(() => { if (pdfOqilmoqda) pdfOqiSahifa(n + 1); });
    }

    document.addEventListener('keydown', function(e) {
      const maydonda = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
      if (maydonda) return;
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        nextPage();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        prevPage();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        window.scrollBy({ top: 400, behavior: 'smooth' });
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        window.scrollBy({ top: -400, behavior: 'smooth' });
      } else if (e.key === 'Escape') {
        e.preventDefault();
        qaytish();
      }
    });
    </script>
    <style>
    #pdf-controls { padding:clamp(4px, 0.6vw, 8px) !important; gap:clamp(4px, 0.7vw, 10px) !important; font-size:clamp(10px, 1vw, 13px); }
    #pdf-controls .pdf-btn { background:white; color:#1a3a6e; border:none; padding:clamp(4px, 0.5vw, 6px) clamp(7px, 0.9vw, 12px); border-radius:4px; cursor:pointer; font-size:clamp(10px, 1vw, 13px); font-weight:bold }
    #pdf-controls input { font-size:clamp(10px, 1vw, 13px); padding:clamp(4px, 0.5vw, 6px) !important; }
    #pdf-controls input[type="number"] { width:clamp(42px, 5vw, 60px) !important; }
    #pdf-controls input[type="range"] { width:clamp(70px, 10vw, 120px) !important; }
    #pdf-controls input[type="text"] { width:clamp(100px, 13vw, 160px) !important; }
    #pdf-controls #zoom-val { min-width:clamp(35px, 3.5vw, 45px) !important; }
    .pdf-btn:hover { background:#f0f0f0 }
    #pdf-controls input[type="number"], #pdf-controls input[type="text"] { background:white; color:#333; border:1px solid #ccc }
    </style>

  {% elif sahifa == 'ochish_drive' %}
    <div class="reader">
      <h2>{% if kitob.nomi %}{{ kitob.nomi }}{% if kitob.muallif %} — {% endif %}{% endif %}{{ kitob.muallif or '' }}</h2>

      <div id="drive-controls" style="display:flex; align-items:center; justify-content:space-between; align-content:center; position:fixed; bottom:0; left:0; right:0; z-index:1000; padding:14px 20px; background:linear-gradient(135deg, #1a3a6e, #2c5aa0); box-shadow:0 -4px 12px rgba(0,0,0,0.3); color:white">
        <button onclick="qaytish()" class="btn-chiqish-pastki">⬅ Chiqish</button>
        {% if kitob.nomi or kitob.muallif %}
        <button onclick="gapir({% if kitob.nomi %}'Kitob nomi: {{ kitob.nomi|e }}. '{% endif %}{% if kitob.muallif %}'Muallif: {{ kitob.muallif|e }}.'{% endif %})" class="btn-yuklab-ochish" aria-label="Kitob nomi va muallifini ovozda eshitish">🔊 Ovozda eshitish</button>
        {% endif %}
        <a href="{{ drive_download }}" target="_blank" rel="noopener" class="btn-yuklab-ochish">⬇ Yuklab olish</a>
      </div>



      <div id="pdf-canvas-wrap" style="position:relative; background:#555; padding:10px; border-radius:8px; margin-bottom:70px">
        <iframe src="{{ drive_preview }}" style="width:100%; height:600px; border:none; border-radius:8px" allow="autoplay; encrypted-media" allowfullscreen></iframe>
      </div>

      <div id="pdf-loading" style="text-align:center; padding:20px; color:#1a3a6e">Yuklanmoqda...</div>
    </div>

    <script>
    function qaytish() {
      if (window.history.length > 1) window.history.back();
      else window.location.href = "{{ url_for('bosh_sahifa') }}";
    }
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') { e.preventDefault(); qaytish(); }
    });
    </script>

  {% elif sahifa == 'kirish' %}
    <form class="auth-form" method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Tizimga kirish</h2>
      <input type="email" name="email" placeholder="Email" required aria-label="Email manzil">
      <input type="password" name="parol" placeholder="Parol" required aria-label="Parol">
      <button type="submit">Kirish</button>
      <div class="auth-link">Akkaunt yo'qmi? <a href="{{ url_for('royxat') }}">Ro'yxatdan o'tish</a></div>
    </form>

  {% elif sahifa == 'royxat' %}
    <form class="auth-form" method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Ro'yxatdan o'tish</h2>
      <input type="text" name="ism" placeholder="Ism" required aria-label="Ism">
      <input type="text" name="familiya" placeholder="Familiya" required aria-label="Familiya">
      <input type="email" name="email" placeholder="Email" required aria-label="Email manzil">
      <input type="tel" name="tel" placeholder="+998 (90) 123-45-67" required title="Format: +998 (xx) xxx-xx-xx" aria-label="Telefon raqam">
      <input type="password" name="parol" placeholder="Parol (kamida 6 ta)" minlength="6" required aria-label="Parol">
      <button type="submit">Ro'yxatdan o'tish</button>
      <div class="auth-link">Akkauntingiz bormi? <a href="{{ url_for('kirish') }}">Kirish</a></div>
    </form>

  {% elif sahifa == 'tasdiqlash' %}
      <form class="auth-form" method="post">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <h2>Email tasdiqlash</h2>
        <p style="text-align:center">{{ email }} manziliga yuborilgan 6 xonali kodni kiriting</p>
        {% if demo_kod %}
        <p style="text-align:center; background:#fff3cd; color:#856404; padding:10px; border-radius:6px">
          Email sozlanmagan (demo rejim).<br>Tasdiqlash kodi: <b style="font-size:20px; letter-spacing:3px">{{ demo_kod }}</b>
        </p>
        {% endif %}
        <input type="text" name="kod" placeholder="123456" maxlength="6" required style="text-align:center; font-size:20px; letter-spacing:5px">
        <button type="submit">Tasdiqlash</button>
      </form>

  {% elif sahifa == 'foydalanuvchilar' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
    <h2 style="color:white">👥 Foydalanuvchilar ({{ foydalanuvchilar|length }} ta)</h2>
    <div class="auth-form">
      <h2>Ro'yxatdan o'tganlar</h2>
      {% for u in foydalanuvchilar %}
        <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid #eee">
          <div>
            <b>{{ u.ism }} {{ u.familiya }}</b><br>
            <small style="color:#666">{{ u.email }}</small>
            {% if u.tel %}<br><small style="color:#666">📱 {{ u.tel }}</small>{% endif %}
          </div>
          <a class="btn btn-tahrirlash" style="min-width:80px" href="{{ url_for('foydalanuvchi_tahrirlash', email=u.email) }}">Tahrir</a>
        </div>
      {% else %}
        <p style="color:#666; text-align:center">Hozircha foydalanuvchi yo'q.</p>
      {% endfor %}
    </div>

    <form class="auth-form" method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Yangi foydalanuvchi yaratish</h2>
      <input type="email" name="email" placeholder="Email (login sifatida)" required>
      <input type="tel" name="tel" placeholder="Telefon (ixtiyoriy, +998 90 123-45-67)">
      <input type="text" name="ism" placeholder="Ism" required>
      <input type="text" name="familiya" placeholder="Familiya">
      <input type="password" name="parol" placeholder="Parol (kamida 6 belgi)" required minlength="6">
      <button type="submit">Yaratish</button>
      <small>Email tasdiqlash talab qilinmaydi — foydalanuvchi kiritilgan login/parol bilan darhol kirishi mumkin.</small>
    </form>

  {% elif sahifa == 'foydalanuvchi_tahrirlash' %}
    <div class="nav"><a href="{{ url_for('foydalanuvchilar_sahifa') }}">👥 Foydalanuvchilar</a></div>
    <form class="auth-form" method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Foydalanuvchini tahrirlash</h2>
      <label>Email (login):</label>
      <input type="email" value="{{ tahrir_email }}" disabled>
      <label>Telefon raqam (+998 (xx) xxx-xx-xx, ixtiyoriy):</label>
      <input type="tel" name="tel" value="{{ tahrir_malumot.tel or '' }}" placeholder="+998 (90) 123-45-67">
      <label>Ism:</label>
      <input type="text" name="ism" value="{{ tahrir_malumot.ism }}" required>
      <label>Familiya:</label>
      <input type="text" name="familiya" value="{{ tahrir_malumot.familiya or '' }}">
      <label>Yangi parol (ixtiyoriy — bo'sh qoldirilsa o'zgarmaydi):</label>
      <input type="password" name="parol" placeholder="Yangi parol" minlength="6">
      <button type="submit">Saqlash</button>
    </form>
  {% endif %}
</div>

{% if sahifa == 'bosh' and texnikum_rasmlari %}
<script>
  const track = document.querySelector('.karusel-track');
  const slides = document.querySelectorAll('.karusel-slide');
  if (track && slides.length > 0) {
    let idx = 0;
    function rotate() {
      idx = (idx + 1) % slides.length;
      track.style.transform = `translateX(-${idx * 100}%)`;
    }
    setInterval(rotate, 5000);
  }
</script>
{% endif %}

<script>
function sevimliBosildi(el, event) {
  event.preventDefault();
  const url = el.getAttribute('data-url');
  const token = document.querySelector('meta[name="csrf-token"]').content;
  fetch(url, { method: 'POST', headers: { 'X-CSRFToken': token } })
    .then(r => r.json())
    .then(data => {
      if (data.xato) { return; }
      if (data.faol) {
        el.classList.add('faol');
        el.textContent = '★';
      } else {
        el.classList.remove('faol');
        el.textContent = '☆';
      }
      const karta = el.closest('[data-olib-tashlansin]');
      if (karta && !data.faol) {
        karta.style.transition = 'opacity 0.3s';
        karta.style.opacity = '0';
        setTimeout(() => karta.remove(), 300);
      }
    })
    .catch(() => {});
  return false;
}
</script>

<script>
/* ===== Aksessbiliti: tungi rejim, shrift, diktor ===== */
const AKY_KEY = 'kutubxona_aky';
let akyHolat = { tun: false, shrift: 0, diktor: false, fokus: false };

function akyOqish() {
  try { Object.assign(akyHolat, JSON.parse(localStorage.getItem(AKY_KEY) || '{}')); } catch (e) {}
}
function akyYozish() {
  try { localStorage.setItem(AKY_KEY, JSON.stringify(akyHolat)); } catch (e) {}
}
function akyQollash() {
  document.body.classList.toggle('tungi', akyHolat.tun);
  document.body.classList.toggle('fokus-kuchli', akyHolat.fokus);
  document.body.style.zoom = akyHolat.shrift === 0 ? '' : (1 + akyHolat.shrift * 0.1).toFixed(2);
  const tun = document.getElementById('aky-tun');
  if (tun) { tun.classList.toggle('faol', akyHolat.tun); tun.setAttribute('aria-pressed', akyHolat.tun); tun.textContent = akyHolat.tun ? '☀️ Kunduzgi rejim' : '🌙 Tungi rejim'; }
  const dik = document.getElementById('aky-diktor');
  if (dik) { dik.classList.toggle('faol', akyHolat.diktor); dik.setAttribute('aria-pressed', akyHolat.diktor); }
  const fok = document.getElementById('aky-fokus');
  if (fok) { fok.classList.toggle('faol', akyHolat.fokus); fok.setAttribute('aria-pressed', akyHolat.fokus); }
  const hol = document.getElementById('diktor-holat');
  if (hol) hol.classList.toggle('ochiq', akyHolat.diktor);
}
function akyPanelAlmashtir() {
  const p = document.getElementById('aky-panel');
  const b = document.getElementById('aky-btn');
  const och = p.classList.toggle('ochiq');
  b.setAttribute('aria-expanded', och);
  if (och && akyHolat.diktor) gapir('Qulaylik sozlamalari ochildi.');
}
function tunAlmashtir() { akyHolat.tun = !akyHolat.tun; akyYozish(); akyQollash(); if (akyHolat.diktor) gapir(akyHolat.tun ? 'Tungi rejim yoqildi.' : 'Kunduzgi rejim yoqildi.'); }
function akyShrift(yon) { akyHolat.shrift = Math.max(-3, Math.min(5, akyHolat.shrift + yon)); akyYozish(); akyQollash(); if (akyHolat.diktor) gapir(akyHolat.shrift > 0 ? 'Shrift kattalashtirildi.' : (akyHolat.shrift < 0 ? 'Shrift kichiklashtirildi.' : 'Shrift oddiy holatda.')); }
function akyFokus() { akyHolat.fokus = !akyHolat.fokus; akyYozish(); akyQollash(); if (akyHolat.diktor) gapir(akyHolat.fokus ? 'Kuchli fokus yoqildi.' : 'Kuchli fokus ochirildi.'); }
function akyTiklash() { akyHolat = { tun: false, shrift: 0, diktor: false, fokus: false }; akyYozish(); akyQollash(); if ('speechSynthesis' in window) speechSynthesis.cancel(); gapir('Sozlamalar boshlangich holatga qaytarildi.'); }

/* --- Diktor (ovozli yo'naltirish) --- */
let diktorOvoz = null;
function diktorOvozTanla() {
  if (!('speechSynthesis' in window)) return;
  const ovozlar = speechSynthesis.getVoices();
  diktorOvoz = ovozlar.find(v => (v.lang || '').toLowerCase().startsWith('uz')) ||
               ovozlar.find(v => (v.lang || '').toLowerCase().startsWith('tr')) ||
               ovozlar.find(v => (v.lang || '').toLowerCase().startsWith('ru')) ||
               ovozlar[0] || null;
}
if ('speechSynthesis' in window) {
  diktorOvozTanla();
  speechSynthesis.onvoiceschanged = diktorOvozTanla;
}
function gapir(matn) {
  if (!('speechSynthesis' in window) || !matn) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(matn);
  u.lang = 'uz-UZ';
  if (diktorOvoz) u.voice = diktorOvoz;
  u.rate = 0.95; u.pitch = 1;
  speechSynthesis.speak(u);
  const ann = document.getElementById('aky-announce');
  if (ann) ann.textContent = matn;
}
function elementTavsifi(el) {
  if (!el || !el.tagName) return '';
  const teg = el.tagName.toLowerCase();
  let matn = (el.getAttribute('aria-label') || el.getAttribute('title') || '');
  if (!matn) {
    if (teg === 'input' || teg === 'select' || teg === 'textarea') matn = el.getAttribute('placeholder') || el.value || el.name || '';
    else matn = (el.textContent || '').trim();
  }
  matn = matn.replace(/\\s+/g, ' ').trim();
  if (!matn) return '';
  let tur = '';
  if (teg === 'a') tur = 'havola';
  else if (teg === 'button') tur = 'tugma';
  else if (teg === 'input') tur = el.type === 'password' ? 'parol maydoni' : 'kiritish maydoni';
  else if (teg === 'select') tur = 'tanlash maydoni';
  else if (teg === 'textarea') tur = 'matn maydoni';
  return tur ? tur + ': ' + matn : matn;
}
document.addEventListener('focusin', function(e) {
  if (!akyHolat.diktor) return;
  const teg = ((e.target && e.target.tagName) || '').toLowerCase();
  if (['input', 'select', 'textarea'].includes(teg)) {
    const t = elementTavsifi(e.target);
    if (t) gapir(t);
  }
});
document.addEventListener('click', function(e) {
  if (!akyHolat.diktor || !e.target || !e.target.closest) return;
  const el = e.target.closest('a, button');
  if (!el || el.id === 'aky-btn' || el.id === 'aky-diktor' || el.id === 'pdf-oqi-btn') return;
  const t = elementTavsifi(el);
  if (t) gapir(t);
});

function diktorAlmashtir() {
  akyHolat.diktor = !akyHolat.diktor;
  akyYozish();
  akyQollash();
  if (akyHolat.diktor) akySahifaAyt();
  else if ('speechSynthesis' in window) speechSynthesis.cancel();
}

const SAHIFA_NOMLARI = {
  bosh: "Bosh sahifa. Kutubxona bo'limlari va kitoblar ro'yxati.",
  qidirish: "Qidirish sahifasi. Kitob nomi yoki muallifini yozib qidiring.",
  sevimlilar: "Sevimlilar sahifasi.",
  kirish: "Tizimga kirish sahifasi.",
  royxat: "Royxatdan otish sahifasi.",
  tasdiqlash: "Email tasdiqlash sahifasi.",
  foydalanuvchilar: "Foydalanuvchilar sahifasi.",
  foydalanuvchi_tahrirlash: "Foydalanuvchini tahrirlash sahifasi.",
  fanlar: "Sinflar va fanlar ro'yxati sahifasi.",
  qoshish: "Yangi kitob qoshish sahifasi.",
  tahrirlash: "Kitobni tahrirlash sahifasi.",
  ochish: "PDF kitob oqish sahifasi.",
  ochish_drive: "Google Drive kitob oqish sahifasi."
};
function akySahifaAyt() {
  const sahifa = (document.body && document.body.dataset.sahifa) || '';
  let matn = SAHIFA_NOMLARI[sahifa] || "Kutubxona sahifasi.";
  if (sahifa === 'ochish' || sahifa === 'ochish_drive') {
    const t = document.querySelector('.reader h2');
    if (t) matn = "Ochilgan kitob: " + t.textContent.replace(/\\s+/g, ' ').trim() +
      (sahifa === 'ochish' ? ". Kitobni ovozda eshitish uchun pastdagi ovozli oqish tugmasini bosing." : ".");
  } else if (sahifa === 'bosh') {
    const s = document.querySelector('.bolim-sarlavha h2');
    if (s) matn += ' ' + s.textContent.replace(/\\s+/g, ' ').trim();
  }
  gapir(matn);
}
document.addEventListener('keydown', function(e) {
  if (e.altKey && (e.key === 'a' || e.key === 'A')) {
    e.preventDefault();
    akyPanelAlmashtir();
  }
});
document.addEventListener('DOMContentLoaded', function() {
  akyOqish();
  akyQollash();
  if (akyHolat.diktor) setTimeout(akySahifaAyt, 700);
});

function saralashIshgaTush() {
  const sinf = document.getElementById('sinf-filter').value;
  const fan = document.getElementById('fan-filter').value;
  document.querySelectorAll('.karta').forEach(karta => {
    const s = karta.dataset.sinf || '';
    const f = karta.dataset.fan || '';
    const mos = (!sinf || s === sinf) && (!fan || f === fan);
    karta.style.display = mos ? '' : 'none';
  });
  document.querySelectorAll('.bolim-sarlavha').forEach(sarlavha => {
    const kitoblar = sarlavha.nextElementSibling;
    if (!kitoblar || !kitoblar.classList.contains('kitoblar')) {
      sarlavha.style.display = 'none';
      return;
    }
    const hechQaysi = [...kitoblar.querySelectorAll('.karta')].some(k => k.style.display !== 'none');
    sarlavha.style.display = hechQaysi ? '' : 'none';
    kitoblar.style.display = hechQaysi ? '' : 'none';
  });
}
function saralashTiklash() {
  document.getElementById('sinf-filter').value = '';
  document.getElementById('fan-filter').value = '';
  saralashIshgaTush();
}
document.addEventListener('DOMContentLoaded', function() {
  [document.getElementById('sinf-filter'), document.getElementById('fan-filter')]
    .forEach(el => { if (el) el.addEventListener('change', saralashIshgaTush); });
});

{% if sahifa == 'qidirish' %}
document.addEventListener('DOMContentLoaded', function() {
  const maydon = document.getElementById('qidiruv-maydon');
  const forma = document.getElementById('qidiruv-form');
  if (!maydon || !forma) return;
  let taymer = null;
  maydon.addEventListener('input', function() {
    clearTimeout(taymer);
    taymer = setTimeout(function() { forma.submit(); }, 400);
  });
  maydon.focus();
});
{% endif %}

function sinfQoshish(e) {
  e.preventDefault();
  const form = e.target;
  const csrf = form.querySelector('input[name="csrf_token"]').value;
  const sinf = form.querySelector('input[name="sinf"]').value.trim();
  const xabar = document.getElementById('sinf-xabar');
  if (!sinf) { xabar.style.color = '#721c24'; xabar.textContent = 'Sinf nomini kiriting'; return; }
  fetch("{{ url_for('sinf_qoshish') }}", {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: new URLSearchParams({ sinf })
  }).then(r => r.json()).then(data => {
    if (data.muvaffaqiyat) {
      xabar.style.color = '#155724'; xabar.textContent = 'Sinf qo\\'shildi! Sahifani yangilang.';
      form.reset();
      setTimeout(() => location.reload(), 800);
    } else {
      xabar.style.color = '#721c24'; xabar.textContent = data.xato || 'Xato';
    }
  });
}
function sinfOchirish(form) {
  const csrf = form.querySelector('input[name="csrf_token"]').value;
  const sinf = form.querySelector('input[name="sinf"]').value;
  if (!confirm('"' + sinf + '" sinfini o\\'chirishga ishonchingiz komilmi?')) return false;
  fetch("{{ url_for('sinf_ochirish') }}", {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: new URLSearchParams({ sinf })
  }).then(r => r.json()).then(data => {
    if (data.muvaffaqiyat) location.reload();
    else alert(data.xato || 'Xato');
  });
  return false;
}
function sinfTahrirlash(form) {
  const csrf = form.querySelector('input[name="csrf_token"]').value;
  const eski = form.querySelector('input[name="eski_sinf"]').value;
  const yangi = form.querySelector('input[name="yangi_sinf"]').value.trim();
  const xabar = document.getElementById('sinf-xabar');
  if (!yangi) { xabar.style.color = '#721c24'; xabar.textContent = 'Yangi sinf nomini kiriting'; return false; }
  fetch("{{ url_for('sinf_tahrirlash') }}", {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: new URLSearchParams({ eski_sinf: eski, yangi_sinf: yangi })
  }).then(r => r.json()).then(data => {
    if (data.muvaffaqiyat) location.reload();
    else {
      xabar.style.color = '#721c24';
      xabar.textContent = data.xato || 'Xato';
    }
  }).catch(() => {});
  return false;
}
function fanTahrirlash(form) {
  const csrf = form.querySelector('input[name="csrf_token"]').value;
  const eski = form.querySelector('input[name="eski_fan"]').value;
  const yangi = form.querySelector('input[name="yangi_fan"]').value.trim();
  const xabar = document.getElementById('fan-xabar');
  if (!yangi) { xabar.style.color = '#721c24'; xabar.textContent = 'Yangi fan nomini kiriting'; return false; }
  fetch("{{ url_for('fan_tahrirlash') }}", {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: new URLSearchParams({ eski_fan: eski, yangi_fan: yangi })
  }).then(r => r.json()).then(data => {
    if (data.muvaffaqiyat) location.reload();
    else {
      xabar.style.color = '#721c24';
      xabar.textContent = data.xato || 'Xato';
    }
  }).catch(() => {});
  return false;
}
function fanQoshish(e) {
  e.preventDefault();
  const form = e.target;
  const csrf = form.querySelector('input[name="csrf_token"]').value;
  const fan = form.querySelector('input[name="fan"]').value.trim();
  const xabar = document.getElementById('fan-xabar');
  if (!fan) { xabar.style.color = '#721c24'; xabar.textContent = 'Fan nomini kiriting'; return; }
  fetch("{{ url_for('fan_qoshish') }}", {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: new URLSearchParams({ fan })
  }).then(r => r.json()).then(data => {
    if (data.muvaffaqiyat) {
      xabar.style.color = '#155724'; xabar.textContent = 'Fan qo\\'shildi! Sahifani yangilang.';
      form.reset();
      setTimeout(() => location.reload(), 800);
    } else {
      xabar.style.color = '#721c24'; xabar.textContent = data.xato || 'Xato';
    }
  });
}
function fanOchirish(form, fanNomi) {
  const csrf = form.querySelector('input[name="csrf_token"]').value;
  if (!confirm('"'+fanNomi+'" ni barcha sinflardan o\\'chirishga ishonchingiz komilmi?')) return false;
  fetch("{{ url_for('fan_ochirish') }}", {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: new URLSearchParams({ fan: form.querySelector('input[name="fan"]').value })
  }).then(r => r.json()).then(data => {
    if (data.muvaffaqiyat) location.reload();
    else alert(data.xato || 'Xato');
  });
  return false;
}
document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('fan-qoshish-form');
  if (form) form.addEventListener('submit', fanQoshish);
  const sinfForm = document.getElementById('sinf-qoshish-form');
  if (sinfForm) sinfForm.addEventListener('submit', sinfQoshish);
});
</script>
</body>
</html>
"""


@app.route("/")
def bosh_sahifa():
    user = joriy_foydalanuvchi()
    m = kitoblar_yuklash()
    return render_template_string(HTML, sahifa="bosh", bolimlar=BO_LIMLAR,
                                   malumot=kitoblarni_tartiblash(m),
                                   filtr=filtr_royxatlari(m),
                                   foydalanuvchi=user,
                                   sevimlilar=foydalanuvchi_sevimlilari(user["email"]) if user else set(),
                                   texnikum_rasmlari=texnikum_rasmlari())


@app.route("/qidirish")
def qidirish():
    user = joriy_foydalanuvchi()
    so_rov = request.args.get("so_rov", "").strip().lower()
    natija = []
    if so_rov:
        for bolim, kitoblar in kitoblar_yuklash().items():
            for idx, kitob in enumerate(kitoblar):
                sf = kitob_sinf_fani(kitob)
                maydonlar = (kitob.get("nomi", ""), kitob.get("muallif", ""), sf["sinf"], sf["fan"])
                if any(so_rov in (m or "").lower() for m in maydonlar):
                    natija.append({"bolim": bolim, "idx": idx, "kitob": kitob})
    natija.sort(key=lambda qator: kitob_tartibi(qator["kitob"]))
    return render_template_string(HTML, sahifa="qidirish", bolimlar=BO_LIMLAR,
                                   so_rov=so_rov, natija=natija, foydalanuvchi=user,
                                   sevimlilar=foydalanuvchi_sevimlilari(user["email"]) if user else set())


@app.route("/sevimlilar")
def sevimlilar_sahifa():
    user = joriy_foydalanuvchi()
    if not user:
        flash("Sevimlilarni ko'rish uchun tizimga kiring", "xato")
        return redirect(url_for("kirish"))
    mening = foydalanuvchi_sevimlilari(user["email"])
    natija = []
    for bolim, kitoblar in kitoblar_yuklash().items():
        for idx, kitob in enumerate(kitoblar):
            if kitob.get("id") in mening:
                natija.append({"bolim": bolim, "idx": idx, "kitob": kitob})
    natija.sort(key=lambda qator: kitob_tartibi(qator["kitob"]))
    return render_template_string(HTML, sahifa="sevimlilar", bolimlar=BO_LIMLAR,
                                   natija=natija, foydalanuvchi=user, sevimlilar=mening)


@app.route("/sevimli/<bolim>/<int:idx>", methods=["POST"])
def sevimli_belgilash(bolim, idx):
    """AJAX orqali kitobni sevimlilarga qo'shadi/olib tashlaydi, sahifa yangilanmaydi."""
    user = joriy_foydalanuvchi()
    if not user:
        return jsonify({"xato": "Tizimga kirilmagan"}), 401
    m = kitoblar_yuklash()
    kitob = kitobni_topish(m, bolim, idx)
    if kitob is None:
        return jsonify({"xato": "Kitob topilmadi"}), 404
    kid = kitob["id"]
    f = foydalanuvchilar_yuklash()
    ro_yxat = f["sevimlilar"].setdefault(user["email"], [])
    if kid in ro_yxat:
        ro_yxat.remove(kid)
        faol = False
    else:
        ro_yxat.append(kid)
        faol = True
    foydalanuvchilar_saqlash(f)
    return jsonify({"faol": faol})


@app.route("/sevimli-id/<kitob_id>", methods=["POST"])
def sevimli_belgilash_id(kitob_id):
    """AJAX orqali kitobni barqaror ID yordamida sevimlilarga qo'shadi/olib tashlaydi."""
    user = joriy_foydalanuvchi()
    if not user:
        return jsonify({"xato": "Tizimga kirilmagan"}), 401
    topilma = kitobni_id_bilan_topish(kitoblar_yuklash(), kitob_id)
    if topilma is None:
        return jsonify({"xato": "Kitob topilmadi"}), 404
    _, _, kitob = topilma
    f = foydalanuvchilar_yuklash()
    roy_xat = f["sevimlilar"].setdefault(user["email"], [])
    if kitob["id"] in roy_xat:
        roy_xat.remove(kitob["id"])
        faol = False
    else:
        roy_xat.append(kitob["id"])
        faol = True
    foydalanuvchilar_saqlash(f)
    return jsonify({"faol": faol})


@app.route("/royxat", methods=["GET", "POST"])
def royxat():
    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        ism = request.form.get("ism", "").strip()
        familiya = request.form.get("familiya", "").strip()
        tel = request.form.get("tel", "").strip()
        parol = request.form.get("parol", "")
        tel_sozlangan = tel_norm(tel)
        if not email or not ism or not familiya or not parol:
            flash("Barcha maydonlarni to'ldiring", "xato")
            return redirect(url_for("royxat"))
        if not tel_sozlangan:
            flash("Telefon raqam +998 (xx) xxx-xx-xx formatida bo'lishi kerak", "xato")
            return redirect(url_for("royxat"))
        if len(parol) < 6:
            flash("Parol kamida 6 belgidan iborat bo'lishi kerak", "xato")
            return redirect(url_for("royxat"))

        f = foydalanuvchilar_yuklash()
        eski_bor = email in f["faollar"] or email in f["tasdiqlanmaganlar"]
        if eski_bor:
            f["faollar"].pop(email, None)
            f["tasdiqlanmaganlar"].pop(email, None)

        kod = kod_yaratish()
        f["tasdiqlanmaganlar"][email] = {
            "ism": ism,
            "familiya": familiya,
            "tel": tel_sozlangan,
            "parol": generate_password_hash(parol),
            "kod": kod,
        }
        foydalanuvchilar_saqlash(f)
        yuborildi = email_yuborish(email, kod)
        admin_ga_royxat_xabari(ism, familiya, email, kod, yuborildi)
        session["tasdiqlash_email"] = email
        if not email_sozlangan():
            flash("Email sozlanmagan (demo rejim). Tasdiqlash kodi keyingi sahifada ko'rsatiladi.", "malumot")
        elif eski_bor:
            flash("Eski akkaunt o'chirildi. Yangi tasdiqlash kodi yuborildi.", "muvaffaqiyat")
        elif not yuborildi:
            flash("Email yuborilmadi. Administrator bilan bog'laning.", "xato")
        return redirect(url_for("tasdiqlash"))
    return render_template_string(HTML, sahifa="royxat", foydalanuvchi=joriy_foydalanuvchi())


@app.route("/tasdiqlash", methods=["GET", "POST"])
def tasdiqlash():
    email = session.get("tasdiqlash_email")
    if not email:
        return redirect(url_for("royxat"))
    f = foydalanuvchilar_yuklash()
    if request.method == "POST":
        if email in f["tasdiqlanmaganlar"]:
            kiritilgan = request.form.get("kod", "").strip()
            if f["tasdiqlanmaganlar"][email]["kod"] == kiritilgan:
                malumot = f["tasdiqlanmaganlar"].pop(email)
                f["faollar"][email] = malumot
                foydalanuvchilar_saqlash(f)
                session["foydalanuvchi"] = {"ism": malumot["ism"], "email": email}
                session.pop("tasdiqlash_email", None)
                flash("Muvaffaqiyatli ro'yxatdan o'tdingiz!", "muvaffaqiyat")
                return redirect(url_for("bosh_sahifa"))
            else:
                flash("Kod noto'g'ri", "xato")
    demo_kod = None
    if not email_sozlangan() and email in f["tasdiqlanmaganlar"]:
        demo_kod = f["tasdiqlanmaganlar"][email]["kod"]
    return render_template_string(HTML, sahifa="tasdiqlash", email=email,
                                   demo_kod=demo_kod,
                                   foydalanuvchi=joriy_foydalanuvchi())


@app.route("/kirish", methods=["GET", "POST"])
def kirish():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        parol = request.form.get("parol", "")

        if ADMIN_LOGIN and email.lower() == ADMIN_LOGIN and parol == ADMIN_PAROL:
            session["foydalanuvchi"] = {"ism": "Admin", "email": ADMIN_LOGIN, "rol": "admin"}
            flash("Xush kelibsiz, Admin!", "muvaffaqiyat")
            return redirect(url_for("bosh_sahifa"))

        email_l = email.lower()
        f = foydalanuvchilar_yuklash()
        user = f["faollar"].get(email_l)
        if user and check_password_hash(user["parol"], parol):
            session["foydalanuvchi"] = {"ism": user["ism"], "email": email_l, "rol": "user"}
            flash(f"Xush kelibsiz, {user['ism']}!", "muvaffaqiyat")
            return redirect(url_for("bosh_sahifa"))
        flash("Email yoki parol noto'g'ri", "xato")
    return render_template_string(HTML, sahifa="kirish", foydalanuvchi=joriy_foydalanuvchi())


@app.route("/chiqish")
def chiqish():
    session.clear()
    return redirect(url_for("bosh_sahifa"))


@app.route("/foydalanuvchilar")
def foydalanuvchilar_sahifa():
    if not admin_mi():
        flash("Bu sahifa faqat admin uchun", "xato")
        return redirect(url_for("bosh_sahifa"))
    f = foydalanuvchilar_yuklash()
    royxat = []
    for email, malumot in f["faollar"].items():
        royxat.append({
            "email": email,
            "ism": malumot.get("ism", ""),
            "familiya": malumot.get("familiya", ""),
            "tel": malumot.get("tel", ""),
        })
    royxat.sort(key=lambda u: u["email"])
    return render_template_string(HTML, sahifa="foydalanuvchilar", foydalanuvchilar=royxat,
                                   foydalanuvchi=joriy_foydalanuvchi())


@app.route("/foydalanuvchi/yaratish", methods=["POST"])
def foydalanuvchi_yaratish():
    if not admin_mi():
        flash("Bu amal faqat admin uchun", "xato")
        return redirect(url_for("bosh_sahifa"))
    email = request.form.get("email", "").lower().strip()
    ism = request.form.get("ism", "").strip()
    familiya = request.form.get("familiya", "").strip()
    tel = request.form.get("tel", "").strip()
    parol = request.form.get("parol", "")
    tel_sozlangan = tel_norm(tel) if tel else ""
    if not email or not ism or not parol:
        flash("Email, ism va parol to'ldirilishi shart", "xato")
        return redirect(url_for("foydalanuvchilar_sahifa"))
    if tel and not tel_sozlangan:
        flash("Telefon raqam +998 (xx) xxx-xx-xx formatida bo'lishi kerak", "xato")
        return redirect(url_for("foydalanuvchilar_sahifa"))
    if len(parol) < 6:
        flash("Parol kamida 6 belgidan iborat bo'lishi kerak", "xato")
        return redirect(url_for("foydalanuvchilar_sahifa"))
    if email == ADMIN_LOGIN:
        flash("Bu email admin uchun band, boshqa email tanlang", "xato")
        return redirect(url_for("foydalanuvchilar_sahifa"))
    f = foydalanuvchilar_yuklash()
    if email in f["faollar"] or email in f["tasdiqlanmaganlar"]:
        flash("Bu email allaqachon mavjud", "xato")
        return redirect(url_for("foydalanuvchilar_sahifa"))
    f["faollar"][email] = {
        "ism": ism,
        "familiya": familiya,
        "tel": tel_sozlangan,
        "parol": generate_password_hash(parol),
    }
    foydalanuvchilar_saqlash(f)
    flash(f"Foydalanuvchi yaratildi: {email} (login: {email}, parol: kiritilgan parol)", "muvaffaqiyat")
    return redirect(url_for("foydalanuvchilar_sahifa"))


@app.route("/foydalanuvchi/tahrirlash/<email>", methods=["GET", "POST"])
def foydalanuvchi_tahrirlash(email):
    if not admin_mi():
        flash("Faqat admin foydalanuvchilarni tahrirlashi mumkin", "xato")
        return redirect(url_for("bosh_sahifa"))
    email = email.lower()
    f = foydalanuvchilar_yuklash()
    if email not in f["faollar"]:
        flash("Foydalanuvchi topilmadi", "xato")
        return redirect(url_for("foydalanuvchilar_sahifa"))
    if request.method == "POST":
        ism = request.form.get("ism", "").strip()
        familiya = request.form.get("familiya", "").strip()
        tel = request.form.get("tel", "").strip()
        yangi_parol = request.form.get("parol", "")
        tel_sozlangan = tel_norm(tel) if tel else ""
        if not ism or not familiya:
            flash("Ism va familiya to'ldirilishi shart", "xato")
            return redirect(url_for("foydalanuvchi_tahrirlash", email=email))
        if tel and not tel_sozlangan:
            flash("Telefon raqam +998 (xx) xxx-xx-xx formatida bo'lishi kerak", "xato")
            return redirect(url_for("foydalanuvchi_tahrirlash", email=email))
        f["faollar"][email]["ism"] = ism
        f["faollar"][email]["familiya"] = familiya
        f["faollar"][email]["tel"] = tel_sozlangan
        if yangi_parol:
            if len(yangi_parol) < 6:
                flash("Yangi parol kamida 6 belgidan iborat bo'lishi kerak", "xato")
                return redirect(url_for("foydalanuvchi_tahrirlash", email=email))
            f["faollar"][email]["parol"] = generate_password_hash(yangi_parol)
        foydalanuvchilar_saqlash(f)
        flash("Foydalanuvchi ma'lumotlari saqlandi", "muvaffaqiyat")
        return redirect(url_for("foydalanuvchilar_sahifa"))
    return render_template_string(HTML, sahifa="foydalanuvchi_tahrirlash",
                                   tahrir_email=email,
                                   tahrir_malumot=f["faollar"][email],
                                   foydalanuvchi=joriy_foydalanuvchi())


@app.route("/admin/boshqaruv", methods=["GET", "POST"])
def admin_boshqaruv():
    if not admin_mi():
        flash("Bu sahifa faqat admin uchun", "xato")
        return redirect(url_for("bosh_sahifa"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if title:
            data = site_settings_yuklash()
            data["title"] = title
            site_settings_saqlash(data)
            flash("Sahifa sarlavhasi saqlandi", "muvaffaqiyat")

        file_item = request.files.get("homepage_image")
        replace_filename = request.form.get("replace_filename", "").strip()
        if file_item and file_item.filename:
            rasm_turi = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
            nomi = secure_filename(file_item.filename)
            if os.path.splitext(nomi)[1].lower() not in rasm_turi:
                flash("Faqat rasm fayllari yuklanadi", "xato")
                return redirect(url_for("admin_boshqaruv"))
            papka = _get_texnikum_dir()
            target_name = secure_filename(replace_filename) if replace_filename else nomi
            target_path = os.path.join(papka, target_name)
            file_item.save(target_path)
            flash("Rasm yuklandi", "muvaffaqiyat")

        return redirect(url_for("admin_boshqaruv"))

    return render_template_string(HTML, sahifa="admin_boshqaruv",
                                   foydalanuvchi=joriy_foydalanuvchi(),
                                   texnikum_rasmlari=texnikum_rasmlari())


@app.route("/admin/rsm/ochirish", methods=["POST"])
def admin_rasm_ochirish():
    if not admin_mi():
        flash("Bu amal faqat admin uchun", "xato")
        return redirect(url_for("bosh_sahifa"))

    filename = secure_filename(request.form.get("filename", "").strip())
    if not filename:
        flash("Rasm nomi topilmadi", "xato")
        return redirect(url_for("admin_boshqaruv"))

    target = os.path.join(_get_texnikum_dir(), filename)
    if os.path.exists(target):
        os.remove(target)
        flash(f"'{filename}' rasm o'chirildi", "muvaffaqiyat")
    else:
        flash("Rasm topilmadi", "xato")
    return redirect(url_for("admin_boshqaruv"))


@app.route("/fanlar")
def fanlar_sahifa():
    if not admin_mi():
        flash("Bu sahifa faqat admin uchun", "xato")
        return redirect(url_for("bosh_sahifa"))
    malumot = fanlar_yuklash()
    return render_template_string(HTML, sahifa="fanlar", sinflar=malumot["sinflar"],
                                  fanlar=malumot["fanlar"], foydalanuvchi=joriy_foydalanuvchi())


def admin_natija(muvaffaqiyat_xabari, xato=None, holat=200):
    """AJAX so'roviga JSON, oddiy brauzer so'roviga esa /fanlar sahifasiga qaytaradi.

    Shu bilan forma JavaScript o'chirilgan holatda ham ishlayveradi."""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if xato:
            return jsonify({"xato": xato}), holat
        return jsonify({"muvaffaqiyat": True})
    flash(xato or muvaffaqiyat_xabari, "xato" if xato else "muvaffaqiyat")
    return redirect(url_for("fanlar_sahifa"))


def admin_ruxsat():
    if admin_mi():
        return None
    return admin_natija("", xato="Bu amal faqat admin uchun", holat=403)


@app.route("/fanlar/qoshish", methods=["POST"])
def fan_qoshish():
    """Bitta fan qo'shadi. Fan ro'yxati barcha sinflar uchun umumiy."""
    ruxsat = admin_ruxsat()
    if ruxsat:
        return ruxsat
    fan = request.form.get("fan", "").strip()
    if not fan:
        return admin_natija("", xato="Fan nomini kiriting", holat=400)
    malumot = fanlar_yuklash()
    if any(x.strip().lower() == fan.lower() for x in malumot["fanlar"]):
        return admin_natija("", xato=f"'{fan}' fani allaqachon mavjud", holat=400)
    malumot["fanlar"].append(fan)
    fanlar_saqlash(malumot)
    return admin_natija(f"'{fan}' fani barcha sinflar uchun qo'shildi")


@app.route("/sinf/qoshish", methods=["POST"])
def sinf_qoshish():
    ruxsat = admin_ruxsat()
    if ruxsat:
        return ruxsat
    sinf = request.form.get("sinf", "").strip()
    if not sinf:
        return admin_natija("", xato="Sinf nomini kiriting", holat=400)
    malumot = fanlar_yuklash()
    if sinf in malumot["sinflar"]:
        return admin_natija("", xato="Bu sinf allaqachon mavjud", holat=400)
    malumot["sinflar"].append(sinf)
    fanlar_saqlash(malumot)
    return admin_natija(f"'{sinf}' sinfi qo'shildi")


@app.route("/sinf/ochirish", methods=["POST"])
def sinf_ochirish():
    ruxsat = admin_ruxsat()
    if ruxsat:
        return ruxsat
    sinf = request.form.get("sinf", "").strip()
    malumot = fanlar_yuklash()
    if sinf not in malumot["sinflar"]:
        return admin_natija("", xato="Sinf topilmadi", holat=404)
    m = kitoblar_yuklash()
    kitoblar_soni = sum(
        1 for kitoblar in m.values() for k in kitoblar if (k.get("sinf") or "") == sinf
    )
    if kitoblar_soni:
        return admin_natija("", xato=(
            f"Bu sinfga {kitoblar_soni} ta kitob biriktirilgan. "
            "Avval kitoblarni boshqa sinfga o'tkazing."
        ), holat=400)
    malumot["sinflar"].remove(sinf)
    fanlar_saqlash(malumot)
    return admin_natija(f"'{sinf}' sinfi o'chirildi")


@app.route("/sinf/tahrirlash", methods=["POST"])
def sinf_tahrirlash():
    """Sinfni qayta nomlaydi va kitoblardagi sinf nomini ham yangilaydi."""
    ruxsat = admin_ruxsat()
    if ruxsat:
        return ruxsat
    eski = request.form.get("eski_sinf", "").strip()
    yangi = request.form.get("yangi_sinf", "").strip()
    malumot = fanlar_yuklash()
    if eski not in malumot["sinflar"]:
        return admin_natija("", xato="Sinf topilmadi", holat=404)
    if not yangi:
        return admin_natija("", xato="Yangi sinf nomini kiriting", holat=400)
    if yangi != eski and yangi in malumot["sinflar"]:
        return admin_natija("", xato=f"'{yangi}' sinfi allaqachon mavjud", holat=400)
    if yangi != eski:
        malumot["sinflar"][malumot["sinflar"].index(eski)] = yangi
        fanlar_saqlash(malumot)
        m = kitoblar_yuklash()
        o_zgardi = False
        for kitoblar in m.values():
            for kitob in kitoblar:
                if kitob.get("sinf") == eski:
                    kitob["sinf"] = yangi
                    o_zgardi = True
        if o_zgardi:
            kitoblar_saqlash(m)
    return admin_natija(f"'{eski}' sinfi '{yangi}' deb yangilandi")


@app.route("/fan/tahrirlash", methods=["POST"])
def fan_tahrirlash():
    """Fan nomini qayta nomlaydi. Fanlar umumiy bo'lgani uchun barcha
    sinflardagi kitoblar ham yangilanadi."""
    ruxsat = admin_ruxsat()
    if ruxsat:
        return ruxsat
    eski = request.form.get("eski_fan", "").strip()
    yangi = request.form.get("yangi_fan", "").strip()
    malumot = fanlar_yuklash()
    if eski not in malumot["fanlar"]:
        return admin_natija("", xato="Fan topilmadi", holat=404)
    if not yangi:
        return admin_natija("", xato="Yangi fan nomini kiriting", holat=400)
    if yangi != eski and any(x.strip().lower() == yangi.lower() for x in malumot["fanlar"]):
        return admin_natija("", xato=f"'{yangi}' fani allaqachon mavjud", holat=400)
    if yangi != eski:
        malumot["fanlar"][malumot["fanlar"].index(eski)] = yangi
        fanlar_saqlash(malumot)
        m = kitoblar_yuklash()
        o_zgardi = False
        for kitoblar in m.values():
            for kitob in kitoblar:
                if kitob.get("fan") == eski:
                    kitob["fan"] = yangi
                    o_zgardi = True
        if o_zgardi:
            kitoblar_saqlash(m)
    return admin_natija(f"'{eski}' fani '{yangi}' deb yangilandi")


@app.route("/fanlar/ochirish", methods=["POST"])
def fan_ochirish():
    """Fan ro'yxatidan o'chiradi. Fan umumiy bo'lgani uchun hamma sinflardan
    o'chadi, lekin kitoblardagi `fan` maydoni saqlanib qoladi."""
    ruxsat = admin_ruxsat()
    if ruxsat:
        return ruxsat
    fan = request.form.get("fan", "").strip()
    malumot = fanlar_yuklash()
    if fan not in malumot["fanlar"]:
        return admin_natija("", xato="Bunday fan topilmadi", holat=404)
    malumot["fanlar"].remove(fan)
    fanlar_saqlash(malumot)
    return admin_natija(f"'{fan}' fani barcha sinflardan o'chirildi")


@app.route("/qoshish", methods=["GET", "POST"])
def qoshish():
    if not joriy_foydalanuvchi():
        flash("Kitob qo'shish uchun tizimga kiring", "xato")
        return redirect(url_for("kirish"))
    if request.method == "POST":
        bolim = request.form.get("bolim", "").strip()
        sinf = request.form.get("sinf", "").strip()
        fan = request.form.get("fan", "").strip()
        nomi = request.form.get("nomi", "").strip()
        muallif = request.form.get("muallif", "").strip()
        yili = request.form.get("yili", "").strip()
        telegram_havola = request.form.get("telegram_havola", "").strip()
        google_drive_havola = request.form.get("google_drive_havola", "").strip()
        if bolim not in BO_LIMLAR:
            flash("Bo'limni tanlang", "xato")
            return redirect(url_for("qoshish"))
        fanlar = fanlar_yuklash()
        if not sinf or sinf not in fanlar["sinflar"]:
            flash("Sinfni tanlang", "xato")
            return redirect(url_for("qoshish"))
        if not fan or fan not in fanlar["fanlar"]:
            flash("Fanni tanlang", "xato")
            return redirect(url_for("qoshish"))
        if not telegram_havola and not google_drive_havola:
            flash("Telegram yoki Google Drive havolasini kiriting", "xato")
            return redirect(url_for("qoshish"))
        if telegram_havola and not telegram_havolasi_mi(telegram_havola):
            flash("Telegram havolasi https://t.me/... yoki https://telegram.me/... ko'rinishida bo'lishi kerak", "xato")
            return redirect(url_for("qoshish"))
        if google_drive_havola and not google_drive_havolasi_mi(google_drive_havola):
            flash("Google Drive havolasi https://drive.google.com/file/d/ID/... ko'rinishida bo'lishi kerak", "xato")
            return redirect(url_for("qoshish"))
        m = kitoblar_yuklash()
        muqova_nom = ""
        f = request.files.get("muqova")
        if f and f.filename:
            rasm = f.read()
            if len(rasm) > MAX_RASM_HAJM:
                flash("Rasm hajmi 0.3 MB dan katta bo'lmasligi kerak", "xato")
                return redirect(url_for("qoshish"))
            muqova_nom = secure_filename(f.filename)
            with open(os.path.join(app.config["COVER_FOLDER"], muqova_nom), "wb") as out:
                out.write(rasm)
        m.setdefault(bolim, [])
        m[bolim].append({
            "nomi": nomi,
            "muallif": muallif,
            "yili": yili,
            "muqova": muqova_nom,
            "telegram_havola": telegram_havola,
            "google_drive_havola": google_drive_havola,
            "tomonidan": joriy_foydalanuvchi()["email"],
            "sinf": sinf,
            "fan": fan,
        })
        kitoblar_saqlash(m)
        flash("Kitob qo'shildi!", "muvaffaqiyat")
        return redirect(url_for("bosh_sahifa", _anchor=bolim_slug(bolim)))
    malumot = fanlar_yuklash()
    return render_template_string(HTML, sahifa="qoshish", bolimlar=BO_LIMLAR,
                                  sinflar=malumot["sinflar"], fanlar=malumot["fanlar"],
                                  foydalanuvchi=joriy_foydalanuvchi())


@app.route("/tahrirlash/<bolim>/<int:idx>", methods=["GET", "POST"])
def tahrirlash(bolim, idx):
    user = joriy_foydalanuvchi()
    if not user:
        return redirect(url_for("kirish"))
    m = kitoblar_yuklash()
    kitob = kitobni_topish(m, bolim, idx)
    if kitob is None:
        flash("Kitob topilmadi", "xato")
        return redirect(url_for("bosh_sahifa"))
    if not admin_mi() and kitob.get("tomonidan") != user["email"]:
        flash("Faqat o'zingiz yuklagan kitobni tahrirlashingiz mumkin", "xato")
        return redirect(url_for("bosh_sahifa"))
    if request.method == "POST":
        nomi = request.form.get("nomi", "").strip()
        muallif = request.form.get("muallif", "").strip()
        yili = request.form.get("yili", "").strip()
        sinf = request.form.get("sinf", "").strip()
        fan = request.form.get("fan", "").strip()
        telegram_havola = request.form.get("telegram_havola", "").strip()
        google_drive_havola = request.form.get("google_drive_havola", "").strip()
        fanlar = fanlar_yuklash()
        if sinf and sinf not in fanlar["sinflar"]:
            flash("Bunday sinf yo'q", "xato")
            return redirect(url_for("tahrirlash", bolim=bolim, idx=idx))
        if fan and fan not in fanlar["fanlar"]:
            flash("Bunday fan ro'yxatda yo'q", "xato")
            return redirect(url_for("tahrirlash", bolim=bolim, idx=idx))
        if not telegram_havola and not google_drive_havola:
            flash("Telegram yoki Google Drive havolasini kiriting", "xato")
            return redirect(url_for("tahrirlash", bolim=bolim, idx=idx))
        if telegram_havola and not telegram_havolasi_mi(telegram_havola):
            flash("Telegram havolasi https://t.me/... yoki https://telegram.me/... ko'rinishida bo'lishi kerak", "xato")
            return redirect(url_for("tahrirlash", bolim=bolim, idx=idx))
        if google_drive_havola and not google_drive_havolasi_mi(google_drive_havola):
            flash("Google Drive havolasi https://drive.google.com/file/d/ID/... ko'rinishida bo'lishi kerak", "xato")
            return redirect(url_for("tahrirlash", bolim=bolim, idx=idx))
        f = request.files.get("muqova")
        if f and f.filename:
            rasm = f.read()
            if len(rasm) > MAX_RASM_HAJM:
                flash("Rasm hajmi 0.3 MB dan katta bo'lmasligi kerak", "xato")
                return redirect(url_for("tahrirlash", bolim=bolim, idx=idx))
            eski_muqova = m[bolim][idx].get("muqova")
            yangi_muqova = secure_filename(f.filename)
            with open(os.path.join(app.config["COVER_FOLDER"], yangi_muqova), "wb") as out:
                out.write(rasm)
            m[bolim][idx]["muqova"] = yangi_muqova
            if eski_muqova and eski_muqova != yangi_muqova:
                fayllarni_tozalash({"muqova": eski_muqova}, m)
        m[bolim][idx]["nomi"] = nomi
        m[bolim][idx]["muallif"] = muallif
        m[bolim][idx]["yili"] = yili
        m[bolim][idx]["telegram_havola"] = telegram_havola
        m[bolim][idx]["google_drive_havola"] = google_drive_havola
        m[bolim][idx]["sinf"] = sinf
        m[bolim][idx]["fan"] = fan
        kitoblar_saqlash(m)
        flash("Kitob saqlandi", "muvaffaqiyat")
        return redirect(url_for("bosh_sahifa", _anchor=bolim_slug(bolim)))
    malumot = fanlar_yuklash()
    return render_template_string(HTML, sahifa="tahrirlash", bolimlar=BO_LIMLAR,
                                  kitob=kitob, foydalanuvchi=user,
                                  sinflar=malumot["sinflar"], fanlar=malumot["fanlar"])


@app.route("/ochirish/<bolim>/<int:idx>", methods=["POST"])
def ochirish(bolim, idx):
    user = joriy_foydalanuvchi()
    if not user:
        return redirect(url_for("kirish"))
    m = kitoblar_yuklash()
    kitob = kitobni_topish(m, bolim, idx)
    if kitob is None:
        flash("Kitob topilmadi", "xato")
        return redirect(url_for("bosh_sahifa"))
    if not admin_mi() and kitob.get("tomonidan") != user["email"]:
        flash("Faqat o'zingiz yuklagan kitobni o'chirishingiz mumkin", "xato")
        return redirect(url_for("bosh_sahifa"))
    m[bolim].pop(idx)
    kitoblar_saqlash(m)
    fayllarni_tozalash(kitob, m)
    yetim_fayllarni_tozalash(m)
    return redirect(url_for("bosh_sahifa", _anchor=bolim_slug(bolim)))


@app.route("/ochirish-id/<kitob_id>", methods=["POST"])
def ochirish_id(kitob_id):
    """Kitobni bo'limdagi o'zgaruvchan indeks emas, barqaror ID orqali o'chiradi."""
    user = joriy_foydalanuvchi()
    if not user:
        return redirect(url_for("kirish"))
    m = kitoblar_yuklash()
    topilma = kitobni_id_bilan_topish(m, kitob_id)
    if topilma is None:
        flash("Kitob topilmadi", "xato")
        return redirect(url_for("bosh_sahifa"))
    bolim, idx, kitob = topilma
    if not admin_mi() and kitob.get("tomonidan") != user["email"]:
        flash("Faqat o'zingiz yuklagan kitobni o'chirishingiz mumkin", "xato")
        return redirect(url_for("bosh_sahifa"))
    m[bolim].pop(idx)
    kitoblar_saqlash(m)
    fayllarni_tozalash(kitob, m)
    yetim_fayllarni_tozalash(m)
    return redirect(url_for("bosh_sahifa", _anchor=bolim_slug(bolim)))


@app.route("/ochish/<bolim>/<int:idx>")
def ochish(bolim, idx):
    kitob = kitobni_topish(kitoblar_yuklash(), bolim, idx)
    if kitob is None:
        flash("Kitob topilmadi", "xato")
        return redirect(url_for("bosh_sahifa"))
    if kitob.get("google_drive_havola"):
        return render_template_string(HTML, sahifa="ochish_drive", bolimlar=BO_LIMLAR,
                                       kitob=kitob, foydalanuvchi=joriy_foydalanuvchi(),
                                       drive_preview=google_drive_preview_url(kitob.get("google_drive_havola")),
                                       drive_download=google_drive_yuklab_url(kitob.get("google_drive_havola")))
    if kitob.get("telegram_havola"):
        return redirect(kitob["telegram_havola"])
    if kitob.get("fayl"):
        return render_template_string(HTML, sahifa="ochish", bolimlar=BO_LIMLAR,
                                       kitob=kitob, foydalanuvchi=joriy_foydalanuvchi())
    flash("Bu kitob uchun o'qish shabloni mavjud emas", "xato")
    return redirect(url_for("bosh_sahifa"))


if __name__ == "__main__":
    debug_yoqilgan = os.getenv("FLASK_DEBUG", "0") == "1"
    if debug_yoqilgan:
        print("OGOHLANTIRISH: Debug rejimi yoqilgan. Buni faqat lokal ishlab chiqishda ishlating, "
              "hech qachon production/internetga ochiq serverda yoqmang.")
    app.run(debug=debug_yoqilgan)