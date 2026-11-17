"""Run without a site:  python -m unittest waba.tests.test_bot_graph_js

The builder's graph helpers (public/js/waba_bot_graph.js) run in Node: adding, joining, removing and tidying blocks, the
3-button / 10-row limits, undo, and that the graph the builder makes is the one the server's rules accept."""

import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(__file__)
NODE = shutil.which("node")
FILE = os.path.abspath(os.path.join(HERE, "..", "public", "js", "waba_bot_graph.js"))


def run(script):
	prelude = f"const G = require({json.dumps(FILE)});\n"
	return json.loads(subprocess.check_output([NODE, "-e", prelude + script], text=True))


@unittest.skipUnless(NODE, "node is not installed")
class TestGraph(unittest.TestCase):
	def test_a_new_bot_has_only_the_trigger(self):
		g = run("console.log(JSON.stringify(G.start()))")
		self.assertEqual([n["type"] for n in g["nodes"]], ["trigger"])
		self.assertEqual(g["edges"], [])

	def test_only_one_trigger(self):
		out = run("const g = G.start(); const second = G.addNode(g, 'trigger', {x:0,y:0}); console.log(JSON.stringify({second, n: g.nodes.length}))")
		self.assertEqual(out, {"second": None, "n": 1})

	def test_ids_are_unique_and_never_reused_by_a_line(self):
		out = run(
			"""const g = G.start();
			const a = G.addNode(g, 'message', {x:1,y:1}), b = G.addNode(g, 'message', {x:1,y:1});
			const e = G.connect(g, 'trigger_1', 'out', a.id);
			console.log(JSON.stringify({a: a.id, b: b.id, e: e.id}))"""
		)
		self.assertEqual(out["a"], "message_1")
		self.assertEqual(out["b"], "message_2")
		self.assertEqual(out["e"], "line_1")

	def test_an_output_has_one_line_and_a_new_one_replaces_it(self):
		out = run(
			"""const g = G.start();
			const a = G.addNode(g, 'message', {}), b = G.addNode(g, 'message', {});
			G.connect(g, 'trigger_1', 'out', a.id); G.connect(g, 'trigger_1', 'out', b.id);
			console.log(JSON.stringify(g.edges.map(e => e.target)))"""
		)
		self.assertEqual(out, ["message_2"])

	def test_cannot_join_into_the_trigger_to_itself_or_from_an_ending_block(self):
		out = run(
			"""const g = G.start();
			const a = G.addNode(g, 'message', {}), end = G.addNode(g, 'end', {});
			console.log(JSON.stringify([G.connect(g, a.id, 'out', 'trigger_1'), G.connect(g, a.id, 'out', a.id), G.connect(g, end.id, 'out', a.id), G.connect(g, a.id, 'nope', end.id)]))"""
		)
		self.assertEqual(out, [None, None, None, None])

	def test_removing_a_block_removes_its_lines_but_never_the_trigger(self):
		out = run(
			"""const g = G.start();
			const a = G.addNode(g, 'message', {}), b = G.addNode(g, 'message', {});
			G.connect(g, 'trigger_1', 'out', a.id); G.connect(g, a.id, 'out', b.id);
			const removed = G.removeNode(g, a.id), trig = G.removeNode(g, 'trigger_1');
			console.log(JSON.stringify({removed, trig, nodes: g.nodes.map(n => n.id), edges: g.edges.length}))"""
		)
		self.assertEqual(out, {"removed": True, "trig": False, "nodes": ["trigger_1", "message_2"], "edges": 0})

	def test_buttons_stop_at_three_and_list_rows_at_ten(self):
		out = run(
			"""const g = G.start();
			const b = G.addNode(g, 'buttons', {}), l = G.addNode(g, 'list', {});
			const added = []; for (let i = 0; i < 4; i++) added.push(!!G.addOption(g, b.id));
			const rows = []; for (let i = 0; i < 12; i++) rows.push(!!G.addOption(g, l.id));
			console.log(JSON.stringify({added, buttons: b.data.buttons.length, rows: l.data.rows.length}))"""
		)
		self.assertEqual(out["buttons"], 3)
		self.assertEqual(out["added"], [True, False, False, False])  # the starter block already has two
		self.assertEqual(out["rows"], 10)

	def test_option_ids_stay_put_when_a_title_changes_and_removal_drops_the_line(self):
		out = run(
			"""const g = G.start();
			const b = G.addNode(g, 'buttons', {}), m = G.addNode(g, 'message', {});
			G.connect(g, b.id, 'b2', m.id);
			b.data.buttons[1].title = 'Renamed';
			const handle = G.handlesOf(b).map(h => h.id + ':' + h.label);
			const removed = G.removeOption(g, b.id, 'b2');
			console.log(JSON.stringify({handle, removed, edges: g.edges.length, left: b.data.buttons.length, again: G.removeOption(g, b.id, 'b1')}))"""
		)
		self.assertEqual(out["handle"], ["b1:Option 1", "b2:Renamed"])
		self.assertEqual((out["removed"], out["edges"], out["left"]), (True, 0, 1))
		self.assertFalse(out["again"])  # a choice block keeps at least one choice

	def test_a_new_option_id_never_clashes_after_a_removal(self):
		out = run(
			"""const g = G.start();
			const b = G.addNode(g, 'buttons', {});
			G.removeOption(g, b.id, 'b1');            // leaves b2
			const o = G.addOption(g, b.id);            // must not reuse b2
			console.log(JSON.stringify(b.data.buttons.map(x => x.id)))"""
		)
		self.assertEqual(len(set(out)), len(out))

	def test_the_output_points(self):
		out = run(
			"""const g = G.start();
			const kinds = ['message','buttons','list','condition','end','handover','assign_team','ask','note'];
			const o = {}; kinds.forEach(k => { o[k] = G.handlesOf(G.addNode(g, k, {})).map(h => h.id) });
			console.log(JSON.stringify(o))"""
		)
		self.assertEqual(out["message"], ["out"])
		self.assertEqual(out["condition"], ["yes", "no"])
		self.assertEqual(out["buttons"], ["b1", "b2"])
		self.assertEqual(out["end"] + out["handover"] + out["assign_team"], [])
		self.assertEqual(out["ask"], ["out"])

	def test_answer_names_are_unique_and_offered_as_values(self):
		out = run(
			"""const g = G.start();
			const a = G.addNode(g, 'ask', {}), b = G.addNode(g, 'ask', {});
			console.log(JSON.stringify({a: a.data.var, b: b.data.var, vars: G.variables(g)}))"""
		)
		self.assertEqual((out["a"], out["b"]), ("answer1", "answer2"))
		self.assertEqual(out["vars"], ["customer_name", "customer_phone", "number_name", "answer1", "answer2"])

	def test_duplicate_copies_the_data_without_lines_and_not_the_trigger(self):
		out = run(
			"""const g = G.start();
			const m = G.addNode(g, 'message', {x:10,y:10}); m.data.text = 'Hi';
			G.connect(g, 'trigger_1', 'out', m.id);
			const c = G.duplicate(g, m.id); c.data.text = 'changed';
			console.log(JSON.stringify({copy: c.id, orig: m.data.text, edges: g.edges.length, trig: G.duplicate(g, 'trigger_1'), pos: c.position}))"""
		)
		self.assertEqual(out["orig"], "Hi")
		self.assertEqual(out["edges"], 1)
		self.assertIsNone(out["trig"])
		self.assertEqual(out["pos"], {"x": 50, "y": 50})

	def test_tidy_puts_blocks_in_columns_by_distance_from_the_trigger(self):
		out = run(
			"""const g = G.start();
			const a = G.addNode(g, 'message', {}), b = G.addNode(g, 'buttons', {}), x = G.addNode(g, 'end', {}), y = G.addNode(g, 'end', {}), lost = G.addNode(g, 'note', {});
			G.connect(g, 'trigger_1', 'out', a.id); G.connect(g, a.id, 'out', b.id); G.connect(g, b.id, 'b1', x.id); G.connect(g, b.id, 'b2', y.id);
			G.tidy(g);
			const p = (n) => [n.position.x, n.position.y];
			console.log(JSON.stringify({t: p(g.nodes[0]), a: p(a), b: p(b), x: p(x), y: p(y), lost: p(lost)}))"""
		)
		self.assertEqual(out["t"][0], 40)
		self.assertEqual(out["a"][0], 340)
		self.assertEqual(out["b"][0], 640)
		self.assertEqual(out["x"][0], out["y"][0])
		self.assertNotEqual(out["x"][1], out["y"][1])
		self.assertGreater(out["lost"][0], out["x"][0])  # nothing leads to it: a last column

	def test_undo_restores_the_earlier_graph_and_is_capped(self):
		out = run(
			"""const g = G.start(), h = new G.History(3);
			for (let i = 0; i < 5; i++) { h.push(g); G.addNode(g, 'message', {}); }
			const back = h.undo();
			console.log(JSON.stringify({can: h.canUndo, nodes: back.nodes.length, stack: h.stack.length}))"""
		)
		self.assertEqual(out["nodes"], 5)  # the latest snapshot: the graph before the last change
		self.assertEqual(out["stack"], 2)

	def test_parse_rejects_nonsense_and_keeps_good_graphs(self):
		out = run("console.log(JSON.stringify([G.parse('not json'), G.parse('{}'), G.parse(''), G.parse('{\"nodes\":[]}')]))")
		self.assertEqual(out, [None, None, None, {"nodes": [], "edges": []}])


@unittest.skipUnless(NODE, "node is not installed")
class TestTheGraphTheBuilderMakesIsAcceptedByTheServerRules(unittest.TestCase):
	def test_a_bot_built_from_the_palette_defaults_validates_once_filled_in(self):
		from waba.rules import bot

		graph = run(
			"""const g = G.start();
			g.nodes[0].data.mode = 'new_conversation';
			const m = G.addNode(g, 'message', {x:300,y:100});
			const b = G.addNode(g, 'buttons', {x:600,y:100});
			const t = G.addNode(g, 'handover', {x:900,y:60});
			const e = G.addNode(g, 'end', {x:900,y:200});
			G.connect(g, 'trigger_1', 'out', m.id); G.connect(g, m.id, 'out', b.id);
			G.connect(g, b.id, 'b1', t.id); G.connect(g, b.id, 'b2', e.id);
			console.log(JSON.stringify(g))"""
		)
		self.assertEqual(bot.validate_graph(graph), [])

	def test_the_unfinished_defaults_are_reported_as_problems_not_accepted(self):
		from waba.rules import bot

		graph = run("const g = G.start(); g.nodes[0].data.mode = ''; const a = G.addNode(g, 'ask', {}); G.addNode(g, 'assign_team', {}); G.connect(g, 'trigger_1', 'out', a.id); console.log(JSON.stringify(g))")
		texts = " | ".join(bot.validate_graph(graph))
		self.assertIn("Choose what starts the bot", texts)
		self.assertIn("Choose the team", texts)

	def test_problems_name_their_block(self):
		from waba.rules import bot

		graph = run("const g = G.start(); G.addNode(g, 'assign_team', {}); console.log(JSON.stringify(g))")
		found = bot.problems_for(graph)
		self.assertTrue(any(p["node"] == "assign_team_1" for p in found))
		self.assertEqual([p["text"] for p in found], bot.validate_graph(graph))


@unittest.skipUnless(NODE, "node is not installed")
class TestPreviewBlockHelpers(unittest.TestCase):
	def test_new_blocks_have_the_right_output_points(self):
		out = run(
			"""const g = G.start();
			const o = {};
			['link_button','send_file','status_lookup'].forEach(k => { o[k] = G.handlesOf(G.addNode(g, k, {})).map(h => h.id + ':' + h.label) });
			console.log(JSON.stringify(o))"""
		)
		self.assertEqual(out["link_button"], ["out:"])
		self.assertEqual(out["send_file"], ["out:Sent", "none:Nothing to send"])
		self.assertEqual(out["status_lookup"], ["found:Found", "none:Not found"])

	def test_a_timeout_adds_a_no_answer_point_and_clearing_it_drops_its_line(self):
		out = run(
			"""const g = G.start();
			const b = G.addNode(g, 'buttons', {}), a = G.addNode(g, 'ask', {}), m = G.addNode(g, 'message', {});
			const before = [G.handlesOf(b).length, G.handlesOf(a).length];
			G.setTimeout(g, b.id, 30); G.setTimeout(g, a.id, 15);
			G.connect(g, b.id, 'timeout', m.id);
			const withTimeout = [G.handlesOf(b).map(h => h.id), G.handlesOf(a).map(h => h.id + ':' + h.label), G.timeoutOf(b)];
			G.setTimeout(g, b.id, 0);
			console.log(JSON.stringify({before, withTimeout, after: G.handlesOf(b).map(h => h.id), edges: g.edges.length, data: b.data.timeout_minutes === undefined}))"""
		)
		self.assertEqual(out["before"], [2, 1])
		self.assertEqual(out["withTimeout"][0], ["b1", "b2", "timeout"])
		self.assertEqual(out["withTimeout"][1], ["out:Answered", "timeout:No answer"])
		self.assertEqual(out["withTimeout"][2], 30)
		self.assertEqual(out["after"], ["b1", "b2"])
		self.assertEqual((out["edges"], out["data"]), (0, True))

	def test_the_time_is_capped_and_only_waiting_blocks_take_one(self):
		out = run(
			"""const g = G.start();
			const b = G.addNode(g, 'buttons', {}), m = G.addNode(g, 'message', {});
			G.setTimeout(g, b.id, 99999);
			console.log(JSON.stringify({capped: b.data.timeout_minutes, message: G.setTimeout(g, m.id, 5), msgTimeout: G.timeoutOf(m)}))"""
		)
		self.assertEqual(out, {"capped": 720, "message": False, "msgTimeout": 0})

	def test_document_values_are_offered_only_with_a_status_block(self):
		out = run(
			"""const g = G.start();
			const without = G.variables(g).length;
			G.addNode(g, 'status_lookup', {});
			console.log(JSON.stringify({without, withDocs: G.variables(g).filter(v => v.startsWith('doc_'))}))"""
		)
		self.assertEqual(out["without"], 3)
		self.assertEqual(out["withDocs"], ["doc_name", "doc_status", "doc_date", "doc_total", "doc_outstanding", "doc_due_date"])

	def test_the_gated_list_matches_the_server(self):
		from waba.rules import bot

		out = run("console.log(JSON.stringify(G.GATED))")
		self.assertEqual(set(out), set(bot.GATED_TYPES))

	def test_what_the_builder_makes_with_defaults_filled_in_passes_the_server_rules(self):
		from waba.rules import bot

		graph = run(
			"""const g = G.start();
			const l = G.addNode(g, 'link_button', {}); l.data.url = 'https://www.example.com';
			const f = G.addNode(g, 'send_file', {}); f.data.shared_file = 'Price list';
			const s = G.addNode(g, 'status_lookup', {});
			const b = G.addNode(g, 'buttons', {}); G.setTimeout(g, b.id, 20);
			const e = G.addNode(g, 'end', {}), h = G.addNode(g, 'handover', {});
			G.connect(g, 'trigger_1', 'out', l.id); G.connect(g, l.id, 'out', f.id);
			G.connect(g, f.id, 'out', s.id); G.connect(g, f.id, 'none', s.id);
			G.connect(g, s.id, 'found', b.id); G.connect(g, s.id, 'none', e.id);
			G.connect(g, b.id, 'b1', e.id); G.connect(g, b.id, 'b2', h.id); G.connect(g, b.id, 'timeout', h.id);
			console.log(JSON.stringify(g))"""
		)
		self.assertEqual(bot.validate_graph(graph, extras=True), [])
		self.assertTrue(bot.validate_graph(graph, extras=False))


if __name__ == "__main__":
	unittest.main()


@unittest.skipUnless(NODE, "node is not installed")
class TestAssignAgent(unittest.TestCase):
	def test_changing_the_team_clears_the_agent(self):
		out = run("const g = G.start(); const a = G.addNode(g, 'assign_team', {}); G.setTeam(g, a.id, 'Sales'); a.data.agent = 'x@y.com'; G.setTeam(g, a.id, 'Sales'); const same = a.data.agent; G.setTeam(g, a.id, 'Accounts'); console.log(JSON.stringify({d: G.addNode(G.empty(), 'assign_team', {}).data, same, now: a.data}))")
		self.assertEqual(out["d"]["agent"], "")
		self.assertEqual(out["same"], "x@y.com")
		self.assertEqual((out["now"]["team"], out["now"]["agent"]), ("Accounts", ""))


@unittest.skipUnless(NODE, "node is not installed")
class TestSeveralStartsInTheBuilder(unittest.TestCase):
	def test_an_older_trigger_is_converted_and_its_line_follows(self):
		out = run("const g = G.start(); g.nodes[0].data = {mode:'keyword', keywords:'hi', match:'exact'}; const m = G.addNode(g,'message',{}); G.connect(g,'trigger_1','out',m.id); const changed = G.normalizeTrigger(g); console.log(JSON.stringify({changed, again: G.normalizeTrigger(g), data: g.nodes[0].data, edge: g.edges[0]}))")
		self.assertTrue(out["changed"])
		self.assertFalse(out["again"])
		self.assertEqual(out["data"]["starts"][0]["keywords"], "hi")
		self.assertEqual(out["edge"]["sourceHandle"], "s1")

	def test_starts_add_remove_and_each_has_its_own_dot(self):
		out = run("const g = G.start(); const a = G.addNode(g,'message',{}); const b = G.addNode(g,'message',{}); G.addStart(g); G.connect(g,'trigger_1','s1',a.id); G.connect(g,'trigger_1','s2',b.id); const dots = G.handlesOf(g.nodes[0]).map(h => h.id); G.setStart(g,'s2','keywords','price, rate'); const label = G.handlesOf(g.nodes[0])[1].label; const removed = G.removeStart(g,'s2'); const last = G.removeStart(g,'s1'); console.log(JSON.stringify({dots, label, removed, last, edges: g.edges.map(e => e.sourceHandle)}))")
		self.assertEqual(out["dots"], ["s1", "s2"])
		self.assertEqual(out["label"], "price, rate")
		self.assertTrue(out["removed"])
		self.assertFalse(out["last"])  # the last start stays
		self.assertEqual(out["edges"], ["s1"])  # only the removed start's line went

	def test_the_limit_is_ten(self):
		out = run("const g = G.start(); let n = 0; while (G.addStart(g)) n++; console.log(JSON.stringify({n, total: g.nodes[0].data.starts.length}))")
		self.assertEqual(out["total"], 10)

	def test_what_the_builder_makes_passes_the_server_rules(self):
		from waba.rules import bot

		graph = run("const g = G.start(); const a = G.addNode(g,'message',{}); const b = G.addNode(g,'end',{}); G.addStart(g); G.setStart(g,'s1','mode','new_conversation'); G.setStart(g,'s2','keywords','price'); G.connect(g,'trigger_1','s1',a.id); G.connect(g,'trigger_1','s2',a.id); G.connect(g,a.id,'out',b.id); console.log(JSON.stringify(g))")
		self.assertEqual(bot.validate_graph(graph), [])

