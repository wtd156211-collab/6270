"""heavyhitters 的验收与单元测试（只用标准库，只读 samples/）。"""

import os
import subprocess
import sys
import tempfile
import tracemalloc
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import heavyhitters

STREAMS = os.path.join(ROOT, "samples", "streams")
EXPECTED = os.path.join(ROOT, "samples", "expected")
MEMORY_LIMIT = 24 * 1024 * 1024


def parse_expected(path):
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    header = {}
    for field in lines[0].split("|")[1:]:
        k, _, v = field.partition("=")
        header[k] = v
    num, den = (int(x) for x in header["eps"].split("/"))
    freq = {}
    must = set()
    bounds = {}
    for line in lines[1:]:
        if not line or line.startswith("T|"):
            break
        p = line.split("|")
        freq[p[1]] = int(p[2])
        if p[3] == "must":
            must.add(p[1])
        bounds[p[1]] = (int(p[4]), int(p[5]))
    return {
        "name": lines[0].split("|")[1],
        "N": int(header["N"]),
        "num": num,
        "den": den,
        "B": int(header["B"]),
        "cap": int(header["命中上限"]),
        "freq": freq,
        "must": must,
        "bounds": bounds,
    }


def parse_result(path):
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    header = {}
    hparts = lines[0].split("|")
    stream_name = hparts[1]
    for field in hparts[2:]:
        k, _, v = field.partition("=")
        header[k] = v
    entries = []
    for line in lines[1:]:
        if not line:
            continue
        p = line.split("|")
        if p[0] == "E":
            entries.append((p[1], int(p[2]), int(p[3]), p[4]))
        elif p[0] == "T":
            trailer = {}
            for field in p[1:]:
                k, _, v = field.partition("=")
                trailer[k] = v
    return stream_name, header, entries, trailer


class SampleAcceptanceTest(unittest.TestCase):
    """对每份样例跑 run，按 README 第五节的口径逐条核对。"""

    def check_sample(self, name):
        stream = os.path.join(STREAMS, name + ".txt")
        exp = parse_expected(os.path.join(EXPECTED, name + ".txt"))
        num, den, B, N = exp["num"], exp["den"], exp["B"], exp["N"]
        with tempfile.TemporaryDirectory() as tmp:
            result = os.path.join(tmp, "result.txt")
            self.assertEqual(heavyhitters.run(stream, result, num, den), 0)
            stream_name, header, entries, trailer = parse_result(result)

        # H 行口径
        self.assertEqual(stream_name, stream)
        self.assertEqual(int(header["N"]), N)
        self.assertEqual(header["eps"], f"{num}/{den}")
        self.assertEqual(int(header["B"]), B)
        self.assertEqual(header["阈值"], f"{num * N}/{den}")
        self.assertEqual(int(header["命中"]), len(entries))
        exact_rows = [e for e in entries if e[3] == "exact"]
        self.assertEqual(int(header["精确"]), len(exact_rows))

        seen = set()
        prev = None
        for key, est, bound, tag in entries:
            # 键不重复、估计 >= 1、误差界 <= B、exact 当且仅当误差界为 0
            self.assertNotIn(key, seen)
            seen.add(key)
            self.assertGreaterEqual(est, 1)
            self.assertGreaterEqual(bound, 0)
            self.assertLessEqual(bound, B)
            self.assertEqual(tag == "exact", bound == 0)
            # 报出条件：估计 + 误差界 严格超过阈值（整数比）
            self.assertGreater((est + bound) * den, num * N)
            # 精确频次按期望文件查（未列出按尾频=1），估计落在区间内
            f = exp["freq"].get(key, 1)
            self.assertLessEqual(max(1, f - B), est, key)
            self.assertLessEqual(est, f + B, key)
            # 排序：估计降序，并列键 ASCII 升序
            if prev is not None:
                self.assertTrue(
                    prev[1] > est or (prev[1] == est and prev[0] < key),
                    f"排序错误: {prev} -> {(key, est)}",
                )
            prev = (key, est)
        # 零漏检：每个 must 键都要出现
        self.assertTrue(exp["must"] <= seen, exp["must"] - seen)
        # 行数不超过命中上限
        self.assertLessEqual(len(entries), exp["cap"])
        # T 行与 E 行一致
        self.assertEqual(int(trailer["命中"]), len(entries))
        self.assertEqual(int(trailer["精确"]), len(exact_rows))
        self.assertEqual(int(trailer["估计合计"]), sum(e[1] for e in entries))
        self.assertEqual(int(trailer["误差合计"]), sum(e[2] for e in entries))

    def test_01_long_tail(self):
        self.check_sample("01-long-tail")

    def test_02_head_heavy(self):
        self.check_sample("02-head-heavy")

    def test_03_near_threshold(self):
        self.check_sample("03-near-threshold")

    def test_04_vast_keyset(self):
        self.check_sample("04-vast-keyset")

    def test_05_scale_1e7(self):
        self.check_sample("05-scale-1e7")

    def test_06_tiny(self):
        self.check_sample("06-tiny")

    def test_reported_keys_actually_in_stream(self):
        # 报出的键必须真的在流里出现过（05 号不同键全在期望文件中，单独核）
        for name in ("01-long-tail", "02-head-heavy", "03-near-threshold",
                     "04-vast-keyset", "06-tiny"):
            stream = os.path.join(STREAMS, name + ".txt")
            exp = parse_expected(os.path.join(EXPECTED, name + ".txt"))
            keys_in_stream = set()
            with open(stream, "r", encoding="utf-8") as fh:
                for line in fh:
                    keys_in_stream.add(line.rstrip("\n"))
            with tempfile.TemporaryDirectory() as tmp:
                result = os.path.join(tmp, "r.txt")
                heavyhitters.run(stream, result, exp["num"], exp["den"])
                _, _, entries, _ = parse_result(result)
            for key, _, _, _ in entries:
                self.assertIn(key, keys_in_stream)


class StructureInvariantTest(unittest.TestCase):
    """合成流上核对 Misra-Gries 不变量与零漏检。"""

    def test_invariants_on_synthetic_stream(self):
        import random

        rng = random.Random(20260930)
        keys = [f"k{i:03d}".encode() for i in range(500)]
        stream = [rng.choice(keys) for _ in range(20000)]
        num, den = 1, 100
        hh = heavyhitters.HeavyHitters(num, den)
        exact = {}
        last_d = 0
        for key in stream:
            hh.offer(key)
            exact[key] = exact.get(key, 0) + 1
            self.assertGreaterEqual(hh.error_bound, last_d)  # 误差界只增不减
            last_d = hh.error_bound
            self.assertLessEqual(len(hh._counts), hh.capacity)
        d = hh.error_bound
        n = hh.n
        # 任意时刻不变量的终点形态：结构内 |est - f| <= D，结构外 f <= D
        for key, f in exact.items():
            est = hh._counts.get(key)
            if est is None:
                self.assertLessEqual(f, d, key)
            else:
                self.assertLessEqual(abs(est - f), d, key)
        # 误差界上限
        self.assertLessEqual(d, num * n // den)
        # 零漏检：必须报的键都在 hits 里
        hit_keys = {k for k, _, _ in hh.hits()}
        for key, f in exact.items():
            if f * den > n * num:
                self.assertIn(key, hit_keys)
        # hits 的每条都满足报出条件与精度
        for key, est, bound in hh.hits():
            self.assertGreater((est + bound) * den, n * num)
            self.assertLessEqual(abs(est - exact[key]), bound)


class DeterminismTest(unittest.TestCase):
    def test_run_twice_byte_identical(self):
        stream = os.path.join(STREAMS, "03-near-threshold.txt")
        with tempfile.TemporaryDirectory() as tmp:
            r1 = os.path.join(tmp, "r1.txt")
            r2 = os.path.join(tmp, "r2.txt")
            heavyhitters.run(stream, r1, 1, 1000)
            heavyhitters.run(stream, r2, 1, 1000)
            with open(r1, "rb") as a, open(r2, "rb") as b:
                self.assertEqual(a.read(), b.read())

    def test_report_twice_byte_identical(self):
        stream = os.path.join(STREAMS, "02-head-heavy.txt")
        with tempfile.TemporaryDirectory() as tmp:
            r = os.path.join(tmp, "r.txt")
            p1 = os.path.join(tmp, "p1.html")
            p2 = os.path.join(tmp, "p2.html")
            heavyhitters.run(stream, r, 1, 10000)
            heavyhitters.report(r, p1)
            heavyhitters.report(r, p2)
            with open(p1, "rb") as a, open(p2, "rb") as b:
                self.assertEqual(a.read(), b.read())


class MemoryTest(unittest.TestCase):
    def measure(self, name, num, den):
        stream = os.path.join(STREAMS, name + ".txt")
        with tempfile.TemporaryDirectory() as tmp:
            result = os.path.join(tmp, "r.txt")
            tracemalloc.start()
            base, _ = tracemalloc.get_traced_memory()
            heavyhitters.run(stream, result, num, den)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        return peak - base

    def test_memory_04_vast_keyset(self):
        self.assertLessEqual(self.measure("04-vast-keyset", 1, 1000), MEMORY_LIMIT)

    def test_memory_05_scale_1e7(self):
        self.assertLessEqual(self.measure("05-scale-1e7", 1, 10000), MEMORY_LIMIT)


class CliTest(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "heavyhitters.py"), *args],
            capture_output=True,
            text=True,
        )

    def test_run_and_report_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = os.path.join(tmp, "r.txt")
            page = os.path.join(tmp, "p.html")
            proc = self.cli("run", os.path.join(STREAMS, "06-tiny.txt"), result, "--eps", "2/7")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.path.exists(result))
            proc = self.cli("report", result, page)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.path.exists(page))

    def test_missing_stream_exit_1_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = os.path.join(tmp, "r.txt")
            proc = self.cli("run", os.path.join(tmp, "nope.txt"), result, "--eps", "1/10")
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(os.path.exists(result))
            self.assertTrue(proc.stderr.strip())

    def test_bad_eps_exit_1_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = os.path.join(tmp, "r.txt")
            for bad in ("3/2", "1/1", "0/5", "a/b", "1-10"):
                proc = self.cli(
                    "run", os.path.join(STREAMS, "06-tiny.txt"), result, "--eps", bad
                )
                self.assertEqual(proc.returncode, 1, bad)
                self.assertFalse(os.path.exists(result), bad)

    def test_report_bad_result_exit_1_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.txt")
            page = os.path.join(tmp, "p.html")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("not a result file\n")
            proc = self.cli("report", bad, page)
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(os.path.exists(page))
            proc = self.cli("report", os.path.join(tmp, "nope.txt"), page)
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(os.path.exists(page))


class ReportPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.result = os.path.join(self.tmp.name, "r.txt")
        self.page = os.path.join(self.tmp.name, "p.html")
        heavyhitters.run(os.path.join(STREAMS, "01-long-tail.txt"), self.result, 1, 1000)
        heavyhitters.report(self.result, self.page)
        with open(self.result, "rb") as fh:
            self.result_bytes = fh.read()
        with open(self.page, "r", encoding="utf-8") as fh:
            self.html = fh.read()

    def tearDown(self):
        self.tmp.cleanup()

    def test_embedded_hits_byte_identical(self):
        marker = '<script id="hits" type="text/plain">'
        start = self.html.index(marker) + len(marker)
        end = self.html.index("</script>", start)
        embedded = self.html[start:end]
        expected = self.result_bytes.decode("utf-8")
        self.assertEqual(embedded, expected[:-1] if expected.endswith("\n") else expected)

    def test_page_self_contained(self):
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        self.assertNotIn("<link", self.html)
        self.assertNotIn("src=", self.html)

    def test_page_sections(self):
        for text in ("总条数", "eps", "误差界上限", "阈值", "命中数", "精确数",
                     "名次", "估计频次", "误差界", "exact", "est", "图例"):
            self.assertIn(text, self.html)
        # 摘要数值与结果文件一致
        self.assertIn("<td>150000</td>", self.html)
        self.assertIn("<td>1/1000</td>", self.html)
        self.assertIn("<td>150</td>", self.html)
        self.assertIn("<td>150000/1000</td>", self.html)

    def test_empty_hits_page(self):
        # 构造一个无命中的结果：06-tiny 用极小 eps 阈值……改用合法结果直接验证渲染
        with tempfile.TemporaryDirectory() as tmp:
            result = os.path.join(tmp, "r.txt")
            page = os.path.join(tmp, "p.html")
            content = (
                "H|s.txt|N=10|eps=1/100|B=0|阈值=1000/100|命中=0|精确=0\n"
                "T|命中=0|精确=0|估计合计=0|误差合计=0\n"
            )
            with open(result, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.assertEqual(heavyhitters.report(result, page), 0)
            with open(page, "r", encoding="utf-8") as fh:
                page_text = fh.read()
            self.assertIn("无命中", page_text)
            self.assertIn('<script id="hits" type="text/plain">', page_text)


if __name__ == "__main__":
    unittest.main()
