# Hejhome Open API for Home Assistant

**English** | [한국어](README.ko.md)

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz)

> **Unofficial integration.** Not affiliated with or endorsed by Hejhome / GOQUAL, and not officially supported by them.
> 비공식 HA 통합입니다. 헤이홈(Hejhome) 및 고퀄(GOQUAL)과 관계가 없으며, 공식 지원을 받지 않습니다.

A custom integration that connects Hejhome (헤이홈) devices to Home Assistant through the **Open API v3** published by GOQUAL. The API is official, but this integration is a personal project — please report problems as issues in this repository, not to Hejhome customer support.

It replaces [ha-hejhome](https://github.com/jongho/ha-hejhome), which used the unofficial web API of Hejhome for Web (square.hej.so). Hejhome for Web shuts down on December 22, 2026 ([notice, in Korean](https://m.hej.life/board/free/read.html?no=131487&board_no=1)).

> Only three devices have been tested on real hardware: the motion sensor (GKZ-MO021), the temperature/humidity sensor (GKZ-TH141), and the Smart Color Bulb Z26. Everything else was built from the API documentation, so please open an issue if something doesn't work.

## Requirements

- Home Assistant 2025.12 or later
- An API key issued from the Hejhome Partners Portal (see [Getting an API key](#getting-an-api-key))
- A Hejhome account linked to that API key

## Getting an API key

API keys are free and come from the Hejhome Partners Portal. You only need to do this once. The portal is in Korean.

1. **Sign up:** Go to [partners.goqual.com](https://partners.goqual.com), verify your email, and accept the Partners Portal Terms and the Open API Terms.
2. **Create an organization:** Applications and API keys live inside an organization. After you request one, GOQUAL approves it and the organization is created.
3. **Create an application:** Create one application in the organization. Pick a name you'll recognize, such as "Home Assistant".
4. **Issue an API key:** Issue a key in the application. **The key is shown only once**, so store it somewhere safe right away.
5. **Link your Hejhome account:** In the portal, enter the ID and password of your Hejhome app account, then the verification code sent to your phone or email.
6. **Register allowed IPs (recommended):** Add your home's public IP to the application. Even if the key leaks, it can't be used from anywhere else.

Good to know:

- Only devices in places where the linked account is the **owner** in the Hejhome app are visible. Devices in places you joined as a manager or member don't show up.
- A Hejhome account can be linked to only one application.
- If your home's public IP changes, calls come from an IP that isn't allowed and the integration stops. When Home Assistant shows a repair notice, update the IP in the portal.
- Never share your API key or post it anywhere public, such as GitHub. If it leaks, revoke it in the portal and issue a new one.
- To rotate a key, issue a new one, enter it through the integration's **Reconfigure** option in Home Assistant, then revoke the old key.

## Installation (HACS)

1. Search for "Hejhome Open API (Unofficial)" in HACS, download it, and restart Home Assistant.
2. Go to **Settings → Devices & services → Add integration**, choose "Hejhome Open API (Unofficial)", and enter your API key. If you have more than one home, choose the one to connect.

If the search doesn't find it, open HACS → top-right menu → **Custom repositories**, add this repository's URL with the type **Integration**, and start again from step 1.

To install without HACS, copy the `custom_components/hejhome_openapi/` folder into `/config/custom_components/` and restart Home Assistant.

## What's supported

| Entity type | Values |
|---|---|
| Sensor | Temperature, humidity, battery, illuminance, power/current/voltage, CO concentration, filter life, and more |
| Binary sensor | Door open, motion, occupancy, water leak, smoke, CO, lock, connectivity |
| Switch | Plugs, wall switches (including multi-gang) |
| Light | On/off, brightness, color temperature, color |

- The Hejhome API doesn't push state changes, so the integration polls every 30 seconds. You can change the interval to 30–300 seconds in the options.
- If the rate limit (429) is hit, polling slows down for a while.
- During short outages, the last known values are kept for up to three failed polls.
- If the API key is blocked or changed, you're asked to enter it again.
- Diagnostics files hide the API key and account details.

## Development

```bash
python3 -I -B tests/test_api.py     # unit tests for api/ (standard library only, no Home Assistant needed)
python3 -I -B tests/live_check.py   # read-only calls against the real API (no device control)
```

`live_check.py` reads the key from `api-key.env` (`HEJHOME_API_KEY=...`) at the repository root. That file is in `.gitignore` and never committed. `docs/samples/` contains real responses with ids and names masked.
