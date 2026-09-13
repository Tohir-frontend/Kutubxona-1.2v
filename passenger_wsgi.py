"""
cPanel "Setup Python App" (Phusion Passenger) uchun kirish nuqtasi.
Passenger shu faylni topib, undan "application" nomli WSGI obyektini kutadi.

MUHIM: cPanel ilova yaratganda bu faylni standart "It works!" shabloni bilan
almashtirib qo'yishi mumkin. Agar sayt "It works!" ko'rsatsa, faylni ochib,
mazmunini quyidagicha qayta yozing va Python App sahifasida Restart bosing.
"""
import os
import sys

# web.py qaysi papkada bo'lsa, o'sha papkani Python yo'liga qo'shamiz
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web import app as application
