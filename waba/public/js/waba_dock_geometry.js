/* Where the floating chat window sits and how big it is: pure functions (no DOM), tested offline in Node.
 *
 * A geometry is {x, y, w, h} in CSS pixels of the viewport (x, y = top-left corner). The window may be dragged anywhere, but its
 * header always stays reachable: at least KEEP px of it remain inside the viewport. Size is limited to MIN..(viewport - margins). */
(function (root, factory) {
	const g = factory();
	if (typeof module !== "undefined" && module.exports) module.exports = g;
	else root.WabaDockGeometry = g;
})(typeof self !== "undefined" ? self : this, function () {
	const MIN_W = 320;
	const MIN_H = 320;
	const MARGIN = 16; // never larger than the viewport minus this on each side
	const KEEP = 80; // how much of the header must stay on screen
	const HEADER = 50;
	const DEFAULT_W = 400;
	const DEFAULT_H = 660;
	const PHONE = 600; // at or below this viewport width the window is full screen and is not moved or resized

	const finite = (n) => typeof n === "number" && Number.isFinite(n);

	function isPhone(vw) {
		return vw <= PHONE;
	}

	/** The bottom-right corner, 20 px from the edges, as before. */
	function defaults(vw, vh) {
		const w = Math.max(Math.min(DEFAULT_W, vw - 2 * MARGIN), Math.min(MIN_W, vw - 2 * MARGIN));
		const h = Math.max(Math.min(DEFAULT_H, vh - 110), Math.min(MIN_H, vh - 2 * MARGIN));
		return { x: Math.round(vw - w - 20), y: Math.round(vh - h - 20), w: Math.round(w), h: Math.round(h) };
	}

	/** Keep a geometry inside what the screen allows. */
	function clamp(g, vw, vh) {
		const maxW = Math.max(vw - 2 * MARGIN, 1);
		const maxH = Math.max(vh - 2 * MARGIN, 1);
		const w = Math.min(Math.max(g.w, Math.min(MIN_W, maxW)), maxW);
		const h = Math.min(Math.max(g.h, Math.min(MIN_H, maxH)), maxH);
		const x = Math.min(Math.max(g.x, KEEP - w), vw - KEEP);
		const y = Math.min(Math.max(g.y, 0), vh - HEADER);
		return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
	}

	/** Move by (dx, dy). */
	function move(g, dx, dy, vw, vh) {
		return clamp({ ...g, x: g.x + dx, y: g.y + dy }, vw, vh);
	}

	/**
	 * Resize from a handle: "n", "s", "e", "w" or a corner such as "nw". Dragging the left or top edge moves the window as it grows,
	 * so the opposite edge stays where it was.
	 */
	function resize(g, handle, dx, dy, vw, vh) {
		const maxW = Math.max(vw - 2 * MARGIN, 1);
		const maxH = Math.max(vh - 2 * MARGIN, 1);
		const minW = Math.min(MIN_W, maxW);
		const minH = Math.min(MIN_H, maxH);
		let { x, y, w, h } = g;
		if (handle.includes("e")) w = Math.min(Math.max(g.w + dx, minW), maxW);
		if (handle.includes("w")) {
			w = Math.min(Math.max(g.w - dx, minW), maxW);
			x = g.x + g.w - w;
		}
		if (handle.includes("s")) h = Math.min(Math.max(g.h + dy, minH), maxH);
		if (handle.includes("n")) {
			h = Math.min(Math.max(g.h - dy, minH), maxH);
			y = g.y + g.h - h;
		}
		return clamp({ x, y, w, h }, vw, vh);
	}

	/** A saved geometry (from stored text) made to fit this screen; the default when it is missing or damaged. */
	function fit(saved, vw, vh) {
		if (!saved || !finite(saved.x) || !finite(saved.y) || !finite(saved.w) || !finite(saved.h)) return defaults(vw, vh);
		return clamp(saved, vw, vh);
	}

	function parse(text) {
		try {
			const value = JSON.parse(text || "null");
			return value && typeof value === "object" ? value : null;
		} catch (e) {
			return null;
		}
	}

	return { MIN_W, MIN_H, MARGIN, KEEP, HEADER, DEFAULT_W, DEFAULT_H, PHONE, isPhone, defaults, clamp, move, resize, fit, parse };
});
