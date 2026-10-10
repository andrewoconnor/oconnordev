import * as THREE from "three";
import Globe from "globe.gl";
import { KTX2Loader } from "three/addons/loaders/KTX2Loader.js";
import { DRUMS } from "./data.js";

// ── Named constants ───────────────────────────────────────────────────────────
const CAMERA_ALTITUDE = 1.8; // point-of-view altitude for navigation
const CAMERA_ALTITUDE_INITIAL = 2.2; // starting altitude on first load
const CAMERA_X_OFFSET_DESKTOP = -180; // px to shift camera right on desktop
const RESIZE_DEBOUNCE_MS = 100; // ms to wait before responding to resize
const SWIPE_THRESHOLD_PX = 50; // min px swipe distance to navigate lightbox
const SCALE_HOVER = 1.35; // globe marker scale on hover
const SCALE_LERP_FACTOR = 0.15; // lerp speed for marker scale animation
const SCALE_LERP_EPSILON = 0.001; // threshold below which lerp is skipped
const MARKER_BORDER_W = 4.6; // world-unit width of marker border plane
const MARKER_BORDER_H = 3.6; // world-unit height of marker border plane
const MARKER_IMG_W = 4; // world-unit width of marker image plane
const MARKER_IMG_H = 3; // world-unit height of marker image plane
const MARKER_IMG_Z = 0.15; // z-offset of image plane above border plane
const STARS_RADIUS = 500; // radius of the background star sphere
const ANISOTROPY_CAP = 16; // cap on texture anisotropic filtering
const PIXEL_RATIO_CAP = 2; // max device pixel ratio for rendering
const MSAA_SAMPLES = 4; // multisample count for the render buffers
const NORMAL_SCALE_MOBILE = 0.8; // globe normal map intensity on mobile
const NORMAL_SCALE_DESKTOP = 1.0; // globe normal map intensity on desktop
const AMBIENT_INTENSITY = 0.8; // fill light, physical units (three r155+)
const KEY_LIGHT_INTENSITY = 3.0; // camera-mounted key light
const KEY_LIGHT_POSITION = [6, 4, 7]; // key light offset, in camera space
const SPECULAR_COLOR = 0x444444; // globe specular colour
const SHININESS_MOBILE = 8; // globe specular shininess on mobile
const SHININESS_DESKTOP = 15; // globe specular shininess on desktop
const LOADING_WATCHDOG_MS = 20000; // ms before the loading screen gives up
const MARKER_COLOR_ACTIVE = 0xce2029; // border colour for the selected marker
const MARKER_COLOR_IDLE = 0x00ffff; // border colour for unselected markers

// ── DOM refs ──────────────────────────────────────────────────────────────────
const panelDragHandle = document.getElementById("panelDragHandle");
const lightbox = document.getElementById("lightbox");
const lightboxImg = document.getElementById("lightboxImg");
const lbPrev = document.getElementById("lbPrev");
const lbNext = document.getElementById("lbNext");
const lbClose = document.getElementById("lbClose");
const lbCounter = document.getElementById("lbCounter");
const globeTooltip = document.getElementById("globeTooltip");
const searchBar = document.getElementById("searchBar");
const entryList = document.getElementById("entryList");
const infoPanel = document.getElementById("infoPanel");
const globeViz = document.getElementById("globeViz");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const panelBody = document.getElementById("panelBody");
const collapseBtn = document.getElementById("collapseBtn");
const activeTitle = document.getElementById("activeTitle");
const siteTitle = document.getElementById("siteTitle");
const HAS_HOVER = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

// ── State ─────────────────────────────────────────────────────────────────────
let currentEntry = null;
let currentImageIdx = 0;
const allEntries = [...DRUMS].sort((a, b) => a.year - b.year);
let filteredEntries = [...allEntries];
let globe;
let _globeW = window.innerWidth;
let _globeH = window.innerHeight;
let starsMesh = null;
let ktx2Loader = null;
let _appliedTier = null;
const _tierLoads = new Map();
let _starsUrl = null;
let _appliedPixelRatio = null;
let _scaleAnimating = false;
let _scaleLoopRunning = false;

// ── Three.js reusables ────────────────────────────────────────────────────────
const textureLoader = new THREE.TextureLoader();
const _scaleVec = new THREE.Vector3();
const _lookVec = new THREE.Vector3();
const borderGeom = new THREE.PlaneGeometry(MARKER_BORDER_W, MARKER_BORDER_H);
const imgGeom = new THREE.PlaneGeometry(MARKER_IMG_W, MARKER_IMG_H);

// ── Utilities ─────────────────────────────────────────────────────────────────
const formatYear = (y) => (y < 0 ? `${Math.abs(y)} BCE` : `${y} CE`);
const formatDisplayDate = (e) => e.dateLabel || formatYear(e.year);

allEntries.forEach((e) => {
  e._displayDate = formatDisplayDate(e);
  e._searchText =
    `${e.title} ${e.region} ${e._displayDate} ${e.type} ${e.description}`.toLowerCase();
});

function isMobileLike() {
  return (
    window.innerWidth <= 600 || window.matchMedia("(hover: none) and (pointer: coarse)").matches
  );
}

function getMaxTextureSize() {
  if (!globe) return 4096;
  if (_maxTextureSize === null) {
    const gl = globe.renderer().getContext();
    _maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
  }
  return _maxTextureSize;
}
let _maxTextureSize = null;

function maxAnisotropy() {
  const hw = globe?.renderer?.().capabilities?.getMaxAnisotropy?.() ?? 1;
  return Math.min(ANISOTROPY_CAP, hw);
}

// ── Globe texture tiers ───────────────────────────────────────────────────────
// A globe is nearly always seen minified, so the GPU samples a mid mip level
// rather than level 0. scripts/build-globe-textures.sh therefore sharpens every
// mip level of every tier.
//
// Tiers upgrade in the background after first paint; zoom takes priority over
// queued background work. The ceiling depends on what the
// GPU can hold, not on whether the device is a phone: a modern phone reports
// MAX_TEXTURE_SIZE 16384 and looked far worse than it had to when it was capped
// at the 4k tier.
const TIER_FIRST_PAINT = "2k";
const TIER_IDLE = "4k";
const TIER_ZOOM = "8k";
const TIER_ULTRA = "10k";
const TIER_ORDER = [TIER_FIRST_PAINT, TIER_IDLE, TIER_ZOOM, TIER_ULTRA];

// Level 0 width of each tier, and the camera altitude below which it is worth
// fetching. Below the last threshold the texture is magnified, so the camera is
// stopped there instead. See MIN_ALTITUDE_BY_TIER.
const TIER_WIDTH = { "2k": 2048, "4k": 4096, "8k": 8192, "10k": 10800 };
const TIER_ALTITUDE = { "8k": 1.0, "10k": 0.5 };

// Lowest altitude worth allowing for a given ceiling tier. Each value keeps the
// texture at roughly 2 screen pixels per texel at a 1200px viewport height.
// Without this the camera can reach altitude 0.001, where the 4k tier stretches
// one texel across 39 screen pixels.
const MIN_ALTITUDE_BY_TIER = { "2k": 1.4, "4k": 0.7, "8k": 0.45, "10k": 0.3 };

// The normal map stops at 8k; relief is low frequency and a 10800px normal map
// would double GPU memory for no visible gain. Keep it in step with the build
// script's NORMAL_MAX_WIDTH.
const NORMAL_MAX_TIER = TIER_ZOOM;

const tierRank = (tier) => TIER_ORDER.indexOf(tier);

function saveDataRequested() {
  const conn = navigator.connection;
  return !!conn && (conn.saveData || /(^|-)2g$/.test(conn.effectiveType || ""));
}

// Phone-sized viewports stop at the 8k tier. The reason is GPU memory, not
// screen size: a 10800px colour map plus its mip chain costs about 78 MB of
// video memory, and mobile Safari has no reliable way to report a budget. The
// 8k tier was already proven on phones by the previous build. Judge by viewport
// rather than pointer media, because those are unreliable under emulation.
function isPhoneLike() {
  return Math.min(window.innerWidth, window.innerHeight) <= 500;
}

// Highest tier this device can hold, ignoring form factor.
function tierCeiling() {
  if (saveDataRequested()) return TIER_FIRST_PAINT;
  const maxSize = getMaxTextureSize();
  let ceiling = TIER_FIRST_PAINT;
  for (const tier of TIER_ORDER) {
    if (maxSize >= TIER_WIDTH[tier]) ceiling = tier;
  }
  if (isPhoneLike() && tierRank(ceiling) > tierRank(TIER_ZOOM)) return TIER_ZOOM;
  return ceiling;
}

function cappedTier(tier) {
  const ceiling = tierCeiling();
  return tierRank(tier) > tierRank(ceiling) ? ceiling : tier;
}

// Tier wanted for a camera altitude, before the device ceiling is applied.
function tierForAltitude(altitude) {
  let wanted = TIER_IDLE;
  for (const tier of TIER_ORDER) {
    const threshold = TIER_ALTITUDE[tier];
    if (threshold !== undefined && altitude <= threshold) wanted = tier;
  }
  return wanted;
}

function tierAssets(tier, ext = "ktx2") {
  const starsRes = tierRank(tier) >= tierRank(TIER_ZOOM) ? "8k" : "4k";
  const normalRes = tierRank(tier) > tierRank(NORMAL_MAX_TIER) ? NORMAL_MAX_TIER : tier;
  return {
    map: `/images/globe/earthmap${tier}.${ext}`,
    normal: `/images/globe/earthnormal${normalRes}.${ext}`,
    spec: `/images/globe/earthspec${tier}.${ext}`,
    stars: `/images/globe/stars${starsRes}.${ext}`,
  };
}

// Stop the camera before the best available texture turns into mush.
function applyZoomLimit() {
  if (!globe) return;
  const radius = typeof globe.getGlobeRadius === "function" ? globe.getGlobeRadius() : 100;
  const minAltitude = MIN_ALTITUDE_BY_TIER[tierCeiling()] ?? 0.7;
  const controls = globe.controls();
  controls.minDistance = radius * (1 + minAltitude);
  if (globe.pointOfView().altitude < minAltitude) {
    const pov = globe.pointOfView();
    globe.pointOfView({ lat: pov.lat, lng: pov.lng, altitude: minAltitude }, 0);
  }
}

function setStarsSphere(tex) {
  if (starsMesh?.material.map === tex) return;
  if (starsMesh) {
    globe.scene().remove(starsMesh);
    starsMesh.geometry.dispose();
    starsMesh.material.map?.dispose();
    starsMesh.material.dispose();
  }
  const geom = new THREE.SphereGeometry(STARS_RADIUS, 32, 16);
  const mat = new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide });
  starsMesh = new THREE.Mesh(geom, mat);
  globe.scene().add(starsMesh);
}

function loadKTX2Texture(url, { srgb = false } = {}) {
  return new Promise((resolve, reject) => {
    ktx2Loader.load(
      url,
      (tex) => {
        if (srgb) tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = maxAnisotropy();
        resolve(tex);
      },
      undefined,
      reject,
    );
  });
}

function loadImageTexture(url, { srgb = false } = {}) {
  return new Promise((resolve, reject) => {
    textureLoader.load(
      url,
      (tex) => {
        if (srgb) tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = maxAnisotropy();
        resolve(tex);
      },
      undefined,
      reject,
    );
  });
}

const _pendingTextureLoads = new Set();

function loadTierTextures(tier, ext = "ktx2") {
  const a = tierAssets(tier, ext);
  const load = ext === "ktx2" ? loadKTX2Texture : loadImageTexture;
  const loaded = new Set();
  let failed = false;
  const trackedLoad = (url, options) => {
    const pending = load(url, options)
      .then((tex) => {
        if (failed) disposeUnusedTextures([tex]);
        else loaded.add(tex);
        return tex;
      })
      .finally(() => _pendingTextureLoads.delete(pending));
    _pendingTextureLoads.add(pending);
    return pending;
  };
  // Cache only the star field actually installed in the scene, not completed loads.
  const stars =
    a.stars === _starsUrl ? Promise.resolve(null) : trackedLoad(a.stars, { srgb: true });
  return Promise.all([
    trackedLoad(a.map, { srgb: true }),
    trackedLoad(a.normal),
    trackedLoad(a.spec),
    stars,
  ])
    .then(([map, normal, spec, starsTex]) => ({
      map,
      normal,
      spec,
      stars: starsTex,
      starsUrl: a.stars,
    }))
    .catch((err) => {
      failed = true;
      disposeUnusedTextures(loaded);
      loaded.clear();
      throw err;
    });
}

function disposeUnusedTextures(textures) {
  const mat = globe?.globeMaterial();
  const active = new Set([mat?.map, mat?.normalMap, mat?.specularMap, starsMesh?.material.map]);
  for (const texture of new Set(textures)) {
    if (texture && !active.has(texture)) texture.dispose();
  }
}

function applyGlobeTextures(tex, tier, mobile = isMobileLike()) {
  // Recheck after the asynchronous loads: a newer tier may already be active.
  if (
    !globe ||
    tierRank(tier) <= tierRank(_appliedTier) ||
    tierRank(tier) > tierRank(tierCeiling())
  ) {
    disposeUnusedTextures([tex.map, tex.normal, tex.spec, tex.stars]);
    return;
  }
  const mat = globe.globeMaterial();
  const previous = [mat.map, mat.normalMap, mat.specularMap];

  mat.map = tex.map;
  // A normal map instead of a bump map: bump mapping derives the slope from
  // screen-space derivatives, which breaks up once the globe is minified.
  mat.bumpMap = null;
  mat.normalMap = tex.normal;
  mat.normalScale.setScalar(mobile ? NORMAL_SCALE_MOBILE : NORMAL_SCALE_DESKTOP);
  mat.specularMap = tex.spec;
  mat.specular = new THREE.Color(SPECULAR_COLOR);
  mat.shininess = mobile ? SHININESS_MOBILE : SHININESS_DESKTOP;
  mat.needsUpdate = true;

  globe.scene().background = null;
  if (tex.stars) {
    setStarsSphere(tex.stars);
    _starsUrl = tex.starsUrl;
  }

  disposeUnusedTextures(previous);
  _appliedTier = tier;
}

function switchTier(tier) {
  if (_tierLoads.has(tier)) return _tierLoads.get(tier);
  if (!globe || tierRank(tier) <= tierRank(_appliedTier)) return Promise.resolve();
  const pending = loadTierTextures(tier)
    .then((tex) => applyGlobeTextures(tex, tier))
    .catch((err) => console.warn(`globe: staying on the ${_appliedTier} tier`, err))
    .finally(() => {
      if (_tierLoads.get(tier) === pending) _tierLoads.delete(tier);
    });
  _tierLoads.set(tier, pending);
  return pending;
}

let _upgradeBusy = false;
let _upgradeScheduled = false;
let _zoomTier = null;
const _backgroundAttempts = new Set();

function nextBackgroundTier() {
  return TIER_ORDER.find(
    (tier) =>
      tierRank(tier) > tierRank(_appliedTier) &&
      tierRank(tier) <= tierRank(tierCeiling()) &&
      !_backgroundAttempts.has(tier),
  );
}

function runTextureUpgrade() {
  if (_upgradeBusy || !globe) return;
  const wanted = _zoomTier && cappedTier(_zoomTier);
  _zoomTier = null;
  const tier = wanted && tierRank(wanted) > tierRank(_appliedTier) ? wanted : nextBackgroundTier();
  if (!tier) return;
  _upgradeBusy = true;
  _backgroundAttempts.add(tier);
  switchTier(tier)
    .then(() => Promise.allSettled([..._pendingTextureLoads]))
    .finally(() => {
      _upgradeBusy = false;
      if (_zoomTier) runTextureUpgrade();
      else upgradeTexturesWhenIdle();
    });
}

function upgradeTexturesWhenIdle() {
  if (_upgradeBusy || _upgradeScheduled || !nextBackgroundTier()) return;
  _upgradeScheduled = true;
  const start = () => {
    _upgradeScheduled = false;
    runTextureUpgrade();
  };
  if (typeof requestIdleCallback === "function") requestIdleCallback(start, { timeout: 3000 });
  else setTimeout(start, 500);
}

// Zoom bypasses idle scheduling, but never overlaps the current tier. It takes
// the next available slot ahead of any intermediate background upgrades.
function upgradeTexturesOnZoom() {
  const controls = globe.controls();
  let scheduled = false;
  const check = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      const wanted = cappedTier(tierForAltitude(globe.pointOfView().altitude));
      if (tierRank(wanted) > tierRank(_appliedTier) && !_backgroundAttempts.has(wanted)) {
        _zoomTier = wanted;
        runTextureUpgrade();
      }
    });
  };
  controls.addEventListener("change", check);
}

function applyRendererTuning() {
  if (!globe || typeof globe.renderer !== "function") return;
  const ratio = Math.min(window.devicePixelRatio || 1, PIXEL_RATIO_CAP);
  globe.renderer().setPixelRatio(ratio);

  // globe.gl always draws through an EffectComposer, so the default framebuffer
  // and its antialiasing are never used. three builds the composer buffers with
  // no multisampling, and the composer keeps the pixel ratio it saw when it was
  // built. Without both fixes below the scene is aliased and then rescaled.
  const composer =
    typeof globe.postProcessingComposer === "function" ? globe.postProcessingComposer() : null;
  if (!composer) return;

  for (const rt of [composer.renderTarget1, composer.renderTarget2]) {
    if (rt && rt.samples !== MSAA_SAMPLES) {
      rt.samples = MSAA_SAMPLES;
      rt.dispose();
    }
  }
  if (_appliedPixelRatio !== ratio) {
    composer.setPixelRatio(ratio);
    _appliedPixelRatio = ratio;
  }
}

function applyCameraOffset() {
  if (!globe) return;
  const cam = globe.camera();
  const panelOpen = !infoPanel.classList.contains("collapsed");
  if (panelOpen) {
    if (isMobileLike()) {
      const panelH = infoPanel.getBoundingClientRect().height;
      cam.setViewOffset(_globeW, _globeH, 0, Math.round(panelH / 2), _globeW, _globeH);
    } else {
      cam.setViewOffset(_globeW, _globeH, CAMERA_X_OFFSET_DESKTOP, 0, _globeW, _globeH);
    }
  } else {
    cam.clearViewOffset();
  }
  cam.updateProjectionMatrix();
}

// ── Lightbox ──────────────────────────────────────────────────────────────────
function openLightbox(idx) {
  const imgs = currentEntry?.images;
  if (!imgs?.length) return;
  currentImageIdx = ((idx % imgs.length) + imgs.length) % imgs.length;
  lightboxImg.src = imgs[currentImageIdx].src;
  const hasMultiple = imgs.length > 1;
  lbCounter.textContent = hasMultiple ? `${currentImageIdx + 1} / ${imgs.length}` : "";
  lbPrev.classList.toggle("hidden", !hasMultiple);
  lbNext.classList.toggle("hidden", !hasMultiple);
  lightbox.classList.add("open");
}

function navigateLightbox(dir) {
  if (currentEntry?.images) openLightbox(currentImageIdx + dir);
}

lbPrev.addEventListener("click", (e) => {
  e.stopPropagation();
  navigateLightbox(-1);
});
lbNext.addEventListener("click", (e) => {
  e.stopPropagation();
  navigateLightbox(1);
});
lbClose.addEventListener("click", (e) => {
  e.stopPropagation();
  lightbox.classList.remove("open");
});
lightbox.addEventListener("click", () => lightbox.classList.remove("open"));

let touchStartX = null;
lightbox.addEventListener(
  "touchstart",
  (e) => {
    touchStartX = e.touches[0].clientX;
  },
  { passive: true },
);
lightbox.addEventListener("touchend", (e) => {
  if (touchStartX === null) return;
  const dx = e.changedTouches[0].clientX - touchStartX;
  touchStartX = null;
  if (Math.abs(dx) > SWIPE_THRESHOLD_PX) navigateLightbox(dx < 0 ? 1 : -1);
  else lightbox.classList.remove("open");
});

document.addEventListener("keydown", (e) => {
  if (!lightbox.classList.contains("open")) return;
  if (e.key === "Escape") lightbox.classList.remove("open");
  else if (e.key === "ArrowLeft") navigateLightbox(-1);
  else if (e.key === "ArrowRight") navigateLightbox(1);
});

// Open lightbox when clicking the main image in any entry body
entryList.addEventListener("click", (e) => {
  if (e.target.closest(".entry-main-img") && currentEntry) openLightbox(currentImageIdx);
});

// ── Rendering helpers ─────────────────────────────────────────────────────────
function renderImageCredit(el, image) {
  const parts = [];
  if (image.credit) parts.push(image.credit);
  if (image.license && image.licenseUrl)
    parts.push(`Licensed under <a href="${image.licenseUrl}" target="_blank">${image.license}</a>`);
  el.innerHTML = parts.join(" ");
}

function renderSource(el, entry) {
  if (!entry?.source) {
    el.textContent = "";
    return;
  }
  const s = entry.source;
  const wrap = (val, suffix = ". ") => (val ? `${val}${suffix}` : "");
  const authors = Array.isArray(s.authors) ? s.authors.join(", ") : "";
  let citation = `Source: ${wrap(authors)}${wrap(s.year)}${wrap(`<em>${s.title}</em>`)}`;
  if (s.doi) citation += `<a href="${s.url}" target="_blank" rel="noopener">DOI: ${s.doi}</a>. `;
  else if (s.url) citation += `<a href="${s.url}" target="_blank" rel="noopener">Link</a>. `;
  el.innerHTML = citation + (s.note || "");
}

function renderGallery(body, entry, idx = 0) {
  const imgs = entry?.images || [
    {
      src: "/assets/question-image.svg",
    },
  ];
  currentImageIdx = Math.max(0, Math.min(idx, imgs.length - 1));
  const cur = imgs[currentImageIdx];
  const imgEl = body.querySelector(".entry-main-img");
  imgEl.classList.remove("portrait");
  imgEl.src = cur.src;
  imgEl.onload = () => {
    const { naturalWidth, naturalHeight } = imgEl;
    imgEl.classList.toggle("portrait", naturalHeight > naturalWidth);
  };
  body.querySelector(".entry-caption").textContent = cur.caption || "";
  renderImageCredit(body.querySelector(".entry-credit"), cur);
  const thumbs = body.querySelector(".entry-thumbs");
  thumbs.innerHTML = "";
  if (imgs.length > 1) {
    imgs.forEach((img, i) => {
      const t = document.createElement("img");
      t.src = img.src.replace(/\.(jpe?g|png)$/i, ".thumb.jpg");
      t.loading = "lazy";
      t.className = `entry-thumb${i === currentImageIdx ? " active" : ""}`;
      t.draggable = false;
      t.onclick = () => renderGallery(body, entry, i);
      thumbs.appendChild(t);
    });
  }
}

function buildEntryBody(entry) {
  if (entry._cachedBody) return entry._cachedBody;
  const wrapper = document.createElement("div");
  wrapper.className = "entry-body-wrapper";
  const body = document.createElement("div");
  body.className = "entry-body";
  body.innerHTML = `<div class="entry-meta"></div><img class="entry-main-img" src="" /><div class="entry-caption"></div><div class="entry-credit"></div><div class="entry-thumbs"></div><p class="entry-desc"></p><div class="entry-source"></div>`;
  body.querySelector(".entry-meta").textContent =
    `${entry.region} • ${entry._displayDate} • ${entry.type}`;
  body.querySelector(".entry-desc").textContent = entry.description;
  renderGallery(body, entry, 0);
  renderSource(body.querySelector(".entry-source"), entry);
  wrapper.appendChild(body);
  entry._cachedBody = wrapper;
  return wrapper;
}

// ── Entry list ────────────────────────────────────────────────────────────────
function activateEntry(entry, item) {
  const prev = entryList.querySelector(".entry-item.active");
  if (prev) prev.classList.remove("active");
  item.classList.add("active");
  item.classList.remove("body-collapsed");
  requestAnimationFrame(() => {
    panelBody.scrollTop = 0;
  });
  item.appendChild(buildEntryBody(entry)); // no-op if already appended (cached)
  if (currentEntry?.__borderMat) currentEntry.__borderMat.color.set(MARKER_COLOR_IDLE);
  currentEntry = entry;
  if (entry.__borderMat) entry.__borderMat.color.set(MARKER_COLOR_ACTIVE);
  activeTitle.textContent = entry.title;
}

function renderEntryList(entries) {
  allEntries.forEach((e) => {
    e._listItem = null;
  });
  entryList.innerHTML = "";
  if (!entries.length) {
    const msg = document.createElement("div");
    msg.style.cssText =
      "padding: 8px 10px; font-size: 13px; color: #888; border-radius: 8px; background: rgba(255,255,255,0.04); border: 1px solid transparent;";
    msg.textContent = "No entries found.";
    entryList.appendChild(msg);
    return;
  }
  const frag = document.createDocumentFragment();
  entries.forEach((entry) => {
    const item = document.createElement("div");
    item.className = `entry-item${entry === currentEntry ? " active" : ""}${entry === currentEntry && entry._bodyCollapsed ? " body-collapsed" : ""}`;
    entry._listItem = item;
    const row = document.createElement("div");
    row.className = "entry-row";
    row.innerHTML = `<div class="entry-title-group"><span class="entry-title">${entry.title}</span><span class="entry-date">${entry._displayDate}</span></div><span class="entry-chevron">▼</span>`;
    row.addEventListener("click", () => {
      if (item.classList.contains("active")) {
        item.classList.toggle("body-collapsed");
        entry._bodyCollapsed = item.classList.contains("body-collapsed");
        return;
      }
      activateEntry(entry, item);
      if (globe) {
        globe.controls().autoRotate = false;
        globe.pointOfView({ lat: entry.lat, lng: entry.lng, altitude: CAMERA_ALTITUDE }, 1000);
      }
    });
    item.appendChild(row);
    if (entry === currentEntry) item.appendChild(buildEntryBody(entry));
    frag.appendChild(item);
  });
  entryList.appendChild(frag);
}

function filterEntries() {
  const q = searchBar.value.trim().toLowerCase();
  filteredEntries = q ? allEntries.filter((e) => e._searchText.includes(q)) : [...allEntries];
  renderEntryList(filteredEntries);
}

function handleInteraction(d) {
  if (globe) {
    globe.controls().autoRotate = false;
    globe.pointOfView({ lat: d.lat, lng: d.lng, altitude: CAMERA_ALTITUDE }, 1000);
  }
  // Ensure entry is visible in list (clear filter if needed)
  if (!filteredEntries.includes(d)) {
    searchBar.value = "";
    filteredEntries = [...allEntries];
    renderEntryList(filteredEntries);
  }
  const item = d._listItem;
  if (item) activateEntry(d, item);
}

// ── Loading screen ────────────────────────────────────────────────────────────
function hideLoadingScreen() {
  const el = document.getElementById("loadingScreen");
  if (!el || el.classList.contains("fade-out")) return;
  el.classList.add("fade-out");
  el.addEventListener("transitionend", () => el.remove(), { once: true });
  // Reduced motion or interrupted CSS transitions may never emit transitionend.
  setTimeout(() => el.remove(), 1000);
}

// ── Globe initialisation ──────────────────────────────────────────────────────
async function init() {
  globe = Globe()(document.getElementById("globeViz"));
  globe
    .width(window.innerWidth)
    .height(window.innerHeight)
    .showAtmosphere(true)
    .atmosphereColor("#5dade2")
    .atmosphereAltitude(0.18)
    .customLayerData(allEntries)
    .customThreeObject((d) => {
      const group = new THREE.Group();

      const borderMat = new THREE.MeshBasicMaterial({
        color: d === currentEntry ? MARKER_COLOR_ACTIVE : MARKER_COLOR_IDLE,
        side: THREE.DoubleSide,
      });
      d.__borderMat = borderMat;
      const borderMesh = new THREE.Mesh(borderGeom, borderMat);

      const thumbSrc = d.images[0].src.replace(/\.(jpe?g|png)$/i, ".thumb.jpg");
      const imgTexture = textureLoader.load(thumbSrc, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = maxAnisotropy();
        const imgAspect = tex.image.width / tex.image.height;
        const planeAspect = MARKER_IMG_W / MARKER_IMG_H;
        if (imgAspect > planeAspect) {
          tex.repeat.set(planeAspect / imgAspect, 1);
          tex.offset.set((1 - tex.repeat.x) / 2, 0);
        } else {
          tex.repeat.set(1, imgAspect / planeAspect);
          tex.offset.set(0, (1 - tex.repeat.y) / 2);
        }
      });

      const imgMat = new THREE.MeshBasicMaterial({
        map: imgTexture,
        side: THREE.DoubleSide,
        transparent: true,
      });

      const imgMesh = new THREE.Mesh(imgGeom, imgMat);
      imgMesh.position.z = MARKER_IMG_Z;

      group.add(borderMesh);
      group.add(imgMesh);
      d.__threeObj = group;
      d.__targetScale = 1.0;
      return group;
    })
    .customThreeObjectUpdate((obj, d) => {
      if (!d.__coords) d.__coords = globe.getCoords(d.lat, d.lng, 0.04);
      const { x, y, z } = d.__coords;
      obj.position.set(x, y, z);
      obj.lookAt(_lookVec.set(x, y, z).multiplyScalar(2));
    })
    .onCustomLayerHover((d, prevD) => {
      if (!HAS_HOVER) return;
      document.body.style.cursor = d ? "pointer" : "default";
      if (prevD) {
        prevD.__targetScale = 1.0;
        startScaleAnimation();
      }
      if (d) {
        d.__targetScale = SCALE_HOVER;
        startScaleAnimation();
        globeTooltip.textContent = `${d.title} · ${d._displayDate}`;
        globeTooltip.style.display = "block";
      } else {
        globeTooltip.style.display = "none";
      }
    })
    .onCustomLayerClick(handleInteraction);

  const mobile = isMobileLike();
  applyRendererTuning();
  applyCameraOffset();
  globe.globeMaterial().color.set(0xffffff);

  // globe.gl installs its own lights: an AmbientLight at pi and a
  // DirectionalLight at 0.6*pi. Adding a second rig on top of those washed the
  // globe out and flattened the relief, so replace them with one deliberate
  // pair. Intensities are in the physical units three uses since r155. Do this
  // before the first texture arrives, so the first painted frame is correct.
  globe.lights([]);
  const keyLight = new THREE.DirectionalLight(0xffffff, KEY_LIGHT_INTENSITY);
  keyLight.position.set(...KEY_LIGHT_POSITION);
  globe.camera().add(keyLight);
  globe.scene().add(globe.camera());
  globe.scene().add(new THREE.AmbientLight(0xffffff, AMBIENT_INTENSITY));

  ktx2Loader = new KTX2Loader()
    .setTranscoderPath("/assets/basis-1.50.0-no-eval/")
    .detectSupport(globe.renderer());

  // Never leave the loading screen up because of a slow or dead texture load.
  const watchdog = setTimeout(() => {
    console.warn("globe: textures are still loading, revealing the scene anyway");
    hideLoadingScreen();
  }, LOADING_WATCHDOG_MS);

  try {
    applyGlobeTextures(await loadTierTextures(TIER_FIRST_PAINT), TIER_FIRST_PAINT, mobile);
    requestAnimationFrame(hideLoadingScreen);
    upgradeTexturesWhenIdle();
    upgradeTexturesOnZoom();
  } catch (err) {
    console.error("Failed loading KTX2 textures, falling back to JPEG:", err);
    try {
      applyGlobeTextures(await loadTierTextures(TIER_FIRST_PAINT, "jpg"), TIER_FIRST_PAINT, mobile);
    } catch (fallbackErr) {
      console.error("Failed loading JPEG textures:", fallbackErr);
    }
    requestAnimationFrame(hideLoadingScreen);
  } finally {
    clearTimeout(watchdog);
  }

  globe.controls().autoRotate = true;
  globe.controls().autoRotateSpeed = 0.4;
  globe.controls().enableDamping = true;
  globe.controls().dampingFactor = 0.05;
  applyZoomLimit();

  let _resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(() => {
      _globeW = window.innerWidth;
      _globeH = window.innerHeight;
      globe.width(_globeW);
      globe.height(_globeH);
      // Drop any inline max-height left over from a mobile drag so the
      // CSS rules for the new viewport size take effect again.
      if (!isMobileLike()) infoPanel.style.maxHeight = "";
      applyRendererTuning();
      applyCameraOffset();
      applyZoomLimit(); // the tier ceiling follows the viewport size
    }, RESIZE_DEBOUNCE_MS);
  });

  function animateScale() {
    let stillAnimating = false;
    allEntries.forEach((d) => {
      if (!d.__threeObj) return;
      const s = d.__targetScale;
      if (Math.abs(d.__threeObj.scale.x - s) > SCALE_LERP_EPSILON) {
        d.__threeObj.scale.lerp(_scaleVec.set(s, s, s), SCALE_LERP_FACTOR);
        stillAnimating = true;
      }
    });
    _scaleAnimating = stillAnimating;
    if (_scaleAnimating) requestAnimationFrame(animateScale);
    else _scaleLoopRunning = false;
  }
  function startScaleAnimation() {
    _scaleAnimating = true;
    if (!_scaleLoopRunning) {
      _scaleLoopRunning = true;
      requestAnimationFrame(animateScale);
    }
  }

  if (currentEntry) {
    globe.pointOfView(
      { lat: currentEntry.lat, lng: currentEntry.lng, altitude: CAMERA_ALTITUDE_INITIAL },
      0,
    );
    applyCameraOffset();
  }
}

// ── Panel controls ────────────────────────────────────────────────────────────
function setPanelState(collapsed) {
  infoPanel.classList.toggle("collapsed", collapsed);
  requestAnimationFrame(applyCameraOffset);
}

setPanelState(window.innerWidth <= 600);

collapseBtn.addEventListener("click", () => {
  setPanelState(!infoPanel.classList.contains("collapsed"));
});
activeTitle.addEventListener("click", () => {
  setPanelState(false);
});

siteTitle.addEventListener("click", () => {
  if (searchBar.value) {
    searchBar.value = "";
    filterEntries();
  }
  panelBody.scrollTop = 0;
  setPanelState(false);
  if (globe) globe.controls().autoRotate = true;
});

searchBar.addEventListener("input", () => {
  if (infoPanel.classList.contains("collapsed")) setPanelState(false);
  filterEntries();
});

prevBtn.addEventListener("click", () => {
  if (!currentEntry) return;
  const list = filteredEntries.length ? filteredEntries : allEntries;
  const idx = list.indexOf(currentEntry);
  handleInteraction(list[(idx - 1 + list.length) % list.length]);
});

nextBtn.addEventListener("click", () => {
  if (!currentEntry) return;
  const list = filteredEntries.length ? filteredEntries : allEntries;
  const idx = list.indexOf(currentEntry);
  handleInteraction(list[(idx + 1) % list.length]);
});

if (HAS_HOVER) {
  globeViz.addEventListener("mousemove", (e) => {
    globeTooltip.style.transform = `translate(calc(${e.clientX}px + 12px), calc(${e.clientY}px - 50%))`;
  });
  globeViz.addEventListener("mouseleave", () => {
    globeTooltip.style.display = "none";
  });
}

// ── Panel drag-to-resize (mobile + mouse) ────────────────────────────────────
let _dragStartY = null;
let _dragStartH = null;

function onDragStart(clientY) {
  _dragStartY = clientY;
  _dragStartH = infoPanel.getBoundingClientRect().height;
}

function onDragMove(clientY) {
  if (_dragStartY === null) return;
  const dy = _dragStartY - clientY;
  const vh = window.innerHeight;
  const clamped = Math.max(vh * 0.55, Math.min(vh * 0.75, _dragStartH + dy));
  infoPanel.style.maxHeight = `${clamped}px`;
  applyCameraOffset();
}

function onDragEnd() {
  _dragStartY = null;
  _dragStartH = null;
}

panelDragHandle.addEventListener("touchstart", (e) => onDragStart(e.touches[0].clientY), {
  passive: true,
});
panelDragHandle.addEventListener("touchmove", (e) => onDragMove(e.touches[0].clientY), {
  passive: true,
});
panelDragHandle.addEventListener("touchend", onDragEnd);

panelDragHandle.addEventListener("mousedown", (e) => {
  e.preventDefault();
  onDragStart(e.clientY);
});
document.addEventListener("mousemove", (e) => onDragMove(e.clientY));
document.addEventListener("mouseup", onDragEnd);

// The artifact browser does not depend on WebGL or network texture requests.
renderEntryList(allEntries);
const initial = allEntries[allEntries.length - 1];
if (initial?._listItem) activateEntry(initial, initial._listItem);

init().catch((err) => {
  console.error("globe: 3D unavailable", err);
  const failedGlobe = globe;
  globe = null; // List and panel handlers must not call a partially initialized globe.
  try {
    failedGlobe?._destructor?.();
  } catch (cleanupErr) {
    console.warn("globe: cleanup failed", cleanupErr);
  }
  const notice = document.createElement("p");
  notice.id = "globeUnavailable";
  notice.setAttribute("role", "status");
  notice.textContent = "3D unavailable. Browse artifacts using search and navigation.";
  globeViz.appendChild(notice);
  hideLoadingScreen();
});
