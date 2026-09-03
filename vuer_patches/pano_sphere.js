// pano sphere layer (vuer client patch) -- adds a 360-degree WebRTC video sphere to the vuer
// scene, bypassing React entirely: the boot shim hands us the renderer via
// the three.js devtools hook, we hook renderer.render() to manage the
// sphere, and from then on it is just another mesh vuer renders --
// including inside the WebXR session.
//
// Offer endpoint: ?pano=<url> query param, else <page-host>:60010/offer with
// the page's own scheme (an https page needs an https bridge -- mixed
// content is blocked by the browser).
//
// Robustness rules learned in bring-up:
//  * the toggle and the render hook are installed BEFORE any network step,
//    so a dead bridge can never take the B key down with it;
//  * the WebRTC connection retries forever (bridge restarts, tunnels
//    flapping); the <video> element survives reconnects, so the texture
//    needs no rebuild;
//  * the page renders MORE THAN ONE scene (main + gizmo overlay), and vuer
//    may rebuild the scene on reconnect -- the sphere binds to the largest
//    scene and re-binds if its home scene stops being rendered.
const log = (...a) => console.log("[pano]", ...a);

async function getThree() {
  // Prefer the app's own three.js chunk (same instance, zero version risk).
  // Vite chunk names change across vuer versions, so probe, don't assume.
  try {
    const m = await import("/assets/chunks/chunk-nB1OriYW.js");
    const T = m.default ?? m;
    if (T && T.SphereGeometry && T.VideoTexture && T.MeshBasicMaterial) {
      log("using the app's bundled three.js, r" + T.REVISION);
      return T;
    }
    log("app chunk lacks named exports, falling back to CDN");
  } catch (e) {
    log("app chunk import failed, falling back to CDN:", e.message);
  }
  // Same revision as the bundle (r172); needs internet on the viewing device.
  return await import("https://unpkg.com/three@0.172.0/build/three.module.js");
}

function waitRenderer() {
  return new Promise((res) => {
    const seen = window.__PANO_RENDERERS__ || [];
    if (seen.length) return res(seen[seen.length - 1]);
    window.addEventListener("pano-renderer", (e) => res(e.detail), {
      once: true,
    });
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function webrtcConnect(offerUrl, video) {
  // LAN peers: host candidates are enough, and skipping STUN keeps ICE
  // gathering instant on an offline hotspot.
  const pc = new RTCPeerConnection({ iceServers: [] });
  window.__PANO_PC__ = pc; // debug handle
  pc.addEventListener("track", (ev) => {
    if (ev.track.kind === "video") {
      // Tele-presence wants freshness over smoothness: ask the browser to
      // keep its jitter buffer empty instead of growing it to hide network
      // jitter (which turns any hiccup into standing latency).
      try { ev.receiver.jitterBufferTarget = 0; } catch (e) { /* older API */ }
      try { ev.receiver.playoutDelayHint = 0; } catch (e) { /* legacy name */ }
      video.srcObject = ev.streams[0];
      video.play().then(
        () => log(`video playing ${video.videoWidth}x${video.videoHeight}`),
        (e) => log("video.play refused:", e.message)
      );
    }
  });
  pc.addTransceiver("video", { direction: "recvonly" });
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise((res) => {
    if (pc.iceGatheringState === "complete") return res();
    const f = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", f);
        res();
      }
    };
    pc.addEventListener("icegatheringstatechange", f);
  });
  const resp = await fetch(offerUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type,
    }),
  });
  if (!resp.ok) {
    pc.close();
    throw new Error(`offer failed: HTTP ${resp.status}`);
  }
  await pc.setRemoteDescription(await resp.json());
  return pc;
}

(async () => {
  const q = new URLSearchParams(location.search);
  const offerUrl =
    q.get("pano") || `${location.protocol}//${location.hostname}:60010/offer`;
  // Home orientation (degrees) aligns the panorama with robot-forward and
  // the horizon (yaw: azimuth, pitch/roll: camera mount tilt). Edit the
  // DEFAULT_* values once the camera mount is final. A home set in the
  // headset (Y with &panocalib=1) is stored per browser and wins; X
  // returns to home.
  const DEFAULT_YAW_DEG = 0;
  const DEFAULT_PITCH_DEG = 0;
  const DEFAULT_ROLL_DEG = 0;
  const HOME_KEY = `pano-home:${location.host}`;
  const calib = q.get("panocalib") === "1";
  const loadHome = () => {
    try {
      const h = JSON.parse(localStorage.getItem(HOME_KEY));
      if (h && [h.yaw, h.pitch, h.roll].every(Number.isFinite)) return h;
    } catch (e) {}
    return { yaw: DEFAULT_YAW_DEG, pitch: DEFAULT_PITCH_DEG, roll: DEFAULT_ROLL_DEG };
  };
  const saveHome = (h) => {
    try { localStorage.setItem(HOME_KEY, JSON.stringify(h)); } catch (e) {}
  };

  // ---- view toggle: installed FIRST, works even with everything else dead.
  // 'robot' shows the teleop video plane(s), 'pano' the sphere -- never
  // both (operator's request). B on the right controller (xr-standard
  // button 5) or the 'b' key; ?panoview=pano starts in panorama.
  let mode = q.get("panoview") === "pano" ? "pano" : "robot";
  const toggle = () => {
    mode = mode === "robot" ? "pano" : "robot";
    log("view:", mode);
  };
  window.addEventListener("keydown", (e) => {
    if (e.key === "b") toggle();
  });
  const isTeleopVideoPlane = (o) =>
    o.isMesh &&
    o.name !== "pano-sphere" &&
    o.material?.uniforms?.texCoordScaleOffset !== undefined;

  const THREE = await getThree();
  const renderer = await waitRenderer();
  log("renderer captured");

  // ---- the sphere; its texture reads one persistent <video> element that
  // reconnects freely underneath it.
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.autoplay = true;
  window.__PANO_VIDEO__ = video; // debug handle
  const tex = new THREE.VideoTexture(video);
  tex.colorSpace = THREE.SRGBColorSpace;
  // Classic equirect-inside-a-sphere: flip X so the texture reads
  // correctly from the inside, keep the default FrontSide.
  const geo = new THREE.SphereGeometry(30, 64, 32);
  geo.scale(-1, 1, 1);
  const mat = new THREE.MeshBasicMaterial({ map: tex, toneMapped: false });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.name = "pano-sphere";
  const DEG = Math.PI / 180;
  const _euler = new THREE.Euler();
  const _dir = new THREE.Vector3();
  const _quat = new THREE.Quaternion();
  const _qYaw = new THREE.Quaternion();
  const _qPitch = new THREE.Quaternion();
  const Y_AXIS = new THREE.Vector3(0, 1, 0);
  const X_AXIS = new THREE.Vector3(1, 0, 0);
  // displayed orientation = viewQuat (X, operator posture) * homeQuat (Y,
  // camera mount calibration)
  const homeQuat = new THREE.Quaternion();
  const viewQuat = new THREE.Quaternion();
  const _viewInv = new THREE.Quaternion();
  const show = () => mesh.quaternion.copy(viewQuat).multiply(homeQuat);
  // yaw about the vertical first, then pitch about the horizontal axis
  // (three.js "XYZ": R = Rx(pitch) * Ry(yaw) * Rz(roll))
  const applyHome = (h) => {
    homeQuat.setFromEuler(_euler.set(h.pitch * DEG, h.yaw * DEG, h.roll * DEG, "XYZ"));
    show();
  };
  const anglesOf = (dir) => ({
    yaw: Math.atan2(-dir.x, -dir.z),
    pitch: Math.asin(Math.max(-1, Math.min(1, dir.y))),
  });
  const gazeDir = (camera) => {
    camera.getWorldQuaternion(_quat);
    return _dir.set(0, 0, -1).applyQuaternion(_quat).normalize();
  };
  const currentHome = () => {
    _euler.setFromQuaternion(homeQuat, "XYZ");
    return { yaw: _euler.y / DEG, pitch: _euler.x / DEG, roll: _euler.z / DEG };
  };
  const fmt = (h) => `yaw=${h.yaw.toFixed(1)} pitch=${h.pitch.toFixed(1)} roll=${h.roll.toFixed(1)}`;
  applyHome(loadHome());
  // Y (calibration): the content the operator is looking at becomes
  // robot-forward, with the operator's head horizon as level (tilt the
  // head to match a tilted horizon before pressing); result = new home
  const setHome = (camera) => {
    // undo the head's yaw, pitch and roll, expressed in the recentered
    // frame: the landmark lands where robot-forward is currently shown
    // (the X direction) with the head's horizon as the level reference
    camera.getWorldQuaternion(_quat);
    _quat.premultiply(_viewInv.copy(viewQuat).invert()).invert();
    homeQuat.premultiply(_quat);
    show();
    const h = currentHome();
    saveHome(h);
    log("home set:", fmt(h), "(DEFAULT_* candidates)");
  };
  // X (recenter): show robot-forward in the direction the operator is
  // facing now; calibration untouched, not stored
  const recenter = (camera) => {
    const g = anglesOf(gazeDir(camera));
    _qPitch.setFromAxisAngle(X_AXIS, g.pitch);
    _qYaw.setFromAxisAngle(Y_AXIS, g.yaw);
    viewQuat.copy(_qYaw).multiply(_qPitch);
    show();
    log("recentered: yaw", (g.yaw / DEG).toFixed(1), "pitch", (g.pitch / DEG).toFixed(1));
  };
  let lastCamera = null;
  window.addEventListener("keydown", (e) => {
    if (e.key === "x" && lastCamera) recenter(lastCamera);
    if (e.key === "y" && calib && lastCamera) setHome(lastCamera);
  });
  mesh.frustumCulled = false;
  mesh.renderOrder = -1; // draw first: a background, never an occluder

  // ---- render hook: sphere binding, controller poll, view enforcement.
  let bWasPressed = false;
  let xWasPressed = false;
  let yWasPressed = false;
  let homeSize = -1;
  let sphereSeen = performance.now();
  const orig = renderer.render.bind(renderer);
  renderer.render = (scene, camera) => {
    if (scene && scene.isScene) {
      const now = performance.now();
      if (mesh.parent === scene) {
        sphereSeen = now;
        homeSize = scene.children.length;
      } else if (mesh.parent && now - sphereSeen > 2000) {
        homeSize = -1; // home scene no longer rendered (vuer rebuilt it)
      }
      if (scene.children.length > homeSize && mesh.parent !== scene) {
        scene.add(mesh); // re-parents: three removes it from the old scene
        homeSize = scene.children.length;
        sphereSeen = now;
        log(`pano sphere bound to scene (${homeSize} children)`);
      }
      lastCamera = camera;
      const session = renderer.xr?.getSession?.();
      if (session) {
        // xr-standard mapping: buttons[4]/[5] = A/B (right), X/Y (left)
        let bPressed = false;
        let xPressed = false;
        let yPressed = false;
        for (const src of session.inputSources) {
          const btn = src.gamepad?.buttons;
          if (!btn) continue;
          if (src.handedness === "right") bPressed ||= !!btn[5]?.pressed;
          if (src.handedness === "left") {
            xPressed ||= !!btn[4]?.pressed;
            yPressed ||= !!btn[5]?.pressed;
          }
        }
        if (bPressed && !bWasPressed) toggle();
        if (xPressed && !xWasPressed) recenter(camera);
        if (yPressed && !yWasPressed && calib) setHome(camera);
        bWasPressed = bPressed;
        xWasPressed = xPressed;
        yWasPressed = yPressed;
      }
      mesh.visible = mode === "pano";
      scene.traverse((o) => {
        if (isTeleopVideoPlane(o)) o.visible = mode === "robot";
      });
    }
    return orig(scene, camera);
  };

  // ---- WebRTC with unbounded retry: bridge restarts must only cost the
  // seconds they last, never the session.
  let pc = null;
  for (;;) {
    try {
      if (!pc || ["failed", "closed", "disconnected"].includes(pc.connectionState)) {
        if (pc) pc.close();
        pc = await webrtcConnect(offerUrl, video);
        log("webrtc connected to", offerUrl);
      }
    } catch (e) {
      log("webrtc connect failed (retrying in 3s):", e.message);
      pc = null;
      await sleep(3000);
      continue;
    }
    await sleep(2000);
  }
})();
