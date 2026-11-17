"""Run without a site:  python -m unittest waba.tests.test_team_setup"""

import unittest

from waba.rules import team_setup as ts

PARENTS = {"Common": None, "Sales": "Common", "Sales North": "Sales", "Accounts": "Common"}
MEMBERS = [
	("Common", "boss@x", "Team Lead"),
	("Sales", "sales.head@x", "Team Lead"),
	("Sales North", "north.a@x", "Agent"),
	("Accounts", "acc.a@x", "Agent"),
]
NUMBERS = {"Sales": ["N-SALES", "N-SUP"], "Accounts": ["N-SUP"]}


class TestDerive(unittest.TestCase):
	def derive(self, number, **kw):
		return ts.derive_agents(number, parents=PARENTS, members=MEMBERS, team_numbers=NUMBERS, **kw)

	def test_a_team_and_the_teams_below_it_work_its_numbers(self):
		rows = self.derive("N-SALES")
		self.assertEqual([(r["user"], r["role"]) for r in rows], [("sales.head@x", "Supervisor"), ("north.a@x", "Agent")])

	def test_a_shared_number_gets_both_departments(self):
		self.assertEqual({r["user"] for r in self.derive("N-SUP")}, {"sales.head@x", "north.a@x", "acc.a@x"})

	def test_people_above_are_not_agents(self):
		self.assertNotIn("boss@x", {r["user"] for r in self.derive("N-SALES")})

	def test_an_unused_number_gets_nobody(self):
		self.assertEqual(self.derive("N-NONE"), [])

	def test_settings_and_availability_are_kept(self):
		rows = self.derive("N-SALES", settings={"north.a@x": {"max_open": 5, "rep_code": "R1", "languages": "hi"}}, existing={"north.a@x": False})
		north = [r for r in rows if r["user"] == "north.a@x"][0]
		self.assertEqual((north["max_open"], north["rep_code"], north["languages"], north["available"]), (5, "R1", "hi", 0))
		self.assertEqual([r for r in rows if r["user"] == "sales.head@x"][0]["available"], 1)


class TestOwnNumbersOnly(unittest.TestCase):
	"""Marketing sits under IT; each owns a number. Marketing works its own number only; IT works IT's."""

	PARENTS = {"Common": None, "IT": "Common", "Marketing": "IT", "Helpdesk": "IT"}
	MEMBERS = [("IT", "it.lead@x", "Team Lead"), ("Marketing", "mkt.lead@x", "Team Lead"), ("Marketing", "mkt.a@x", "Agent"), ("Helpdesk", "help.a@x", "Agent")]
	NUMBERS = {"IT": ["N-IT"], "Marketing": ["N-MKT"]}

	def derive(self, number):
		return {r["user"] for r in ts.derive_agents(number, parents=self.PARENTS, members=self.MEMBERS, team_numbers=self.NUMBERS)}

	def test_a_sub_team_with_its_own_number_does_not_also_work_its_parents(self):
		self.assertEqual(self.derive("N-MKT"), {"mkt.lead@x", "mkt.a@x"})
		self.assertNotIn("mkt.a@x", self.derive("N-IT"))
		self.assertNotIn("mkt.lead@x", self.derive("N-IT"))

	def test_a_sub_team_with_no_number_inherits_the_nearest_parents(self):
		self.assertEqual(self.derive("N-IT"), {"it.lead@x", "help.a@x"})

	def test_effective_team(self):
		e = lambda t: ts.effective_team(t, self.PARENTS, self.NUMBERS)
		self.assertEqual((e("Marketing"), e("Helpdesk"), e("IT"), e("Common")), ("Marketing", "IT", "IT", None))

	def test_a_team_with_no_number_anywhere_above_works_none(self):
		self.assertEqual(ts.derive_agents("N-MKT", parents={"A": None, "B": "A"}, members=[("B", "u@x", "Agent")], team_numbers={}), [])


class TestRoles(unittest.TestCase):
	def test_lead_and_agent_roles(self):
		self.assertEqual(ts.wanted_roles(MEMBERS), {"boss@x": "Waba Supervisor", "sales.head@x": "Waba Supervisor", "north.a@x": "Waba Agent", "acc.a@x": "Waba Agent"})

	def test_a_lead_wins_when_listed_twice(self):
		self.assertEqual(ts.wanted_roles([("A", "u@x", "Agent"), ("B", "u@x", "Team Lead")])["u@x"], "Waba Supervisor")


class TestCheck(unittest.TestCase):
	def check(self, **kw):
		args = dict(parents=PARENTS, members=MEMBERS, team_numbers=NUMBERS, numbers=[{"name": "N-SALES", "enabled": 1}, {"name": "N-SUP", "enabled": 1}], access={})
		args.update(kw)
		return ts.check(**args)

	def texts(self, found, level=None):
		return " | ".join(f["text"] for f in found if level in (None, f["level"]))

	def test_a_clean_setup_has_no_errors(self):
		self.assertEqual(ts.blocking(self.check()), [])

	def test_a_person_in_two_teams_is_an_error(self):
		found = self.check(members=MEMBERS + [("Accounts", "north.a@x", "Agent")])
		self.assertIn("north.a@x is in more than one team", self.texts(found, "error"))
		self.assertTrue(ts.blocking(found))

	def test_a_disabled_member_is_an_error(self):
		found = self.check(enabled_users={"boss@x"})
		self.assertIn("disabled or does not exist", self.texts(found, "error"))

	def test_a_number_nobody_uses(self):
		found = self.check(numbers=[{"name": "N-LOOSE", "enabled": 1}])
		self.assertIn("N-LOOSE is not used by any team", self.texts(found, "warning"))

	def test_a_disabled_unused_number_is_only_information(self):
		found = self.check(numbers=[{"name": "N-OLD", "enabled": 0}])
		self.assertIn("N-OLD", self.texts(found, "info"))

	def test_a_number_with_no_lead_above_it(self):
		found = self.check(members=[m for m in MEMBERS if m[2] != "Team Lead" or m[0] == "Common"])
		self.assertIn("Nobody leads the teams that use N-SALES", self.texts(found, "warning"))

	def test_root_without_a_lead(self):
		found = self.check(members=[m for m in MEMBERS if m[0] != "Common"])
		self.assertIn("The top-level team Common has no Team Lead", self.texts(found, "warning"))

	def test_a_loose_agent_is_named_and_a_new_one_announced(self):
		found = self.check(access={"N-SALES": ["atharva@x", "sales.head@x"]})
		self.assertIn("atharva@x is an agent on N-SALES but not in any team", self.texts(found, "warning"))
		self.assertIn("north.a@x will become an agent on N-SALES", self.texts(found, "info"))

	def test_roles_that_apply_will_add(self):
		found = self.check(user_roles={"boss@x": {"Waba Supervisor"}})
		self.assertIn("acc.a@x will be given the role Waba Agent", self.texts(found, "info"))
		self.assertNotIn("boss@x will be given", self.texts(found))

	def test_someone_with_a_waba_role_but_no_team_is_named(self):
		found = self.check(user_roles={"ghost@x": {"Waba Agent"}, "boss@x": {"Waba Supervisor"}, "adm@x": {"Waba Admin", "Waba Agent"}})
		text = self.texts(found, "warning")
		self.assertIn("ghost@x has a Waba role but is in no team", text)
		self.assertNotIn("boss@x has a Waba role", text)
		self.assertNotIn("adm@x has a Waba role", text)

	def test_open_chats_with_someone_outside_the_teams_are_named(self):
		roles = {"ghost@x": set(), "acc.a@x": {"Waba Agent"}}
		found = self.check(user_roles=roles, assignments={"ghost@x": ["WCONV-1", "WCONV-2"], "acc.a@x": ["WCONV-3"]})
		text = self.texts(found, "warning")
		self.assertIn("ghost@x has open conversations (WCONV-1, WCONV-2)", text)
		self.assertNotIn("acc.a@x has open conversations", text)

	def test_errors_come_first(self):
		found = self.check(members=MEMBERS + [("Accounts", "north.a@x", "Agent")], numbers=[{"name": "N-LOOSE", "enabled": 1}])
		self.assertEqual(found[0]["level"], "error")
