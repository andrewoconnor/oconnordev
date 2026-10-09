import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = (await readFile(new URL("./main.js", import.meta.url), "utf8")).replace(
  /^import .*;\n/gm,
  "",
);

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.attributes = {};
    this.value = "";
    this.textContent = "";
    this.classes = new Set();
    this.classList = {
      add: (...names) => {
        for (const name of names) this.classes.add(name);
      },
      remove: (...names) => {
        for (const name of names) this.classes.delete(name);
      },
      contains: (n) => this.classes.has(n),
      toggle: (n, force = !this.classes.has(n)) => {
        if (force) this.classes.add(n);
        else this.classes.delete(n);
      },
    };
  }
  set className(value) {
    this.classes = new Set(value.split(" "));
  }
  set innerHTML(value) {
    this.children = [];
    for (const match of value.matchAll(/class="([^"]+)"/g)) {
      const child = new Element();
      child.className = match[1];
      this.children.push(child);
    }
  }
  appendChild(child) {
    if (child.fragment) this.children.push(...child.children);
    else {
      this.children = this.children.filter((c) => c !== child);
      this.children.push(child);
    }
    return child;
  }
  querySelector(selector) {
    const classes = selector.split(".").filter(Boolean);
    for (const child of this.children) {
      if (classes.every((c) => child.classes.has(c))) return child;
      const found = child.querySelector(selector);
      if (found) return found;
    }
    return null;
  }
  addEventListener(name, handler) {
    this.listeners[name] ||= [];
    this.listeners[name].push(handler);
  }
  dispatch(name, event = {}) {
    for (const handler of this.listeners[name] || []) handler(event);
  }
  setAttribute(name, value) {
    this.attributes[name] = value;
  }
  getBoundingClientRect() {
    return { height: 300 };
  }
  remove() {
    this.removed = true;
  }
}

function harness({ throwing = false, widthThrow = false, setupThrow = false } = {}) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const requests = [];
  const timers = [];
  const frames = [];
  const errors = [];
  const load = (url, resolve, _progress, reject) => requests.push({ url, resolve, reject });
  class Loader {
    load = load;
    setTranscoderPath() {
      return this;
    }
    detectSupport() {
      return this;
    }
  }
  class Vector {
    set() {
      return this;
    }
    multiplyScalar() {
      return this;
    }
  }
  const material = { color: { set() {} }, normalScale: { setScalar() {} } };
  const controls = { addEventListener() {} };
  const scene = { add() {}, remove() {} };
  const camera = {
    add() {},
    setViewOffset() {},
    clearViewOffset() {},
    updateProjectionMatrix() {},
  };
  const renderer = {
    setPixelRatio() {
      if (setupThrow) throw new Error("renderer setup failed");
    },
    capabilities: { getMaxAnisotropy: () => 1 },
    getContext: () => ({ MAX_TEXTURE_SIZE: 1, getParameter: () => 16384 }),
  };
  let ctorListCount;
  let destructorCalls = 0;
  const globe = new Proxy(
    {},
    {
      get: (_target, name) => {
        if (name === "_destructor")
          return () => {
            destructorCalls++;
          };
        if (name === "width")
          return () => {
            if (widthThrow) throw new Error("globe width configuration failed");
            return globe;
          };
        if (name === "controls") return () => controls;
        if (name === "scene") return () => scene;
        if (name === "camera") return () => camera;
        if (name === "renderer") return () => renderer;
        if (name === "globeMaterial") return () => material;
        if (name === "getGlobeRadius") return () => 100;
        if (name === "postProcessingComposer") return () => null;
        if (name === "pointOfView") return (value) => (value ? globe : { altitude: 2.2 });
        return () => globe;
      },
    },
  );
  const document = {
    getElementById: get,
    createElement: () => {
      const element = new Element();
      Object.defineProperty(element, "id", { set: (id) => elements.set(id, element) });
      return element;
    },
    createDocumentFragment: () => Object.assign(new Element(), { fragment: true }),
    addEventListener() {},
    body: new Element(),
  };
  const THREE = {
    TextureLoader: Loader,
    Vector3: Vector,
    PlaneGeometry: class {},
    DirectionalLight: class {
      position = new Vector();
    },
    AmbientLight: class {},
    Color: class {},
    SphereGeometry: class {
      dispose() {}
    },
    MeshBasicMaterial: class {
      constructor(options) {
        Object.assign(this, options);
      }
      dispose() {}
    },
    Mesh: class {
      constructor(geometry, mat) {
        this.geometry = geometry;
        this.material = mat;
      }
    },
  };
  const context = vm.createContext({
    THREE,
    KTX2Loader: Loader,
    Globe: () => {
      ctorListCount = get("entryList").children.length;
      if (throwing) throw new Error("WebGL unavailable");
      return () => globe;
    },
    DRUMS: [1, 2].map((n) => ({
      title: `Drum ${n}`,
      year: n,
      region: "Earth",
      type: "Drum",
      description: "Artifact",
      images: [{ src: `/${n}.jpg` }, { src: `/${n}-b.jpg` }],
    })),
    document,
    window: {
      innerWidth: 1200,
      innerHeight: 900,
      matchMedia: () => ({ matches: false }),
      addEventListener() {},
    },
    navigator: {},
    console: { warn: (...args) => errors.push(args), error: (...args) => errors.push(args) },
    setTimeout: (fn, ms) => {
      const timer = { fn, ms };
      timers.push(timer);
      return timer;
    },
    clearTimeout: (timer) => {
      timer.cleared = true;
    },
    requestAnimationFrame: (fn) => frames.push(fn),
  });
  vm.runInContext(source, context);
  return {
    get,
    context,
    requests,
    timers,
    frames,
    errors,
    material,
    ctorListCount: () => ctorListCount,
    destructorCalls: () => destructorCalls,
    run: (code) => vm.runInContext(code, context),
  };
}
const flush = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};

test("WebGL constructor failure retains selected searchable list and gallery", async () => {
  const h = harness({ throwing: true });
  await flush();
  assert.equal(h.ctorListCount(), 2, "list must exist before Globe construction");
  assert.equal(h.get("activeTitle").textContent, "Drum 2");
  h.get("prevBtn").dispatch("click");
  assert.equal(h.get("activeTitle").textContent, "Drum 1");
  h.get("searchBar").value = "Drum 1";
  h.get("searchBar").dispatch("input");
  assert.equal(h.get("entryList").children.length, 1);
  const body = h.get("entryList").querySelector(".entry-body");
  body.querySelector(".entry-thumbs").children[1].onclick();
  assert.equal(body.querySelector(".entry-main-img").src, "/1-b.jpg");
  h.get("entryList").dispatch("click", { target: { closest: () => true } });
  assert.equal(h.get("lightboxImg").src, "/1-b.jpg");
  assert.ok(h.get("loadingScreen").classList.contains("fade-out"));
  const notice = h.get("globeUnavailable");
  assert.equal(notice.attributes.role, "status");
  assert.match(notice.textContent, /3D unavailable/);
});

test("stalled first-paint textures leave navigation usable and loading bounded", async () => {
  const h = harness();
  await flush();
  assert.equal(h.ctorListCount(), 2);
  assert.equal(h.requests.length, 4);
  h.get("prevBtn").dispatch("click");
  assert.equal(h.get("activeTitle").textContent, "Drum 1");
  h.get("nextBtn").dispatch("click");
  assert.equal(h.get("activeTitle").textContent, "Drum 2");
  h.get("searchBar").value = "Drum 1";
  h.get("searchBar").dispatch("input");
  assert.equal(h.get("entryList").children.length, 1);
  h.timers.find((t) => t.ms === 20000).fn();
  assert.ok(h.get("loadingScreen").classList.contains("fade-out"));
  for (const timer of [...h.timers]) if (timer.ms < 20000 && !timer.cleared) timer.fn();
  assert.ok(h.get("loadingScreen").removed, "dismiss even without transitionend");
});

function texture() {
  return {
    disposals: 0,
    dispose() {
      this.disposals++;
    },
  };
}
function complete(requests) {
  return requests.map((request) => {
    const tex = texture();
    request.resolve(tex);
    return tex;
  });
}
async function painted() {
  const h = harness();
  complete(h.requests);
  await flush();
  return h;
}

test("late 4k completion cannot replace 8k or poison the applied stars cache", async () => {
  const h = await painted();
  h.run('_starsUrl = null; switchTier("4k")');
  const lowRequests = h.requests.slice(4);
  h.run('switchTier("8k")');
  const highRequests = h.requests.slice(4 + lowRequests.length);
  const high = complete(highRequests);
  await flush();
  const low = complete(lowRequests);
  await flush();
  assert.equal(h.run("_appliedTier"), "8k");
  assert.equal(h.material.map, high[highRequests.findIndex((r) => r.url.includes("earthmap"))]);
  assert.equal(h.run("_starsUrl"), "/images/globe/stars8k.ktx2");
  for (const tex of low) assert.equal(tex.disposals, 1);
  for (const tex of high) assert.equal(tex.disposals, 0);
  h.run('switchTier("10k")');
  assert.equal(h.requests.filter((r) => r.url === "/images/globe/stars8k.ktx2").length, 1);
});

test("overlapping tiers dedupe their own work and completion preserves other pending tiers", async () => {
  const h = await painted();
  const low = h.run('switchTier("4k")');
  const lowRequests = h.requests.slice(4);
  const high = h.run('switchTier("8k")');
  const highRequests = h.requests.slice(4 + lowRequests.length);
  assert.equal(h.run('switchTier("4k")'), low);
  complete(lowRequests);
  await low;
  assert.equal(h.run('switchTier("8k")'), high);
  assert.equal(h.requests.length, 4 + lowRequests.length + highRequests.length);
  complete(highRequests);
  await high;
});

test("failed tier disposes partial and late textures and can retry without touching active textures", async () => {
  const h = await painted();
  const active = h.material.map;
  const pending = h.run('switchTier("8k")');
  const requests = h.requests.slice(4);
  const first = texture();
  requests[0].resolve(first);
  await flush();
  requests[1].reject(new Error("network failure"));
  await pending;
  const late = complete(requests.slice(2));
  await flush();
  assert.equal(first.disposals, 1);
  for (const tex of late) assert.equal(tex.disposals, 1);
  assert.equal(active.disposals, 0);
  assert.equal(h.run("_starsUrl"), "/images/globe/stars4k.ktx2");
  const retry = h.run('switchTier("8k")');
  const retryRequests = h.requests.slice(8);
  assert.equal(retryRequests.length, 4);
  complete(retryRequests);
  await retry;
  assert.equal(h.run("_appliedTier"), "8k");
  assert.equal(active.disposals, 1);
});

test("fluent width failure destroys the mounted globe before list controls run", async () => {
  const h = harness({ widthThrow: true });
  await flush();
  assert.equal(h.run("globe"), null);
  assert.equal(h.destructorCalls(), 1);
  assert.match(h.errors[0][1].message, /globe width configuration failed/);
  h.get("prevBtn").dispatch("click");
  h.get("siteTitle").dispatch("click");
  for (const frame of h.frames) frame();
  assert.equal(h.get("activeTitle").textContent, "Drum 1");
  assert.match(h.get("globeUnavailable").textContent, /3D unavailable/);
  assert.ok(h.get("loadingScreen").classList.contains("fade-out"));
});

test("renderer setup failure clears the partial globe before list controls run", async () => {
  const h = harness({ setupThrow: true });
  await flush();
  assert.equal(h.run("globe"), null);
  assert.equal(h.destructorCalls(), 1);
  h.get("prevBtn").dispatch("click");
  h.get("siteTitle").dispatch("click");
  for (const frame of h.frames) frame();
  assert.equal(h.get("activeTitle").textContent, "Drum 1");
  assert.match(h.get("globeUnavailable").textContent, /3D unavailable/);
});

test("JPEG fallback still paints the first tier after compressed texture rejection", async () => {
  const h = harness();
  h.requests[0].reject(new Error("KTX2 unavailable"));
  await flush();
  const jpeg = h.requests.slice(4);
  assert.equal(jpeg.length, 4);
  assert.ok(jpeg.every((request) => request.url.endsWith(".jpg")));
  complete(jpeg);
  await flush();
  assert.equal(h.run("_appliedTier"), "2k");
  assert.equal(h.run("_starsUrl"), "/images/globe/stars4k.jpg");
  for (const frame of h.frames) frame();
  assert.ok(h.get("loadingScreen").classList.contains("fade-out"));
});

test("reusing active textures in an upgrade or discarded tier does not dispose them", async () => {
  const h = await painted();
  const star = h.run("starsMesh.material.map");
  h.run(
    'applyGlobeTextures({map: globe.globeMaterial().map, normal: globe.globeMaterial().normalMap, spec: globe.globeMaterial().specularMap, stars: starsMesh.material.map, starsUrl: _starsUrl}, "8k")',
  );
  assert.equal(star.disposals, 0);
  assert.equal(h.material.map.disposals, 0);
  h.run(
    'applyGlobeTextures({map: globe.globeMaterial().map, normal: globe.globeMaterial().normalMap, spec: globe.globeMaterial().specularMap, stars: starsMesh.material.map}, "4k")',
  );
  assert.equal(star.disposals, 0);
  assert.equal(h.material.map.disposals, 0);
});
