const state = {
    loopback_running: false,
    loopback_mode: "virtual-sink",
    current_file: null,
    volume: 300,
    playback_duration: 0,
    playback_started_at: 0,
    playback_speed: 1.0,
    playback_position: 0,
    conversation_running: false,
    conversation_script: null,
    conversation_turns: [],
    conversation_current_turn: -1,
    conversation_gap_min: 0.1,
    conversation_gap_max: 1.0,
    conversation_playback_duration: 0,
    conversation_playback_started_at: 0,
    conversation_loopbacks_ready: false,
    gen_active: false,
    gen_step: null,
    gen_tts_total: 0,
    gen_tts_completed: 0,
    gen_error: null,
    gen_conversation_name: null,
};

let capabilities = {
    platform: "Linux",
    supports_dynamic_device_creation: true,
    virtual_cables: [],
};

let appConfig = {};
let convTranscript = []; // transcript text per turn (if available)

function playNotificationSound() {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    gain.gain.value = 0.3;
    osc.frequency.value = 880;
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.15);
    osc.frequency.setValueAtTime(660, ctx.currentTime + 0.15);
    gain.gain.setValueAtTime(0.3, ctx.currentTime + 0.25);
    gain.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.4);
    osc.start();
    osc.stop(ctx.currentTime + 0.4);
    osc.onended = () => ctx.close();
}

function notifyConversationDone() {
    if (Notification.permission === "granted") {
        new Notification("Conversation finished", { body: "The conversation has ended." });
    } else if (Notification.permission !== "denied") {
        Notification.requestPermission().then((perm) => {
            if (perm === "granted") {
                new Notification("Conversation finished", { body: "The conversation has ended." });
            }
        });
    }
}

// Request notification permission early so the prompt doesn't come at an awkward time
if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
}

// SSE connection
const evtSource = new EventSource("/api/status");
evtSource.onmessage = (event) => {
    const prev = state.current_file;
    const prevConv = state.conversation_running;
    Object.assign(state, JSON.parse(event.data));
    if (prev && !state.current_file) {
        playNotificationSound();
    }
    if (prevConv && !state.conversation_running) {
        notifyConversationDone();
    }
    render();
};

// --- API functions ---

async function startLoopback() {
    const mode = document.getElementById("mode-select").value;
    const body = { mode };
    if (mode === "sink-capture") {
        body.sink = document.getElementById("sink-select").value;
    }
    await fetch("/api/loopback/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
}

async function stopLoopback() {
    await fetch("/api/loopback/stop", { method: "POST" });
}

async function playFile(filename) {
    await fetch("/api/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }),
    });
}

async function stopPlayback() {
    await fetch("/api/stop", { method: "POST" });
}

async function setVolume(percent) {
    await fetch("/api/volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ percent: parseInt(percent) }),
    });
}

let speedCooldown = false;

async function setSpeed(speed) {
    if (speedCooldown) return;
    speedCooldown = true;
    setTimeout(() => { speedCooldown = false; }, 300);
    await fetch("/api/speed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speed }),
    });
}

async function loadCapabilities() {
    const resp = await fetch("/api/capabilities");
    capabilities = await resp.json();
    applyCapabilities();
}

function applyCapabilities() {
    const modeRow = document.getElementById("mode-row");
    if (modeRow) {
        modeRow.style.display = capabilities.supports_dynamic_device_creation ? "" : "none";
    }
    const loopbackButtons = document.getElementById("loopback-buttons");
    const cableSelect = document.getElementById("cable-select-group");
    if (!capabilities.supports_dynamic_device_creation) {
        if (loopbackButtons) loopbackButtons.style.display = "none";
        if (cableSelect) {
            cableSelect.style.display = "flex";
            const sel = document.getElementById("cable-select");
            sel.innerHTML = "";
            capabilities.virtual_cables.forEach((c) => {
                const opt = document.createElement("option");
                opt.value = c.name;
                opt.textContent = c.name;
                sel.appendChild(opt);
            });
        }
    } else {
        if (loopbackButtons) loopbackButtons.style.display = "";
        if (cableSelect) cableSelect.style.display = "none";
    }
}

async function loadConfig() {
    const resp = await fetch("/api/config");
    appConfig = await resp.json();
    populateSettingsForm();
    buildSpeedButtons();
}

async function saveConfig() {
    const form = document.getElementById("settings-form");
    const updated = {
        samples_dir: form.querySelector("#cfg-samples-dir").value,
        default_volume: parseInt(form.querySelector("#cfg-default-volume").value),
        sample_rate: parseInt(form.querySelector("#cfg-sample-rate").value),
        channels: parseInt(form.querySelector("#cfg-channels").value),
        tts_provider: form.querySelector("#cfg-tts-provider").value,
        conversation_gap_min: parseFloat(form.querySelector("#cfg-gap-min").value),
        conversation_gap_max: parseFloat(form.querySelector("#cfg-gap-max").value),
        allowed_speeds: form.querySelector("#cfg-speeds").value
            .split(",").map(s => parseFloat(s.trim())).filter(n => !isNaN(n)),
        virtual_sink_name: form.querySelector("#cfg-sink-name").value,
        virtual_mic_name: form.querySelector("#cfg-mic-name").value,
        conversation_sink1_name: form.querySelector("#cfg-conv-sink1").value,
        conversation_sink2_name: form.querySelector("#cfg-conv-sink2").value,
        conversation_mic1_name: form.querySelector("#cfg-conv-mic1").value,
        conversation_mic2_name: form.querySelector("#cfg-conv-mic2").value,
        host: form.querySelector("#cfg-host").value,
        port: parseInt(form.querySelector("#cfg-port").value),
    };

    const resp = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
    });
    const result = await resp.json();
    const status = document.getElementById("settings-status");
    if (result.errors) {
        status.textContent = "Error: " + result.errors.join(", ");
        status.className = "settings-status error";
    } else {
        appConfig = result;
        status.textContent = "Saved";
        status.className = "settings-status ok";
        buildSpeedButtons();
        loadFiles();
        loadConversations();
        setTimeout(() => { status.textContent = ""; }, 2000);
    }
}

function populateSettingsForm() {
    const c = appConfig;
    document.getElementById("cfg-samples-dir").value = c.samples_dir || "";
    document.getElementById("cfg-default-volume").value = c.default_volume ?? 300;
    document.getElementById("cfg-sample-rate").value = c.sample_rate ?? 48000;
    document.getElementById("cfg-channels").value = c.channels ?? 2;
    document.getElementById("cfg-tts-provider").value = c.tts_provider || "deepgram";
    document.getElementById("cfg-gap-min").value = c.conversation_gap_min ?? 0.1;
    document.getElementById("cfg-gap-max").value = c.conversation_gap_max ?? 1.0;
    document.getElementById("cfg-speeds").value = (c.allowed_speeds || []).join(", ");
    document.getElementById("cfg-sink-name").value = c.virtual_sink_name || "";
    document.getElementById("cfg-mic-name").value = c.virtual_mic_name || "";
    document.getElementById("cfg-conv-sink1").value = c.conversation_sink1_name || "";
    document.getElementById("cfg-conv-sink2").value = c.conversation_sink2_name || "";
    document.getElementById("cfg-conv-mic1").value = c.conversation_mic1_name || "";
    document.getElementById("cfg-conv-mic2").value = c.conversation_mic2_name || "";
    document.getElementById("cfg-host").value = c.host || "127.0.0.1";
    document.getElementById("cfg-port").value = c.port ?? 8000;
}

function buildSpeedButtons() {
    const container = document.getElementById("speed-controls");
    if (!container) return;
    container.innerHTML = "";
    const speeds = (appConfig.allowed_speeds || [1.0]).slice().sort((a, b) => a - b);
    speeds.forEach((s) => {
        const btn = document.createElement("button");
        btn.className = "speed-btn";
        btn.textContent = `${s}x`;
        btn.onclick = () => setSpeed(s);
        container.appendChild(btn);
    });
}

function toggleSettings() {
    const panel = document.getElementById("settings-panel");
    const arrow = document.getElementById("settings-toggle");
    if (panel.style.display === "none") {
        panel.style.display = "block";
        arrow.textContent = "▲";
    } else {
        panel.style.display = "none";
        arrow.textContent = "▼";
    }
}

async function loadConversations() {
    const resp = await fetch("/api/conversations");
    const data = await resp.json();
    ["conversation-select", "conversation-select-ready"].forEach((id) => {
        const select = document.getElementById(id);
        select.innerHTML = "";
        data.conversations.forEach((script) => {
            const option = document.createElement("option");
            option.value = script;
            option.textContent = script;
            select.appendChild(option);
        });
    });
}

async function fetchConversationTranscript(script) {
    const name = script.replace(/\.json$/, "");
    try {
        const resp = await fetch(`/api/conversations/${encodeURIComponent(name)}/transcript`);
        const data = await resp.json();
        convTranscript = data.turns || [];
    } catch {
        convTranscript = [];
    }
}

async function startConversation() {
    const script = document.getElementById("conversation-select").value;
    if (!script) return;
    await fetchConversationTranscript(script);
    await fetch("/api/conversation/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script }),
    });
}

async function stopConversation() {
    await fetch("/api/conversation/stop", { method: "POST" });
    convTranscript = [];
}

async function prepareConversation() {
    await fetch("/api/conversation/prepare", { method: "POST" });
}

async function unprepareConversation() {
    await fetch("/api/conversation/unprepare", { method: "POST" });
}

async function startConversationFromReady() {
    const script = document.getElementById("conversation-select-ready").value;
    if (!script) return;
    await fetchConversationTranscript(script);
    await fetch("/api/conversation/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script }),
    });
}

async function loadFiles() {
    const resp = await fetch("/api/files");
    const data = await resp.json();
    const list = document.getElementById("file-list");
    list.innerHTML = "";
    data.files.forEach((file) => {
        const li = document.createElement("li");
        const span = document.createElement("span");
        span.textContent = file;
        const btn = document.createElement("button");
        btn.className = "play-btn";
        btn.textContent = "Play";
        btn.onclick = () => playFile(file);
        li.appendChild(span);
        li.appendChild(btn);
        list.appendChild(li);
    });
}

async function loadSinks() {
    const resp = await fetch("/api/sinks");
    const data = await resp.json();
    const select = document.getElementById("sink-select");
    select.innerHTML = "";
    data.sinks.forEach((sink) => {
        const option = document.createElement("option");
        option.value = sink;
        option.textContent = sink;
        select.appendChild(option);
    });
}

// --- Rendering ---

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

let convTurnListBuilt = false;

function renderConvTurnList(activeTurn) {
    const container = document.getElementById("conv-turn-list");
    const turns = state.conversation_turns;

    // Build the list once, then just update classes
    if (!convTurnListBuilt || container.children.length !== turns.length) {
        container.innerHTML = "";
        turns.forEach((t, i) => {
            const div = document.createElement("div");
            div.className = "conv-turn-item";
            div.dataset.index = i;

            const speakerNum = t.speaker;
            const transcript = convTranscript[i];

            if (transcript && transcript.text) {
                div.innerHTML =
                    `<span class="conv-turn-speaker speaker-${speakerNum}">${transcript.speaker}:</span> ` +
                    `<span class="conv-turn-text">${escapeHtml(transcript.text)}</span>`;
            } else {
                const file = (t.file || "").split("/").pop();
                div.innerHTML =
                    `<span class="conv-turn-speaker speaker-${speakerNum}">Speaker ${speakerNum}:</span> ` +
                    `<span class="conv-turn-file">${file}</span>`;
            }
            container.appendChild(div);
        });
        convTurnListBuilt = true;
    }

    // Update active/done classes
    for (const child of container.children) {
        const idx = parseInt(child.dataset.index);
        child.classList.toggle("active", idx === activeTurn);
        child.classList.toggle("done", idx < activeTurn);
    }

    // Auto-scroll to active turn
    const activeEl = container.querySelector(".conv-turn-item.active");
    if (activeEl) {
        activeEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function render() {
    const statusEl = document.getElementById("loopback-status");
    statusEl.textContent = state.loopback_running
        ? `Running (${state.loopback_mode})`
        : "Stopped";
    statusEl.className = state.loopback_running ? "status-on" : "status-off";

    document.getElementById("btn-start").disabled = state.loopback_running;
    document.getElementById("btn-stop").disabled = !state.loopback_running;

    document.getElementById("volume-slider").value = state.volume;
    document.getElementById("volume-value").textContent = `${state.volume}%`;

    const nowPlaying = document.getElementById("now-playing");
    if (state.current_file) {
        nowPlaying.style.display = "block";
        document.getElementById("now-playing-file").textContent = state.current_file;
        document.querySelectorAll(".speed-btn").forEach((btn) => {
            const btnSpeed = parseFloat(btn.textContent);
            btn.classList.toggle("active", btnSpeed === state.playback_speed);
        });
    } else {
        nowPlaying.style.display = "none";
    }

    document.querySelectorAll(".play-btn").forEach((btn) => {
        btn.disabled = !state.loopback_running || state.loopback_mode !== "virtual-sink";
    });

    const convControl = document.getElementById("conversation-control");
    const convPlaying = document.getElementById("conversation-playing");
    const convReady = document.getElementById("conversation-ready");

    if (state.conversation_running) {
        document.getElementById("loopback-control").style.display = "none";
        document.getElementById("volume-control").style.display = "none";
        document.getElementById("audio-files").style.display = "none";
        nowPlaying.style.display = "none";
        convControl.style.display = "none";
        convReady.style.display = "none";
        convPlaying.style.display = "block";

        const turn = state.conversation_current_turn;
        const total = state.conversation_turns.length;
        document.getElementById("conv-turn-info").textContent = `— Turn ${turn + 1} of ${total}`;

        renderConvTurnList(turn);
    } else {
        convTurnListBuilt = false;
        if (state.conversation_loopbacks_ready) {
            document.getElementById("loopback-control").style.display = "none";
            document.getElementById("volume-control").style.display = "none";
            document.getElementById("audio-files").style.display = "none";
            nowPlaying.style.display = "none";
            convControl.style.display = "none";
            convPlaying.style.display = "none";
            convReady.style.display = "block";
        } else {
            document.getElementById("loopback-control").style.display = "";
            document.getElementById("volume-control").style.display = "";
            document.getElementById("audio-files").style.display = "";
            convControl.style.display = "";
            convReady.style.display = "none";
            convPlaying.style.display = "none";
        }
    }

    renderGeneration();
}

// --- Generate Conversation ---

let genParsedTurns = [];
let genSpeakerMapping = {};
let genCurrentStep = 1;

function toggleGenerate() {
    const panel = document.getElementById("generate-panel");
    const arrow = document.getElementById("generate-toggle");
    if (panel.style.display === "none") {
        panel.style.display = "block";
        arrow.innerHTML = "&#9650;";
    } else {
        panel.style.display = "none";
        arrow.innerHTML = "&#9660;";
    }
}

function genSetStep(step) {
    genCurrentStep = step;
    document.getElementById("gen-step-1").style.display = step === 1 ? "" : "none";
    document.getElementById("gen-step-2").style.display = step === 2 ? "" : "none";
    document.getElementById("gen-step-3").style.display = step === 3 ? "" : "none";
    document.querySelectorAll(".step-pill").forEach((pill) => {
        const s = parseInt(pill.dataset.step);
        pill.classList.toggle("active", s === step);
        pill.classList.toggle("done", s < step);
    });
}

function genShowManual() {
    const name = document.getElementById("gen-name").value.trim();
    if (!name) { alert("Enter a conversation name first."); return; }
    document.getElementById("gen-transcript").value = "";
    genSetStep(2);
}

function genShowClaude() {
    document.getElementById("gen-claude-panel").style.display = "block";
}

async function genRunClaude() {
    const name = document.getElementById("gen-name").value.trim();
    if (!name) { alert("Enter a conversation name first."); return; }

    const topic = document.getElementById("gen-topic").value.trim();
    if (!topic) { alert("Enter a topic."); return; }

    const speakersRaw = document.getElementById("gen-speakers-input").value.trim();
    const speakers = speakersRaw ? speakersRaw.split(",").map(s => s.trim()).filter(Boolean) : null;

    const btn = document.getElementById("gen-claude-btn");
    const statusEl = document.getElementById("gen-claude-status");
    btn.disabled = true;
    statusEl.textContent = "Generating...";

    try {
        const resp = await fetch("/api/generate/transcript", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ topic, speakers }),
        });

        if (!resp.ok) {
            const data = await resp.json();
            statusEl.textContent = data.error || "Failed";
            btn.disabled = false;
            return;
        }

        let transcript = "";
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split("\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                try {
                    const msg = JSON.parse(line.slice(6));
                    if (msg.text) {
                        transcript += msg.text;
                        statusEl.textContent = transcript;
                        statusEl.scrollTop = statusEl.scrollHeight;
                    }
                    if (msg.error) {
                        statusEl.textContent += "\nError: " + msg.error;
                    }
                    if (msg.done) {
                        document.getElementById("gen-transcript").value = transcript.trim();
                        genSetStep(2);
                    }
                } catch {}
            }
        }
    } catch (err) {
        statusEl.textContent = "Error: " + err.message;
    }
    btn.disabled = false;
}

function genBackToStep1() {
    genSetStep(1);
}

async function genProceedToTTS() {
    const text = document.getElementById("gen-transcript").value.trim();
    if (!text) { alert("Enter a transcript first."); return; }

    const resp = await fetch("/api/generate/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
    });
    const data = await resp.json();
    if (data.error) {
        alert(data.error);
        return;
    }

    genParsedTurns = data.turns;
    const speakers = data.speakers;

    // Auto-assign first two speakers
    genSpeakerMapping = {};
    speakers.forEach((s, i) => {
        genSpeakerMapping[s] = i < 2 ? i + 1 : 1;
    });

    const infoEl = document.getElementById("gen-speakers-info");
    infoEl.textContent = `Detected ${speakers.length} speaker(s): ${speakers.join(", ")} (${genParsedTurns.length} turns)`;

    const mappingEl = document.getElementById("gen-speaker-mapping");
    if (speakers.length > 2) {
        mappingEl.style.display = "block";
        mappingEl.innerHTML = "<p style='font-size:0.85rem;color:#aaa;margin-bottom:0.5rem'>Assign each speaker to Mic 1 or Mic 2:</p>";
        speakers.forEach((name) => {
            const row = document.createElement("div");
            row.className = "mapping-row";
            row.innerHTML = `
                <label>${name}</label>
                <select data-speaker="${name}">
                    <option value="1" ${genSpeakerMapping[name] === 1 ? "selected" : ""}>Mic 1</option>
                    <option value="2" ${genSpeakerMapping[name] === 2 ? "selected" : ""}>Mic 2</option>
                </select>
            `;
            row.querySelector("select").addEventListener("change", function () {
                genSpeakerMapping[name] = parseInt(this.value);
            });
            mappingEl.appendChild(row);
        });
    } else {
        mappingEl.style.display = "none";
    }

    // Show summary on step 3
    const summaryEl = document.getElementById("gen-tts-speakers-summary");
    summaryEl.innerHTML = speakers.map(s =>
        `<span class="speaker-${genSpeakerMapping[s]}">${s} → Mic ${genSpeakerMapping[s]}</span>`
    ).join(", ");

    // Default the TTS provider dropdown to the configured provider
    if (appConfig.tts_provider) {
        document.getElementById("gen-provider").value = appConfig.tts_provider;
    }

    genSetStep(3);
}

function genBackToStep2() {
    genSetStep(2);
}

async function genStartTTS() {
    const name = document.getElementById("gen-name").value.trim();
    const provider = document.getElementById("gen-provider").value;
    const speed = parseFloat(document.getElementById("gen-speed").value);
    const gapMin = parseFloat(document.getElementById("gen-gap-min").value);
    const gapMax = parseFloat(document.getElementById("gen-gap-max").value);

    // Re-read mapping from dropdowns if they exist
    document.querySelectorAll("#gen-speaker-mapping select[data-speaker]").forEach((sel) => {
        genSpeakerMapping[sel.dataset.speaker] = parseInt(sel.value);
    });

    // Update summary colors before starting
    const speakers = [...new Set(genParsedTurns.map(t => t.speaker))];
    document.getElementById("gen-tts-speakers-summary").innerHTML = speakers.map(s =>
        `<span class="speaker-${genSpeakerMapping[s]}">${s} → Mic ${genSpeakerMapping[s]}</span>`
    ).join(", ");

    const resultEl = document.getElementById("gen-result");
    resultEl.style.display = "none";

    const resp = await fetch("/api/generate/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name,
            turns: genParsedTurns,
            speaker_mapping: genSpeakerMapping,
            provider,
            speed,
            gap_min: gapMin,
            gap_max: gapMax,
        }),
    });
    const data = await resp.json();
    if (data.error) {
        resultEl.textContent = data.error;
        resultEl.className = "error";
        resultEl.style.display = "block";
    }
}

async function genCancelTTS() {
    await fetch("/api/generate/cancel", { method: "POST" });
}

function renderGeneration() {
    const progressEl = document.getElementById("gen-progress");
    const cancelBtn = document.getElementById("gen-cancel-btn");
    const ttsBtn = document.getElementById("gen-tts-btn");
    const resultEl = document.getElementById("gen-result");

    if (state.gen_active && state.gen_step === "tts") {
        progressEl.style.display = "block";
        cancelBtn.style.display = "";
        ttsBtn.disabled = true;

        const pct = state.gen_tts_total > 0
            ? (state.gen_tts_completed / state.gen_tts_total) * 100
            : 0;
        document.getElementById("gen-progress-bar").style.width = `${pct}%`;
        document.getElementById("gen-progress-text").textContent =
            `${state.gen_tts_completed} / ${state.gen_tts_total} turns`;
    } else {
        cancelBtn.style.display = "none";
        ttsBtn.disabled = false;

        if (state.gen_error) {
            progressEl.style.display = "none";
            resultEl.textContent = "Error: " + state.gen_error;
            resultEl.className = "error";
            resultEl.style.display = "block";
        } else if (!state.gen_active && state.gen_tts_total > 0 && state.gen_tts_completed === state.gen_tts_total) {
            document.getElementById("gen-progress-bar").style.width = "100%";
            resultEl.textContent = `Done! "${state.gen_conversation_name}" is ready to play.`;
            resultEl.className = "success";
            resultEl.style.display = "block";
            loadConversations();
        }
    }
}

// --- Event handlers ---

document.getElementById("mode-select").addEventListener("change", function () {
    const isSinkCapture = this.value === "sink-capture";
    document.getElementById("sink-group").style.display = isSinkCapture ? "flex" : "none";
    if (isSinkCapture) loadSinks();
});

document.getElementById("volume-slider").addEventListener("input", function () {
    document.getElementById("volume-value").textContent = `${this.value}%`;
});

document.getElementById("volume-slider").addEventListener("change", function () {
    setVolume(this.value);
});

// Progress bar update
setInterval(() => {
    if (state.current_file && state.playback_duration > 0) {
        const elapsed_in_source =
            state.playback_position +
            (Date.now() / 1000 - state.playback_started_at) * state.playback_speed;
        const progress = Math.min((elapsed_in_source / state.playback_duration) * 100, 100);
        document.getElementById("progress-bar").style.width = `${progress}%`;
        document.getElementById("progress-time").textContent =
            `${formatTime(elapsed_in_source)} / ${formatTime(state.playback_duration)}`;
    }
    if (state.conversation_running && state.conversation_playback_duration > 0) {
        const elapsed = Date.now() / 1000 - state.conversation_playback_started_at;
        const progress = Math.min((elapsed / state.conversation_playback_duration) * 100, 100);
        document.getElementById("conv-progress-bar").style.width = `${progress}%`;
        document.getElementById("conv-progress-time").textContent =
            `${formatTime(elapsed)} / ${formatTime(state.conversation_playback_duration)}`;
    }
}, 500);

// Initial load
loadCapabilities();
loadConfig();
loadFiles();
loadConversations();
