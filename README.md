# Hejhome Open API for Home Assistant

> **비공식 HA 통합입니다.** 헤이홈(Hejhome) 및 고퀄(GOQUAL)과 관계가 없으며, 공식 지원을 받지 않습니다.
> Unofficial — not affiliated with or endorsed by Hejhome / GOQUAL.

헤이홈(GoQual)이 공개한 **Open API v3**로 헤이홈 기기를 Home Assistant에 연결하는 커스텀 통합입니다. API는 헤이홈이 제공하는 공식 API지만, 이 통합은 개인이 만든 것입니다. 문제가 생기면 헤이홈 고객센터가 아니라 이 저장소의 이슈로 알려 주세요. 비공식 앱 API를 쓰던 [ha-hejhome](https://github.com/jongho/ha-hejhome)를 대신하려고 만들었습니다.

> 실제 기기로 동작을 확인한 것은 만든 사람이 가진 모션 센서(GKZ-MO021), 온습도계(GKZ-TH141), 스마트 컬러 전구 Z26 세 가지뿐입니다. 다른 기기는 API 문서를 보고 만들었으므로, 동작하지 않으면 이슈로 알려 주세요.

## 필요한 것

- Home Assistant 2025.12 이상
- 헤이홈 파트너스 포털에서 발급한 API 키와, 그 키에 연결한 헤이홈 계정

## 설치 (HACS)

1. HACS → 오른쪽 위 메뉴 → **사용자 지정 저장소**에 이 저장소 주소를 넣고 유형은 **통합**으로 추가합니다.
2. "Hejhome Open API (Unofficial)"를 내려받고 Home Assistant를 재시작합니다.
3. **설정 → 기기 및 서비스 → 통합 추가**에서 "Hejhome Open API (Unofficial)"를 고르고 API 키를 넣습니다. 집이 여러 곳이면 집을 고릅니다.

직접 설치하려면 `custom_components/hejhome_openapi/`를 HA의 `/config/custom_components/`에 복사하고 재시작합니다.

## 지원 범위

| 플랫폼 | 능력 |
|---|---|
| 센서 | 온도, 습도, 배터리, 조도, 전력·전류·전압, CO 농도, 필터 수명 등 |
| 이진 센서 | 문 열림, 움직임, 재실, 누수, 연기, 일산화탄소, 잠금, 연결 상태 |
| 스위치 | 플러그·벽 스위치(여러 구 포함) |
| 조명 | 켜기/끄기, 밝기, 색온도, 색상 |

- 상태는 30초마다 가져옵니다(옵션에서 30~300초). API가 푸시를 주지 않아 폴링만 씁니다.
- 호출 한도(429)에 걸리면 간격을 늘리고, 일시 오류는 3번까지 이전 값을 유지합니다.
- 키가 막히거나 바뀌면 재인증·재설정 화면으로 다시 넣을 수 있습니다.
- 진단 파일을 내려받을 때 API 키와 계정 정보는 가립니다.

## 개발

```bash
python3 -I -B tests/test_api.py     # api/ 단위 테스트 (표준 라이브러리만, HA 불필요)
python3 -I -B tests/live_check.py   # 실제 API 조회만 (제어 없음)
```

`live_check.py`는 저장소 최상위의 `api-key.env`(`HEJHOME_API_KEY=...`)에서 키를 읽습니다. 이 파일은 `.gitignore`로 커밋에서 빠집니다. `docs/samples/`는 실제 응답에서 id와 이름을 가린 것입니다.
