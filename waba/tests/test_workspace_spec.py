"""Run without a site:  python -m unittest waba.tests.test_workspace_spec

The workspace is built from plain data. Check that it only points at doctypes the app ships, that its body is
valid and that every shortcut and card it names exists as a row, so migrate on a site cannot fail on it."""

import json
import os
import unittest

from waba.constants import ROLE_ADMIN, ROLE_AGENT, ROLE_SUPERVISOR
from waba.setup import install
from waba.setup import workspace_spec as spec

DOCTYPE_DIR = os.path.join(os.path.dirname(__file__), "..", "waba", "doctype")
SHIPPED = {d.replace("_", " ").title() for d in os.listdir(DOCTYPE_DIR) if d.startswith("waba_")}


class TestWorkspaceSpec(unittest.TestCase):
	def test_every_target_is_a_shipped_doctype(self):
		targets = {d for _t, rows in spec.SECTIONS for d, _l, _x in rows} | {d for d, _l in spec.SHORTCUTS}
		self.assertFalse(targets - SHIPPED, targets - SHIPPED)

	def test_content_is_a_list_of_blocks_with_unique_ids(self):
		blocks = json.loads(spec.content())
		self.assertIsInstance(blocks, list)
		ids = [b["id"] for b in blocks]
		self.assertEqual(len(ids), len(set(ids)))

	def test_content_names_only_existing_rows(self):
		blocks = json.loads(spec.content())
		labels = {r["label"] for r in spec.shortcut_rows()}
		cards = {r["label"] for r in spec.link_rows() if r["type"] == "Card Break"}
		for b in blocks:
			if b["type"] == "shortcut":
				self.assertIn(b["data"]["shortcut_name"], labels)
			if b["type"] == "card":
				self.assertIn(b["data"]["card_name"], cards)

	def test_labels_are_unique_per_kind(self):
		for rows in (spec.shortcut_rows(), [r for r in spec.link_rows() if r["type"] == "Card Break"]):
			labels = [r["label"] for r in rows]
			self.assertEqual(len(labels), len(set(labels)))

	def test_roles_created_and_viewable(self):
		self.assertEqual(set(install.ROLES), {ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_AGENT})
		self.assertTrue(set(install.ROLES) <= set(spec.VIEWER_ROLES))

	def test_module_matches_modules_txt(self):
		path = os.path.join(os.path.dirname(__file__), "..", "modules.txt")
		with open(path) as f:
			self.assertIn(spec.MODULE, f.read().split())


if __name__ == "__main__":
	unittest.main()


class TestMerge(unittest.TestCase):
	def test_a_complete_workspace_is_left_alone(self):
		rows = spec.link_rows()
		self.assertEqual(spec.merge_links(rows, rows), rows)

	def test_a_missing_card_is_added_at_the_end_and_nothing_existing_moves(self):
		rows = spec.link_rows()
		old = rows[: rows.index(next(r for r in rows if r.get("label") == "Activity"))]
		merged = spec.merge_links(old, rows)
		self.assertEqual(merged[: len(old)], old)
		self.assertEqual(merged, rows)

	def test_a_missing_link_goes_under_its_own_card(self):
		rows = spec.link_rows()
		without = [r for r in rows if r.get("label") != "Numbers"]
		merged = spec.merge_links(without, rows)
		labels = [r["label"] for r in merged]
		self.assertEqual(labels, [r["label"] for r in rows])

	def test_site_changes_to_existing_rows_survive(self):
		rows = spec.link_rows()
		edited = [dict(r, description="mine") if r.get("label") == "Portfolios" else r for r in rows]
		merged = spec.merge_links(edited, rows)
		self.assertEqual(next(r for r in merged if r.get("label") == "Portfolios")["description"], "mine")

	def test_missing_blocks_only_for_named_things_that_exist(self):
		body = json.dumps([b for b in json.loads(spec.content()) if b["data"].get("shortcut_name") != "Webhook Events"])
		labels = {r["label"] for r in spec.shortcut_rows()}
		cards = {r["label"] for r in spec.link_rows() if r["type"] == "Card Break"}
		added = spec.missing_blocks(body, labels, cards)
		self.assertEqual([b["data"].get("shortcut_name") for b in added], ["Webhook Events"])
		self.assertEqual(spec.missing_blocks(spec.content(), labels, cards), [])
		self.assertEqual(spec.missing_blocks(body, set(), set()), [])


class TestSidebar(unittest.TestCase):
	"""The sidebar is what people click every day; its file is shipped, so check it offline."""

	PATH = os.path.join(os.path.dirname(__file__), "..", "waba", "sidebar", "waba", "waba.json")

	def load(self):
		with open(self.PATH, encoding="utf-8") as f:
			return json.load(f)

	def test_shape(self):
		d = self.load()
		self.assertEqual((d["doctype"], d["name"], d["title"], d["module"], d["standard"]), ("Sidebar", "Waba", "Waba", "Waba", 1))

	def test_links_point_at_shipped_doctypes_or_the_workspace(self):
		for item in self.load()["items"]:
			if item["type"] != "Link":
				continue
			if item["link_type"] == "Workspace":
				self.assertEqual(item["link_to"], spec.WORKSPACE)
			else:
				self.assertIn(item["link_to"], SHIPPED, item["label"])

	def test_triage_filter_is_valid_json_and_names_a_real_field(self):
		triage = next(i for i in self.load()["items"] if i["label"] == "Triage")
		filters = json.loads(triage["filters"])
		self.assertEqual(filters, [["Waba Conversation", "match_state", "=", "Triage"]])

	def test_labels_are_unique_and_every_workspace_doctype_is_reachable(self):
		items = [i for i in self.load()["items"] if i["type"] == "Link"]
		labels = [i["label"] for i in items]
		self.assertEqual(len(labels), len(set(labels)))
		reachable = {i["link_to"] for i in items}
		self.assertTrue({d for _t, rows in spec.SECTIONS for d, _l, _x in rows} <= reachable)
