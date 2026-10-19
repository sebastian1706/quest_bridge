// Vibration der Quest-Controller ueber vuer -- ohne Patch am vuer-Bundle.
//
// Geladen ueber vuers ContribLoader von /static/haptics.js (vuers eigener Webserver, gleicher
// Port und gleiches Zertifikat wie die Seite). Registriert die Komponente HapticFeedback in
// vuers CONTRIB_COMPONENT_LIST; ein Szenenelement {tag: "HapticFeedback", left, right} wird
// damit gerendert. In jedem Frame laesst sie die Controller mit der aktuellen Staerke (0..1)
// vibrieren.
//
// Ihren Zustand meldet sie per uplink als HAPTIC_STATUS an den Server -- dann steht im
// Bridge-Terminal, ob Skript, XR-Sitzung und Vibrationsmotor gefunden wurden, ohne dass man auf
// der Quest eine Browser-Konsole oeffnen muss.
(function () {
  "use strict";
  var VUER = window.VUER;
  var FIBER = window.FIBER;
  var React = window.React;
  if (!VUER || !FIBER || !React || !VUER.CONTRIB_COMPONENT_LIST || !VUER.useSocket) {
    console.error("[haptics] vuer-Globals fehlen", { VUER: !!VUER, FIBER: !!FIBER, React: !!React });
    return;
  }

  function clamp01(x) {
    x = Number(x);
    return x > 0 ? (x < 1 ? x : 1) : 0;
  }

  function HapticFeedback(props) {
    var gl = FIBER.useThree(function (state) { return state.gl; });
    var socket = VUER.useSocket();
    var uplink = socket && socket.uplink;
    var reported = React.useRef({});
    var propsRef = React.useRef(props);
    propsRef.current = props;

    // Nur Aenderungen melden, sonst kaeme mit jedem Frame eine Nachricht.
    function report(key, value) {
      var text = JSON.stringify(value);
      if (reported.current[key] === text) return;
      reported.current[key] = text;
      console.info("[haptics]", key, value);
      if (uplink) uplink.publish({ etype: "HAPTIC_STATUS", value: { key: key, value: value } });
    }

    React.useEffect(function () { report("mounted", true); }, []);

    FIBER.useFrame(function (_state, delta) {
      var session = gl && gl.xr && gl.xr.getSession ? gl.xr.getSession() : null;
      report("session", !!session);
      if (!session) return;

      var p = propsRef.current;
      // Etwas laenger als ein Frame pulsen, damit zwischen zwei Frames keine Luecke entsteht.
      var ms = Math.min(Math.max(delta * 1500, 15), 100);
      var seen = [];
      var sources = session.inputSources;
      for (var i = 0; i < sources.length; i++) {
        var src = sources[i];
        var gp = src.gamepad;
        var actuators = gp && gp.hapticActuators;
        seen.push(src.handedness + ":" + (actuators ? actuators.length : 0)
                  + (gp && gp.vibrationActuator ? "+vibrationActuator" : ""));
        var amp = clamp01(src.handedness === "left" ? p.left : src.handedness === "right" ? p.right : 0);
        if (amp <= 0) continue;
        try {
          if (actuators && actuators.length && actuators[0].pulse) {
            actuators[0].pulse(amp, ms);
          } else if (gp && gp.vibrationActuator && gp.vibrationActuator.playEffect) {
            gp.vibrationActuator.playEffect("dual-rumble",
              { duration: ms, strongMagnitude: amp, weakMagnitude: amp });
          } else {
            report("noActuator", src.handedness);
          }
        } catch (e) {
          report("pulseError", String(e));
        }
      }
      report("inputs", seen);
    });
    return null;
  }

  VUER.CONTRIB_COMPONENT_LIST.HapticFeedback = HapticFeedback;
  console.info("[haptics] HapticFeedback registriert");
})();
