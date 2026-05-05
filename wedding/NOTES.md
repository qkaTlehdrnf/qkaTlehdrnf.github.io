# 웨딩 청첩장 개발 노트

> `wedding/index.html` 단일 파일 정적 청첩장의 개발 흐름과 기술 결정 기록.  
> 실제 git 커밋 순서를 따라 "왜 그렇게 만들었는가"를 정리했다.

---

## 새로 모청 만들 때 반드시 확인할 것

> 이 프로젝트를 짜면서 실제로 막혔던 지점들. 처음 만드는 사람은 여기부터 읽으면 된다.

### 1. 기존 React SPA의 서비스워커를 먼저 죽여라

GitHub Pages에 React 앱이 이미 있는 상태에서 `/wedding/` 같은 서브 경로를 추가하면, **기존 SW(Service Worker)가 해당 URL을 가로채서 React 앱 껍데기를 반환**한다. `wedding/index.html`이 분명히 있는데 흰 화면만 나오면 SW가 범인이다.

해결: `service-worker.js`를 kill-switch로 교체한다.
```js
// service-worker.js — 기존 캐시 전체 삭제 후 즉시 제어권 반환
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k)))));
  return self.clients.claim();
});
```
SW 파일을 그냥 삭제하면 **이미 설치된 SW가 남아서 기존 방문자에게 계속 문제**가 생긴다. 반드시 kill-switch로 교체해야 한다.

---

### 2. 백엔드는 반드시 HTTPS

GitHub Pages는 HTTPS만 제공한다. 백엔드 서버가 HTTP면 브라우저가 **mixed content 정책**으로 요청을 통째로 차단한다. 에러 메시지도 안 뜨고 그냥 데이터가 안 불러와진다.

- 홈 서버(HTTP) → Cloudflare Workers(HTTPS 기본) 로 이전한 이유가 바로 이것.
- 자체 서버를 쓴다면 Let's Encrypt 등으로 HTTPS를 붙여야 한다.

---

### 3. CORS 설정 시 Origin 대소문자 주의

Worker의 `ALLOWED_ORIGIN`을 실제 GitHub Pages URL과 **정확히 동일한 케이스**로 맞춰야 한다. 브라우저가 보내는 `Origin` 헤더는 주소창 URL을 그대로 반영하기 때문에, 대소문자가 한 글자라도 다르면 `Access-Control-Allow-Origin` 불일치로 CORS 차단된다.

```js
// votes-worker/src/index.js
const ALLOWED_ORIGIN = 'https://qkaTlehdrnf.github.io';  // 정확한 케이스로
```

확인 방법: `curl -sv URL -H "Origin: 실제URL" 2>&1 | grep -i access-control`

---

### 4. 백엔드를 교체할 때는 데이터도 옮겨라

Python/SQLite → Cloudflare KV 처럼 백엔드를 교체하면 **코드만 바뀌는 게 아니라 기존 데이터가 새 저장소에 없다**. Worker는 정상 응답하는데 하트 카운트가 전부 0으로 보이면 데이터 마이그레이션 누락을 의심한다.

진단 순서: Worker 응답 정상 여부 → CORS 정상 여부 → 실제 KV 데이터 존재 여부 (`wrangler kv key list --binding VOTES`)

KV 초기화가 필요할 때:
```bash
cd votes-worker
npx wrangler kv key list --binding VOTES          # 키 목록 확인
npx wrangler kv key delete --binding VOTES "votes"
# IP 키(ip:xxx.xxx.xxx.xxx)도 모두 삭제
```

---

### 5. 사진 로딩은 썸네일/원본을 분리해야 쓸 만하다

원본 사진(수 MB)을 그대로 쓰면 갤러리 초기 로드가 수십 초. 반드시 썸네일을 별도로 만들어야 한다.

```bash
# 520px 썸네일 일괄 생성 (ImageMagick)
mogrify -path pictures/thumbs -resize 520x pictures/*.jpg
```

로딩 전략:
| 용도 | 사용 이미지 | 시점 |
|---|---|---|
| 히어로 배경 첫 장 | 썸네일 → 원본으로 교체 | 즉시 표시, 원본 로드 후 조용히 swap |
| 히어로 이후 슬라이드 | 원본 | onload 후 전환 (깜박임 없음) |
| 갤러리 썸네일 | 썸네일 | IntersectionObserver 레이지 로딩 |
| 라이트박스 | 썸네일 즉시 → 원본 교체 | 열리는 즉시 썸네일, 원본 준비되면 swap |
| 원본 프리패치 | 원본 | 페이지 로드 후 순차적으로 백그라운드 |

히어로 첫 장을 빠르게 보여주는 핵심: `img.onload`를 기다리지 말고 썸네일을 즉시 `src`에 넣어버린다. 원본은 별도 `Image()` 객체로 로드하고 `onload`에서 같은 `<img>` 태그의 `src`를 교체.

---

### 6. 갤러리 순서 셔플은 모듈 스코프에서 딱 한 번

```js
const SHUFFLED = [...PHOTOS].sort(() => Math.random() - 0.5);
```

이걸 `renderGallery()` 안에서 매번 하면 "추천순 ↔ 랜덤" 토글을 누를 때마다 순서가 바뀐다. 모듈 스코프(최상단)에서 한 번만 계산하고, 히어로 슬라이드쇼와 갤러리가 같은 배열을 공유.

---

## 전체 구조

```
wedding/
├── index.html          ← 모든 CSS·JS 인라인, 단일 파일
├── map.svg             ← 커스텀 경로 지도 (별도 파일)
├── NOTES.md            ← 이 문서
└── pictures/
    ├── *.jpg           ← 원본 고해상도 (약 667 MB)
    └── thumbs/
        └── *.jpg       ← 520px 썸네일 (약 4.8 MB)
```

**외부 서비스**  
- `votes-worker/` — Cloudflare Workers + KV  
  엔드포인트: `https://wedding-votes.wonjoong11.workers.dev`

---

## 기능 진화 (커밋 순서)

### 1. `2397671` — 최초 청첩장 (2026-04-26)

**만든 것**
- 인트로 애니메이션 (꽃잎 캔버스 + 클릭 해제)
- D-day 카운터 (초 단위 실시간)
- 갤러리 (가로 스크롤)
- 커스텀 SVG 지도 (`map.svg`)
- 계좌 아코디언 + 복사 버튼
- 포트폴리오 메인(`index.html`)에 플로팅 ♥ 청첩장 버튼

**노하우**  
- `service-worker.js`를 kill-switch로 교체해야 했음.  
  기존 React SPA의 SW가 `/wedding/` URL을 가로채 빈 화면을 냈기 때문.  
  SW를 삭제하면 캐시가 남아 문제 재발 → `self.skipWaiting()` + `caches.keys()` 전체 삭제로 해결.

---

### 2. `4515a05` — 사진 81장 추가 (2026-05-05)

**만든 것**  
- `wedding/pictures/` 에 원본 JPG 81장 (quality 92로 재압축)

**노하우**  
- 원본 그대로 커밋하면 저장소가 수백 MB. quality 92 재압축으로 화질 거의 유지하면서 크기 절감.
- 파일명 앞에 `01_`, `02_` 숫자 prefix → 순서 보장 + PHOTOS 배열 관리 편의.

---

### 3. `f7f3999` — 썸네일 + 레이지 로딩 (2026-05-05)

**만든 것**  
- `pictures/thumbs/` — 520px 썸네일 81장 (총 4.8 MB)
- 첫 3장만 즉시 로드, 나머지는 `IntersectionObserver`로 뷰포트 진입 시 로드
- `rootMargin: '0px 400px 0px 0px'` — 400px 미리 로드해 스크롤 끊김 방지

**노하우**  
- 원본만 썼을 때 초기 로드가 수십 초 → 썸네일 도입 후 첫 화면 로드 ~1초대.
- `IntersectionObserver`의 `rootMargin`은 수평 스크롤 방향(right)만 크게 잡아야 한다.  
  세로 스크롤 갤러리라면 bottom을 키워야 하지만 이 갤러리는 가로 스크롤.
- `img[data-src]` 패턴: lazy 대상은 `src` 대신 `data-src`에 경로를 두고 `opacity:0` 처리 → 로드 완료 시 `src`로 복사 후 `data-src` 삭제 + fade-in.

---

### 4. `198bdd0` — 전체 해상도 프리패치 (2026-05-05)

**만든 것**  
- 페이지 로드 후 원본 이미지 순차 백그라운드 프리패치
- 호버/터치한 카드를 프리패치 큐 맨 앞으로 이동 (`prioritizePrefetch`)
- 라이트박스: 썸네일 즉시 표시 → 원본 준비되면 교체

**노하우**  
- 순차 프리패치(`prefetchActive` 플래그)가 핵심.  
  동시에 여러 장을 요청하면 네트워크 포화 → 한 장씩 완료 후 다음 장 요청.
- 라이트박스를 열었을 때 이미 캐시된 경우 `lbImg.src`를 두 번 바꾸지 않아야 깜박임 없음 →  
  `prefetched.has(name)` 분기로 캐시 여부를 확인 후 즉시 표시.

---

### 5. `2f46f09` — 하트(투표) 기능 첫 버전 (2026-05-05)

**만든 것**  
- `photo-pipeline/votes_server.py` — Python/SQLite 백엔드 (홈 서버)
- IP별 중복 투표 방지 (`ip_votes` 테이블)
- `GET /votes` → 전체 득표 + 내 IP가 찍은 사진 목록 반환
- 하트 버튼을 갤러리 썸네일이 아닌 라이트박스에만 배치

**노하우 (설계 판단)**  
- 썸네일에 버튼을 넣으면 작은 터치 영역이 지저분해 보임 → 라이트박스 집중.
- `localStorage`로 투표 저장했더니 다른 기기에서 같은 사람이 중복 투표 가능 →  
  서버 IP 기반으로 이동.

---

### 6. `b06fad1` + `4970b98` — 갤러리 정렬 + 하트 배지 (2026-05-05)

**만든 것**  
- 세션마다 갤러리 순서 무작위화 (`SHUFFLED = [...PHOTOS].sort(() => Math.random()-0.5)`)
- "추천순 정렬" 토글 버튼 → 득표수 내림차순
- 썸네일 위에 항상 하트 배지 표시 (0표: `♡`, N표: `♥ N`)

**노하우**  
- `SHUFFLED`를 모듈 스코프에서 한 번만 계산해야 페이지 내 정렬 전환 시 일관성 유지.  
  렌더링마다 다시 섞으면 버튼 클릭할 때마다 순서가 바뀜.
- 배지를 `position: absolute` + `pointer-events: none`으로 이미지 위에 얹기 →  
  클릭이 그 아래 `imgWrap.onclick`으로 통과됨.

---

### 7. `b49f676` — Cloudflare Workers로 백엔드 이전 (2026-05-05)

**만든 것**  
- `votes-worker/src/index.js` — Cloudflare Workers + KV
- Python 홈 서버 → Workers로 교체
- HTTPS 기본 제공 → GitHub Pages(HTTPS) ↔ 백엔드 mixed content 문제 해결

**노하우 (핵심)**  
- GitHub Pages는 HTTPS만 제공.  
  홈 서버가 HTTP였기 때문에 브라우저가 mixed content 정책으로 요청을 차단 →  
  해결책: HTTPS를 기본으로 제공하는 Cloudflare Workers.
- KV 구조: 키 `"votes"` 하나에 전체 득표 JSON 저장, 키 `"ip:{IP}"` 에 투표한 사진 목록 저장.  
  조회할 때 두 키를 `Promise.all`로 동시에 읽어 응답 속도 최소화.
- CORS: `Origin` 헤더 검사로 `qkaTlehdrnf.github.io`와 `localhost`만 허용.  
  `OPTIONS` preflight에 204 응답 필수 (브라우저 CORS 정책).

---

### 8. `7676f6b` + `2a7fc0f` — 히어로 슬라이드쇼 (2026-05-05)

**만든 것**  
- 히어로 배경: 5초마다 랜덤 사진으로 크로스페이드
- 슬라이드 2장(`#hero-slide-a`, `#hero-slide-b`)을 교대 사용

**노하우**  
- 이미지 2장을 `position: absolute` + `opacity` 전환으로 크로스페이드.  
  `src` 교체 타이밍: `img.onload` 콜백 안에서 교체 → 로드 전에 전환되는 깜박임 없음.
- `SHUFFLED` 배열을 히어로와 갤러리가 공유 → 사진 풀(pool)이 동일해서 관리 편의.

---

### 9. 오늘 — 라이트박스 네비게이션 + 공유 버튼 (2026-05-05)

**만든 것**  
- 라이트박스 `‹` / `›` 화살표 버튼
- 키보드 `←` `→` `Esc` 지원
- 터치 스와이프 (50px 이상 수평 드래그)
- 사진 카운터 (`1 / 81`)
- 공유하기 FAB (우상단 고정) — Web Share API / 링크 복사 fallback

**노하우**  
- `getDisplayOrder()` 헬퍼로 현재 정렬 상태(셔플/추천순)를 가져오고,  
  `currentLightboxIndex`로 위치를 추적하면 정렬 전환 후에도 올바른 이웃 사진으로 이동.
- 터치 스와이프는 `touchstart`→`touchend` deltaX만 체크.  
  50px 임계값 미만은 탭으로 인식해 기존 `onclick="closeLightbox()"` 그대로 작동.
- `showToast(msg)` 헬퍼를 추출해 계좌 복사 / 링크 공유 두 곳에서 재사용.

---

## 현재 구성 요약

| 섹션 | 주요 로직 |
|---|---|
| 인트로 | 꽃잎 캔버스(`requestAnimationFrame`) + 클릭 해제 |
| 히어로 | 2-슬라이드 크로스페이드, 5초 인터벌, `SHUFFLED` 공유 |
| D-day | `setInterval(1000)`, 웨딩 날짜 `WEDDING = new Date('2026-08-17T11:00:00')` |
| 갤러리 | 썸네일 레이지 로딩, 원본 프리패치, 랜덤/추천순 토글 |
| 라이트박스 | 썸네일 즉시 표시 → 원본 교체, prev/next, 키보드/스와이프 |
| 하트 투표 | Cloudflare Workers KV, IP 중복 방지, 낙관적 UI 업데이트 |
| 지도 | `map.svg` 인라인 표시 + 카카오/네이버 지도 외부 링크 |
| 계좌 | 아코디언 토글, `navigator.clipboard` + `execCommand` fallback |
| 공유 | `navigator.share` (모바일 시트) + 클립보드 복사 (PC) fallback |

---

## 자주 하는 작업

### 사진 추가
1. `wedding/pictures/` 에 JPG 복사
2. 썸네일 생성: `mogrify -path wedding/pictures/thumbs -resize 520x wedding/pictures/새파일.jpg`
3. `PHOTOS` 배열에 파일명 추가

### 백엔드 배포 (votes-worker 변경 시)
```bash
cd votes-worker
npx wrangler deploy
```

### 신부측 혼주 이름 입력
`wedding/index.html` → `invitation-family` 섹션, 두 번째 `family-line` 의 빈칸(`&nbsp;` 부분) 수정.

### KV 데이터 초기화 (투표 리셋)
```bash
cd votes-worker
npx wrangler kv key list --binding VOTES        # 현재 키 목록 확인
npx wrangler kv key delete --binding VOTES "votes"
npx wrangler kv key delete --binding VOTES "ip:xxx.xxx.xxx.xxx"  # IP 키는 여러 개일 수 있음
```

---

## 트러블슈팅 기록

### Cloudflare KV 데이터가 비어있는 문제 (2026-05-05)

**증상**: 갤러리 하트 카운트가 모두 0, `GET /votes` 응답이 `{"my_votes":[]}`.

**원인**: `b49f676` 커밋에서 Python/SQLite 홈 서버 → Cloudflare Workers + KV로 교체할 때 **기존 투표 데이터를 마이그레이션하지 않았음**. 새로 생성된 KV 네임스페이스는 당연히 비어있다.

**진단 과정**:
1. `curl https://wedding-votes.wonjoong11.workers.dev/votes` → `{"my_votes":[]}` 확인
2. `curl -X POST .../vote -d '{...}'` → 저장 정상 동작 확인 → Worker 자체는 이상 없음
3. CORS 의심 → `-H "Origin: ..."` 붙여서 테스트 → `Access-Control-Allow-Origin` 정상 반환
4. GitHub Pages URL 케이스 확인 (`qkaTlehdrnf` 대문자 유지, 리다이렉트 없음) → CORS 설정과 일치
5. **결론**: Worker·CORS 문제 아님. KV가 순수하게 비어있는 것.

**해결**: 새로 시작(초기화)하기로 결정.
```bash
npx wrangler kv key list --binding VOTES
npx wrangler kv key delete --binding VOTES "votes"
npx wrangler kv key delete --binding VOTES "ip:165.132.143.142"
```

**노하우**:
- 백엔드를 교체할 때는 **데이터 마이그레이션 계획**을 먼저 세울 것. "교체"는 코드만 바꾸는 게 아니라 데이터도 옮기는 것.
- KV가 비어있으면 `GET /votes` 응답은 `{"my_votes":[]}` — 이게 정상 응답이라 에러 로그가 없음. 서버 자체에 문제가 없어도 데이터가 없으면 없어 보이는 것.
- 확인 순서: **Worker 응답** → **CORS 헤더** → **실제 데이터** 순으로 범위를 좁힌다.
- `wrangler kv key list`로 어떤 키가 실제로 있는지 먼저 확인할 것. IP 키(`ip:xxx`)는 접속자마다 생기므로 초기화 시 전부 삭제해야 한다.
