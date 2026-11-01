import tempfile
import unittest
from pathlib import Path

from tests.test_repo import RepoCase
from timetra.db.connection import connect
from timetra.db.repo import Repo
from timetra.services.autoplace import auto_place, best_slots, pick_room
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
            report = auto_place(self.repo, self.ver)
        self.assertEqual(report.placed, 20)
        self.assertEqual(report.missing, [])
        self.assertEqual(self.repo.conflict_pairs(self.ver), [])

    def test_odd_remainder_goes_to_one_week(self):
        with self.conn:
            self.repo.save_workload(self.wl, self.cls, self.subject, 0, self.teacher, 3)
            auto_place(self.repo, self.ver)
        self.assertEqual(self.repo.workload_item(self.ver, self.wl)["placed"], 3)

    def test_existing_lessons_kept_and_counted(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.wl, 1, 5, self.slot, None)
            self.repo.add_lesson(self.ver, self.wl, 2, 5, self.slot, None)
            auto_place(self.repo, self.ver)
        rows = [r for r in self.repo.lessons(self.ver) if r["workload_id"] == self.wl]
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(r["weekday_id"] == 5 and r["lesson_slot_id"] == self.slot for r in rows), 2)

    def test_impossible_lesson_reported(self):
        off = [(d, s["id"]) for d in range(1, 7) for s in self.repo.slots(1)]
        with self.conn:
            self.repo.save_teacher(self.teacher, "Иванова", "Мария", "", [self.subject], off)
            report = auto_place(self.repo, self.ver)
        self.assertEqual(report.placed, 0)
        self.assertEqual(len(report.missing), 10)

    def test_missing_scores_reported(self):
        with self.conn:
            self.repo.save_subject(self.subject, "Математика", "", None, {})
            report = auto_place(self.repo, self.ver)
        self.assertEqual(report.no_scores, ["Математика"])
        self.assertEqual(report.placed, 20)

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


class ComposeQualityTest(unittest.TestCase):
    """Школа, похожая на настоящую: проверяем, что костяк соответствует правилам по баллам."""

    PLAN = [
        ("Математика", 12, 10), ("Русский язык", 11, 10), ("Физика", 10, 4), ("Литература", 4, 4),
        ("История", 5, 4), ("Биология", 7, 2), ("Физкультура", 3, 4), ("Музыка", 2, 2),
    ]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.conn = connect(Path(tmp.name) / "t.db")
        self.addCleanup(self.conn.close)
        repo = self.repo = Repo(self.conn)
        repo.ensure_defaults()
        self.ver = repo.versions()[0]["id"]
        with self.conn:
            for n in range(1, 7):
                repo.save_room(None, f"10{n}", 30, 1)
            repo.save_room(None, "Спортзал", 60, 3)
            grades = {name: {7: score} for name, score, _l in self.PLAN}
            subject_ids = {
                name: repo.save_subject(None, name, "", 3 if name == "Физкультура" else None, grades[name])
                for name, _s, _l in self.PLAN
            }
            subject_ids["Английский"] = repo.save_subject(None, "Английский", "", None, {7: 9})
            for letter in "АБВГ":
                repo.save_class(None, 7, letter, 1, 5, 25, None, None)
            for i, cls in enumerate(repo.classes()):
                for name, _score, lessons in self.PLAN:
                    teacher = repo.save_teacher(None, f"{name}{i}", "И", "", [subject_ids[name]])
                    repo.save_workload(None, cls["id"], subject_ids[name], 0, teacher, lessons)
                for group in (1, 2):
                    teacher = repo.save_teacher(None, f"Англ{i}{group}", "И", "", [subject_ids["Английский"]])
                    repo.save_workload(None, cls["id"], subject_ids["Английский"], group, teacher, 4)
        self.numbers = {s["id"]: s["number"] for s in repo.slots()}

    def compose(self, peak="even"):
        with self.conn:
            self.report = auto_place(self.repo, self.ver, peak)
        return self.repo.lessons(self.ver, 1)

    def day_totals(self, lessons, class_id):
        return [day_score(lessons, class_id, 1, d) for d in range(1, 6)]

    def test_everything_placed_without_clashes_or_rooms_lost(self):
        lessons = self.compose()
        self.assertEqual(self.report.missing, [])
        self.assertEqual(self.repo.conflict_pairs(self.ver), [])
        gym = [x for x in lessons if x["subject_name"] == "Физкультура"]
        self.assertTrue(all(x["room_number"] == "Спортзал" for x in gym))

    def test_hard_subjects_mostly_on_lessons_two_to_four(self):
        lessons = self.compose()
        hard = [x for x in lessons if x["subject_name"] in ("Математика", "Русский язык")]
        good = sum(self.numbers[x["lesson_slot_id"]] in best_slots(7) for x in hard)
        self.assertGreaterEqual(good / len(hard), 0.75)

    def test_load_spread_between_days(self):
        lessons = self.compose()
        for cls in self.repo.classes():
            totals = self.day_totals(lessons, cls["id"])
            self.assertLessEqual(max(totals) - min(totals), 12, totals)

    def test_peak_days_are_heaviest(self):
        lessons = self.compose("wed_thu")
        for cls in self.repo.classes():
            totals = self.day_totals(lessons, cls["id"])
            self.assertGreaterEqual(totals[2] + totals[3], totals[0] + totals[4], totals)

    def test_subject_not_repeated_in_day(self):
        lessons = self.compose()
        seen = {}
        for x in lessons:
            key = (x["class_id"], x["weekday_id"], x["subject_id"], x["subgroup"])
            seen[key] = seen.get(key, 0) + 1
        # 5 уроков в неделю на 5 дней: повторы не нужны ни одному предмету
        self.assertEqual(max(seen.values()), 1)

    def test_subgroups_run_in_parallel(self):
        lessons = self.compose()
        english = {}
        for x in lessons:
            if x["subject_name"] == "Английский":
                english.setdefault((x["class_id"], x["weekday_id"], x["lesson_slot_id"]), []).append(x["subgroup"])
        self.assertTrue(all(sorted(v) == [1, 2] for v in english.values()))

    def test_no_gaps_inside_a_day(self):
        lessons = self.compose()
        days = {}
        for x in lessons:
            days.setdefault((x["class_id"], x["weekday_id"]), set()).add(self.numbers[x["lesson_slot_id"]])
        for key, numbers in days.items():
            self.assertEqual(sorted(numbers), list(range(1, max(numbers) + 1)), key)


if __name__ == "__main__":
    unittest.main()
