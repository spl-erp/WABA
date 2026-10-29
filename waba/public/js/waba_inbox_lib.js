/* Helpers for the WhatsApp inbox page: inline icons and small pure functions.
 *
 * Loaded by the page (waba/page/waba_inbox/waba_inbox.js) and also by Node for the offline tests, so it touches no
 * Frappe or DOM global. Everything that goes into HTML is escaped here first. */
(function (root, factory) {
	const lib = factory();
	if (typeof module !== "undefined" && module.exports) module.exports = lib;
	else root.WabaLib = lib;
})(typeof self !== "undefined" ? self : this, function () {
	// ------------------------------------------------------------------ icons (stroke icons, 24x24, drawn inline)
	const STROKE = {
		phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
		search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
		refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
		paperclip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
		smile: '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
		send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
		link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
		external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
		more: '<circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>',
		chevron: '<path d="m6 9 6 6 6-6"/>',
		check: '<path d="M20 6 9 17l-5-5"/>',
		checks: '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/>',
		warning: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
		arrowdown: '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
		arrowup: '<path d="m18 15-6-6-6 6"/>',
		bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
		back: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
		x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
		copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
		clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
		info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
	};

	function icon(name, size, cls) {
		const body = STROKE[name];
		if (!body) return "";
		const s = size || 18;
		return `<svg class="waba-i ${cls || ""}" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
	}

	/** The product mark: a green speech bubble with a phone handset (WhatsApp-inspired, not the trademark logo). */
	function brandMark(size) {
		const s = size || 36;
		return `<svg class="waba-i waba-brand" width="${s}" height="${s}" viewBox="0 0 32 32" aria-hidden="true"><path d="M16 2.5a13.5 13.5 0 0 0-11.6 20.4L2.5 29.5l6.8-1.8A13.5 13.5 0 1 0 16 2.5z" fill="#25d366"/><g transform="translate(8.2 8.2) scale(0.64)" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${STROKE.phone}</g></svg>`;
	}

	/** A small solid green check badge: this sender is matched to a record in the ERP. */
	function verifiedBadge(size) {
		const s = size || 15;
		return `<svg class="waba-i waba-verified" width="${s}" height="${s}" viewBox="0 0 24 24" aria-label="Matched to an ERP record" role="img"><circle cx="12" cy="12" r="10.5" fill="#25d366"/><path d="m7.6 12.6 3 3 5.8-6.2" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
	}

	// ------------------------------------------------------------------ text
	function escapeHtml(value) {
		return String(value === null || value === undefined ? "" : value)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#39;");
	}

	/** One or two capital letters for an avatar; "?" when the name has no letters (a bare phone number). */
	function initials(name) {
		const words = String(name || "")
			.replace(/[^\p{L} ]/gu, " ")
			.trim()
			.split(/\s+/)
			.filter(Boolean);
		if (!words.length) return "?";
		const letters = (words[0][0] + (words.length > 1 ? words[1][0] : "")).toUpperCase();
		return letters;
	}

	const AVATAR_COLORS = ["#19a974", "#5b6fd6", "#d6559b", "#3b82f6", "#8b5cf6", "#0d9488", "#e08a00", "#e0604f"];

	/** The same customer always gets the same colour. */
	function avatarColor(seed) {
		const text = String(seed || "");
		let hash = 0;
		for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
		return AVATAR_COLORS[hash % AVATAR_COLORS.length];
	}

	/** {name, sub}: the first line and the second line of a customer in a list or header. */
	function customerLines(row) {
		const phone = row.customer_phone || "";
		const bsuid = row.customer_bsuid || "";
		const name = (row.profile_name || "").trim() || phone || bsuid || row.name || "";
		const sub = phone || bsuid;
		return { name, sub: sub && sub !== name ? sub : "" };
	}

	// ------------------------------------------------------------------ the 24-hour window
	/** "23 h 53 m" until `expires` (a Date), or null when it is over. */
	function timeLeft(expires, now) {
		const ms = expires - (now || new Date());
		if (!(ms > 0)) return null;
		const minutes = Math.floor(ms / 60000);
		return `${Math.floor(minutes / 60)} h ${minutes % 60} m`;
	}

	// ------------------------------------------------------------------ message status
	/** How a message's delivery state is drawn: which icon, which colour. */
	function tickFor(status) {
		switch (status) {
			case "Queued":
				return { icon: "clock", tone: "grey", label: "Sending" };
			case "Sent":
				return { icon: "check", tone: "grey", label: "Sent" };
			case "Delivered":
				return { icon: "checks", tone: "grey", label: "Delivered" };
			case "Read":
				return { icon: "checks", tone: "blue", label: "Read" };
			case "Failed":
				return { icon: "warning", tone: "red", label: "Not delivered" };
			default:
				return null;
		}
	}

	const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

	/** "28 Oct 2026" from "2026-10-28 14:39:21" (the server's datetime text). */
	function dayLabel(text) {
		const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(text || ""));
		return m ? `${parseInt(m[3], 10)} ${MONTHS[parseInt(m[2], 10) - 1]} ${m[1]}` : "";
	}

	/** "14:39" from "2026-10-28 14:39:21". */
	function clockLabel(text) {
		const m = /\s(\d{2}:\d{2})/.exec(String(text || ""));
		return m ? m[1] : "";
	}

	// ------------------------------------------------------------------ links, search highlight
	/** Escape the text, then turn http(s) web addresses into links. Nothing else is ever linked (no javascript:). */
	function linkify(text) {
		return escapeHtml(text).replace(/\bhttps?:\/\/[^\s<]+/gi, (match) => {
			let url = match;
			let trail = "";
			for (;;) {
				const entity = /(&quot;|&#39;|&gt;|&lt;)$/.exec(url);
				if (entity) {
					trail = entity[1] + trail;
					url = url.slice(0, -entity[1].length);
					continue;
				}
				if (/[.,;:!?)\]}]$/.test(url)) {
					trail = url.slice(-1) + trail;
					url = url.slice(0, -1);
					continue;
				}
				break;
			}
			if (!/^https?:\/\/[^\s/?#]+/i.test(url)) return match;
			return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${trail}`;
		});
	}

	function escapeRegex(text) {
		return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	}

	/** Wrap every match of `query` in <mark>, in the TEXT of already-escaped html only (never inside a tag or an entity). */
	function highlight(html, query) {
		const q = String(query || "").trim();
		if (!q) return html;
		const pattern = new RegExp(escapeRegex(escapeHtml(q)), "gi");
		return String(html)
			.split(/(<[^>]*>|&[#a-z0-9]+;)/gi)
			.map((part, i) => (i % 2 === 1 ? part : part.replace(pattern, (m) => `<mark>${m}</mark>`)))
			.join("");
	}

	/** How many times `query` occurs in plain `text` (case-insensitive). */
	function countMatches(text, query) {
		const q = String(query || "").trim();
		if (!q) return 0;
		return (String(text || "").match(new RegExp(escapeRegex(q), "gi")) || []).length;
	}

	// ------------------------------------------------------------------ emoji (a compact set for business chat)
	const EMOJI_GROUPS = [
		{ name: "Smileys", icon: "😀", items: [["😀", "grin smile happy"], ["😃", "smile happy"], ["😄", "smile laugh"], ["😁", "grin"], ["😆", "laugh"], ["😅", "sweat relief"], ["😂", "joy laugh tears"], ["🤣", "rofl laugh"], ["🙂", "slight smile"], ["😉", "wink"], ["😊", "blush smile"], ["😍", "love heart eyes"], ["😘", "kiss"], ["😎", "cool sunglasses"], ["🤔", "thinking"], ["😐", "neutral"], ["😮", "surprised wow"], ["😢", "sad cry"], ["😭", "cry sob"], ["😡", "angry"], ["😴", "sleep"], ["🤗", "hug"], ["🙄", "eye roll"], ["😬", "grimace"]] },
		{ name: "Gestures", icon: "👍", items: [["👍", "thumbs up ok yes like good"], ["👎", "thumbs down no bad"], ["👌", "ok perfect"], ["🙏", "thanks please namaste pray"], ["👏", "clap well done"], ["🙌", "praise celebrate"], ["💪", "strong muscle"], ["🤝", "deal handshake agreement"], ["✌️", "peace victory"], ["🤞", "fingers crossed luck"], ["👋", "hello hi wave bye"], ["☝️", "point up one"], ["👉", "point right"], ["👀", "eyes look"]] },
		{ name: "Symbols", icon: "❤️", items: [["❤️", "heart love red"], ["💚", "green heart"], ["💙", "blue heart"], ["✅", "check done yes"], ["❌", "cross no wrong"], ["⚠️", "warning caution"], ["⭐", "star"], ["🔥", "fire hot"], ["✨", "sparkles new"], ["💯", "hundred perfect"], ["❗", "important exclamation"], ["❓", "question"], ["🎉", "party celebrate congratulations"], ["🎁", "gift offer"]] },
		{ name: "Business", icon: "📦", items: [["📦", "package parcel order box"], ["🚚", "truck delivery dispatch transport"], ["📄", "document page"], ["📎", "attachment clip"], ["💰", "money payment cash"], ["💳", "card payment"], ["📞", "phone call"], ["📱", "mobile phone"], ["📧", "email mail"], ["🕒", "clock time"], ["📅", "calendar date"], ["🏭", "factory plant"], ["🖨️", "printer print ink"], ["🧾", "receipt invoice bill"], ["📝", "note memo write"], ["🔔", "bell reminder"], ["📍", "location pin address"], ["🏷️", "price tag label"]] },
	];

	function emojiSearch(query) {
		const q = String(query || "").trim().toLowerCase();
		if (!q) return [];
		const out = [];
		EMOJI_GROUPS.forEach((g) => g.items.forEach(([e, kw]) => { if (kw.includes(q)) out.push([e, kw]); }));
		return out;
	}

	return { linkify, highlight, countMatches, emojiSearch, EMOJI_GROUPS, icon, brandMark, verifiedBadge, escapeHtml, initials, avatarColor, customerLines, timeLeft, tickFor, dayLabel, clockLabel, AVATAR_COLORS };
});
