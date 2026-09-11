"""
aHost (cPanel "Setup Python App" / Phusion Passenger) uchun kirish nuqtasi.
Passenger shu faylni topib, undan "application" nomli WSGI obyektini kutadi.
"""
from web import app as application
