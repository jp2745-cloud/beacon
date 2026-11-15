/* Beacon front end. No libraries, no network calls except to this machine. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var body = document.body;

  var sys = null;                       // last /api/status
  var view = { card: null, step: 0, log: [], turns: {} };
  var ttsMode = "browser";              // "server" = Argmax TTSKit, "browser" = built-in voice
  var canListen = false;
  var busy = false;

  var SEVERITY = { critical: "Life-threatening", urgent: "Urgent", minor: "Stay safe" };
  var GROUPS = { medical: "Medical", wilderness: "Outdoors", disaster: "Disasters" };

  // ------------------------------------------------------------------ api
  function api(path, payload) {
    return fetch(path, {
      method: payload === undefined ? "GET" : "POST",
      headers: payload === undefined ? {} : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload)
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    });
  }

  // ------------------------------------------------------------- captions
  function idleCaption() {
    return canListen ? "Hold the space bar to talk." : "Typing only on this machine. Use the box on the right.";
  }
  function caption(text, kind) {
    var el = $("caption");
    el.textContent = text;
    el.className = "caption" + (kind ? " " + kind : "");
  }

  // ---------------------------------------------------------------- pills
  function pill(id, cls, text, title) {
    var el = $(id);
    el.className = "pill" + (cls ? " " + cls : "");
    el.querySelector(".pill-text").textContent = text;
    el.title = title || "";
  }
  function renderNet() {
    if (navigator.onLine) pill("pill-net", "", "Network is on, but not used");
    else pill("pill-net", "best", "Wi-Fi off. Running on this laptop");
  }
  function prettyModel(name) {
    var m = /bonsai[-_ ]?2[-_ ](\d+(?:\.\d+)?B)/i.exec(name || "");
    return m ? "Bonsai 2 " + m[1].toUpperCase() : (name || "model");
  }
  function renderStatus() {
    if (!sys) return;
    var l = sys.llm, s = sys.speech;
    if (!l.ok) pill("pill-llm", "bad", "Bonsai is not running", l.error || "");
    else if (!l.is_bonsai) pill("pill-llm", "bad", prettyModel(l.model) + " is not Bonsai", l.url);
    else pill("pill-llm", "good", prettyModel(l.model) + " on this laptop", l.model + " at " + l.url);

    if (s.provider === "argmax" || s.provider === "argmax-cli") {
      if (s.error) pill("pill-voice", "bad", "Argmax failed to start", s.error);
      else if (!s.ready) pill("pill-voice", "", "Argmax is loading models", s.message);
      else if (s.tts_ok === false) pill("pill-voice", "good", "Argmax WhisperKit, system voice", s.message);
      else pill("pill-voice", "good", "Argmax WhisperKit and TTSKit", s.stt + ", " + s.tts);
    } else {
      pill("pill-voice", "", "Development voice, not Argmax", s.message);
    }
    ttsMode = s.tts_mode === "server" && s.ready ? "server" : "browser";
    var could = canListen;
    canListen = !!s.can_listen;
    $("talk").disabled = !canListen;
    if (could !== canListen && !body.classList.contains("listening") && !voice.playing && !busy) caption(idleCaption());
    if (canListen && !mic.asked) ensureMic();
  }
  function poll() {
    api("/api/status").then(function (j) {
      var first = !sys;
      sys = j;
      renderStatus();
      if (first) {
        buildLibrary(j.library || []);
        render(j.state);
        caption(idleCaption());
      }
    }).catch(function () {
      pill("pill-llm", "bad", "Beacon server stopped");
    });
  }

  // --------------------------------------------------------------- render
  function buildLibrary(cards) {
    var box = $("library");
    box.textContent = "";
    Object.keys(GROUPS).forEach(function (g) {
      cards.filter(function (c) { return c.category === g; }).forEach(function (c) {
        var b = document.createElement("button");
        b.className = "lib";
        b.textContent = c.title;
        b.title = GROUPS[g];
        b.addEventListener("click", function () { act("/api/open", { id: c.id }); });
        box.appendChild(b);
      });
    });
  }

  function fillList(id, items) {
    var ul = $(id);
    ul.textContent = "";
    items.forEach(function (t) {
      var li = document.createElement("li");
      li.textContent = t;
      ul.appendChild(li);
    });
    ul.parentElement.hidden = items.length === 0;
  }

  function render(state) {
    var prevCard = view.card && view.card.id, prevStep = view.step;
    view = state;
    var c = state.card;
    $("idle").hidden = !!c;
    $("card").hidden = !c;

    if (c) {
      var el = $("card");
      el.className = "card " + c.severity;
      $("card-title").textContent = c.title;
      $("card-call").textContent = c.call;
      $("card-severity").textContent = SEVERITY[c.severity] || c.severity;
      var st = c.steps[state.step];
      $("now-count").textContent = "Step " + (state.step + 1) + " of " + c.steps.length;
      $("now-text").textContent = st.text;
      $("btn-back").disabled = state.step === 0;
      $("btn-next").textContent = state.step === c.steps.length - 1 ? "Last step" : "Next step";

      var ol = $("steps");
      ol.textContent = "";
      c.steps.forEach(function (s, i) {
        var li = document.createElement("li");
        li.textContent = s.text;
        if (i < state.step) li.className = "done";
        if (i === state.step) li.className = "current";
        li.addEventListener("click", function () { act("/api/step", { step: i }); });
        ol.appendChild(li);
      });
      fillList("dont", c.dont);
      fillList("redflags", c.redflags);
      $("card-source").textContent = "Steps follow public guidance: " + c.source + ". Demo content, not medically reviewed.";

      var changed = prevCard !== c.id || prevStep !== state.step;
      if (changed) {
        timer.setup(st.timer || 0);
        if (prevCard !== c.id) $("card").parentElement.scrollTop = 0;
      }
      metro.set(st.metronome || 0);
    } else {
      timer.setup(0);
      metro.set(0);
    }
    renderLog(state.log || []);
    renderTally(state.turns || {});
  }

  function renderLog(log) {
    var ol = $("log");
    $("log-empty").hidden = log.length > 0;
    $("btn-report").disabled = log.length === 0;
    ol.textContent = "";
    log.forEach(function (e) {
      var li = document.createElement("li");
      var t = document.createElement("time");
      t.textContent = e.time;
      var p = document.createElement("span");
      p.className = "who-" + e.who;
      p.textContent = (e.who === "you" ? "You: " : e.who === "beacon" ? "Beacon: " : "") + e.text;
      li.appendChild(t);
      li.appendChild(p);
      ol.appendChild(li);
    });
    ol.scrollTop = ol.scrollHeight;
  }

  function renderTally(t) {
    var model = t.bonsai || 0, free = (t.rule || 0) + (t.fastpath || 0);
    if (!model && !free && !(t.retrieval || 0)) { $("w-tally").textContent = ""; return; }
    $("w-tally").textContent = model + (model === 1 ? " model call" : " model calls") + " so far. " +
      free + (free === 1 ? " turn" : " turns") + " answered without one.";
  }

  function secs(ms) { return (ms / 1000).toFixed(ms < 9950 ? 1 : 0); }
  function setWork(id, value, unit) {
    var dd = $(id);
    dd.textContent = value;
    if (unit) {
      var s = document.createElement("small");
      s.textContent = unit;
      dd.appendChild(s);
    }
  }
  function renderWork(reply, stt) {
    if (stt) setWork("w-stt", secs(stt.ms || 0), "s"); else setWork("w-stt", "typed");
    if (reply.route === "bonsai" && reply.llm) {
      setWork("w-llm", secs(reply.llm.ms), "s");
      $("w-route").textContent = "Bonsai read the sentence and " + (reply.intent === "open" ? "chose the card" : reply.intent === "ask" ? "asked for more" : "answered from the card") +
        (reply.llm.tokens ? ", " + reply.llm.tokens + " tokens." : ".");
    } else if (reply.route === "fastpath") {
      setWork("w-llm", "0", "s");
      $("w-route").textContent = "Life-threat phrase matched. The card opened without waiting for the model.";
    } else if (reply.route === "retrieval") {
      setWork("w-llm", "–");
      $("w-route").textContent = "Bonsai was unreachable, so keywords picked the card.";
    } else {
      setWork("w-llm", "0", "s");
      $("w-route").textContent = "Handled by a rule. The model was not woken up.";
    }
    setWork("w-tts", ttsMode === "server" ? "…" : "–");
  }

  // ---------------------------------------------------------------- turns
  function handle(reply, stt) {
    render(reply);
    renderWork(reply, stt);
    if (reply.stop) { stopSpeaking(); caption(idleCaption()); return; }
    if (reply.timer) timer.start();
    if (reply.say && reply.say.length) speak(reply.say);
    else caption(idleCaption());
  }

  function act(path, payload, stt) {
    if (busy) return;
    busy = true;
    stopSpeaking();
    return api(path, payload).then(function (reply) {
      busy = false;
      handle(reply, stt);
    }).catch(function (e) {
      busy = false;
      caption("Something went wrong: " + e.message, "problem");
    });
  }

  function send(text, stt) {
    text = (text || "").trim();
    if (!text) return;
    caption("“" + text + "”", "heard");
    act("/api/turn", { text: text }, stt);
  }

  // ---------------------------------------------------------------- voice
  var voice = { token: 0, playing: false, audio: null };

  function stopSpeaking() {
    voice.token++;
    voice.playing = false;
    if (voice.audio) { try { voice.audio.pause(); } catch (e) {} voice.audio = null; }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    body.classList.remove("speaking");
  }

  function fetchTTS(text) {
    return fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text }) })
      .then(function (r) {
        if (!r.ok) throw new Error("tts " + r.status);
        var ms = parseInt(r.headers.get("X-Beacon-Ms") || "0", 10);
        return r.blob().then(function (b) { return { blob: b, ms: ms }; });
      });
  }

  function playBlob(blob, my) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(blob);
      var a = new Audio(url);
      voice.audio = a;
      var done = function () { URL.revokeObjectURL(url); resolve(); };
      a.onended = done;
      a.onerror = done;
      a.onpause = function () { if (my !== voice.token) done(); };
      a.play().catch(done);
    });
  }

  var chosenVoice = null;
  function pickVoice() {
    if (chosenVoice || !window.speechSynthesis) return chosenVoice;
    var all = window.speechSynthesis.getVoices().filter(function (v) { return /^en/i.test(v.lang); });
    chosenVoice = all.filter(function (v) { return v.localService && /en-US/i.test(v.lang); })[0] ||
      all.filter(function (v) { return v.localService; })[0] || all[0] || null;
    return chosenVoice;
  }
  function browserSay(text, my) {
    return new Promise(function (resolve) {
      if (!window.speechSynthesis) return resolve();
      var u = new SpeechSynthesisUtterance(text);
      var v = pickVoice();
      if (v) u.voice = v;
      u.rate = 1.02;
      var guard = setTimeout(resolve, 20000);
      u.onend = u.onerror = function () { clearTimeout(guard); resolve(); };
      window.speechSynthesis.speak(u);
    });
  }

  function speak(lines) {
    stopSpeaking();
    var my = voice.token;
    voice.playing = true;
    body.classList.add("speaking");
    var jobs = [];
    var job = function (i) { return jobs[i] || (jobs[i] = fetchTTS(lines[i]).catch(function () { return null; })); };
    var spent = 0, i = 0;

    function next() {
      if (my !== voice.token) return;
      if (i >= lines.length) {
        voice.playing = false;
        body.classList.remove("speaking");
        caption(idleCaption());
        return;
      }
      var line = lines[i];
      var idx = i++;
      caption(line, "speaking");
      if (ttsMode === "server") {
        var p = job(idx);
        if (idx + 1 < lines.length) job(idx + 1);   // start the next sentence while this one plays
        p.then(function (res) {
          if (my !== voice.token) return;
          if (!res) return browserSay(line, my).then(next);
          spent += res.ms;
          setWork("w-tts", secs(spent), "s");
          return playBlob(res.blob, my).then(next);
        });
      } else {
        browserSay(line, my).then(next);
      }
    }
    next();
  }

  // ----------------------------------------------------------- microphone
  var mic = { asked: false, stream: null, ctx: null, analyser: null, chunks: [], recording: false, held: false, startedAt: 0 };

  function ensureMic() {
    if (mic.stream) return Promise.resolve(true);
    if (mic.pending) return mic.pending;
    mic.asked = true;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      caption("This browser cannot record audio. Type instead.", "problem");
      return Promise.resolve(false);
    }
    mic.pending = navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      .then(function (stream) {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        mic.stream = stream;
        mic.ctx = new Ctx();
        var src = mic.ctx.createMediaStreamSource(stream);
        mic.analyser = mic.ctx.createAnalyser();
        mic.analyser.fftSize = 512;
        src.connect(mic.analyser);
        var proc = mic.ctx.createScriptProcessor(2048, 1, 1);
        proc.onaudioprocess = function (e) {
          if (mic.recording) mic.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
        };
        var mute = mic.ctx.createGain();
        mute.gain.value = 0;
        src.connect(proc);
        proc.connect(mute);
        mute.connect(mic.ctx.destination);
        mic.pending = null;
        return true;
      })
      .catch(function () {
        mic.pending = null;
        caption("The microphone is blocked. Allow it in the address bar, or type instead.", "problem");
        return false;
      });
    return mic.pending;
  }

  function startRecording() {
    if (!canListen || mic.held || busy) return;
    mic.held = true;
    stopSpeaking();
    ensureMic().then(function (ok) {
      if (!ok || !mic.held) { if (ok) caption("Microphone ready. " + idleCaption()); return; }
      if (mic.ctx.state === "suspended") mic.ctx.resume();
      mic.chunks = [];
      mic.recording = true;
      mic.startedAt = Date.now();
      body.classList.add("listening");
      caption("Listening…");
    });
  }

  function stopRecording() {
    if (!mic.held) return;
    mic.held = false;
    if (!mic.recording) return;
    setTimeout(function () {           // keep the tail of the last word
      mic.recording = false;
      body.classList.remove("listening");
      var held = Date.now() - mic.startedAt;
      var samples = merge(mic.chunks);
      mic.chunks = [];
      if (held < 450 || samples.length < mic.ctx.sampleRate * 0.3) { caption("Hold the space bar while you talk."); return; }
      caption("Transcribing on this laptop…");
      var wav = encodeWav(resample(samples, mic.ctx.sampleRate, 16000), 16000);
      busy = true;
      fetch("/api/transcribe", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav })
        .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || "transcription failed"); return j; }); })
        .then(function (j) {
          busy = false;
          if (!j.text) { caption("I didn't catch that. Try again, a little closer to the microphone."); return; }
          send(j.text, j);
        })
        .catch(function (e) { busy = false; caption(e.message, "problem"); });
    }, 220);
  }

  function merge(chunks) {
    var n = 0, i;
    for (i = 0; i < chunks.length; i++) n += chunks[i].length;
    var out = new Float32Array(n), o = 0;
    for (i = 0; i < chunks.length; i++) { out.set(chunks[i], o); o += chunks[i].length; }
    return out;
  }
  function resample(input, from, to) {
    if (from === to) return input;
    var ratio = from / to, n = Math.floor(input.length / ratio), out = new Float32Array(n);
    for (var i = 0; i < n; i++) {           // average each window: a cheap low-pass before decimating
      var a = Math.floor(i * ratio), b = Math.min(input.length, Math.floor((i + 1) * ratio)), s = 0;
      for (var j = a; j < b; j++) s += input[j];
      out[i] = b > a ? s / (b - a) : 0;
    }
    return out;
  }
  function encodeWav(samples, rate) {
    var buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
    var w = function (o, s) { for (var i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    w(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    w(36, "data"); v.setUint32(40, samples.length * 2, true);
    for (var i = 0; i < samples.length; i++) {
      var x = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  // ------------------------------------------------------------- waveform
  var wave = $("wave"), wctx = wave.getContext("2d"), wdata = null, phase = 0;
  function sizeWave() {
    var dpr = window.devicePixelRatio || 1;
    wave.width = Math.max(1, Math.floor(wave.clientWidth * dpr));
    wave.height = Math.floor(44 * dpr);
  }
  function drawWave() {
    var W = wave.width, H = wave.height, bars = 72, gap = W / bars, mid = H / 2;
    wctx.clearRect(0, 0, W, H);
    var listening = mic.recording && mic.analyser, speaking = voice.playing;
    if (listening) {
      if (!wdata) wdata = new Uint8Array(mic.analyser.fftSize);
      mic.analyser.getByteTimeDomainData(wdata);
    }
    phase += 0.09;
    for (var i = 0; i < bars; i++) {
      var h = 2;
      if (listening) {
        var seg = Math.floor(wdata.length / bars), peak = 0;
        for (var j = 0; j < seg; j++) peak = Math.max(peak, Math.abs(wdata[i * seg + j] - 128));
        h = Math.max(2, (peak / 128) * H * 1.6);
      } else if (speaking) {
        h = 3 + (Math.sin(phase + i * 0.45) * 0.5 + 0.5) * (Math.sin(phase * 0.6 + i * 0.13) * 0.5 + 0.5) * H * 0.7;
      }
      h = Math.min(h, H);
      wctx.fillStyle = listening ? "#e8472b" : speaking ? "#f4d61f" : "#3a4d46";
      wctx.fillRect(i * gap + gap * 0.2, mid - h / 2, gap * 0.6, h);
    }
    requestAnimationFrame(drawWave);
  }

  // ---------------------------------------------------------------- timer
  var timer = {
    total: 0, left: 0, id: null,
    fmt: function (s) { return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2); },
    setup: function (seconds) {
      this.stop();
      this.total = this.left = seconds;
      $("timer").hidden = !seconds;
      $("timer-btn").textContent = "Start " + this.fmt(seconds) + " timer";
      $("timer-read").textContent = "";
    },
    start: function () {
      if (!this.total || this.id) return;
      var self = this;
      this.left = this.total;
      $("timer-btn").textContent = "Stop timer";
      $("timer-read").textContent = this.fmt(this.left);
      this.id = setInterval(function () {
        self.left--;
        $("timer-read").textContent = self.fmt(Math.max(0, self.left));
        if (self.left <= 0) {
          self.stop();
          $("timer-read").textContent = "Time is up";
          $("timer-btn").textContent = "Restart timer";
          beep(880, 0.25); setTimeout(function () { beep(880, 0.25); }, 400);
          if (!voice.playing) speak(["Time is up. Say next when you are ready."]);
        }
      }, 1000);
    },
    stop: function () { if (this.id) { clearInterval(this.id); this.id = null; } },
    toggle: function () {
      if (this.id) { this.stop(); this.setup(this.total); } else this.start();
    }
  };

  // ------------------------------------------------------------ metronome
  var actx = null;
  function beep(freq, len, gain) {
    try {
      if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
      if (actx.state === "suspended") actx.resume();
      var o = actx.createOscillator(), g = actx.createGain(), t = actx.currentTime;
      o.frequency.value = freq;
      g.gain.setValueAtTime(gain || 0.25, t);
      g.gain.exponentialRampToValueAtTime(0.001, t + len);
      o.connect(g); g.connect(actx.destination);
      o.start(t); o.stop(t + len);
    } catch (e) {}
  }
  var metro = {
    bpm: 0, id: null, count: 0, muted: false,
    set: function (bpm) {
      if (bpm === this.bpm) return;
      this.bpm = bpm;
      if (this.id) { clearInterval(this.id); this.id = null; }
      $("metro").hidden = !bpm;
      if (!bpm) return;
      var self = this;
      this.count = 0;
      this.id = setInterval(function () {
        self.count = self.count % 30 + 1;
        $("metro-count").textContent = self.count;
        var p = $("metro-pulse");
        p.classList.add("beat");
        setTimeout(function () { p.classList.remove("beat"); }, 90);
        if (!self.muted && !voice.playing && !mic.recording) beep(self.count === 1 ? 1320 : 990, 0.07, 0.3);
      }, 60000 / bpm);
    }
  };

  // --------------------------------------------------------------- report
  function writeReport() {
    var btn = $("btn-report");
    btn.disabled = true;
    btn.textContent = "Writing the report…";
    api("/api/handoff", {}).then(function (j) {
      $("report").hidden = false;
      $("report-text").textContent = j.report;
      $("report-by").textContent = j.route === "bonsai" ? "Written by Bonsai in " + secs(j.llm.ms) + " s" : "Built from the log";
      btn.disabled = false;
      btn.textContent = "Write handoff report";
      $("report").scrollIntoView({ block: "nearest" });
      $("log").scrollTop = $("log").scrollHeight;
    }).catch(function (e) {
      btn.disabled = false;
      btn.textContent = "Write handoff report";
      caption("Could not write the report: " + e.message, "problem");
    });
  }

  // --------------------------------------------------------------- wiring
  $("btn-next").addEventListener("click", function () { send("next"); });
  $("btn-back").addEventListener("click", function () { send("go back"); });
  $("btn-repeat").addEventListener("click", function () { send("repeat"); });
  $("btn-reset").addEventListener("click", function () { $("report").hidden = true; act("/api/reset", {}); });
  $("btn-report").addEventListener("click", writeReport);
  $("btn-report-close").addEventListener("click", function () { $("report").hidden = true; });
  $("btn-report-read").addEventListener("click", function () {
    speak($("report-text").textContent.split("\n").filter(function (l) { return l.trim(); }));
  });
  $("btn-report-copy").addEventListener("click", function () {
    var t = $("report-text").textContent;
    if (navigator.clipboard) navigator.clipboard.writeText(t);
    $("btn-report-copy").textContent = "Copied";
    setTimeout(function () { $("btn-report-copy").textContent = "Copy"; }, 1500);
  });
  $("timer-btn").addEventListener("click", function () { timer.toggle(); });
  $("metro-btn").addEventListener("click", function () {
    metro.muted = !metro.muted;
    $("metro-btn").textContent = metro.muted ? "Play beat" : "Mute beat";
  });
  Array.prototype.forEach.call(document.querySelectorAll(".example"), function (b) {
    b.addEventListener("click", function () { send(b.getAttribute("data-say")); });
  });
  $("type-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var input = $("type-input");
    send(input.value);
    input.value = "";
    input.blur();
  });

  var talk = $("talk");
  talk.addEventListener("pointerdown", function (e) { e.preventDefault(); startRecording(); });
  talk.addEventListener("pointerup", stopRecording);
  talk.addEventListener("pointerleave", stopRecording);
  talk.addEventListener("pointercancel", stopRecording);

  function typing(e) {
    var t = e.target;
    return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
  }
  document.addEventListener("keydown", function (e) {
    if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.code === "Space") { e.preventDefault(); if (!e.repeat) startRecording(); return; }
    if (e.repeat) return;
    if (e.key === "Escape") { stopSpeaking(); caption(idleCaption()); }
    else if (view.card && e.key === "ArrowRight") send("next");
    else if (view.card && e.key === "ArrowLeft") send("go back");
    else if (view.card && (e.key === "r" || e.key === "R")) send("repeat");
  });
  document.addEventListener("keyup", function (e) {
    if (e.code === "Space" && !typing(e)) { e.preventDefault(); stopRecording(); }
  });
  window.addEventListener("blur", stopRecording);
  window.addEventListener("online", renderNet);
  window.addEventListener("offline", renderNet);
  window.addEventListener("resize", sizeWave);
  if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = function () { chosenVoice = null; };

  sizeWave();
  drawWave();
  renderNet();
  poll();
  setInterval(poll, 3000);
})();
