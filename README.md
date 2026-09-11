# Xorazm Pedagogika Texnikumi Elektron Kutubxonasi

Python'da yozilgan oddiy konsol kutubxona tizimi.

## Bo'limlar

- Umumta'lim fanlar
- Umumkasbiy fanlar
- Maxsus fanlar
- Badiiy adabiyotlar

## Konsol versiyasini ishga tushirish

```
python main.py
```

## Web versiyasini ishga tushirish

```powershell
python web.py
```

Keyin brauzerda `http://127.0.0.1:5000/` manzilini oching. Brauzerda `ERR_CONNECTION_REFUSED` chiqsa, Flask serveri hali ishga tushirilmagan bo'ladi.

## Imkoniyatlar

- Bo'limlarni ko'rish
- Telegram kanalidagi kitob havolasini qo'shish
- Bo'lim bo'yicha kitoblarni ko'rish
- Kitob qidirish (nom yoki muallif bo'yicha)
- Telegram kanaliga o'tib kitobni yuklab olish

Kitob ma'lumotlari `kutubxona.json` faylida saqlanadi. Kitob qo'shishda avval
kitobni ochiq Telegram kanaliga yuklang, so'ng kanal yoki post havolasini saytga
kiriting. Saytdagi `Telegramdan yuklash` tugmasi foydalanuvchini shu havolaga olib boradi.
