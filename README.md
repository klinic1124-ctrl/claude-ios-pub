# 매일 회화 — English · Español (Argentina)

매일 **오전 7시(KST)** 에 영어와 아르헨티나 스페인어 일상회화 5문장을 공개하는 모바일 웹앱(PWA)입니다.

- 🇺🇸 **English** / 🇦🇷 **Español (리오플라텐세)** / 📚 **복습** 3개 탭
- 문장 · 한국어 번역(가리기) · 사용 상황 · 단어 설명(뜻/품사/IPA/기본형/메모) · 팁
- 🔊 원어 발음(보통 / 천천히), 단어별 발음
- ⭐ 즐겨찾기, ✓ 학습 완료 체크, 날짜별 지난 학습 복습
- 오프라인 지원, 홈 화면 설치

## 휴대폰에서 사용하기

1. 배포 주소 접속: `https://klinic1124-ctrl.github.io/claude-ios-pub/`
2. iPhone Safari → 공유 버튼 → **홈 화면에 추가**

## 배포 설정 (최초 1회)

저장소 **Settings → Pages → Build and deployment → Source** 를 **GitHub Actions** 로 바꾸면,
이후 푸시마다 `.github/workflows/pages.yml` 이 자동 배포합니다.

## 매일 자동 생성 (5단계)

`.github/workflows/daily.yml` 이 **매일 05:17 KST** 에 실행됩니다.

1. `scripts/generate_daily.py` 가 AI(Claude / Gemini / NVIDIA NIM 중 선택)로 영어·스페인어 5문장씩 생성 (주제는 25개를 순환, 이전 문장 300개를 넘겨 중복 방지)
2. Azure 신경망 TTS로 문장(보통/느리게)과 단어 발음 mp3 생성 — 영어 `en-US-JennyNeural`/`GuyNeural`, 스페인어 `es-AR-ElenaNeural`/`TomasNeural` (문장마다 여/남 교대)
3. `content/`, `audio/` 커밋 → GitHub Pages 재배포

### 필요한 Secrets (Settings → Secrets and variables → Actions)
| 이름 | 용도 |
|---|---|
| `GEMINI_API_KEY` | 문장 생성 — Google AI Studio (무료) |
| `NVIDIA_API_KEY` | 문장 생성 — NVIDIA NIM build.nvidia.com (무료) |
| `ANTHROPIC_API_KEY` | 문장 생성 — Claude (유료) |
| `AZURE_SPEECH_KEY` | 원어민 음성 (선택 — 없으면 기기 음성) |
| `AZURE_SPEECH_REGION` | Azure Speech 리소스 지역, 예: `koreacentral`, `eastus` |

AI 키는 **하나만** 있으면 됩니다. 여러 개면 Anthropic → Gemini → NVIDIA 순으로 사용합니다.
직접 고르려면 **Settings → Secrets and variables → Actions → Variables** 탭에서:
- `AI_PROVIDER` = `gemini` | `nvidia` | `anthropic`
- `AI_MODEL` = 모델 이름 (기본값: `gemini-flash-latest`, `meta/llama-3.3-70b-instruct`, `claude-opus-5-5`)

### 수동 실행 (Actions → Daily content → Run workflow)
- `date`: 특정 날짜 생성 (비우면 오늘)
- `force`: 이미 있는 날도 다시 생성
- `backfill_audio`: 음성이 없는 기존 날짜(샘플 포함)에 음성만 추가

로컬 실행: `pip install -r scripts/requirements.txt && python scripts/generate_daily.py --date 2026-11-08`

> 음성 용량은 하루 약 0.5–1MB입니다. 1년 이상 쌓이면 오래된 음성 정리를 고려하세요.

## 구조

```
index.html  styles.css  app.js     앱 (빌드 과정 없는 순수 HTML/CSS/JS)
sw.js  manifest.webmanifest  icons/  PWA (오프라인 캐시, 홈 화면 설치)
content/index.json                 언어별 사용 가능한 날짜 목록
content/{en,es}/YYYY-MM-DD.json    하루치 콘텐츠
audio/{en,es}/YYYY-MM-DD/           원어민 TTS mp3
scripts/generate_daily.py          콘텐츠·음성 생성 스크립트
```

### 공개 규칙
날짜 `D` 의 콘텐츠는 **D일 07:00 KST** 에 공개됩니다. 그 전에는 전날 콘텐츠가 "오늘"로 보입니다.

### 콘텐츠 형식
```json
{
  "date": "2026-11-02", "language": "es", "theme": "카페·식당", "level": "초급~중급",
  "sentences": [{
    "id": "es-20261102-1",
    "text": "¿Me das un cortado, por favor?",
    "translation": "코르타도 한 잔 주실래요?",
    "situation": "카페에서 주문할 때",
    "tip": "...",
    "audio": { "normal": "audio/es-20261102-1.mp3", "slow": "audio/es-20261102-1-slow.mp3" },
    "words": [{ "word": "das", "lemma": "dar", "pos": "동사", "meaning": "주다", "ipa": "das",
                "note": "vos 현재형도 das", "audio": "audio/w-es-das.mp3" }]
  }]
}
```
`audio` 필드가 없으면 기기 내장 음성(Web Speech API)으로 읽습니다. 스페인어는 `es-AR` → `es-419` → `es-US` → `es-MX` 순으로 음성을 고릅니다.

### 아르헨티나 스페인어 기준
- **voseo**: *vos tenés, querés, andás*, 명령형 *disculpá, vení*
- **발음**: ll/y = [ʃ] (*llevar* /ʃeˈβaɾ/)
- **어휘**: *colectivo, subte, laburo, che, dale, re, finde, talle, valija, maní* (스페인 스페인어와의 차이를 메모로 표시)

## 로컬 실행
```bash
python3 -m http.server 8000   # http://localhost:8000
```

## 로드맵
- [x] 1단계 데이터 형식 + 샘플 7일치 (2026-11-01 ~ 11-07)
- [x] 2단계 앱 화면: 탭 · 문장 카드 · 단어 시트 · 음성 재생
- [x] 3단계 PWA: 홈 화면 설치 · 오프라인 · 07:00 공개 · 학습 기록
- [x] 4단계 GitHub Pages 배포 워크플로
- [x] 5단계 매일 자동 생성: AI(Claude/Gemini/NVIDIA) 문장 + Azure TTS → GitHub Actions 05:17 KST
- [ ] 6단계 07:00 웹 푸시 알림 · 퀴즈
