import io
import json

import pytest

from web import app


app.config['TESTING'] = True


@pytest.fixture(autouse=True)
def disable_csrf(monkeypatch):
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', False)


def _set_session(client, email='admin@example.com', role='admin'):
    with client.session_transaction() as sess:
        sess['foydalanuvchi'] = {'ism': 'Admin', 'email': email, 'rol': role}


def test_homepage_title_is_loaded_from_settings(tmp_path, monkeypatch):
    settings_path = tmp_path / 'site_settings.json'
    settings_path.write_text(json.dumps({'title': 'Yangi maktab nomi'}), encoding='utf-8')
    monkeypatch.setattr('web.SITE_SETTINGS_FILE', str(settings_path))

    client = app.test_client()
    resp = client.get('/')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Yangi maktab nomi' in body


def test_admin_can_upload_delete_images(tmp_path, monkeypatch):
    settings_path = tmp_path / 'site_settings.json'
    settings_path.write_text(json.dumps({'title': 'Test title'}), encoding='utf-8')
    static_dir = tmp_path / 'static' / 'texnikum'
    static_dir.mkdir(parents=True)
    monkeypatch.setattr('web.SITE_SETTINGS_FILE', str(settings_path))
    monkeypatch.setattr('web.app.config', {**app.config, 'UPLOAD_FOLDER': str(tmp_path / 'uploads'), 'COVER_FOLDER': str(tmp_path / 'covers')})
    monkeypatch.setattr('web._get_texnikum_dir', lambda: str(static_dir))
    monkeypatch.setattr('web.ADMIN_LOGIN', 'admin@example.com')
    monkeypatch.setattr('web.ADMIN_PAROL', 'secret')

    client = app.test_client()
    _set_session(client)

    image = (b'\x89PNG\r\n\x1a\n' + b'0' * 64)
    resp = client.post('/admin/boshqaruv', data={
        'title': 'Yangi title',
        'homepage_image': (io.BytesIO(image), 'school.png')
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert (static_dir / 'school.png').exists()

    resp = client.post('/admin/rsm/ochirish', data={'filename': 'school.png'}, follow_redirects=True)
    assert resp.status_code == 200
    assert not (static_dir / 'school.png').exists()
