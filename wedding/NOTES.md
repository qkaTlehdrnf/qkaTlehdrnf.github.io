# 모바일 청첩장 (모청) — LLM 작업 가이드

이 문서는 LLM이 이 프로젝트를 수정하거나 유사한 모청을 새로 만들 때
**실제로 발생한 실수를 반복하지 않도록** 작성되었다.
서술이 아니라 함정(trap) 중심으로 구성한다.

---

## 이 프로젝트 구조

```
wedding/index.html          ← 모든 CSS·JS 인라인. 빌드 없음. 이 파일 하나가 전부.
wedding/pictures/*.jpg      ← 원본 고해상도 (수 MB/장)
wedding/pictures/thumbs/    ← 520px 썸네일 (30–150 KB/장). 갤러리·히어로 초기 표시용.
wedding/map.svg             ← 커스텀 경로 지도
votes-worker/src/index.js   ← Cloudflare Workers 백엔드 (투표 API)
```

외부 엔드포인트: `https://wedding-votes.wonjoong11.workers.dev`  
KV 바인딩: `VOTES` (namespace id: `adf1945952914d07a70452426663dcf3`)  
배포: `git push` → GitHub Pages 자동 반영. Worker 변경은 `cd votes-worker && npx wrangler deploy` 별도 필요.

---

## 함정 목록

### TRAP-1: GitHub Pages + 기존 React SW → 새 서브경로가 흰 화면

**언제 발생하나**  
`index.html`(React SPA)이 이미 배포된 GitHub Pages 저장소에 `/wedding/` 같은 서브경로를 추가할 때.

**증상**  
`wedding/index.html`이 분명히 존재하는데 브라우저에서 열면 흰 화면. 개발자 도구 Network 탭을 보면 React 앱의 JS를 불러온다.

**원인**  
React CRA가 등록한 Service Worker가 모든 URL을 가로채 캐시된 React 앱 shell을 반환한다.

**잘못된 접근**  
`service-worker.js` 파일을 저장소에서 그냥 삭제한다. → 이미 SW를 설치한 기존 방문자에게는 여전히 같은 문제가 발생한다. 새 방문자만 해결된다.

**올바른 처리**  
`service-worker.js`를 아래 내용으로 교체(파일 자체는 남긴다):
```js
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k)))));
  return self.clients.claim();
});
```
기존 방문자의 SW가 이 kill-switch로 업데이트되면서 캐시를 전부 삭제하고 제어권을 반환한다.

---

### TRAP-2: GitHub Pages(HTTPS) ↔ HTTP 백엔드 → 요청이 무음으로 차단됨

**증상**  
투표 API를 호출해도 응답이 없다. 콘솔에 에러가 없거나, 있어도 "Mixed Content" 경고만 뜬다. `fetch().catch()`가 항상 실행된다.

**원인**  
GitHub Pages는 HTTPS로만 서빙된다. HTTPS 페이지에서 HTTP 엔드포인트를 호출하면 브라우저가 mixed content 정책으로 요청 자체를 차단한다. 서버까지 요청이 도달하지 않으므로 서버 로그에도 아무것도 안 찍힌다.

**잘못된 접근**  
홈 서버(HTTP)를 백엔드로 사용하고 "나중에 HTTPS 붙이면 되지"라고 생각한다. → 브라우저 정책이라 우회 불가.

**올바른 처리**  
백엔드는 처음부터 HTTPS여야 한다. 이 프로젝트는 Cloudflare Workers를 사용한다(HTTPS 기본 제공). 자체 서버를 쓴다면 Let's Encrypt 인증서를 먼저 설정한다.

---

### TRAP-3: 백엔드 교체 후 데이터가 모두 사라진 것처럼 보임

**증상**  
Worker가 정상 응답하는데 하트 카운트가 전부 0. `GET /votes` → `{"my_votes":[]}`.

**잘못된 진단 순서**  
Worker가 배포됐는지, CORS가 맞는지부터 확인한다. → 둘 다 이상 없다고 나와서 원인을 못 찾는다.

**올바른 진단 순서**
```
1. curl https://.../votes  → 응답 오는지 (Worker 생존 확인)
2. curl -X POST .../vote -d '{"photo":"test","action":"up"}'  → 저장되는지 (쓰기 확인)
3. npx wrangler kv key list --binding VOTES  → KV에 실제 키가 있는지
```
3번에서 키가 없으면 → **마이그레이션 누락**.

**원인**  
Python/SQLite → Cloudflare KV처럼 저장소를 교체하면 새 저장소는 빈 상태로 시작한다. 코드를 교체했다고 데이터가 따라오지 않는다.

**올바른 처리**  
백엔드 교체 전에 기존 데이터를 새 저장소 포맷으로 변환하는 마이그레이션 스크립트를 먼저 작성한다. 이미 교체했다면: 데이터를 복구할 수 없으면 새로 시작하고, 기존 데이터가 보존되어 있으면 스크립트로 KV에 밀어넣는다.

KV 초기화(새로 시작):
```bash
cd votes-worker
npx wrangler kv key list --binding VOTES          # "votes", "ip:xxx.xxx.xxx.xxx" 등 확인
npx wrangler kv key delete --binding VOTES "votes"
# IP 키는 여러 개. 목록에 나온 것 전부 삭제.
npx wrangler kv key delete --binding VOTES "ip:xxx.xxx.xxx.xxx"
```

---

### TRAP-4: CORS 설정 — Origin 대소문자 불일치

**증상**  
`curl`로 직접 호출하면 정상인데 브라우저에서만 API 요청이 실패한다. 개발자 도구에 "CORS" 에러가 표시된다.

**원인**  
브라우저가 보내는 `Origin` 헤더는 주소창 URL의 스킴+호스트를 그대로 담는다. Worker의 `ALLOWED_ORIGIN`과 대소문자가 한 글자라도 다르면 `Access-Control-Allow-Origin` 값이 실제 Origin과 달라져 브라우저가 응답을 거부한다.

```js
// 잘못된 예: 실제 URL이 https://qkaTlehdrnf.github.io 인데
const ALLOWED_ORIGIN = 'https://qkatlehdrnf.github.io';  // 소문자로 잘못 씀
```

**확인 방법**  
실제 GitHub Pages URL로 직접 curl:
```bash
# GitHub Pages가 리다이렉트 없이 실제로 서빙하는 URL 확인
curl -sIL https://qkaTlehdrnf.github.io/wedding/ | grep -i "location\|200"

# 해당 URL을 Origin으로 달아서 CORS 헤더 확인
curl -sv https://wedding-votes.wonjoong11.workers.dev/votes \
  -H "Origin: https://qkaTlehdrnf.github.io" 2>&1 | grep -i "access-control-allow-origin"
```
응답의 `Access-Control-Allow-Origin` 값이 요청한 Origin과 정확히 일치해야 한다.

---

### TRAP-5: 원본 사진을 갤러리에 직접 쓰면 로딩이 수십 초

**증상**  
갤러리 스크롤이 버벅이고, 사진이 오래 안 뜬다. 페이지 초기 로드가 느리다.

**원인**  
원본 사진 한 장이 수 MB. 81장이면 수백 MB를 브라우저가 받아야 한다.

**올바른 구조**  
썸네일(520px, 30–150 KB)과 원본을 분리해서, 각 용도에 맞게 사용한다.

| 위치 | 사용 이미지 | 이유 |
|---|---|---|
| 갤러리 카드 | `thumbs/` 썸네일 | 화면에 작게 표시되므로 원본 불필요 |
| 히어로 첫 장 | `thumbs/` 썸네일 즉시 → 원본으로 교체 | 첫 인상이 중요, 지연 없이 뭔가 보여야 함 |
| 히어로 이후 | 원본 (`onload` 후 전환) | 이미 화면에 뭔가 있으므로 기다려도 됨 |
| 라이트박스 | `thumbs/` 즉시 → 원본 교체 | 열리는 순간 썸네일 표시, 원본 로드되면 swap |
| 백그라운드 프리패치 | 원본 | 페이지 로드 후 순차적으로 캐시에 올림 |

썸네일 생성:
```bash
# ImageMagick — 520px 너비로 일괄 리사이즈
mogrify -path wedding/pictures/thumbs -resize 520x wedding/pictures/*.jpg
```

히어로 첫 장 즉시 표시 패턴:
```js
// 썸네일로 즉시 표시하고, 원본은 로드되면 같은 슬라이드에 조용히 교체
slides[next].src = `./pictures/thumbs/${name}`;
slides[next].classList.add('active');
current = next;
const hi = new Image();
hi.onload = () => { slides[current].src = hi.src; };
hi.src = `./pictures/${name}`;
```

---

### TRAP-6: 이미지 병렬 프리패치 → 모바일 네트워크 포화

**증상**  
갤러리 스크롤은 빠른데 라이트박스를 열면 원본이 오래 걸린다. 모바일에서 더 심하다.

**원인**  
`PHOTOS.forEach(name => new Image().src = ...)` 처럼 전체를 동시에 프리패치하면 모바일의 제한된 대역폭을 모두 잡아먹어 실제 사용 중인 요청(라이트박스 원본)이 대기한다.

**올바른 처리**  
한 장씩 순차 프리패치. `prefetchActive` 플래그로 동시 요청을 1개로 제한한다:
```js
let prefetchActive = false;
function doPrefetch() {
  if (prefetchActive || prefetchQueue.length === 0) return;
  prefetchActive = true;
  const name = prefetchQueue.shift();
  const hi = new Image();
  hi.onload = hi.onerror = () => { prefetchActive = false; doPrefetch(); };
  hi.src = `./pictures/${name}`;
}
```
사용자가 호버/터치한 카드는 `prefetchQueue` 맨 앞으로 이동시켜 우선 캐시한다.

---

### TRAP-7: 갤러리 셔플을 renderGallery() 안에서 매번 실행

**증상**  
"추천순 ↔ 랜덤" 버튼을 누를 때마다 랜덤 순서가 새로 바뀐다. 사용자가 기억하는 위치의 사진이 계속 달라진다.

**원인**  
`renderGallery()` 안에서 `[...PHOTOS].sort(() => Math.random() - 0.5)`를 실행하면 호출할 때마다 다른 순서가 나온다.

**올바른 처리**  
모듈 스코프(최상단)에서 딱 한 번 계산해 `SHUFFLED` 상수에 저장. 히어로 슬라이드쇼와 갤러리가 같은 배열을 공유:
```js
// 스크립트 최상단 — 페이지 로드 시 한 번만 실행
const SHUFFLED = [...PHOTOS].sort(() => Math.random() - 0.5);
```

---

### TRAP-8: 라이트박스 prev/next 탐색 시 정렬 상태 무시

**증상**  
"추천순" 정렬 상태에서 라이트박스를 열고 → 다음 사진으로 넘기면 추천순이 아닌 엉뚱한 사진으로 간다.

**원인**  
`currentLightboxIndex`를 `PHOTOS` 또는 `SHUFFLED` 고정 배열 기준으로 계산하면 현재 갤러리 표시 순서와 다르다.

**올바른 처리**  
탐색할 때마다 현재 정렬 상태를 반영하는 `getDisplayOrder()`를 호출해 배열을 가져온다:
```js
function getDisplayOrder() {
  return sortByHearts
    ? [...PHOTOS].sort((a, b) => (heartCounts[b] || 0) - (heartCounts[a] || 0))
    : SHUFFLED;
}
function navigateLightbox(dir) {
  const order = getDisplayOrder();
  currentLightboxIndex = (currentLightboxIndex + dir + order.length) % order.length;
  _loadLightboxPhoto(order[currentLightboxIndex], order.length);
}
```

---

### TRAP-9: 터치 스와이프 구현 시 기존 클릭 핸들러 충돌

**증상**  
라이트박스를 스와이프하면 사진이 넘어가지만 동시에 라이트박스가 닫혀버린다.

**원인**  
라이트박스 배경에 `onclick="closeLightbox()"` 가 있는데, 스와이프 직후 브라우저가 `touchend`→`click` 이벤트를 순서대로 발생시킨다.

**잘못된 접근**  
`touchend`에서 `event.preventDefault()`를 호출한다. → `passive: true` 기본값과 충돌해 에러.

**올바른 처리**  
스와이프가 발생한 경우(deltaX > 50px)에만 `navigateLightbox()`를 호출한다. 스와이프 거리가 충분히 크면 브라우저는 `click` 이벤트를 발생시키지 않는다(이미 드래그로 처리했으므로):
```js
lb.addEventListener('touchstart', e => { startX = e.touches[0].clientX; }, { passive: true });
lb.addEventListener('touchend', e => {
  const dx = e.changedTouches[0].clientX - startX;
  if (Math.abs(dx) > 50) navigateLightbox(dx < 0 ? 1 : -1);
  // 50px 미만은 탭 → 기존 onclick="closeLightbox()" 그대로 동작
});
```

---

## 현재 기능 목록 (상태: 2026-05-05)

| 섹션 | 핵심 구현 |
|---|---|
| 인트로 | 꽃잎 캔버스 (`requestAnimationFrame`), 클릭 해제 |
| 히어로 | 슬라이드 2장 교대, 5초 크로스페이드, 첫 장은 썸네일 즉시 |
| D-day | `setInterval(1000)`, `WEDDING = new Date('2026-08-17T11:00:00')` |
| 갤러리 | 썸네일 레이지 로딩 (`IntersectionObserver`), 원본 순차 프리패치 |
| 라이트박스 | prev/next 버튼·키보드·스와이프, 사진 카운터, 썸네일→원본 swap |
| 하트 투표 | Cloudflare Workers KV, IP 중복 방지, 낙관적 UI |
| 지도 | `map.svg` + 카카오맵·네이버지도 외부 링크 |
| 계좌 | 아코디언, `navigator.clipboard` + `execCommand` fallback |
| 공유 FAB | `navigator.share` (모바일) + 클립보드 링크 복사 (데스크톱) |

---

## 자주 하는 작업

**사진 추가**
1. `wedding/pictures/`에 JPG 복사
2. `mogrify -path wedding/pictures/thumbs -resize 520x wedding/pictures/새파일.jpg`
3. `wedding/index.html`의 `PHOTOS` 배열에 파일명 추가

**Worker 배포**
```bash
cd votes-worker && npx wrangler deploy
```

**KV 초기화**
```bash
cd votes-worker
npx wrangler kv key list --binding VOTES
npx wrangler kv key delete --binding VOTES "votes"
npx wrangler kv key delete --binding VOTES "ip:xxx.xxx.xxx.xxx"  # 목록에 있는 IP 키 전부
```

**신부측 혼주 이름 입력**  
`wedding/index.html` → `invitation-family` 섹션, 두 번째 `family-line`의 `&nbsp;` 부분 교체
