import unittest

from tests.test_repo import RepoCase
from timetra.services.autoplace import auto_place, pick_room
from timetra.services.checks import CONFLICT, WARNING, check_placement, day_score, find_problems


class ServicesCase(RepoCase):
    def setUp(self):
        super().setUp()
        with self.conn:
            self.repo.save_class(None, 5, "Б", 1, 5, 24, None, None)
            self.cls2 = [c["id"] for c in self.repo.classes() if c["letter"] == "Б"][0]
            self.repo.save_workload(None, self.cls2, self.subject, 0, self.teacher, 10)
            self.repo.save_room(None, "101", 30, 1)
            self.repo.save_room(None, "102", 30, 1)
        self.wl2 = [w["id"] for w in self.repo.workload(self.ver) if w["class_id"] == self.cls2][0]
        self.room = self.repo.rooms()[0]["id"]
        self.room2 = self.repo.rooms()[1]["id"]

    def item(self, wl):
        return self.repo.workload_item(self.ver, wl)

    def check(self, wl, room=None, skip=()):
        return check_placement(self.repo, self.ver, self.item(wl), 1, 1, self.slot, room, skip)

    def place(self, wl, room=None, week=1):
        with self.conn:
            self.repo.add_lesson(self.ver, wl, week, 1, self.slot, room)


class CheckTest(ServicesCase):
    def test_free_slot_is_clean(self):
        with self.conn:
            self.repo.save_teacher(self.teacher, "Иванова", "Мария", "", [self.subject])
        self.assertTrue(self.check(self.wl).clean)

    def test_busy_room_blocks(self):
        self.place(self.wl, self.room)
        self.assertIn("101", self.check(self.wl2, self.room).room_busy)

    def test_busy_teacher_only_warns(self):
        self.place(self.wl, self.room)
        result = self.check(self.wl2, self.room2)
        self.assertIsNone(result.room_busy)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("занят", result.warnings[0])

    def test_skip_ignores_lesson_being_moved(self):
        self.place(self.wl, self.room)
        lesson = self.repo.lessons(self.ver)[0]
        self.assertIsNone(self.check(self.wl, self.room, [lesson["id"]]).room_busy)

    def test_teacher_off_warns(self):
        with self.conn:
            self.repo.save_teacher(self.teacher, "Иванова", "Мария", "", [self.subject], [(1, self.slot)])
        self.assertIn("не может", self.check(self.wl).warnings[0])

    def test_room_type_and_capacity_warn(self):
        with self.conn:
            self.repo.save_subject(self.subject, "Математика", "", 2, {5: 10})
            self.repo.save_room(self.room, "101", 10, 1)
        warnings = self.check(self.wl, self.room).warnings
        self.assertTrue(any("типа" in w for w in warnings))
        self.assertTrue(any("10 мест" in w for w in warnings))


class ProblemsTest(ServicesCase):
    def test_teacher_clash_is_warning_merged_over_weeks(self):
        for week in (1, 2):
            self.place(self.wl, week=week)
            self.place(self.wl2, week=week)
        problems = [p for p in find_problems(self.repo, self.ver) if "два урока" in p.title]
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].severity, WARNING)
        self.assertEqual(problems[0].weeks, {1, 2})

    def test_class_clash_is_conflict_and_sorted_first(self):
        with self.conn:
            other = self.repo.save_subject(None, "Музыка", "", None, {})
            self.repo.save_workload(None, self.cls, other, 0, self.teacher, 2)
        wl3 = [w["id"] for w in self.repo.workload(self.ver, self.cls) if w["subject_id"] == other][0]
        self.place(self.wl)
        self.place(wl3)
        problems = find_problems(self.repo, self.ver)
        self.assertEqual(problems[0].severity, CONFLICT)

    def test_unqualified_teacher_reported_only_if_subjects_filled(self):
        self.place(self.wl)
        self.assertFalse(any("не отмечен" in p.title for p in find_problems(self.repo, self.ver)))
        with self.conn:
            other = self.repo.save_subject(None, "Музыка", "", None, {})
            self.repo.save_teacher(self.teacher, "Иванова", "Мария", "", [other])
        self.assertTrue(any("не отмечен" in p.title for p in find_problems(self.repo, self.ver)))

    def test_daily_limit_reported(self):
        with self.conn:
            self.repo.set_grade_limit(5, 1)
            for slot in self.repo.slots(1)[:2]:
                self.repo.add_lesson(self.ver, self.wl, 1, 2, slot["id"], None)
        self.assertTrue(any("при лимите 1" in p.title for p in find_problems(self.repo, self.ver)))


class DayScoreTest(ServicesCase):
    def test_parallel_subgroups_counted_once(self):
        with self.conn:
            self.repo.save_workload(None, self.cls2, self.subject, 1, self.teacher, 2)
            self.repo.save_workload(None, self.cls2, self.subject, 2, self.teacher, 2)
            for w in self.repo.workload(self.ver, self.cls2):
                if w["subgroup"]:
                    self.repo.add_lesson(self.ver, w["id"], 1, 1, self.slot, None)
        self.assertEqual(day_score(self.repo.lessons(self.ver), self.cls2, 1, 1), 10)


class AutoPlaceTest(ServicesCase):
    def test_places_all_without_clashes(self):
        with self.conn:
            placed = auto_place(self.repo, self.ver)
        self.assertEqual(placed, 20)
        self.assertEqual(self.repo.conflict_pairs(self.ver), [])

    def test_odd_remainder_goes_to_one_week(self):
        with self.conn:
            self.repo.save_workload(self.wl, self.cls, self.subject, 0, self.teacher, 3)
            auto_place(self.repo, self.ver, self.cls)
        self.assertEqual(self.repo.workload_item(self.ver, self.wl)["placed"], 3)

    def test_keeps_teacher_off_time(self):
        with self.conn:
            self.repo.save_teacher(self.teacher, "Иванова", "Мария", "", [self.subject], [(1, self.slot)])
            auto_place(self.repo, self.ver)
        self.assertFalse(any(r["weekday_id"] == 1 and r["lesson_slot_id"] == self.slot for r in self.repo.lessons(self.ver)))

    def test_pick_room_prefers_home_and_skips_busy(self):
        with self.conn:
            self.repo.save_class(self.cls, 5, "А", 1, 5, 26, None, self.room2)
        wl = self.item(self.wl)
        self.assertEqual(pick_room(self.repo, wl, self.ver, (1,), 1, self.slot), self.room2)
        self.place(self.wl2, self.room2)
        self.assertEqual(pick_room(self.repo, wl, self.ver, (1,), 1, self.slot), self.room)

    def test_pick_room_respects_required_type(self):
        with self.conn:
            self.repo.save_subject(self.subject, "Математика", "", 2, {})
        self.assertIsNone(pick_room(self.repo, self.item(self.wl), self.ver, (1,), 1, self.slot))


if __name__ == "__main__":
    unittest.main()
