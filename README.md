# ble-ai — تونل WebRTC روی Bale.ai / LiveKit

یک تونل SOCKS5 که ترافیک TCP رو روی DataChannel‌های WebRTC (LiveKit) مولتی‌پلکس می‌کنه. هدف: ساخت یه مسیر بای‌پس که به‌جای اینکه شبیه VPN معمولی باشه، شبیه یه میتینگ Bale به‌نظر برسه (چون زیرساخت Bale از داخل ایران فیلتر نیست).

> **هشدار حقوقی / مسئولیت:** این ابزار برای استفاده‌ی شخصی و عبور از سانسور غیراخلاقیه. کاربر مسئول مطابقت با قوانین محل خودشه.

---

## معماری

```
┌──────────────────┐                                           ┌─────────────────┐
│   کلاینت VPN     │                                           │     اینترنت     │
│  (داخل ایران)    │                                           │       آزاد       │
└────────┬─────────┘                                           └────────▲────────┘
         │ Xray/V2Ray/WireGuard                                         │ TCP
         ▼                                                              │
┌──────────────────┐    SOCKS5     ┌──────────────┐  WebRTC  ┌──────────┴──────┐
│  سرور ایران (VPS)│────127.0.0.1──▶│  tunnel entry │═════════▶│  tunnel exit    │
│  + Xray + entry  │    :1080      │              │ DataChan │                 │
└──────────────────┘                └──────────────┘ (Bale)   └─────────────────┘
                                                                    سرور خارج
```

- **entry** (سمت ایران): یه پروکسی SOCKS5 محلی روی `127.0.0.1:1080` بالا میاره. هر اتصال SOCKS رو روی LiveKit DataChannel فریم‌بندی شده می‌فرسته.
- **exit** (سمت خارج): فریم‌ها رو می‌خونه، اتصال TCP واقعی رو به مقصد باز می‌کنه و داده رو دو طرفه pump می‌کنه.
- **روتر داخلی**: Xray یا redsocks روی سرور ایران که ترافیک کلاینت‌ها رو به SOCKS5 محلی هدایت می‌کنه (نمونه‌های آماده توی [`examples/`](examples/)).

---

## نصب

سه روش:

### الف) روش یک‌خطی (وقتی GitHub در دسترسه)

روی **هر دو سرور** (ایران و خارج)، با sudo:

```bash
# سرور خارج:
curl -fsSL https://raw.githubusercontent.com/womanlifefreedom13/ble-ai/main/install.sh | sudo bash -s -- exit

# سرور ایران (اگه GitHub باز بود):
curl -fsSL https://raw.githubusercontent.com/womanlifefreedom13/ble-ai/main/install.sh | sudo bash -s -- entry
```

این اسکریپت:
- پایتون 3.10+ رو نصب می‌کنه
- ریپو رو توی `/opt/ble-ai` کلون می‌کنه
- venv و وابستگی‌ها رو می‌سازه
- یوزر `tunnel` می‌سازه (بدون شل)
- یونیت systemd رو نصب و enable می‌کنه (ولی شروع نمی‌کنه؛ اول کانفیگ رو ویرایش می‌کنی)

### ب) روش آفلاین برای ایران (وقتی GitHub فیلتره)

از یه ماشین که اینترنت آزاد داره (مثلاً همون سرور خارج بعد از نصب) bootstrap رو بساز:

```bash
cd /opt/ble-ai
./scripts/build-bootstrap.sh
# خروجی: /opt/ble-ai/bootstrap.sh (~50KB)
```

این تک‌فایل bootstrap.sh رو با هر روشی به سرور ایران منتقل کن (Bale chat → دانلود روی سرور با مرورگر، یا scp از یه ماشین واسط، یا حتی paste توی editor). بعد:

```bash
sudo bash bootstrap.sh entry
```

bootstrap همه فایل‌ها (که داخلش base64 شدن) رو استخراج می‌کنه، venv می‌سازه، systemd رو نصب می‌کنه. کاملاً آفلاین.

### ج) روش دستی (development)

```bash
git clone https://github.com/womanlifefreedom13/ble-ai.git
cd ble-ai
bash tunnel/setup.sh
source .venv/bin/activate
cp tunnel/settings.example.json tunnel/settings.json
$EDITOR tunnel/settings.json
python -m tunnel entry --config tunnel/settings.json
```

---

## گرفتن توکن از Bale.ai

Bale **API عمومی برای توکن مهمان نداره**. باید توکن رو از کلاینت وب Bale به‌صورت دستی استخراج کنی:

1. توی مرورگر دسکتاپ به [meet.bale.ai](https://meet.bale.ai) برو و لاگین کن.
2. یه میتینگ بساز یا join کن. **شناسه‌ی میتینگ** (room name) رو نگه دار — این میشه `room_name` توی `settings.json`.
3. F12 (DevTools) → تب **Network** → فیلتر `livekit` یا `token` یا `join`.
4. به دنبال یه درخواست بگرد که توکن JWT (شکل `eyJhbG...`) رو برمی‌گردونه. معمولاً:
   - یه درخواست `POST` به یه endpoint از Bale که توی پاسخ `accessToken`/`token`/`jwt` داره
   - یا یه WebSocket به `wss://meet.bale.ai/rtc?access_token=eyJ...`
5. JWT رو کپی کن.
6. **توکن دوم** برای exit: یه پنجره‌ی incognito یا مرورگر دیگه باز کن، با حساب دیگه به همون room جوین شو، و توکن دومی رو هم کپی کن. (entry و exit باید identity متفاوت داشته باشن.)
7. هر دو رو توی `settings.json` پیست کن:

```json
{
  "livekit_url": "wss://meet.bale.ai",
  "room_name": "<meeting-id>",
  "token_mode": "preset",
  "entry_token": "eyJhbG... (token از مرورگر اول)",
  "exit_token":  "eyJhbG... (token از مرورگر دوم)"
}
```

**نکته‌ی مهم:** توکن‌های Bale معمولاً TTL کوتاهی دارن (چند ساعت تا چند روز). وقتی منقضی شد، سرویس reconnect می‌خوره تا موفق بشه — باید توکن جدید بدی. کد در `bale_token.py` هنگام تجدید اتصال، توکن رو دوباره از فایل/env می‌خونه — برای rotation بدون restart از این سینتکس استفاده کن:

```json
{
  "entry_token": "@/etc/tunnel/entry.token",
  "exit_token":  "${TUNNEL_EXIT_TOKEN}"
}
```

با `@/path` از فایل می‌خونه و با `${ENV}` از متغیر محیط.

---

## گزینه‌ی بهتر: LiveKit سلف‌هاست

اگه Bale توی آینده endpointش رو ببنده یا توکن‌ها به‌سرعت expire بشن، می‌تونی LiveKit خودت رو روی **سرور خارج** اجرا کنی:

```bash
# روی سرور خارج:
docker run -d --name livekit \
  -p 7880:7880 -p 7881:7881 -p 7882:7882/udp \
  -e LIVEKIT_KEYS="APIxxxxxx: secretxxxxxx" \
  livekit/livekit-server --dev
```

بعد توی `settings.json` (هر دو سرور):

```json
{
  "livekit_url": "wss://livekit.your-domain.tld",
  "room_name": "tunnel",
  "token_mode": "selfhost",
  "api_key": "APIxxxxxx",
  "api_secret": "secretxxxxxx",
  "token_ttl_hours": 168
}
```

این حالت توکن رو خودش لوکال می‌سازه و expiry نداره (تا TTL تنظیم شده).

**عیب:** دامنه‌ی شخصی ممکنه بعداً فیلتر بشه — برای همین Bale طراحی شده که میزبان اصلی باشه.

---

## استفاده روی سرور ایران (روتر کردن ترافیک VPN)

روی سرور ایران بعد از نصب entry، یه SOCKS5 روی `127.0.0.1:1080` داری. حالا باید VPN سرورت (Xray/V2Ray/...) رو تنظیم کنی که outboundش از این SOCKS رد بشه.

### Xray / V2Ray

[`examples/xray-outbound.json`](examples/xray-outbound.json) رو نگاه کن. خلاصه‌اش:

```json
{
  "outbounds": [
    {
      "tag": "tunnel-out",
      "protocol": "socks",
      "settings": { "servers": [{ "address": "127.0.0.1", "port": 1080 }] }
    },
    { "tag": "direct", "protocol": "freedom" }
  ],
  "routing": {
    "rules": [
      { "type": "field", "ip": ["geoip:private"], "outboundTag": "direct" },
      { "type": "field", "domain": ["geosite:category-ir"], "outboundTag": "direct" },
      { "type": "field", "outboundTag": "tunnel-out", "network": "tcp,udp" }
    ]
  }
}
```

این کانفیگ، ترافیک ایرانی رو direct می‌فرسته و بقیه رو از تونل رد می‌کنه.

### redsocks (transparent redirect)

اگه می‌خوای **همه** ترافیک TCP خروجی سرور (نه فقط ترافیک VPN) از تونل رد بشه، [`examples/redsocks.conf`](examples/redsocks.conf) و دستورات iptables داخلش.

### تست سریع

```bash
curl --socks5 127.0.0.1:1080 https://ifconfig.me
```

باید IP **سرور خارج** برگرده، نه سرور ایران.

---

## دستورات روزمره

```bash
# لاگ‌ها به‌صورت زنده:
journalctl -u tunnel-entry -f          # روی سرور ایران
journalctl -u tunnel-exit  -f          # روی سرور خارج

# ری‌استارت بعد از تغییر کانفیگ:
sudo systemctl restart tunnel-entry

# وضعیت:
systemctl status tunnel-entry
```

---

## رفع اشکال

| علامت | دلیل احتمالی | راه حل |
|---|---|---|
| `LiveKit connect failed` در حلقه | توکن منقضی، room اشتباه، یا فیلترینگ wss | توکن جدید بگیر؛ از مرورگر سرور ایران میتینگ Bale رو تست کن |
| `Timeout waiting for CONNECTED` | سمت exit اتصال نداره یا فعال نیست | روی سرور خارج: `systemctl status tunnel-exit` و logs |
| سرعت خیلی پایین | LiveKit DataChannel reliable مثل TCP-over-TCP عمل می‌کنه | برای throughput بالا، sport کم می‌شه؛ برای latency-sensitive (AI streaming) خوبه |
| اتصال SSH بعد از چند دقیقه قطع | (دیگه نباید باشه — TCP keepalive روشنه) ولی NAT بین کلاینت و entry idle رو می‌بنده | روی کلاینت SSH `ServerAliveInterval 30` |
| `Resolved 'entry_token' is empty` | فایل توکن خالی یا env var نیست | چک کن `cat /etc/tunnel/entry.token` |
| `JWT already expired` توی لاگ | توکن Bale تموم شده | توکن جدید بگیر، به فایل منتقل کن، `systemctl restart` |

---

## ساختار ریپو

```
ble-ai/
├── tunnel/                  # کد اصلی (Python package)
│   ├── __main__.py          # python -m tunnel ... وارد شدن
│   ├── tunnel.py            # CLI parser
│   ├── entry.py             # سمت ایران: SOCKS5 server
│   ├── exit_node.py         # سمت خارج: TCP forwarder
│   ├── protocol.py          # فریمینگ
│   ├── bale_token.py        # توکن از preset / file / env / selfhost
│   ├── config.py            # JSON loader + اعتبارسنجی
│   ├── requirements.txt
│   ├── settings.example.json
│   └── setup.sh             # venv محلی (development)
├── systemd/
│   ├── tunnel-entry.service
│   └── tunnel-exit.service
├── examples/
│   ├── xray-outbound.json   # کانفیگ نمونه Xray
│   └── redsocks.conf        # کانفیگ نمونه redsocks
├── scripts/
│   └── build-bootstrap.sh   # سازنده‌ی bootstrap.sh
├── install.sh               # one-click installer (با git)
├── bootstrap.sh             # self-extracting (بدون git؛ با build-bootstrap ساخته می‌شه)
└── README.md
```

---

## بهبودهای آینده

- [ ] flow control / window-based backpressure (الان فقط write-buffer threshold دارد)
- [ ] رمزنگاری روی frame (الان به TLS لایه‌ی LiveKit متکیه — کافیه ولی لایه‌ی بیشتر بد نیست)
- [ ] احراز هویت SOCKS5 با user/pass (الان no-auth؛ روی `127.0.0.1` خطر کمه ولی روی `0.0.0.0` لازمه)
- [ ] متریک Prometheus
- [ ] auto token refresh از یه webhook بدون restart

---

## License

MIT.
