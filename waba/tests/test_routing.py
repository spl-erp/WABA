"""Run without a site:  python -m unittest waba.tests.test_routing

The scenarios of the plan's section 12.6 that are decided by the routing rules.
"""

import datetime
import unittest

from waba.rules.routing import (
	LANGUAGE,
	LEAST_BUSY,
	NUMBER_OWNER,
	POOL,
	RECORD_OWNER,
	REP_TAG,
	STICKY,
	Agent,
	Context,
	Rule,
	choose_assignee,
)


def ctx(**kw):
	return Context(**kw)


def ag(user, **kw):
	return Agent(user=user, **kw)


class TestSharedNumber(unittest.TestCase):
	def test_least_busy_available_agent(self):
		c = ctx(agents=[ag("a", open_count=3), ag("b", open_count=1), ag("c", open_count=2)])
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), ("b", "least_busy"))

	def test_ties_break_by_never_assigned_then_oldest_then_name(self):
		old, new = datetime.datetime(2026, 10, 1), datetime.datetime(2026, 10, 2)
		c = ctx(agents=[ag("a", last_assigned_at=new), ag("b", last_assigned_at=old), ag("c")])
		self.assertEqual(choose_assignee(c).assignee, "c")  # never assigned goes first
		c = ctx(agents=[ag("a", last_assigned_at=new), ag("b", last_assigned_at=old)])
		self.assertEqual(choose_assignee(c).assignee, "b")  # then the one assigned longest ago
		c = ctx(agents=[ag("z"), ag("m")])
		self.assertEqual(choose_assignee(c).assignee, "m")  # then by name, so the result is deterministic

	def test_away_agents_are_skipped(self):
		c = ctx(agents=[ag("a", available=False), ag("b", open_count=9)])
		self.assertEqual(choose_assignee(c).assignee, "b")

	def test_agents_at_capacity_are_skipped(self):
		c = ctx(default_max_open=2, agents=[ag("a", open_count=2), ag("b", open_count=1)])
		self.assertEqual(choose_assignee(c).assignee, "b")
		c = ctx(default_max_open=2, agents=[ag("a", open_count=2), ag("b", open_count=5, max_open=6)])
		self.assertEqual(choose_assignee(c).assignee, "b")  # an agent's own limit overrides the default
		c = ctx(default_max_open=0, agents=[ag("a", open_count=500)])
		self.assertEqual(choose_assignee(c).assignee, "a")  # 0 means unlimited

	def test_supervisors_do_not_receive_automatic_assignments(self):
		c = ctx(agents=[ag("boss", role="Supervisor"), ag("a", open_count=5)])
		self.assertEqual(choose_assignee(c).assignee, "a")

	def test_nobody_usable_means_the_pool(self):
		for agents in ([], [ag("a", available=False)], [ag("boss", role="Supervisor")]):
			d = choose_assignee(ctx(agents=agents))
			self.assertEqual((d.assignee, d.reason), (None, POOL))
		d = choose_assignee(ctx(default_max_open=1, agents=[ag("a", open_count=1)]))
		self.assertEqual(d.reason, POOL)


class TestStickiness(unittest.TestCase):
	def test_open_conversation_stays_with_its_agent_even_when_busy(self):
		c = ctx(default_max_open=1, current_assignee="a", agents=[ag("a", open_count=9), ag("b")])
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), ("a", "sticky"))

	def test_unavailable_agent_loses_the_conversation(self):
		c = ctx(current_assignee="a", agents=[ag("a", available=False), ag("b")])
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), ("b", "least_busy"))
		self.assertEqual(d.trail, (STICKY, NUMBER_OWNER, REP_TAG, RECORD_OWNER, LANGUAGE))

	def test_an_agent_removed_from_the_number_loses_it(self):
		c = ctx(current_assignee="gone", agents=[ag("b")])
		self.assertEqual(choose_assignee(c).assignee, "b")


class TestRepTag(unittest.TestCase):
	def test_tag_picks_that_rep(self):
		c = ctx(tag="r12", agents=[ag("a", open_count=0), ag("b", rep_code="R12", open_count=7)])
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), ("b", "rep_tag"))  # case-insensitive, beats least busy

	def test_tagged_rep_away_falls_through(self):
		c = ctx(tag="R12", agents=[ag("a"), ag("b", rep_code="R12", available=False)])
		self.assertEqual(choose_assignee(c).assignee, "a")

	def test_tagged_rep_at_capacity_falls_through(self):
		c = ctx(tag="R12", default_max_open=1, agents=[ag("a"), ag("b", rep_code="R12", open_count=1)])
		self.assertEqual(choose_assignee(c).assignee, "a")

	def test_unknown_tag_falls_through(self):
		c = ctx(tag="zzz", agents=[ag("a")])
		self.assertEqual(choose_assignee(c).reason, "least_busy")


class TestRecordOwner(unittest.TestCase):
	def test_owner_who_works_the_number_gets_it(self):
		c = ctx(record_owner="b", agents=[ag("a"), ag("b", open_count=5)])
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), ("b", "record_owner"))

	def test_owner_not_on_the_number_is_ignored(self):
		c = ctx(record_owner="outsider", agents=[ag("a")])
		self.assertEqual(choose_assignee(c).reason, "least_busy")

	def test_owner_away_or_full_is_skipped(self):
		self.assertEqual(
			choose_assignee(ctx(record_owner="b", agents=[ag("a"), ag("b", available=False)])).assignee, "a"
		)
		self.assertEqual(
			choose_assignee(
				ctx(record_owner="b", default_max_open=1, agents=[ag("a"), ag("b", open_count=1)])
			).assignee,
			"a",
		)

	def test_tag_beats_record_owner_by_default(self):
		c = ctx(tag="R1", record_owner="b", agents=[ag("a", rep_code="R1"), ag("b")])
		self.assertEqual(choose_assignee(c).assignee, "a")


class TestLanguage(unittest.TestCase):
	def test_speaker_of_the_language_least_busy(self):
		c = ctx(
			language="hi",
			agents=[
				ag("a", open_count=0),
				ag("b", languages=frozenset({"Hi", "en"}), open_count=3),
				ag("c", languages=frozenset({"hi"}), open_count=1),
			],
		)
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), ("c", "language"))

	def test_no_speaker_falls_back_to_least_busy(self):
		c = ctx(language="ta", agents=[ag("a", languages=frozenset({"hi"}))])
		self.assertEqual(choose_assignee(c).reason, "least_busy")


class TestPersonalNumber(unittest.TestCase):
	def test_owner_gets_everything(self):
		c = ctx(number_type="Personal", owner_user="rahul", agents=[ag("rahul"), ag("other", open_count=0)])
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), ("rahul", "number_owner"))

	def test_other_rules_never_move_a_conversation_off_a_personal_number(self):
		c = ctx(
			number_type="Personal",
			owner_user="rahul",
			tag="R9",
			record_owner="other",
			agents=[ag("rahul", open_count=50), ag("other", rep_code="R9")],
		)
		self.assertEqual(choose_assignee(c).assignee, "rahul")

	def test_owner_away_goes_to_a_supervisor(self):
		c = ctx(
			number_type="Personal",
			owner_user="rahul",
			agents=[ag("rahul", available=False), ag("s1", role="Supervisor", open_count=2), ag("s2", role="Supervisor")],
		)
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), ("s2", "owner_away_supervisor"))

	def test_owner_away_and_no_supervisor_means_the_pool(self):
		c = ctx(number_type="Personal", owner_user="rahul", agents=[ag("rahul", available=False), ag("x")])
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), (None, POOL))

	def test_sticky_conversation_stays_with_the_owner(self):
		c = ctx(number_type="Personal", owner_user="rahul", current_assignee="rahul", agents=[ag("rahul")])
		self.assertEqual(choose_assignee(c).reason, "sticky")

	def test_a_departed_owner_leaves_the_conversation_unassigned(self):
		# the owner was removed from the number's agent rows: nobody to give it to but supervisors, if any
		c = ctx(number_type="Personal", owner_user="gone", agents=[ag("s", role="Supervisor")])
		self.assertEqual(choose_assignee(c).assignee, "s")
		self.assertEqual(choose_assignee(ctx(number_type="Personal", owner_user="gone", agents=[])).reason, POOL)


class TestConfiguredRules(unittest.TestCase):
	def test_admin_can_put_record_owner_before_the_tag(self):
		agents = [ag("a", rep_code="R1"), ag("b")]
		c = ctx(tag="R1", record_owner="b", agents=agents, rules=[Rule(RECORD_OWNER), Rule(REP_TAG)])
		self.assertEqual(choose_assignee(c).assignee, "b")

	def test_disabled_rules_are_skipped(self):
		agents = [ag("a", rep_code="R1"), ag("b")]
		c = ctx(tag="R1", agents=agents, rules=[Rule(REP_TAG, enabled=False), Rule(LEAST_BUSY)])
		self.assertEqual(choose_assignee(c).reason, "least_busy")

	def test_only_the_listed_rules_run(self):
		c = ctx(record_owner="b", agents=[ag("a"), ag("b")], rules=[Rule(REP_TAG)])
		d = choose_assignee(c)
		self.assertEqual((d.assignee, d.reason), (None, POOL))  # record owner is not in the list, no fallback to least busy

	def test_unknown_rule_types_are_ignored(self):
		c = ctx(agents=[ag("a")], rules=[Rule("Nonsense"), Rule(LEAST_BUSY)])
		self.assertEqual(choose_assignee(c).assignee, "a")

	def test_everything_disabled_means_the_pool(self):
		c = ctx(agents=[ag("a")], rules=[Rule(LEAST_BUSY, enabled=False)])
		self.assertEqual(choose_assignee(c).reason, POOL)

	def test_stickiness_can_be_switched_off(self):
		c = ctx(current_assignee="a", agents=[ag("a", open_count=5), ag("b")], rules=[Rule(LEAST_BUSY)])
		self.assertEqual(choose_assignee(c).assignee, "b")


if __name__ == "__main__":
	unittest.main()
