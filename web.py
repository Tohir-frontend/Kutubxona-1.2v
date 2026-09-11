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
import string
import uuid
from urllib.parse import urlparse

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

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

csrf = CSRFProtect(app)

DATA_FILE = os.path.join(os.path.dirname(__file__), "kutubxona.json")
USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")

BO_LIMLAR = [
    "Umumta'lim fanlar",
    "Umumkasbiy fanlar",
    "Maxsus fanlar",
    "Badiiy adabiyotlar",
]

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["COVER_FOLDER"], exist_ok=True)


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


def texnikum_rasmlari():
    papka = os.path.join(os.path.dirname(__file__), "static", "texnikum")
    if not os.path.exists(papka):
        return []
    rasm_turlari = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    tartib = {"texnikum 1": 0, "kitob": 1, "texnikum 2": 2}
    rasmlar = [f for f in os.listdir(papka) if os.path.splitext(f)[1].lower() in rasm_turlari]
    return sorted(
        rasmlar,
        key=lambda fayl: tartib.get(os.path.splitext(fayl)[0].lower(), len(tartib)),
    )


def kod_yaratish():
    return "".join(random.choices(string.digits, k=6))


def email_yuborish(manzil, kod):
    """Gmail SMTP orqali tasdiqlash kodini yuboradi"""
    import smtplib
    from email.mime.text import MIMEText

    gmail = os.getenv("GMAIL")
    parol = os.getenv("APP_PASSWORD")

    if not gmail or not parol or "your_" in gmail:
        print(f"[DEMO] {manzil} -> tasdiqlash kodi: {kod}")
        return False

    msg = MIMEText(
        f"Xorazm Pedagogika Texnikumi Kutubxonasi\n\n"
        f"Sizning tasdiqlash kodingiz: {kod}\n\n"
        f"Agar bu siz bo'lsangiz, kodni kiriting. Aks holda e'tibor bermang."
    )
    msg["Subject"] = "Kutubxona - Tasdiqlash kodi"
    msg["From"] = gmail
    msg["To"] = manzil

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
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


HTML = """
<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5">
<meta name="csrf-token" content="{{ csrf_token() }}">
<title>Xorazm Pedagogika Texnikumi Kutubxonasi</title>
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
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  .nav { background: #fff; padding: 15px; border-radius: 10px; margin-bottom: 20px; text-align: center; position: sticky; top: 10px; z-index: 500; box-shadow: 0 4px 12px rgba(0,0,0,0.25); }
  .nav a { color: #1a3a6e; margin: 0 12px; text-decoration: none; font-weight: bold; }
  .flash { padding: 12px; border-radius: 6px; margin: 10px auto; max-width: 600px; text-align: center; }
  .flash-muvaffaqiyat { background: #d4edda; color: #155724; }
  .flash-xato { background: #f8d7da; color: #721c24; }
  .auth-form { background: #fff; padding: 30px; border-radius: 10px; max-width: 450px; margin: 30px auto; }
  .auth-form h2 { text-align: center; color: #1a3a6e; margin-top: 0; }
  .auth-form input, .auth-form select { width: 100%; padding: 10px; margin: 8px 0; border: 1px solid #ddd; border-radius: 6px; }
  .auth-form button { width: 100%; background: #1a3a6e; color: white; padding: 12px; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; }
  .auth-link { text-align: center; margin-top: 15px; }
  .auth-link a { color: #1a3a6e; }
  .bolim-sarlavha { color: white; background: rgba(0,0,0,0.3); padding: 12px; border-radius: 10px; margin: 20px 0 10px; }
  .kitoblar { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 20px; }
  .karta { background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.15); transition: transform 0.2s; }
  .karta:hover { transform: translateY(-5px); }
  .muqova { position: relative; width: 100%; height: 280px; background: linear-gradient(135deg, #1a3a6e, #2c5aa0); display: flex; align-items: center; justify-content: center; color: white; font-size: 48px; font-weight: bold; overflow: hidden }
  .muqova img { width: 100%; height: 100%; object-fit: contain }
  .yulduzcha { position: absolute; top: 8px; right: 8px; width: 34px; height: 34px; border-radius: 50%; background: rgba(0,0,0,0.45); display: flex; align-items: center; justify-content: center; font-size: 20px; text-decoration: none; color: #fff; line-height: 1; transition: transform 0.15s, background 0.15s; }
  .yulduzcha:hover { transform: scale(1.15); background: rgba(0,0,0,0.65); }
  .yulduzcha.faol { color: #ffc107; }
  .karta-tana { padding: 15px; }
  .karta-tana h3 { margin: 0 0 8px; color: #1a3a6e; font-size: 16px; }
  .karta-tana p { margin: 4px 0; color: #666; font-size: 14px; }
  .karta-tana .qator { display: flex; justify-content: space-between; gap: 8px; }
  .karta-tana .yuklagan { font-size: 12px; color: #999; font-style: italic; }
  .tugmalar { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
  .btn { flex: 1; min-width: 70px; padding: 7px; border: none; border-radius: 6px; cursor: pointer; text-decoration: none; text-align: center; font-size: 12px; color: white; }
  .btn-ochish { background: #1a3a6e; }
  .btn-yuklash { background: #28a745; }
  .btn-tahrirlash { background: #ffc107; color: #333; }
  .btn-ochirish { background: #dc3545; }
  form { background: #fff; padding: 20px; border-radius: 10px; margin: 20px 0; }
  form input, form select { width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 6px; }
  form button { background: #1a3a6e; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }
  .qidiruv-form { display: flex; gap: 10px; }
  .qidiruv-form input { flex: 1; }
  .reader { background: #fff; padding: 20px; border-radius: 10px; text-align: center; }
  .reader iframe { width: 100%; height: 600px; border: none; border-radius: 8px; }

  .btn-qaytish { display: inline-flex; align-items: center; gap: 10px; background: linear-gradient(135deg, #ff7a45, #ff4d4d); color: #fff; border: none; padding: 12px 22px; border-radius: 30px; font-size: 15px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 14px rgba(255, 77, 77, 0.45); transition: transform 0.15s, box-shadow 0.15s; }
  .btn-qaytish:hover { transform: translateY(-2px) scale(1.03); box-shadow: 0 6px 18px rgba(255, 77, 77, 0.6); }
  .btn-qaytish:active { transform: translateY(0) scale(0.98); }
  .btn-qaytish .btn-qaytish-ok { font-size: 18px; }
  .btn-qaytish .btn-qaytish-esc { background: rgba(255,255,255,0.25); border: 1px solid rgba(255,255,255,0.6); border-radius: 6px; padding: 2px 8px; font-size: 12px; letter-spacing: 0.5px; }

  .karusel { background: rgba(255,255,255,0.05); border-radius: 12px; overflow: hidden; margin-bottom: 25px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
  .karusel-track { display: flex; transition: transform 2s ease-in-out; }
  .karusel-slide { min-width: 100%; display: flex; align-items: center; justify-content: center; background: #000 }
  .karusel-slide img { width: 100%; height: 400px; object-fit: contain; display: block }

  @media (max-width: 700px) {
    .header-inner { flex-direction: column; align-items: center; gap: 8px; text-align: center; padding: 12px; }
    .header h1 { font-size: 18px; }
    .header-right { justify-content: center; }
    .container { padding: 10px; }
    .nav { padding: 10px; margin-bottom: 14px; }
    .nav a { margin: 0 6px; font-size: 14px; display: inline-block; }
    .bolim-sarlavha { padding: 10px; margin: 14px 0 8px; }
    .bolim-sarlavha h2 { font-size: 17px; }
    .kitoblar { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }
    .muqova { height: 180px; font-size: 34px; }
    .yulduzcha { width: 28px; height: 28px; font-size: 16px; }
    .karta-tana { padding: 10px; }
    .karta-tana h3 { font-size: 14px; }
    .karta-tana p { font-size: 12px; }
    .btn { font-size: 11px; padding: 6px; min-width: 60px; }
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

  @media (max-width: 420px) {
    .kitoblar { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
    .muqova { height: 140px; font-size: 26px; }
    #search-status { display: none; }
  }
</style>
</head>
<body>
<div class="header">
  <div class="header-inner">
    <h1>Xorazm Pedagogika Texnikumi — Kutubxona</h1>
    <div class="header-right">
      {% if foydalanuvchi %}
        <span>Salom, <b>{{ foydalanuvchi.ism }}</b>!</span>
        <a class="btn-chiqish" href="{{ url_for('chiqish') }}">⏻ Chiqish</a>
      {% else %}
        <a href="{{ url_for('kirish') }}">Kirish</a>
        <a href="{{ url_for('royxat') }}">Ro'yxatdan o'tish</a>
      {% endif %}
    </div>
  </div>
</div>
<div class="container">

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

    {% for bolim in bolimlar %}
      <div class="bolim-sarlavha" id="{{ bolim_slug(bolim) }}">
        <h2 style="margin:0">{{ bolim }} <small>({{ malumot[bolim]|length }} ta)</small></h2>
      </div>
      {% if malumot[bolim] %}
      <div class="kitoblar">
        {% for kitob in malumot[bolim] %}
        <div class="karta">
          <div class="muqova">
            {% if kitob.muqova %}
              <img src="{{ url_for('static', filename='covers/' + kitob.muqova) }}" alt="">
            {% else %}
              {{ kitob.nomi[0]|upper }}
            {% endif %}
            {% if foydalanuvchi %}
              <a class="yulduzcha {{ 'faol' if kitob.id in sevimlilar else '' }}" href="#"
                 data-url="{{ url_for('sevimli_belgilash', bolim=bolim, idx=loop.index0) }}"
                 onclick="return sevimliBosildi(this, event)"
                 title="Sevimlilarga qo'shish/olib tashlash">{{ '★' if kitob.id in sevimlilar else '☆' }}</a>
            {% endif %}
          </div>
          <div class="karta-tana">
            <h3>{{ kitob.nomi }}</h3>
            <p class="qator"><span>{{ kitob.muallif }}</span><span>{{ kitob.yili }}</span></p>
            <p class="qator yuklagan"><span>{% if kitob.telegram_havola %}Telegram kanal{% elif kitob.fayl %}MB: {{ fayl_hajmi(kitob.fayl) }}{% endif %}</span><span>{{ foydalanuvchi_ismi(kitob.tomonidan) }}</span></p>
            <div class="tugmalar">
              {% if kitob.telegram_havola %}
                <a class="btn btn-ochish" href="{{ kitob.telegram_havola }}" target="_blank" rel="noopener">O'qish</a>
                <a class="btn btn-yuklash" href="{{ kitob.telegram_havola }}" target="_blank" rel="noopener">Telegramdan yuklash</a>
              {% elif kitob.fayl %}
                <a class="btn btn-ochish" href="{{ url_for('ochish', bolim=bolim, idx=loop.index0) }}">O'qish</a>
                <a class="btn btn-yuklash" href="{{ url_for('static', filename='files/' + kitob.fayl) }}" download>Yuklab</a>
              {% endif %}
              {% if foydalanuvchi and (kitob.tomonidan == foydalanuvchi.email or foydalanuvchi.rol == 'admin') %}
                <a class="btn btn-tahrirlash" href="{{ url_for('tahrirlash', bolim=bolim, idx=loop.index0) }}">Tahrir</a>
                <a class="btn btn-ochirish" href="{{ url_for('ochirish', bolim=bolim, idx=loop.index0) }}" onclick="return confirm('O\\'chirilsinmi?')">O'chirish</a>
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
    <form class="qidiruv-form" method="get">
      <input type="text" name="so_rov" placeholder="Kitob yoki muallif izlash..." value="{{ so_rov or '' }}">
      <button type="submit">Qidirish</button>
    </form>
    {% if natija %}
    <div class="kitoblar" style="margin-top:20px">
      {% for item in natija %}
      <div class="karta">
        <div class="muqova">
          {% if item.kitob.muqova %}
            <img src="{{ url_for('static', filename='covers/' + item.kitob.muqova) }}" alt="">
          {% else %}
            {{ item.kitob.nomi[0]|upper }}
          {% endif %}
          {% if foydalanuvchi %}
            <a class="yulduzcha {{ 'faol' if item.kitob.id in sevimlilar else '' }}" href="#"
               data-url="{{ url_for('sevimli_belgilash', bolim=item.bolim, idx=item.idx) }}"
               onclick="return sevimliBosildi(this, event)"
               title="Sevimlilarga qo'shish/olib tashlash">{{ '★' if item.kitob.id in sevimlilar else '☆' }}</a>
          {% endif %}
        </div>
        <div class="karta-tana">
          <small style="color:#1a3a6e">{{ item.bolim }}</small>
          <h3>{{ item.kitob.nomi }}</h3>
          <p>{{ item.kitob.muallif }} ({{ item.kitob.yili }})</p>
          <div class="tugmalar">
            {% if item.kitob.telegram_havola %}
              <a class="btn btn-ochish" href="{{ item.kitob.telegram_havola }}" target="_blank" rel="noopener">O'qish</a>
              <a class="btn btn-yuklash" href="{{ item.kitob.telegram_havola }}" target="_blank" rel="noopener">Telegramdan yuklash</a>
            {% elif item.kitob.fayl %}
              <a class="btn btn-ochish" href="{{ url_for('ochish', bolim=item.bolim, idx=item.idx) }}">O'qish</a>
              <a class="btn btn-yuklash" href="{{ url_for('static', filename='files/' + item.kitob.fayl) }}" download>Yuklab</a>
            {% endif %}
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
    {% elif so_rov %}
    <p style="color:white; text-align:center; margin-top:20px">Hech narsa topilmadi.</p>
    {% endif %}

  {% elif sahifa == 'sevimlilar' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
    <h2 style="color:white">★ Mening sevimlilarim</h2>
    {% if natija %}
    <div class="kitoblar" style="margin-top:20px">
      {% for item in natija %}
      <div class="karta" data-olib-tashlansin="1">
        <div class="muqova">
          {% if item.kitob.muqova %}
            <img src="{{ url_for('static', filename='covers/' + item.kitob.muqova) }}" alt="">
          {% else %}
            {{ item.kitob.nomi[0]|upper }}
          {% endif %}
          <a class="yulduzcha faol" href="#"
             data-url="{{ url_for('sevimli_belgilash', bolim=item.bolim, idx=item.idx) }}"
             onclick="return sevimliBosildi(this, event)"
             title="Sevimlilardan olib tashlash">★</a>
        </div>
        <div class="karta-tana">
          <small style="color:#1a3a6e">{{ item.bolim }}</small>
          <h3>{{ item.kitob.nomi }}</h3>
          <p class="qator"><span>{{ item.kitob.muallif }}</span><span>{{ item.kitob.yili }}</span></p>
          <div class="tugmalar">
            {% if item.kitob.telegram_havola %}
              <a class="btn btn-ochish" href="{{ item.kitob.telegram_havola }}" target="_blank" rel="noopener">O'qish</a>
              <a class="btn btn-yuklash" href="{{ item.kitob.telegram_havola }}" target="_blank" rel="noopener">Telegramdan yuklash</a>
            {% elif item.kitob.fayl %}
              <a class="btn btn-ochish" href="{{ url_for('ochish', bolim=item.bolim, idx=item.idx) }}">O'qish</a>
              <a class="btn btn-yuklash" href="{{ url_for('static', filename='files/' + item.kitob.fayl) }}" download>Yuklab</a>
            {% endif %}
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
      <select name="bolim">
        {% for bolim in bolimlar %}<option value="{{ bolim }}">{{ bolim }}</option>{% endfor %}
      </select>
      <label>Kitob nomi:</label>
      <input type="text" name="nomi" required>
      <label>Muallif:</label>
      <input type="text" name="muallif" required>
      <label>Yili:</label>
      <input type="text" name="yili" required>
      <label>Muqova rasmi:</label>
      <input type="file" name="muqova" accept="image/*">
      <label>Kitob fayli (PDF):</label>
      <input type="file" name="fayl" accept=".pdf">
      <label>Telegram kanalidagi kitob havolasi:</label>
      <input type="url" name="telegram_havola" placeholder="https://t.me/kanal/123" required>
      <small>Kitobni avval ochiq Telegram kanaliga yuklang, so'ng shu kanal yoki post havolasini kiriting.</small>
      <button type="submit">Saqlash</button>
    </form>

  {% elif sahifa == 'tahrirlash' %}
    <div class="nav"><a href="{{ url_for('bosh_sahifa') }}">Bosh sahifa</a></div>
    <form method="post" enctype="multipart/form-data">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Kitobni tahrirlash</h2>
      <label>Nomi:</label>
      <input type="text" name="nomi" value="{{ kitob.nomi }}" required>
      <label>Muallif:</label>
      <input type="text" name="muallif" value="{{ kitob.muallif }}" required>
      <label>Yili:</label>
      <input type="text" name="yili" value="{{ kitob.yili }}" required>
      <label>Yangi muqova (ixtiyoriy):</label>
      <input type="file" name="muqova" accept="image/*">
      <label>Yangi kitob fayli (PDF, ixtiyoriy):</label>
      <input type="file" name="fayl" accept=".pdf">
      <label>Telegram kanalidagi kitob havolasi:</label>
      <input type="url" name="telegram_havola" value="{{ kitob.telegram_havola or '' }}" placeholder="https://t.me/kanal/123" required>
      <small>Kitobning Telegram kanalidagi yangi havolasini kiriting.</small>
      <button type="submit">Saqlash</button>
    </form>

  {% elif sahifa == 'ochish' %}
    <div class="nav" style="text-align:left; background:transparent; padding:0; box-shadow:none; position:static">
      <button type="button" class="btn-qaytish" onclick="qaytish()">
        <span class="btn-qaytish-ok">←</span> Oldingi joyga qaytish
        <span class="btn-qaytish-esc">Esc</span>
      </button>
    </div>
    <div class="reader">
      <h2>{{ kitob.nomi }} — {{ kitob.muallif }}</h2>
      <p style="color:#666">PDF hajmi: {{ fayl_hajmi(kitob.fayl) }}</p>

      <div id="pdf-controls" style="background:#1a3a6e; padding:12px; border-radius:8px; margin:10px 0; display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:center; position:fixed; bottom:0; left:0; right:0; z-index:1000; box-shadow:0 -4px 12px rgba(0,0,0,0.2); color:white">
        <button onclick="prevPage()" class="pdf-btn">◄ Oldingi</button>
        <span style="display:flex; align-items:center; gap:5px">
          <input type="number" id="page-num" min="1" value="1" style="width:60px; padding:6px; text-align:center; border:1px solid #ddd; border-radius:4px">
          <span>/ <span id="page-count">0</span></span>
        </span>
        <button onclick="nextPage()" class="pdf-btn">Keyingi ►</button>
        <button onclick="zoomOut()" class="pdf-btn">−</button>
        <input type="range" id="zoom-slider" min="50" max="200" value="100" step="10" style="width:120px" oninput="setZoom(this.value)">
        <button onclick="zoomIn()" class="pdf-btn">+</button>
        <span id="zoom-val" style="min-width:45px">100%</span>
        <input type="text" id="search-text" placeholder="Matn izlash..." style="padding:6px; border:1px solid #ddd; border-radius:4px; width:160px">
        <button onclick="searchPDF()" class="pdf-btn">🔍 Izlash</button>
        <span id="search-status" style="font-size:12px; color:#666"></span>
        <a class="pdf-btn" href="{{ url_for('static', filename='files/' + kitob.fayl) }}" download style="background:#28a745; text-decoration:none">⬇ Yuklab</a>
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

  {% elif sahifa == 'kirish' %}
    <form class="auth-form" method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Tizimga kirish</h2>
      <input type="email" name="email" placeholder="Email" required>
      <input type="password" name="parol" placeholder="Parol" required>
      <button type="submit">Kirish</button>
      <div class="auth-link">Akkaunt yo'qmi? <a href="{{ url_for('royxat') }}">Ro'yxatdan o'tish</a></div>
    </form>

  {% elif sahifa == 'royxat' %}
    <form class="auth-form" method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Ro'yxatdan o'tish</h2>
      <input type="text" name="ism" placeholder="Ism" required>
      <input type="text" name="familiya" placeholder="Familiya" required>
      <input type="email" name="email" placeholder="Email" required>
      <input type="password" name="parol" placeholder="Parol (kamida 6 ta)" minlength="6" required>
      <button type="submit">Ro'yxatdan o'tish</button>
      <div class="auth-link">Akkauntingiz bormi? <a href="{{ url_for('kirish') }}">Kirish</a></div>
    </form>

  {% elif sahifa == 'tasdiqlash' %}
    <form class="auth-form" method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <h2>Email tasdiqlash</h2>
      <p style="text-align:center">{{ email }} manziliga yuborilgan 6 xonali kodni kiriting</p>
      <input type="text" name="kod" placeholder="123456" maxlength="6" required style="text-align:center; font-size:20px; letter-spacing:5px">
      <button type="submit">Tasdiqlash</button>
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
</body>
</html>
"""


@app.route("/")
def bosh_sahifa():
    user = joriy_foydalanuvchi()
    return render_template_string(HTML, sahifa="bosh", bolimlar=BO_LIMLAR,
                                   malumot=kitoblar_yuklash(),
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
                if so_rov in kitob["nomi"].lower() or so_rov in kitob["muallif"].lower():
                    natija.append({"bolim": bolim, "idx": idx, "kitob": kitob})
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


@app.route("/royxat", methods=["GET", "POST"])
def royxat():
    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        ism = request.form.get("ism", "").strip()
        familiya = request.form.get("familiya", "").strip()
        parol = request.form.get("parol", "")
        if not email or not ism or not familiya or not parol:
            flash("Barcha maydonlarni to'ldiring", "xato")
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
            "parol": generate_password_hash(parol),
            "kod": kod,
        }
        foydalanuvchilar_saqlash(f)
        yuborildi = email_yuborish(email, kod)
        admin_ga_royxat_xabari(ism, familiya, email, kod, yuborildi)
        session["tasdiqlash_email"] = email
        if eski_bor:
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
    return render_template_string(HTML, sahifa="tasdiqlash", email=email,
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


@app.route("/qoshish", methods=["GET", "POST"])
def qoshish():
    if not joriy_foydalanuvchi():
        flash("Kitob qo'shish uchun tizimga kiring", "xato")
        return redirect(url_for("kirish"))
    if request.method == "POST":
        bolim = request.form.get("bolim")
        nomi = request.form.get("nomi", "").strip()
        muallif = request.form.get("muallif", "").strip()
        yili = request.form.get("yili", "").strip()
        telegram_havola = request.form.get("telegram_havola", "").strip()
        if bolim not in BO_LIMLAR:
            flash("Noto'g'ri bo'lim tanlandi", "xato")
            return redirect(url_for("qoshish"))
        if not nomi or not muallif or not yili:
            flash("Kitob nomi, muallif va yili to'ldirilishi shart", "xato")
            return redirect(url_for("qoshish"))
        if not telegram_havolasi_mi(telegram_havola):
          flash("Telegram havolasi https://t.me/... yoki https://telegram.me/... ko'rinishida bo'lishi kerak", "xato")
          return redirect(url_for("qoshish"))
        m = kitoblar_yuklash()
        muqova_nom = ""
        fayl_nom = ""
        if "muqova" in request.files:
            f = request.files["muqova"]
            if f.filename:
                muqova_nom = secure_filename(f.filename)
                f.save(os.path.join(app.config["COVER_FOLDER"], muqova_nom))
        if "fayl" in request.files:
            f = request.files["fayl"]
            if f.filename:
                fayl_nom = secure_filename(f.filename)
                f.save(os.path.join(app.config["UPLOAD_FOLDER"], fayl_nom))
        m[bolim].append({
            "nomi": nomi,
            "muallif": muallif,
            "yili": yili,
            "muqova": muqova_nom,
            "fayl": fayl_nom,
            "telegram_havola": telegram_havola,
            "tomonidan": joriy_foydalanuvchi()["email"],
        })
        kitoblar_saqlash(m)
        flash("Kitob qo'shildi!", "muvaffaqiyat")
        return redirect(url_for("bosh_sahifa", _anchor=bolim_slug(bolim)))
    return render_template_string(HTML, sahifa="qoshish", bolimlar=BO_LIMLAR, foydalanuvchi=joriy_foydalanuvchi())


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
        telegram_havola = request.form.get("telegram_havola", "").strip()
        if not nomi or not muallif or not yili:
            flash("Kitob nomi, muallif va yili to'ldirilishi shart", "xato")
            return redirect(url_for("tahrirlash", bolim=bolim, idx=idx))
        if not telegram_havolasi_mi(telegram_havola):
          flash("Telegram havolasi https://t.me/... yoki https://telegram.me/... ko'rinishida bo'lishi kerak", "xato")
          return redirect(url_for("tahrirlash", bolim=bolim, idx=idx))
        m[bolim][idx]["nomi"] = nomi
        m[bolim][idx]["muallif"] = muallif
        m[bolim][idx]["yili"] = yili
        m[bolim][idx]["telegram_havola"] = telegram_havola
        if "muqova" in request.files:
            f = request.files["muqova"]
            if f.filename:
                nom = secure_filename(f.filename)
                f.save(os.path.join(app.config["COVER_FOLDER"], nom))
                m[bolim][idx]["muqova"] = nom
        if "fayl" in request.files:
            f = request.files["fayl"]
            if f.filename:
                nom = secure_filename(f.filename)
                f.save(os.path.join(app.config["UPLOAD_FOLDER"], nom))
                m[bolim][idx]["fayl"] = nom
        kitoblar_saqlash(m)
        return redirect(url_for("bosh_sahifa", _anchor=bolim_slug(bolim)))
    return render_template_string(HTML, sahifa="tahrirlash", bolimlar=BO_LIMLAR,
                                   kitob=kitob, foydalanuvchi=user)


@app.route("/ochirish/<bolim>/<int:idx>")
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
    return redirect(url_for("bosh_sahifa", _anchor=bolim_slug(bolim)))


@app.route("/ochish/<bolim>/<int:idx>")
def ochish(bolim, idx):
    kitob = kitobni_topish(kitoblar_yuklash(), bolim, idx)
    if kitob is None:
        flash("Kitob topilmadi", "xato")
        return redirect(url_for("bosh_sahifa"))
    return render_template_string(HTML, sahifa="ochish", bolimlar=BO_LIMLAR,
                                   kitob=kitob, foydalanuvchi=joriy_foydalanuvchi())


if __name__ == "__main__":
    debug_yoqilgan = os.getenv("FLASK_DEBUG", "0") == "1"
    if debug_yoqilgan:
        print("OGOHLANTIRISH: Debug rejimi yoqilgan. Buni faqat lokal ishlab chiqishda ishlating, "
              "hech qachon production/internetga ochiq serverda yoqmang.")
    app.run(debug=debug_yoqilgan)