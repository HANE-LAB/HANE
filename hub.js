// HANE 入口页的动效。做法和参数移植自 Nova（sanidhyy/game-website，MIT，见 THIRD_PARTY_NOTICES.md）：
// 首屏视频轮换、中间预览下一部并点开放大、滚动时把首屏裁成斜切多边形、标题逐词翻入、图片从卡片放大到全屏。
// 原作用 React + GSAP 写，这里用原生 JS 做同样的计算，GSAP 的缓动换成对应的公式和 cubic-bezier。

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
// 和 HANE Lantern 一样，「减少动态」不改写默认播放：Windows 关掉动画效果时浏览器也会报告它，整页就成了静止的封面。想要静止的人用左下角的暂停
const saveData = navigator.connection?.saveData === true;
const clamp01 = x => Math.min(1, Math.max(0, x));
const inOut = t => t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;   // GSAP power1.inOut
const out = t => 1 - (1 - t) * (1 - t);                                // GSAP power1.out（时间线的默认缓动）

const WORLDS = [
  { short: '灯下', title: '灯下千本鸟居', en: 'HANE LANTERN · 第一部', desc: '她发的每一条动态，一个月一座鸟居，围成一座会转的神社。',
    href: 'https://hane-lab.github.io/HANE-LANTERN/', bv: 'https://www.bilibili.com/video/BV1icWb6BEQD/', video: 'video/lantern.mp4', poster: 'video/lantern.webp', pos: '6% 50%' },
  { short: '海上', title: '海上千本鸟居', en: 'HANE VOYAGE · 第二部', desc: '大航海名单上的每一个人是一艘船，跟着她从 2021 年航行到今天。',
    href: 'https://hane-lab.github.io/HANE-VOYAGE/', bv: 'https://www.bilibili.com/video/BV1PuWE6pEMk/', video: 'video/voyage.mp4', poster: 'video/voyage.webp', pos: '50% 50%' },
  { short: '云中', title: '云中千本鸟居', en: 'HANE FLIGHT · 第三部', desc: '她播过的每一夜是云中的一座鸟居，舰长化作小鸟跟着她飞到今天。',
    href: 'https://hane-lab.github.io/HANE-FLIGHT/', bv: 'https://www.bilibili.com/video/BV1gQ4i6tEQx/', video: 'video/flight.mp4', poster: 'video/flight.webp', pos: '50% 50%' },
];
const DWELL = 9000;   // 每一部停留多久再自动换下一部

// ---------- 首屏：视频轮换 ----------
const hero = $('#hero'), frame = $('.frame', hero), copy = $('.world', hero), peek = $('.peek', hero);
const chips = $$('.chip', hero), toggle = $('.hold', hero);
let [front, back] = $$('.v', hero);
let cur = 0, busy = false, timer = 0, heroOn = true, paused = saveData, peeking = false;

const load = (v, w) => {
  v.style.setProperty('--pos', w.pos);
  v.poster = w.poster;
  v.src = w.video;
};
const play = v => { if (!paused && heroOn) v.play().catch(() => {}); };

function setCopy(i) {
  const w = WORLDS[i];
  copy.classList.add('swap');
  setTimeout(() => {
    $('.w-en', copy).textContent = w.en;
    $('.w-title', copy).textContent = w.title;
    $('.w-desc', copy).textContent = w.desc;
    const go = $('.w-go', copy);
    go.href = w.href;
    $('span', go).textContent = '进入' + w.short;
    $('.w-bv', copy).href = w.bv;
    copy.classList.remove('swap');
  }, 240);
  chips.forEach((c, j) => { c.classList.toggle('on', j === i); c.setAttribute('aria-pressed', j === i); });
}
// 中间的小窗是下一部；换过去以后，小窗换成再下一部并从零放大（原作 gsap.from scale 0，1.5 秒）
function setPeek(i) {
  const w = WORLDS[i];
  peek.setAttribute('aria-label', '下一部：' + w.title);
  $('img', peek).src = w.poster;
  $('em', peek).textContent = 'NEXT · ' + w.short;
  peek.classList.remove('pop');
  void peek.offsetWidth;
  peek.classList.add('pop');
}
// 点开下一部：新视频从中间 16rem 的方块放大到全屏（原作 1 秒，power1.inOut）
function go(i) {
  if (busy || i === cur) return;
  busy = true;
  load(back, WORLDS[i]);
  back.classList.remove('idle');
  back.classList.add('grow');
  play(back);
  requestAnimationFrame(() => requestAnimationFrame(() => back.classList.add('full')));
  setCopy(i);
  setPeek((i + 1) % WORLDS.length);
  setTimeout(() => {
    front.pause();
    front.classList.add('idle');
    back.classList.remove('grow', 'full');
    [front, back] = [back, front];
    cur = i;
    busy = false;
    schedule();
  }, 1050);
}
function schedule() {
  clearTimeout(timer);
  hero.classList.remove('tick');
  if (paused) return;
  void hero.offsetWidth;
  hero.classList.add('tick');
  timer = setTimeout(() => (heroOn && !document.hidden && !peeking ? go((cur + 1) % WORLDS.length) : schedule()), DWELL);
}
peek.addEventListener('click', () => go((cur + 1) % WORLDS.length));
peek.addEventListener('pointerenter', () => { peeking = true; });
peek.addEventListener('pointerleave', () => { peeking = false; });
chips.forEach((c, j) => c.addEventListener('click', () => go(j)));
toggle.addEventListener('click', () => {
  paused = !paused;
  toggle.setAttribute('aria-pressed', paused);
  toggle.textContent = paused ? '播放画面' : '暂停画面';
  if (paused) front.pause(); else play(front);
  schedule();
});
toggle.setAttribute('aria-pressed', paused);
toggle.textContent = paused ? '播放画面' : '暂停画面';
new IntersectionObserver(([e]) => {
  heroOn = e.isIntersecting;
  if (heroOn) play(front); else front.pause();
}).observe(hero);

load(front, WORLDS[0]);
setPeek(1);
play(front);
schedule();

// ---------- 滚动：首屏裁成斜切多边形（原作 polygon(14% 0, 72% 0, 90% 90%, 0 100%)，右下圆角 40%） ----------
function morph() {
  const p = inOut(clamp01(scrollY / (innerHeight * 0.5)));
  frame.style.clipPath = `polygon(${14 * p}% 0%, ${100 - 28 * p}% 0%, ${100 - 10 * p}% ${100 - 10 * p}%, 0% 100%)`;
  frame.style.borderRadius = `0 0 ${40 * p}% ${10 * p}%`;
}

// ---------- 标题逐词翻入：顶边进到视口底部以上 100px 时播放，往回滚时倒放 ----------
const titles = $$('.atitle');
titles.forEach(t => $$('.aw', t).forEach((w, i) => w.style.setProperty('--i', i)));
const titleCheck = () => titles.forEach(t => t.classList.toggle('in', t.getBoundingClientRect().top < innerHeight - 100));

// ---------- 图片从卡片放大到全屏：钉住 800px 的滚动（原作 scrub 0.5，这里用 0.17 秒的平滑追上） ----------
const clip = $('.clip'), mask = $('.mask', clip), sub = $('.about-sub', clip);
let cp = 0, cpTarget = 0;

// 卡片里的图：灯下、海上、云中各一张，每 4 秒交叉淡化到下一张；这一段看不见、页面在后台或按了暂停时不换
const shots = $$('img', mask);
let shot = 0, clipOn = false;
new IntersectionObserver(([e]) => { clipOn = e.isIntersecting; }).observe(clip);
setInterval(() => {
  if (paused || !clipOn || document.hidden) return;
  shots[shot].classList.remove('on');
  shot = (shot + 1) % shots.length;
  shots[shot].classList.add('on');
}, 4000);
function applyClip(p) {
  const e = out(p), w0 = innerWidth > 768 ? innerWidth * 0.3 : Math.min(384, innerWidth * 0.86);
  mask.style.width = `${w0 + (innerWidth - w0) * e}px`;
  mask.style.height = `${innerHeight * (0.6 + 0.4 * e)}px`;
  mask.style.borderRadius = `${24 * (1 - e)}px`;
  sub.style.opacity = 1 - clamp01(p * 2.5);
}

// ---------- 三部作品：桌面上悬停时播放 ----------
if (matchMedia('(hover: hover)').matches && !saveData) {
  for (const part of $$('.part')) {
    const v = $('video', part);
    part.addEventListener('mouseenter', () => { v.preload = 'auto'; v.play().catch(() => {}); });
    part.addEventListener('mouseleave', () => v.pause());
  }
}

// ---------- 导航：往下滚收起，往上滚出现（原作 navbar 的做法） ----------
const nav = $('.top');
let lastY = scrollY;
function navTick() {
  const y = scrollY;
  if (y <= 0) nav.classList.remove('float', 'away');
  else if (y > lastY + 2) nav.classList.add('float', 'away');
  else if (y < lastY - 2) { nav.classList.add('float'); nav.classList.remove('away'); }
  lastY = y;
}
nav.addEventListener('focusin', () => nav.classList.remove('away'));

// ---------- 每一帧：只在滚动或平滑还没追上时跑 ----------
let ticking = false, last = 0;
function frameTick(now) {
  const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
  last = now;
  morph();
  navTick();
  titleCheck();
  cpTarget = clamp01(-clip.getBoundingClientRect().top / 800);
  cp += (cpTarget - cp) * (1 - Math.exp(-dt / 0.17));
  if (Math.abs(cpTarget - cp) < 1e-4) cp = cpTarget;
  applyClip(cp);
  if (cp !== cpTarget) requestAnimationFrame(frameTick);
  else { ticking = false; last = 0; }
}
const kick = () => { if (!ticking) { ticking = true; requestAnimationFrame(frameTick); } };
addEventListener('scroll', kick, { passive: true });
addEventListener('resize', kick);
kick();
