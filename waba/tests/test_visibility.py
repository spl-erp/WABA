"""Run without a site:  python -m unittest waba.tests.test_visibility

The owner's sketch as fixtures: Common at the top; Marketing, Sales Domestic, Sales Export and Export under it, each
with its own WhatsApp number; Sales Domestic has two sub-teams.
"""

import unittest

from waba.rules import visibility as v

PARENTS = {
	"Common": None,
	"Marketing": "Common",
	"Sales Domestic": "Common",
	"Domestic North": "Sales Domestic",
	"Domestic South": "Sales Domestic",
	"Sales Export": "Common",
	"Export": "Common",
}
MEMBERS = [
	("Common", "boss@x", "Team Lead"),
	("Marketing", "mk.head@x", "Team Lead"),
	("Marketing", "mk.agent@x", "Agent"),
	("Sales Domestic", "dom.head@x", "Team Lead"),
	("Domestic North", "north.lead@x", "Team Lead"),
	("Domestic North", "north.a@x", "Agent"),
	("Domestic South", "south.a@x", "Agent"),
	("Sales Export", "exp.head@x", "Team Lead"),
	("Sales Export", "exp.a@x", "Agent"),
]
NUMBERS = {"Marketing": ["N-MK"], "Sales Domestic": ["N-DOM"], "Sales Export": ["N-EXP"], "Export": ["N-EXP2"]}
VISIBILITY = {"N-DOM": "Own conversations only", "N-MK": "All conversations on this number"}


def scope(user, **kw):
	return v.visible_scope(user, parents=PARENTS, members=MEMBERS, team_numbers=NUMBERS, number_visibility=VISIBILITY, **kw)


class TestTree(unittest.TestCase):
	def test_subtree(self):
		self.assertEqual(v.subtree("Sales Domestic", PARENTS), {"Sales Domestic", "Domestic North", "Domestic South"})
		self.assertEqual(v.subtree("Export", PARENTS), {"Export"})

	def test_ancestors(self):
		self.assertEqual(v.ancestors("Domestic North", PARENTS), ["Domestic North", "Sales Domestic", "Common"])

	def test_a_loop_does_not_hang(self):
		loop = {"A": "B", "B": "A"}
		self.assertEqual(v.subtree("A", loop), {"A", "B"})
		self.assertEqual(v.ancestors("A", loop), ["A", "B"])


class TestWhoSeesWhat(unittest.TestCase):
	def test_common_lead_and_admin_see_everything(self):
		self.assertTrue(scope("boss@x").everything)
		self.assertTrue(scope("anyone@x", everyone=True).everything)
		self.assertTrue(v.can_see(scope("boss@x"), None, "N-EXP2"))
		self.assertTrue(v.can_see_unassigned(scope("boss@x"), "N-EXP2"))

	def test_department_lead_sees_the_whole_department(self):
		s = scope("dom.head@x")
		self.assertTrue(v.can_see(s, None, "N-DOM"))  # unassigned on its number
		self.assertTrue(v.can_see(s, "somebody.else@x", "N-DOM"))  # assigned to anyone on its number
		self.assertTrue(v.can_see(s, "north.a@x", "N-OTHER"))  # assigned to a member below
		self.assertTrue(v.can_see_unassigned(s, "N-DOM"))

	def test_department_lead_never_sees_sideways(self):
		s = scope("dom.head@x")
		self.assertFalse(v.can_see(s, "exp.a@x", "N-EXP"))
		self.assertFalse(v.can_see(s, None, "N-EXP"))
		self.assertFalse(v.can_see(s, "mk.agent@x", "N-MK"))
		self.assertFalse(v.can_see_unassigned(s, "N-MK"))

	def test_sub_team_lead_sees_only_their_branch(self):
		s = scope("north.lead@x")
		self.assertTrue(v.can_see(s, "north.a@x", "N-DOM"))
		self.assertFalse(v.can_see(s, "south.a@x", "N-DOM"))  # a sibling branch
		self.assertFalse(v.can_see(s, None, "N-DOM"))  # the number belongs to the department above
		self.assertFalse(v.can_see_unassigned(s, "N-DOM"))

	def test_agent_sees_only_their_own(self):
		s = scope("north.a@x", agent_numbers=["N-DOM"])
		self.assertTrue(v.can_see(s, "north.a@x", "N-DOM"))
		self.assertFalse(v.can_see(s, "south.a@x", "N-DOM"))
		self.assertFalse(v.can_see(s, None, "N-DOM"))
		self.assertFalse(v.can_see_unassigned(s, "N-DOM"))

	def test_agent_on_a_number_that_shows_all(self):
		s = scope("mk.agent@x", agent_numbers=["N-MK"])
		self.assertTrue(v.can_see(s, None, "N-MK"))
		self.assertTrue(v.can_see(s, "mk.head@x", "N-MK"))
		self.assertFalse(v.can_see_unassigned(s, "N-MK"))  # still not an overseer

	def test_a_person_in_no_team_sees_only_their_own(self):
		s = scope("stranger@x")
		self.assertTrue(v.can_see(s, "stranger@x", "N-DOM"))
		self.assertFalse(v.can_see(s, "north.a@x", "N-DOM"))
		self.assertFalse(v.can_see(s, None, "N-DOM"))

	def test_agent_role_in_common_is_not_everything(self):
		members = MEMBERS + [("Common", "clerk@x", "Agent")]
		s = v.visible_scope("clerk@x", parents=PARENTS, members=members, team_numbers=NUMBERS)
		self.assertFalse(s.everything)

	def test_unassigned_has_no_assignee_match(self):
		self.assertFalse(v.can_see(scope("north.a@x"), "", "N-DOM"))


class TestOverseers(unittest.TestCase):
	def kw(self):
		return dict(parents=PARENTS, members=MEMBERS, team_numbers=NUMBERS)

	def test_unassigned_goes_to_the_department_head_and_above(self):
		self.assertEqual(v.overseers(None, "N-DOM", **self.kw()), {"dom.head@x", "boss@x"})

	def test_assigned_inside_a_sub_team_reaches_each_lead_above(self):
		got = v.overseers("north.a@x", "N-DOM", **self.kw())
		self.assertEqual(got, {"north.lead@x", "dom.head@x", "boss@x"})

	def test_other_departments_are_not_told(self):
		got = v.overseers("exp.a@x", "N-EXP", **self.kw())
		self.assertEqual(got, {"exp.head@x", "boss@x"})
		self.assertNotIn("dom.head@x", got)

	def test_the_assignee_is_not_listed(self):
		self.assertNotIn("exp.head@x", v.overseers("exp.head@x", "N-EXP", **self.kw()))


if __name__ == "__main__":
	unittest.main()


class TestSharedNumbers(unittest.TestCase):
	"""A number used by two departments: each head sees only their own people's chats, plus what nobody has yet."""

	PARENTS = {"Common": None, "Sales": "Common", "Accounts": "Common", "Sales North": "Sales"}
	MEMBERS = [
		("Sales", "sales.head@x", "Team Lead"),
		("Sales North", "north.a@x", "Agent"),
		("Accounts", "acc.head@x", "Team Lead"),
		("Accounts", "acc.a@x", "Agent"),
	]
	NUMBERS = {"Sales": ["N-SALES", "N-SUPPORT"], "Sales North": [], "Accounts": ["N-ACC", "N-SUPPORT"]}

	def scope(self, user):
		return v.visible_scope(user, parents=self.PARENTS, members=self.MEMBERS, team_numbers=self.NUMBERS)

	def test_a_number_only_one_branch_uses_shows_everything_on_it(self):
		s = self.scope("sales.head@x")
		self.assertIn("N-SALES", s.exclusive_numbers)
		self.assertTrue(v.can_see(s, "stranger@x", "N-SALES"))

	def test_a_shared_number_shows_only_own_branch_and_unassigned(self):
		s = self.scope("sales.head@x")
		self.assertNotIn("N-SUPPORT", s.exclusive_numbers)
		self.assertIn("N-SUPPORT", s.lead_numbers)
		self.assertTrue(v.can_see(s, "north.a@x", "N-SUPPORT"))
		self.assertFalse(v.can_see(s, "acc.a@x", "N-SUPPORT"))
		self.assertTrue(v.can_see_unassigned(s, "N-SUPPORT"))

	def test_the_other_head_sees_the_mirror_image(self):
		s = self.scope("acc.head@x")
		self.assertTrue(v.can_see(s, "acc.a@x", "N-SUPPORT"))
		self.assertFalse(v.can_see(s, "north.a@x", "N-SUPPORT"))
		self.assertFalse(v.can_see(s, "north.a@x", "N-SALES"))

	def test_managing_follows_the_same_split(self):
		s = self.scope("sales.head@x")
		self.assertTrue(v.can_manage(s, "north.a@x", "N-SUPPORT"))
		self.assertFalse(v.can_manage(s, "acc.a@x", "N-SUPPORT"))
		self.assertTrue(v.can_manage(s, None, "N-SUPPORT"))
		self.assertTrue(v.can_manage(s, "gone@x", "N-SALES"))
		self.assertFalse(v.can_manage(s, None, "N-ACC"))

	def test_an_agent_manages_only_their_own(self):
		s = self.scope("north.a@x")
		self.assertTrue(v.can_manage(s, "north.a@x", "N-SUPPORT"))
		self.assertFalse(v.can_manage(s, "acc.a@x", "N-SUPPORT"))
		self.assertFalse(v.can_manage(s, None, "N-SUPPORT"))

	def test_admins_manage_everything(self):
		self.assertTrue(v.can_manage(v.visible_scope("a@x", everyone=True), "x@x", "N-ACC"))

	def test_live_updates_go_to_the_right_heads(self):
		kw = dict(parents=self.PARENTS, members=self.MEMBERS, team_numbers=self.NUMBERS)
		self.assertEqual(v.overseers("north.a@x", "N-SUPPORT", **kw), {"sales.head@x"})
		self.assertEqual(v.overseers(None, "N-SUPPORT", **kw), {"sales.head@x", "acc.head@x"})
		self.assertEqual(v.overseers("x@x", "N-ACC", **kw), {"acc.head@x"})


class TestUnassignedOnSharedNumbers(unittest.TestCase):
	def test_a_lead_can_open_what_nobody_has_yet_on_a_shared_number(self):
		parents = {"Common": None, "Sales": "Common", "Accounts": "Common"}
		members = [("Sales", "sales.head@x", "Team Lead"), ("Accounts", "acc.head@x", "Team Lead"), ("Accounts", "acc.a@x", "Agent")]
		numbers = {"Sales": ["N-SUP"], "Accounts": ["N-SUP"]}
		for lead in ("sales.head@x", "acc.head@x"):
			s = v.visible_scope(lead, parents=parents, members=members, team_numbers=numbers)
			self.assertTrue(v.can_see(s, None, "N-SUP"), lead)
			self.assertTrue(v.can_see(s, "", "N-SUP"), lead)
		agent = v.visible_scope("acc.a@x", parents=parents, members=members, team_numbers=numbers)
		self.assertFalse(v.can_see(agent, None, "N-SUP"))
		stranger = v.visible_scope("x@x", parents=parents, members=members, team_numbers=numbers)
		self.assertFalse(v.can_see(stranger, None, "N-SUP"))


class TestVisibleNumbers(unittest.TestCase):
	"""Which business numbers a person sees in the inbox's picker and the Desk list."""

	ALL = ["N1", "N2", "N3"]

	def scope(self, **kw):
		from waba.rules import visibility as v

		return v.Scope(me="u", **kw)

	def test_admin_sees_every_number(self):
		from waba.rules import visibility as v

		self.assertEqual(v.visible_numbers(self.scope(everything=True), [], self.ALL), self.ALL)

	def test_an_agent_sees_only_the_number_they_work(self):
		from waba.rules import visibility as v

		self.assertEqual(v.visible_numbers(self.scope(), ["N2"], self.ALL), ["N2"])

	def test_a_lead_sees_the_numbers_their_team_owns(self):
		from waba.rules import visibility as v

		self.assertEqual(v.visible_numbers(self.scope(lead_numbers=frozenset({"N1"}), numbers=frozenset({"N1"})), [], self.ALL), ["N1"])

	def test_agent_and_lead_numbers_are_combined(self):
		from waba.rules import visibility as v

		self.assertEqual(v.visible_numbers(self.scope(lead_numbers=frozenset({"N3"})), ["N1"], self.ALL), ["N1", "N3"])

	def test_nobody_sees_nothing_and_unknown_numbers_are_dropped(self):
		from waba.rules import visibility as v

		self.assertEqual(v.visible_numbers(self.scope(), [], self.ALL), [])
		self.assertEqual(v.visible_numbers(self.scope(), ["GONE"], self.ALL), [])
