/* The browser phone for WhatsApp calls (Meta Business Calling API, browser-direct: the audio goes straight between this browser and Meta, nothing
 * passes through the ERP server). Loaded on every Desk page by waba_alerts_core.js only for people the server flagged (frappe.boot.waba_calls).
 *
 *   - placing a call: ask the customer's permission when needed, call with a WebRTC offer, take Meta's answer, show the call bar;
 *   - taking a call: a ring box with a ringtone and Accept / Decline; the first person to accept gets the call;
 *   - a missed call: a toast with an Open button;
 *   - no microphone: when Waba Settings allows it, the call is made or taken listen-only (a silent audio track is sent, the customer hears silence).
 * Every decision is made on the server (waba.api.calls); this file only draws and carries audio. Pure helpers come first (tested offline in Node). */
(function (root, factory) {
	const phone = factory();
	if (typeof module !== "undefined" && module.exports) module.exports = phone;
	else phone.start(root);
})(typeof self !== "undefined" ? self : this, function () {
	const STUN = [{ urls: "stun:stun.l.google.com:19302" }, { urls: "stun:stun1.l.google.com:19302" }];
	const ANSWER_POLL_MS = 1000;
	const ANSWER_GIVE_UP_MS = 70000;
	const ALERT_KEY = "waba_alerts_v1";
	const FAINT_HZ = 997; // the listen-only signal: about -62 dB, inaudible, but real audio so the call is carried and recorded
	const FAINT_GAIN = 0.0008;

	/** "00:07", "02:10", "1:02:03": the talk timer. */
	function timerText(seconds) {
		const s = Math.max(0, Math.floor(Number(seconds) || 0));
		const h = Math.floor(s / 3600);
		const m = Math.floor((s % 3600) / 60);
		const ss = s % 60;
		const two = (n) => String(n).padStart(2, "0");
		return h ? `${h}:${two(m)}:${two(ss)}` : `${two(m)}:${two(ss)}`;
	}

	/** The words on the call bar for a call status (the server's Waba Call statuses). */
	function statusText(status, direction) {
		const out = direction !== "Incoming";
		return (
			{
				Ringing: out ? "Ringing..." : "Incoming call",
				Answered: "Connected",
				Completed: "Call ended",
				Missed: "No answer",
				"No answer": "No answer",
				Rejected: "Declined",
				Failed: "The call failed",
				Cancelled: "Call cancelled",
			}[status] || status || ""
		);
	}

	const FINISHED = ["Completed", "Missed", "No answer", "Rejected", "Failed", "Cancelled"];
	const isFinished = (status) => FINISHED.includes(status);

	/** What to tell the person when the microphone cannot be used. */
	function micProblem(error) {
		const name = error && error.name;
		if (name === "NotAllowedError" || name === "SecurityError") return "The browser blocked the microphone. Allow it for this site (the lock icon in the address bar) and try again.";
		if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone was found. Connect a headset and try again.";
		if (name === "NotReadableError") return "The microphone is being used by another program.";
		return "The microphone could not be started.";
	}

	/** Listen-only is offered when the computer has no (usable) microphone and Waba Settings allows it. A microphone the person BLOCKED is
	 *  their choice, so it is not replaced by silence. */
	function listenOnlyAllowed(error, flags) {
		const name = error && error.name;
		return !!(flags && flags.listen_only) && ["NotFoundError", "OverconstrainedError", "NotReadableError", "DevicesNotFoundError"].includes(name);
	}

	/** A plain SDP offer for Meta: audio only. The offer needs no candidates (Meta answers as an ICE-lite endpoint). */
	function offerOptions() {
		return { offerToReceiveAudio: true, offerToReceiveVideo: false };
	}

	/** True when the browser can do WebRTC audio calls at all. */
	function supported(root) {
		return !!(root.RTCPeerConnection && root.navigator && root.navigator.mediaDevices && root.navigator.mediaDevices.getUserMedia);
	}

	/** The line on a ring box / toast: who is calling. The server sends `label` (record name, a real WhatsApp name or the phone). */
	function ringLabel(data) {
		return String((data && (data.label || data.name || data.phone)) || "WhatsApp");
	}

	/** Seconds left of a ring (never negative), from the moment it started. */
	function ringLeft(total, startedMs, nowMs) {
		return Math.max(0, Math.ceil(Number(total || 30) - (Number(nowMs) - Number(startedMs)) / 1000));
	}

	/** What a realtime `waba_call` event means for the phone right now.
	 * ctx: {activeCall (the call this person is in, or null), ringing (calls with a ring box), me (the user)}
	 * Returns one of: "ring", "close-ring", "taken", "missed", "active-progress", "active-answer", "ignore". */
	function routeEvent(data, ctx) {
		if (!data || !data.call) return "ignore";
		const kind = data.kind;
		const mine = ctx.activeCall && data.call === ctx.activeCall;
		if (kind === "ring") return mine || ctx.ringing.includes(data.call) ? "ignore" : "ring";
		if (kind === "taken") return ctx.ringing.includes(data.call) ? "taken" : "ignore";
		if (kind === "dismiss") return ctx.ringing.includes(data.call) ? "close-ring" : "ignore";
		if (kind === "missed") return "missed";
		if (kind === "ended") return mine ? "active-progress" : ctx.ringing.includes(data.call) ? "close-ring" : "ignore";
		if (kind === "answer") return mine ? "active-answer" : "ignore";
		if (kind === "progress") return mine ? "active-progress" : ctx.ringing.includes(data.call) && isFinished(data.status) ? "close-ring" : "ignore";
		return "ignore";
	}

	const CSS =
		".waba-callbar,.waba-ringbox{position:fixed;right:20px;z-index:1060;min-width:300px;max-width:92vw;padding:14px 16px;border-radius:16px;background:var(--bg-color,#fff);color:var(--text-color,#222);box-shadow:0 10px 36px rgba(0,0,0,.28);border:1px solid var(--border-color,#d1d8dd);font-size:14px}" +
		".waba-callbar{bottom:20px}.waba-ringbox{bottom:20px}.waba-ringbox+.waba-ringbox{bottom:150px}.waba-callbar~.waba-ringbox{bottom:150px}" +
		".waba-callbar .wc-top,.waba-ringbox .wc-top{display:flex;align-items:center;gap:10px}.waba-callbar .wc-dot,.waba-ringbox .wc-dot{width:10px;height:10px;border-radius:50%;background:#f5a623;flex:none}" +
		".waba-callbar.live .wc-dot{background:#25d366}.waba-callbar.over .wc-dot{background:#9aa5b1}.waba-ringbox .wc-dot{background:#25d366;animation:wabaRing 1s infinite}" +
		"@keyframes wabaRing{0%{box-shadow:0 0 0 0 rgba(37,211,102,.6)}100%{box-shadow:0 0 0 12px rgba(37,211,102,0)}}" +
		".waba-callbar .wc-who,.waba-ringbox .wc-who{font-weight:600;line-height:1.2}.wc-sub{color:var(--text-muted,#6c7680);font-size:12px}" +
		".waba-callbar .wc-time,.waba-ringbox .wc-time{margin-left:auto;font-variant-numeric:tabular-nums;font-weight:600}" +
		".waba-callbar .wc-actions,.waba-ringbox .wc-actions{display:flex;gap:8px;margin-top:12px}.waba-callbar button,.waba-ringbox button{flex:1;border:0;border-radius:10px;padding:9px 10px;font-weight:600;cursor:pointer}" +
		".waba-callbar .wc-mute{background:var(--control-bg,#eef1f4);color:inherit}.waba-callbar .wc-mute.on{background:#ffe1e1;color:#a11}.waba-callbar .wc-hang,.waba-ringbox .wc-decline{background:#e5484d;color:#fff}" +
		".waba-ringbox .wc-accept{background:#25d366;color:#fff}.waba-callbar .wc-close{background:var(--control-bg,#eef1f4);color:inherit}.waba-ringbox a{color:inherit;text-decoration:underline}";

	function start(root) {
		if (!root.frappe || !root.document || root.WabaPhone) return;
		const frappe = root.frappe;
		const __ = root.__ || ((t) => t);
		const flags = () => (frappe.boot && frappe.boot.waba_calls) || {};
		const state = { pc: null, stream: null, ctx: null, call: null, timer: null, since: null, started: null, poll: null, muted: false, listenOnly: false, $bar: null, audio: null, ended: false, label: "", phone: "", direction: "Outgoing" };
		const rings = {}; // call name -> {$box, timer, ends}
		const ringing = () => Object.keys(rings);
		const tone = { ctx: null, timer: null, title: null, blink: null };

		function ensureStyle() {
			if (root.document.getElementById("waba-callbar-css")) return;
			const el = root.document.createElement("style");
			el.id = "waba-callbar-css";
			el.textContent = CSS;
			root.document.head.appendChild(el);
		}

		const esc = (t) => frappe.utils.escape_html(String(t == null ? "" : t));

		function wantsSound() {
			try {
				const stored = JSON.parse(root.localStorage.getItem(ALERT_KEY) || "{}") || {};
				return typeof stored.sound === "boolean" ? stored.sound : true;
			} catch (e) {
				return true;
			}
		}

		// ------------------------------------------------------------ ringtone, title blink, desktop notice
		function ringOnce() {
			try {
				const Ctx = root.AudioContext || root.webkitAudioContext;
				if (!Ctx) return;
				tone.ctx = tone.ctx || new Ctx();
				if (tone.ctx.state === "suspended") tone.ctx.resume();
				const c = tone.ctx;
				const t = c.currentTime;
				[0, 0.45].forEach((at) => {
					const osc = c.createOscillator();
					const gain = c.createGain();
					osc.type = "sine";
					osc.frequency.value = at ? 480 : 440;
					gain.gain.setValueAtTime(0.0001, t + at);
					gain.gain.exponentialRampToValueAtTime(0.35, t + at + 0.03);
					gain.gain.exponentialRampToValueAtTime(0.0001, t + at + 0.38);
					osc.connect(gain);
					gain.connect(c.destination);
					osc.start(t + at);
					osc.stop(t + at + 0.4);
				});
			} catch (e) {
				/* the browser may block sound until the first click in the page */
			}
		}

		function startAlerting() {
			if (tone.timer) return;
			if (wantsSound()) {
				ringOnce();
				tone.timer = setInterval(ringOnce, 2200);
			} else tone.timer = setInterval(() => {}, 2200);
			tone.title = root.document.title;
			let on = false;
			tone.blink = setInterval(() => {
				on = !on;
				root.document.title = on ? __("Incoming WhatsApp call") : tone.title;
			}, 900);
		}

		function stopAlerting() {
			if (tone.timer) clearInterval(tone.timer);
			if (tone.blink) clearInterval(tone.blink);
			tone.timer = tone.blink = null;
			if (tone.title != null) root.document.title = tone.title;
			tone.title = null;
		}

		function desktopNotice(label) {
			try {
				if (!root.document.hidden || !root.Notification || root.Notification.permission !== "granted") return;
				new root.Notification(__("Incoming WhatsApp call"), { body: label, tag: "waba-call" });
			} catch (e) {
				/* optional */
			}
		}

		// ------------------------------------------------------------ the call bar
		function bar() {
			if (state.$bar) return state.$bar;
			ensureStyle();
			state.$bar = root.$(
				`<div class="waba-callbar" role="dialog" aria-label="${esc(__("WhatsApp call"))}">
					<div class="wc-top"><span class="wc-dot"></span><div><div class="wc-who"></div><div class="wc-sub"></div></div><span class="wc-time"></span></div>
					<div class="wc-actions"><button class="wc-mute">${esc(__("Mute"))}</button><button class="wc-hang">${esc(__("Hang up"))}</button></div>
				</div>`
			).appendTo(root.document.body);
			state.$bar.find(".wc-mute").on("click", toggleMute);
			state.$bar.find(".wc-hang").on("click", hangUp);
			return state.$bar;
		}

		function paint(status) {
			const $b = bar();
			$b.toggleClass("live", status === "Answered").toggleClass("over", isFinished(status));
			$b.find(".wc-who").text(state.label || state.phone || "");
			const extra = state.listenOnly && !isFinished(status) ? " · " + __("Listen only") : state.phone && state.label ? " · " + state.phone : "";
			$b.find(".wc-sub").text(__(statusText(status, state.direction)) + extra);
			if (state.listenOnly) $b.find(".wc-mute").hide();
			if (isFinished(status)) {
				$b.find(".wc-actions").html(`<button class="wc-close">${esc(__("Close"))}</button>`);
				$b.find(".wc-close").on("click", closeBar);
				$b.find(".wc-time").text(state.since ? timerText((Date.now() - state.since) / 1000) : "");
			}
		}

		function tick() {
			if (state.since && state.$bar) state.$bar.find(".wc-time").text(timerText((Date.now() - state.since) / 1000));
		}

		function closeBar() {
			if (state.timer) clearInterval(state.timer);
			if (state.$bar) state.$bar.remove();
			state.$bar = null;
			state.timer = null;
		}

		function release() {
			try {
				if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
				if (state.pc) state.pc.close();
				if (state.ctx) state.ctx.close();
				if (state.audio) {
					state.audio.srcObject = null;
					state.audio.remove();
				}
			} catch (e) {
				/* already closed */
			}
			if (state.poll) clearInterval(state.poll);
			Object.assign(state, { pc: null, stream: null, ctx: null, audio: null, poll: null, muted: false });
		}

		function finish(status) {
			if (state.ended) return;
			state.ended = true;
			paint(status);
			release();
			if (state.timer) clearInterval(state.timer);
			state.timer = null;
			state.call = null;
		}

		function toggleMute() {
			if (!state.stream || state.listenOnly) return;
			state.muted = !state.muted;
			state.stream.getAudioTracks().forEach((t) => (t.enabled = !state.muted));
			state.$bar && state.$bar.find(".wc-mute").toggleClass("on", state.muted).text(state.muted ? __("Unmute") : __("Mute"));
		}

		function hangUp() {
			if (!state.call) return closeBar();
			frappe.call({ method: "waba.api.calls.hangup", args: { call: state.call }, silent: true }).then((r) => {
				const out = (r && r.message) || {};
				if (out.ok === false && out.reason) frappe.show_alert({ message: out.reason, indicator: "orange" }, 6);
			});
			finish("Completed");
		}

		function beginTalking() {
			if (state.since) return;
			state.since = Date.now();
			state.timer = setInterval(tick, 1000);
		}

		// ------------------------------------------------------------ audio: the microphone, or silence when there is none
		/** The audio a person without a microphone sends: practically silent (a tone at about -62 dB, far below anything audible on a phone) but NOT
		 *  digital silence. A call that carries no real signal was not recorded by Meta (the first listen-only call produced no recording, calls with
		 *  real audio did), so the stream must keep producing samples: the context is resumed and checked. */
		async function silentStream() {
			const Ctx = root.AudioContext || root.webkitAudioContext;
			const ctx = new Ctx();
			try {
				await ctx.resume();
			} catch (e) {
				/* checked below */
			}
			const osc = ctx.createOscillator();
			osc.frequency.value = FAINT_HZ;
			const gain = ctx.createGain();
			gain.gain.value = FAINT_GAIN;
			const dest = ctx.createMediaStreamDestination();
			osc.connect(gain);
			gain.connect(dest);
			osc.start();
			state.ctx = ctx;
			if (ctx.state !== "running") frappe.show_alert({ message: __("The browser did not start the audio engine. Click in the page and try the call again."), indicator: "orange" }, 8);
			return dest.stream;
		}

		/** The audio we send: the microphone, or (when allowed and the person agrees) a silent track. Resolves to a stream, or null when the call
		 *  must not go on (the reason has been shown). */
		async function getAudio() {
			if (!supported(root)) {
				frappe.msgprint(__("This browser cannot make WhatsApp calls. Use a current Chrome, Edge or Firefox."));
				return null;
			}
			try {
				state.listenOnly = false;
				return await root.navigator.mediaDevices.getUserMedia({ audio: true });
			} catch (e) {
				if (!listenOnlyAllowed(e, flags())) {
					frappe.msgprint({ title: __("Microphone"), message: esc(__(micProblem(e))), indicator: "red" });
					return null;
				}
				const go = await new Promise((resolve) =>
					frappe.confirm(esc(__("No microphone was found on this computer.")) + "<br><br>" + esc(__("Take part in the call anyway and only listen? The customer will hear silence.")), () => resolve(true), () => resolve(false))
				);
				if (!go) return null;
				state.listenOnly = true;
				return await silentStream();
			}
		}

		function newPeer(stream) {
			const pc = new root.RTCPeerConnection({ iceServers: STUN, bundlePolicy: "max-bundle" });
			state.pc = pc;
			state.stream = stream;
			stream.getTracks().forEach((t) => pc.addTrack(t, stream));
			const audio = root.document.createElement("audio");
			audio.autoplay = true;
			root.document.body.appendChild(audio);
			state.audio = audio;
			pc.ontrack = (ev) => {
				audio.srcObject = ev.streams[0];
			};
			pc.oniceconnectionstatechange = () => {
				if (state.pc === pc && ["failed", "disconnected"].includes(pc.iceConnectionState) && state.call) frappe.show_alert({ message: __("The audio connection was lost."), indicator: "orange" }, 6);
			};
			return pc;
		}

		// ------------------------------------------------------------ outgoing
		/** Meta's SDP answer to the call we placed: set it as the remote side as soon as it has arrived. */
		async function takeAnswer() {
			if (!state.call || !state.pc || state.pc.remoteDescription) return;
			const r = await frappe.call({ method: "waba.api.calls.answer_sdp", args: { call: state.call }, silent: true });
			const out = (r && r.message) || {};
			if (out.status && isFinished(out.status)) return finish(out.status);
			if (out.sdp && state.pc && !state.pc.remoteDescription) await state.pc.setRemoteDescription({ type: "answer", sdp: out.sdp });
		}

		async function place(conversation, label, phone) {
			if (state.call || state.pc) return frappe.show_alert({ message: __("You are already in a call."), indicator: "orange" }, 5);
			Object.assign(state, { label, phone, ended: false, since: null, direction: "Outgoing" });
			const stream = await getAudio();
			if (!stream) return release();
			const pc = newPeer(stream);
			paint("Ringing");
			try {
				await pc.setLocalDescription(await pc.createOffer(offerOptions()));
				const r = await frappe.call({ method: "waba.api.calls.place", args: { conversation, sdp: pc.localDescription.sdp }, freeze: true, freeze_message: __("Calling...") });
				const out = (r && r.message) || {};
				if (!out.ok) {
					release();
					closeBar();
					return frappe.msgprint({ title: __("Call not placed"), message: esc(out.reason || ""), indicator: "orange" });
				}
				state.call = out.call;
				state.started = Date.now();
				state.poll = setInterval(() => {
					if (Date.now() - state.started > ANSWER_GIVE_UP_MS) return finish("No answer");
					takeAnswer().catch(() => {});
				}, ANSWER_POLL_MS);
			} catch (e) {
				release();
				closeBar();
				frappe.msgprint({ title: __("Call not placed"), message: esc((e && e.message) || ""), indicator: "red" });
			}
		}

		/** The Call button: ask the server (and through it Meta) whether we may call, ask for permission when needed, then call. */
		async function startCall(conversation, label, phone) {
			const f = flags();
			if (!f.enabled || !f.make) return frappe.msgprint(__("You are not set up to place WhatsApp calls."));
			const r = await frappe.call({ method: "waba.api.calls.can_call", args: { conversation }, freeze: true, freeze_message: __("Checking with WhatsApp...") });
			const info = (r && r.message) || {};
			if (!info.may) return frappe.msgprint({ title: __("Call"), message: esc(info.reason || __("You cannot call this customer.")), indicator: "orange" });
			if (info.can_call) {
				return frappe.confirm(
					esc(__("Call {0} on WhatsApp now?", [label || phone || ""])) + "<br><br>" + esc(__("The call is recorded (WhatsApp tells both people) and outgoing calls are billed per minute.")),
					() => place(conversation, label, phone)
				);
			}
			if (info.status === "no_permission" || info.status === "none") {
				return frappe.confirm(
					esc(__("{0} has not allowed WhatsApp calls yet. Send them a message asking to allow calls?", [label || phone || ""])) + "<br><br>" + esc(__("They tap Allow in the chat, then you can call. WhatsApp allows one such request a day.")),
					() =>
						frappe
							.call({ method: "waba.api.calls.request_permission", args: { conversation }, freeze: true, freeze_message: __("Sending...") })
							.then(() => frappe.show_alert({ message: __("Request sent. Call again when the customer has allowed calls."), indicator: "green" }, 8))
				);
			}
			frappe.msgprint({ title: __("Call"), message: esc(info.reason || __("A call to this customer is not possible right now.")), indicator: "orange" });
		}

		// ------------------------------------------------------------ incoming: the ring box
		function closeRing(call) {
			const ring = rings[call];
			if (!ring) return;
			clearInterval(ring.timer);
			ring.$box.remove();
			delete rings[call];
			if (!ringing().length) stopAlerting();
		}

		function showRing(data) {
			if (rings[data.call]) return;
			ensureStyle();
			const total = Number(data.seconds || flags().ring_seconds || 30);
			const started = Date.now() - Math.max(0, Number(total) - Number(data.seconds_left == null ? total : data.seconds_left)) * 1000;
			const label = ringLabel(data);
			const record = data.party_doctype && data.party ? `<a href="${esc(frappe.utils.get_form_link(data.party_doctype, data.party))}" target="_blank">${esc(data.party)}</a>` : "";
			const $box = root
				.$(
					`<div class="waba-ringbox" role="alertdialog" aria-label="${esc(__("Incoming WhatsApp call"))}">
						<div class="wc-top"><span class="wc-dot"></span><div><div class="wc-who">${esc(label)}</div><div class="wc-sub">${esc(__("Incoming WhatsApp call"))}${record ? " · " + record : ""}${data.phone && label !== data.phone ? " · " + esc(data.phone) : ""}</div></div><span class="wc-time"></span></div>
						<div class="wc-actions"><button class="wc-accept">${esc(__("Accept"))}</button><button class="wc-decline">${esc(__("Decline"))}</button></div>
					</div>`
				)
				.appendTo(root.document.body);
			const ring = { $box, timer: null, data };
			ring.timer = setInterval(() => {
				const left = ringLeft(total, started, Date.now());
				$box.find(".wc-time").text(timerText(left));
				if (!left) closeRing(data.call);
			}, 500);
			rings[data.call] = ring;
			$box.find(".wc-accept").on("click", () => accept(data.call, data));
			$box.find(".wc-decline").on("click", () => decline(data.call));
			startAlerting();
			desktopNotice(label);
		}

		async function decline(call) {
			closeRing(call);
			frappe.call({ method: "waba.api.calls.decline", args: { call }, silent: true });
		}

		/** Take a ringing call: microphone (or silence), Meta's offer, our answer. The first person to accept gets it. */
		async function accept(call, data) {
			if (state.call || state.pc) return frappe.show_alert({ message: __("You are already in a call."), indicator: "orange" }, 5);
			Object.assign(state, { label: ringLabel(data), phone: data.phone || "", ended: false, since: null, direction: "Incoming" });
			const stream = await getAudio();
			if (!stream) return release();
			try {
				const r = await frappe.call({ method: "waba.api.calls.offer", args: { call }, freeze: true, freeze_message: __("Connecting...") });
				const offer = (r && r.message) || {};
				const pc = newPeer(stream);
				await pc.setRemoteDescription({ type: "offer", sdp: offer.sdp });
				await pc.setLocalDescription(await pc.createAnswer());
				const a = await frappe.call({ method: "waba.api.calls.answer", args: { call, sdp: pc.localDescription.sdp }, freeze: true, freeze_message: __("Connecting...") });
				const out = (a && a.message) || {};
				if (!out.ok) {
					release();
					closeRing(call);
					return frappe.show_alert({ message: out.reason || __("The call could not be taken."), indicator: "orange" }, 7);
				}
				state.call = call;
				closeRing(call);
				Object.keys(rings).forEach(closeRing);
				paint("Answered");
				beginTalking();
			} catch (e) {
				release();
				closeRing(call);
				frappe.show_alert({ message: (e && e.message) || __("The call could not be taken."), indicator: "red" }, 7);
			}
		}

		function openMissed(data) {
			if (data.conversation) {
				root.waba_open_conversation = data.conversation;
				frappe.set_route("waba-inbox");
			} else frappe.set_route("Form", "Waba Call", data.call);
		}

		function onEvent(data) {
			const action = routeEvent(data, { activeCall: state.call, ringing: ringing() });
			if (action === "ring") return showRing(data);
			if (action === "close-ring") return closeRing(data.call);
			if (action === "taken") {
				closeRing(data.call);
				return frappe.show_alert({ message: __("The call was taken by {0}.", [esc(data.taken_by || "")]), indicator: "blue" }, 6);
			}
			if (action === "missed") {
				closeRing(data.call);
				if (wantsSound()) ringOnce();
				return frappe.show_alert({ message: __("Missed WhatsApp call from {0}", [esc(ringLabel(data))]), indicator: "orange" }, 15, { [__("Open")]: () => openMissed(data) });
			}
			if (action === "active-answer") return takeAnswer().catch(() => {});
			if (action === "active-progress") {
				if (data.status === "Answered") beginTalking();
				if (isFinished(data.status)) return finish(data.status);
				paint(data.status || "Ringing");
			}
		}

		frappe.realtime.on("waba_call", onEvent);
		// a page opened while a call is ringing still shows the ring box
		if (flags().enabled && flags().take) {
			frappe.call({ method: "waba.api.calls.my_calls", silent: true }).then((r) => ((r && r.message) || []).forEach((c) => showRing({ ...c, kind: "ring", seconds: flags().ring_seconds, seconds_left: c.seconds_left })));
		}
		root.WabaPhone = { start: startCall, place, hangUp, accept, decline };
	}

	return { start, timerText, statusText, isFinished, micProblem, listenOnlyAllowed, offerOptions, supported, ringLabel, ringLeft, routeEvent, STUN };
});
