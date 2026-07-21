import urllib.request, urllib.error, json, hashlib, ctypes, uuid, os

data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
install_id_file = os.path.join(data_dir, 'install_id.txt')
os.makedirs(data_dir, exist_ok=True)
if os.path.exists(install_id_file):
    install_id = open(install_id_file, 'r', encoding='utf-8').read().strip()
else:
    install_id = str(uuid.uuid4())
    open(install_id_file, 'w', encoding='utf-8').write(install_id)
print('installId:', install_id)

drive = os.path.splitdrive(os.path.abspath(os.path.dirname(__file__)))[0]
root = drive + '\\'
print('Root drive:', root)

volume_serial = ctypes.c_ulong()
ctypes.windll.kernel32.GetVolumeInformationW(
    ctypes.c_wchar_p(root), None, 0, ctypes.byref(volume_serial), None, None, None, 0
)
serial = str(volume_serial.value)
print('Volume serial:', serial)
raw = root + '|' + serial + '|openclaw-launcher'
device_id = hashlib.sha256(raw.encode('utf-8')).hexdigest()
print('deviceId:', device_id)

code = 'OC-PRO-XXXX-XXXX-XXXX-XXXX'
payload = {
    'code': code,
    'installId': install_id,
    'deviceId': device_id,
    'appVersion': 'desktop',
}
print('Payload:', json.dumps(payload, indent=2))

req = urllib.request.Request(
    'https://license.heang.top/activate',
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json', 'User-Agent': 'OpenClaw-Desktop/2.0'},
    method='POST',
)
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print('Response:', json.dumps(data, indent=2, ensure_ascii=False))
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8')
    print('HTTP %d: %s' % (e.code, body))
except Exception as e:
    print('Error:', e)
